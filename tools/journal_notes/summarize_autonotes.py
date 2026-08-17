#!/usr/bin/env python3
"""
Generate journal-style auto-notes for data/bg/autonotes.txt and
data/bg/autonotes_zh.txt by having a local LLM (Ollama) analyze the
decompiled usecode dialogue around each flag write.

Unlike generate_autonotes.py (which quotes the nearest dialogue line),
this script summarizes the *event* the flag records: what happened and,
when the dialogue says so, the quest purpose and destination - matching
the style of the hand-written entries ("Julia, my old friend, is living
in Minoc. Perhaps she will join me.").

Pipeline:
  1. Reuse the parser from generate_autonotes.py to map every flag write
     to its function's dialogue blocks. The scene context sent to the LLM
     is the WHOLE function transcript (capped), so summaries can mention
     the full quest arc, not just the block at the write.
  2. Ask the LLM, in batches, to write a first-person journal sentence
     (EN), its Traditional Chinese equivalent, and a classification:
     "quest" (advances an objective) vs "journey" (no objective).
  3. Flags with no dialogue are converted from the flag mnemonic.
  4. Hand-written curated entries keep their text; the LLM classifies.
  5. --audit-short: entries that are just a name or very short are
     checked against their dialogue - refined with real info, or
     removed (commented out) when the event is trivial.
  6. --repair-zh: a second LLM pass fixes zh entries where NPC/place
     names were translated to Chinese, using name_place_list.txt.
  7. Every response is cached (resumable, idempotent).
  8. Emit: "# Quest"/"# Journey" comment markers above each entry;
     zh entries keep proper nouns in English only.

Baselines: by default the scripts use the GIT HEAD version of
autonotes.txt / autonotes_zh.txt (the original hand-written files), so
cache keys stay stable across re-runs. Pass --en-baseline/--zh-baseline
to use a different (e.g. hand-edited) file instead.

Recommended order: summarize -> --audit-short -> --repair-zh -> --emit
(--repair-zh also fixes the zh texts that --audit-short rewrites, so it
must run after the audit; run it last before --emit).

Usage:
  python tools/journal_notes/summarize_autonotes.py \
      --en-baseline <base_en.txt> --zh-baseline <base_zh.txt>      # summarize
  python tools/journal_notes/summarize_autonotes.py --audit-short  # audit short entries
  python tools/journal_notes/summarize_autonotes.py --repair-zh    # fix zh names
  python tools/journal_notes/summarize_autonotes.py --emit         # write outputs
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_autonotes as gen  # noqa: E402

ROOT = gen.ROOT
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_MODEL = "qwen3:14b"
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autonote_summary_cache.jsonl")
REPAIR_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autonote_zh_repair_cache.jsonl")
AUDIT_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autonote_short_audit_cache.jsonl")

SYSTEM_PROMPT = """You are the Avatar's journal writer for Ultima VII: The Black Gate.
You are given scene transcripts from the game (each may span an entire
conversation). For each scene, write the journal note the Avatar would write
at that moment: a first-person past-tense sentence (EN) stating WHAT HAPPENED,
and when the dialogue reveals it, the quest PURPOSE and DESTINATION ("...I
should go to X..."). Write like a 18th-century adventurer's diary: warm, plain,
a little old-fashioned. Do NOT quote dialogue verbatim; summarize the meaning.
1-2 sentences.
Also classify each entry with one of exactly two types:
- "quest": the event advances an objective - an investigation, a task, a
  person to find, a place to reach, or something the Avatar must do next.
- "journey": a travel, meeting, observation, or state change with no
  objective attached (e.g. "I met old friend Julia.").
If a scene has NO dialogue (only a flag mnemonic), infer the event from the
flag name and write the sentence the Avatar would write.
IMPORTANT for zh text: keep ALL proper nouns (NPC names and place names) in
English exactly as spelled in the en text - do NOT transliterate them and do
NOT use "Chinese（English）" dual forms. Write zh in Traditional Chinese,
using 「聖者」 for the Avatar.
If an entry has an "existing" field, keep that text verbatim (it is a
hand-written note) and write the zh as a faithful Traditional Chinese
translation of that exact EN text; only provide its type.
Respond ONLY with JSON:
{"entries":[{"index":N,"type":"quest|journey","en":"...","zh":"..."}]}"""

FEW_SHOT = [
    {"index": -1,
     "scene": 'Iolo: "Julia, my old friend, is living in Minoc now. She told me to come visit."',
     "type": "journey",
     "en": "Julia, my old friend, is living in Minoc. Perhaps she will join me.",
     "zh": "我的老友 Julia 住在 Minoc。或許她會加入我的隊伍。"},
    {"index": -1,
     "scene": 'Batlin: "Avatar, join the Fellowship. Meet me at the Fellowship Hall."',
     "type": "quest",
     "en": "I have joined the Fellowship of Batlin. He awaits me at the Fellowship Hall.",
     "zh": "我加入了 Batlin 的友誼會。他在友誼會館等我。"},
    {"index": -1,
     "scene": 'Guard: "The murderer strikes in Trinsic at night. Only the password keeps the city safe."',
     "type": "quest",
     "en": "A murderer stalks the streets of Trinsic by night. I should learn the password to keep the city safe.",
     "zh": "一名兇手在夜裡的 Trinsic 街頭遊蕩。我必須查明口令，確保城市安全。"},
    {"index": -1,
     "scene": "[Scene: SEEN_TETRA]\n[No dialogue transcript available; only the flag mnemonic 'SEEN_TETRA'. Infer the event from the flag name.]",
     "type": "journey",
     "en": "I have seen the tetrahedron generator.",
     "zh": "我見過了四面體生成器。"},
]

PROMPT_VERSION = "journal-v3"

REPAIR_PROMPT_VERSION = "repair-v3"
REPAIR_SYSTEM_PROMPT = """You fix Traditional Chinese translations of Ultima VII
journal notes. Given an English note, its current Traditional Chinese
translation, and the list of proper nouns for that entry, rewrite the zh so
that EVERY proper noun from the "names" list appears in English, spelled
exactly as in the en text. Two mistakes to fix:
- bare transliterations (e.g. 特林蒂克 -> Trinsic, 哥倫書 -> Golem Book)
- "Chinese（English）" dual forms: drop the Chinese half, keep the English
  name (e.g. 伊欧洛（Iolo） -> Iolo, 克里斯托弗（Christopher） -> Christopher)
Only change the names; keep all other wording natural. Use Traditional
Chinese. A few names must NEVER appear in English in zh - use their
established translations instead: 「聖者」 for Avatar, 「友誼會」 for The
Fellowship, 「友誼會館」 for Fellowship Hall, 「內在之聲」 for Inner Voice,
「受難劇」 for Passion Play (if one of these appears in English in the zh,
replace it with the translation).
IMPORTANT: the names list only contains names whose EN usage is a proper
noun. If a listed name is used as an ordinary common noun in this en text
(e.g. "wrong" in "something is wrong", "hook" in "a man with a hook",
"guard" in "Captain of the Guard"), leave the corresponding zh word as a
natural translation and do NOT force the English word in.
Respond ONLY with JSON:
{"entries":[{"index":N,"zh":"..."}]}"""

AUDIT_PROMPT_VERSION = "audit-v2"
AUDIT_SYSTEM_PROMPT = """You review journal notes for Ultima VII: The Black Gate.
Given a scene transcript and the current journal note, decide whether the note
is worth keeping:
- "rewrite": the scene reveals meaningful info beyond the note (quest purpose,
  destination, a notable event, or who/what was met). Write a fuller 1-2
  sentence first-person note in EN and in Traditional Chinese. Base the
  rewrite ONLY on facts in the scene transcript - do not invent characters,
  places, events, or relationships the transcript does not state.
- "keep": the note is already fine, or the scene adds nothing.
- "remove": ONLY when the note AND the scene contain no information at all - a
  bare name or greeting with nothing else (e.g. "Met Mama." with no dialogue
  of substance). When in doubt, choose "keep".
Rules:
- If "curated" is true, the note is a hand-written original from the game:
  NEVER remove it; choose "keep" or "rewrite".
- zh text: keep proper nouns (NPC names, place names) in English exactly as
  spelled in the en text, but keep these translated: 「聖者」 for the Avatar,
  「友誼會」 for The Fellowship, 「友誼會館」 for Fellowship Hall,
  「內在之聲」 for Inner Voice, 「受難劇」 for Passion Play. Use Traditional
  Chinese.
Respond ONLY with JSON:
{"entries":[{"index":N,"action":"rewrite|keep|remove","en":"...","zh":"..."}]}"""

MAX_CONTEXT_CHARS = 2000          # cap for the whole-function transcript

# words that are not proper nouns - skip them in name-presence checks
STOP_NAMES = {"the", "lord", "of", "and", "a", "in", "to", "is", "i", "he", "she", "avatar"}
# names that MUST stay translated in zh (game convention; they read
# naturally in Chinese and are not NPC/place/item names)
KEEP_TRANSLATED = {
    "Avatar": "聖者",
    "The Fellowship": "友誼會",
    "The Fellowship's": "友誼會",
    "Fellowship Hall": "友誼會館",
    "Inner Voice": "內在之聲",
    "Passion Play": "受難劇",
}

SHORT_RE = re.compile(
    r"^(I )?(met|Met|saw|Saw|found|Found|met with|talked to|spoke to|"
    r"visited|helped|joined|saved|bought|sold|gave|took)"
    r"\s+[A-Za-z][A-Za-z' .]*\.?$")

NPC_TAG_RE = re.compile(r"\[\s*npc=([^\]]*)\]")


def strip_npc(text):
    return re.sub(r"\[\s*npc=[^\]]*\]", "", text or "").strip()


def flag_label(flag, en_entries):
    """Human-readable hint: the flag mnemonic from the existing file."""
    old = en_entries.get(flag, ("", ""))
    return old[1] or f"FLAG_{flag:X}"


def head_baseline(rel_path, dest):
    """Return a path to the git HEAD version of a data file, or None."""
    try:
        p = subprocess.run(["git", "show", f"HEAD:{rel_path}"],
                           capture_output=True, cwd=ROOT, timeout=30)
        if p.returncode == 0 and p.stdout.strip():
            with open(dest, "wb") as f:
                f.write(p.stdout)
            return dest
    except Exception:
        pass
    return None


def build_flag_blocks(en_funcs):
    """flag -> (blocks, blk_index) using the same write->block resolution as
    build_flag_context. blk_index is the flag's target block in `blocks`."""
    out = {}
    for func in en_funcs.values():
        blocks = func["blocks"]
        if not blocks:
            continue
        for flag, blk_ref in func["writes"]:
            if blk_ref is None or not (0 <= blk_ref < len(blocks)):
                continue
            if flag not in out:
                out[flag] = (blocks, blk_ref)
    return out


def build_scene_context(blocks, blk_ref, max_chars=MAX_CONTEXT_CHARS):
    """The dialogue transcript around the flag write.

    If the whole function fits the cap, include every block (so the summary
    can mention the full quest arc). Otherwise use a centered window around
    the write."""
    if not blocks:
        return ""
    if sum(len(b.text) for b in blocks) <= max_chars:
        idxs = range(len(blocks))
    else:
        lo = max(0, blk_ref - 6)
        hi = min(len(blocks), blk_ref + 7)
        idxs = range(lo, hi)
    parts = []
    for i in idxs:
        b = blocks[i]
        if not b.text:
            continue
        who = f"{b.speaker}: " if b.speaker else "Narrator: "
        parts.append(who + b.text)
    return "\n".join(parts)


def cache_key(model, index, flag_hint, scene, existing):
    value = json.dumps(
        {"model": model, "prompt_version": PROMPT_VERSION, "index": index,
         "flag_hint": flag_hint, "scene": scene, "existing": existing},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generic_cache_key(model, version, index, **fields):
    value = json.dumps(
        {"model": model, "prompt_version": version, "index": index, **fields},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_cache(path):
    cache = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    cache[rec["cache_key"]] = rec
    return cache


def append_cache(path, rec):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def call_ollama(url, model, system_prompt, few_shot, payload,
                json_field="entries", timeout=1200):
    """Generic batched Ollama call. payload: list of dicts (must include
    'index'). few_shot: list of exemplar dicts or None. Returns
    {index: {field: value}} for each entry in the response."""
    messages = [{"role": "system", "content": system_prompt}]
    if few_shot:
        examples = []
        for fs in few_shot:
            examples.append({k: v for k, v in fs.items() if k != "scene"})
        messages.append({"role": "user", "content": json.dumps(few_shot, ensure_ascii=False)})
        messages.append({"role": "assistant", "content": json.dumps(
            {"entries": examples}, ensure_ascii=False)})
    messages.append({"role": "user", "content": json.dumps(payload, ensure_ascii=False)})
    prompt = {"model": model, "stream": False, "think": False, "format": "json",
              "options": {"temperature": 0.2, "num_ctx": 8192}, "messages": messages}
    req = urllib.request.Request(
        url, data=json.dumps(prompt, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    content = body.get("message", {}).get("content", body.get("response", body))
    if isinstance(content, str):
        content = json.loads(content)
    entries = content.get(json_field, []) if isinstance(content, dict) else content
    out = {}
    for item in entries or []:
        if isinstance(item, dict) and "index" in item:
            out[int(item["index"])] = item
    if not out:
        raise KeyError(f"no usable entries; raw={json.dumps(content, ensure_ascii=False)[:400]}")
    return out


def call_summarize(url, model, flags_data, timeout=1200):
    """flags_data: list of (flag, flag_hint, scene, existing).
    Returns {flag: (en, zh, type)}."""
    payload = []
    for flag, hint, scene, existing in flags_data:
        item = {"index": flag, "scene": f"[Scene: {hint}]\n{scene}"}
        if existing:
            item["existing"] = existing
        payload.append(item)
    results = call_ollama(url, model, SYSTEM_PROMPT, FEW_SHOT, payload)
    out = {}
    for flag, item in results.items():
        out[flag] = (str(item.get("en", "")).strip(),
                     str(item.get("zh", "")).strip(),
                     str(item.get("type", "journey")).strip().lower())
    return out


def clean_entry(text):
    """Post-process an LLM journal sentence for the autonotes format."""
    if not text:
        return text
    t = re.sub(r"\s{2,}", " ", text.strip())
    t = t.replace("\ufffd", "")
    # strip a spurious ASCII period glued after CJK punctuation (。. or ？.)
    t = re.sub(r"([。！？!?])\s*\.", r"\1", t)
    if not t.endswith((".", "!", "?", "。」", "。", "！", "？")):
        t += "."
    return t


def load_name_list(path=None):
    """Load the canonical English proper-noun list (NPC + place names).
    Returns a set of display names."""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "name_place_list.txt")
    names = set()
    if os.path.exists(path):
        for ln in open(path, encoding="utf-8", newline="").read().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                names.add(ln)
    return names


NAME_LIST = load_name_list()


def zh_names_to_english(text):
    """zh entries keep proper nouns in English only.

    No regex-level name surgery happens here: a "Chinese（English）" dual
    form cannot be safely split from its sentence (e.g. 我遇见了老友伊欧洛
    （Iolo）) without language understanding, so dual forms and bare
    transliterations are fixed by the LLM repair pass, which is triggered
    for every name found in en that is absent or dual-form in zh.
    """
    return text.strip()


def en_contains_name(text, name, case_sensitive=False):
    """Word-boundary check that `name` appears in English `text`."""
    if not name or name.lower() in STOP_NAMES:
        return False
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = r"(?<![A-Za-z])" + re.escape(name) + r"(?![A-Za-z])"
    return re.search(pattern, text, flags) is not None


# listed names that are ordinary English words when used in lowercase or as
# titles - common-noun usage ("a man with a hook", "Captain of the Guard",
# "the wench", "the ferryman") must stay translated; detection skips them
SKIP_COMMON = {"Guard", "Wench", "Hook", "Wrong", "Blackrock", "Hydra",
               "Town Mayor", "Head Servant", "Ferryman", "Flower Man"}


def zh_name_base(name):
    """Name as it should appear in zh: drop possessives ("Lord British's" ->
    "Lord British", since zh says "Lord British 的...") and leading "The "
    ("The Blue Boar" -> "Blue Boar"; zh already writes "Blue Boar 酒館")."""
    base = name[:-2] if name.endswith("'s") else name
    return base[4:] if base.startswith("The ") else base


def apply_keep_translated(text):
    """Deterministically swap English KEEP_TRANSLATED forms back to their
    established zh translations (the repair LLM sometimes leaves them in
    English). Longest name first so "Fellowship Hall" wins over
    "The Fellowship"; word-boundary guarded; case-insensitive."""
    if not text:
        return text
    for name, zh_form in sorted(KEEP_TRANSLATED.items(),
                                key=lambda kv: (-len(kv[0]), kv[0])):
        core = name[:-2] if name.endswith("'s") else name
        pat = r"\s+".join(re.escape(w) for w in core.split())
        pat = r"(?:The\s+)?" + pat
        text = re.sub(r"(?<![A-Za-z])" + pat + r"(?![A-Za-z])",
                      zh_form, text, flags=re.IGNORECASE)
    return text


def find_missing_names(en_text, zh_text):
    """Names from the list present in en_text but not in zh_text in
    standalone English form - i.e. names the zh translation either
    transliterated (特林蒂克 for Trinsic) or wrapped in a "Chinese（English）"
    dual form (伊欧洛（Iolo）). Returns the names to repair.

    A name counts only when en_text uses it title-cased (proper-noun usage);
    lowercase occurrences ("something is wrong", "a man with a hook") are
    common-noun uses and are ignored. In zh, possessives and leading "The"
    are matched loosely (see zh_name_base)."""
    if not en_text or not zh_text:
        return []
    missing = []
    for name in sorted(NAME_LIST, key=len, reverse=True):
        if name in KEEP_TRANSLATED or name in SKIP_COMMON:
            continue                       # stays translated by convention
        if not en_contains_name(en_text, name[:1].upper() + name[1:],
                                case_sensitive=True):
            continue                       # not a proper-noun usage in en
        zh_name = zh_name_base(name)
        if en_contains_name(zh_text, zh_name):
            # present in English, but only inside a dual form? e.g. 伊欧洛（Iolo）
            dual = re.search(
                r"[\u4e00-\u9fff]+[（(]\s*" + re.escape(zh_name) + r"\s*[）)]",
                zh_text)
            if not dual:
                continue                   # already standalone English
        missing.append(name)
    # KEEP_TRANSLATED names must appear in zh in their TRANSLATED form: if
    # en uses the name and zh has the English form (or lacks the zh form),
    # flag it so the repair LLM swaps it back (e.g. "The Fellowship" -> 友誼會)
    for name, zh_form in KEEP_TRANSLATED.items():
        base = name[:-2] if name.endswith("'s") else name
        if not en_contains_name(en_text, base, case_sensitive=False):
            continue                       # en mentions "Fellowship" at all
        if zh_form in zh_text:
            continue                       # correctly translated
        missing.append(name)
    return missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--en-baseline", default=None,
                        help="existing autonotes.txt to preserve curated entries from "
                             "(default: the git HEAD version of the file)")
    parser.add_argument("--zh-baseline", default=None,
                        help="existing autonotes_zh.txt to preserve curated entries from "
                             "(default: the git HEAD version of the file)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--url", default=OLLAMA_URL)
    parser.add_argument("--cache", default=CACHE_PATH)
    parser.add_argument("--limit", type=int, default=None,
                        help="only process the first N flags (testing)")
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=int, default=15)
    parser.add_argument("--emit", action="store_true",
                        help="write output files using cached summaries")
    parser.add_argument("--repair-zh", action="store_true",
                        help="run the zh name-repair pass (or resume it)")
    parser.add_argument("--audit-short", action="store_true",
                        help="audit short/name-only entries against their dialogue")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    en_baseline = args.en_baseline or head_baseline(
        "data/bg/autonotes.txt", os.path.join(script_dir, "autonotes_head_en.txt")) or gen.EN_OUT
    zh_baseline = args.zh_baseline or head_baseline(
        "data/bg/autonotes_zh.txt", os.path.join(script_dir, "autonotes_head_zh.txt")) or gen.ZH_OUT
    if not args.en_baseline and not args.zh_baseline:
        if en_baseline != gen.EN_OUT or zh_baseline != gen.ZH_OUT:
            print(f"baselines: {en_baseline}\n           {zh_baseline}")

    en_funcs = gen.collect_all_scripts(gen.ES_DIR)
    zh_funcs = gen.collect_all_scripts(gen.ZH_DIR)
    en_ctx = gen.build_flag_context(en_funcs)
    zh_ctx = gen.build_flag_context(zh_funcs)
    flag_blocks = build_flag_blocks(en_funcs)
    existing_en = gen.load_existing(en_baseline)
    existing_zh = gen.load_existing(zh_baseline)
    en_entries, en_comments = existing_en
    zh_entries, zh_comments = existing_zh

    all_flags = sorted(set(en_ctx) | set(en_entries) | set(zh_entries))
    if args.limit:
        all_flags = all_flags[: args.limit]

    def need_for(flag):
        old_line, old_text = en_entries.get(flag, ("", ""))
        if old_line.startswith("#"):
            return None
        hint = flag_label(flag, en_entries)
        if flag in flag_blocks:
            blocks, blk_ref = flag_blocks[flag]
            scene = build_scene_context(blocks, blk_ref)
        else:
            scene = ""
        if not scene and flag in zh_ctx:
            blk = zh_ctx[flag][1]
            scene = f"[zh dialogue]\n{blk.speaker + ': ' if blk.speaker else 'Narrator: '}{blk.text}"
        if not scene:
            scene = f"[No dialogue transcript available; only the flag mnemonic '{hint}'. Infer the event from the flag name.]"
        curated = bool(old_text and not gen.is_bare_flag_text(old_text))
        existing = old_text if curated else ""
        return flag, hint, scene, existing

    need = [n for n in (need_for(f) for f in all_flags) if n]

    cache = load_cache(args.cache)

    def summary_rec(flag):
        item = need_for(flag)
        if not item:
            return None
        flag, hint, scene, existing = item
        return cache.get(cache_key(args.model, flag, hint, scene, existing))

    def run_batches(todo, mode_call, build_record, store, cache_path, label):
        """Run LLM batches with retry/resume; build_record(item, result) ->
        full cache record dict. Writes to cache_path + in-memory `store`."""
        start = time.time()
        n_failed = 0
        for i in range(0, len(todo), args.batch_size):
            batch = todo[i:i + args.batch_size]
            results = {}
            for attempt in range(1, args.retries + 1):
                try:
                    results = mode_call(batch)
                    break
                except Exception as exc:
                    if attempt < args.retries:
                        wait = args.retry_delay * attempt
                        print(f"  batch {i // args.batch_size} attempt {attempt} failed: {exc} "
                              f"(retrying in {wait}s)", flush=True)
                        time.sleep(wait)
                    else:
                        print(f"  batch {i // args.batch_size} FAILED after {args.retries} attempts: "
                              f"{exc}", flush=True)
                        n_failed += 1
            if not results:
                continue
            for item in batch:
                result = results.get(item[0])
                if result is None:
                    continue
                rec = build_record(item, result)
                append_cache(cache_path, rec)
                store[rec["cache_key"]] = rec
            done = min(i + args.batch_size, len(todo))
            elapsed = time.time() - start
            rate = done / elapsed if elapsed else 0
            eta = (len(todo) - done) / rate if rate else 0
            print(f"  {done}/{len(todo)} ({100 * done / len(todo):.0f}%)  "
                  f"elapsed {elapsed / 60:.1f}m  eta {eta / 60:.1f}m  failed {n_failed}",
                  flush=True)
        if n_failed:
            print(f"Done with {n_failed} failed batches - re-run to resume.")
        else:
            print(label)

    if not args.emit and not args.repair_zh and not args.audit_short:
        # ---------- summarize pass ----------
        print(f"Flags to process: {len(need)}")
        todo = [it for it in need
                if cache_key(args.model, it[0], it[1], it[2], it[3]) not in cache]
        print(f"Already cached: {len(need) - len(todo)}, to process: {len(todo)}")

        def summarize_build(item, result):
            flag, hint, scene, existing = item
            en_txt, zh_txt, typ = result
            return {"cache_key": cache_key(args.model, flag, hint, scene, existing),
                    "index": flag, "flag_hint": hint, "scene": scene,
                    "existing": existing, "en": en_txt, "zh": zh_txt,
                    "type": typ if typ in ("quest", "journey") else "journey",
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}

        run_batches(todo,
                    lambda b: call_summarize(args.url, args.model, b),
                    summarize_build, cache, args.cache,
                    "All summaries cached. Run --audit-short / --repair-zh / --emit next.")
        return

    audit_cache = load_cache(AUDIT_CACHE_PATH)
    repair_cache = load_cache(REPAIR_CACHE_PATH)

    # ---------- shared final-text helpers (used by audit, repair, emit) ----
    def audit_for(flag):
        """Audit result for a flag, keyed by its would-be emitted EN text."""
        old_line, old_text = en_entries.get(flag, ("", ""))
        if old_line.startswith("#"):
            return None
        if old_text and not gen.is_bare_flag_text(old_text):
            entry = strip_npc(old_text)
        else:
            rec = summary_rec(flag)
            if not (rec and rec.get("en")):
                return None
            entry = strip_npc(clean_entry(rec["en"]))
        key = generic_cache_key(args.model, AUDIT_PROMPT_VERSION, flag, entry=entry)
        rec = audit_cache.get(key)
        return rec["result"] if rec else None

    def final_en(flag):
        """The EN text emit will write for this flag (pre-repair, npc tags
        stripped) - audit rewrite > curated > LLM."""
        aud = audit_for(flag)
        if aud and aud.get("action") == "rewrite" and aud.get("en"):
            return strip_npc(clean_entry(aud["en"]))
        old_line, old_text = en_entries.get(flag, ("", ""))
        if old_line.startswith("#"):
            return None
        if old_text and not gen.is_bare_flag_text(old_text):
            return strip_npc(old_text)
        rec = summary_rec(flag)
        if rec and rec.get("en"):
            return strip_npc(clean_entry(rec["en"]))
        return None

    def final_zh(flag):
        """The ZH text emit will write for this flag (pre-repair, npc tags
        stripped) - audit rewrite > curated > LLM > zh-dialogue fallback."""
        aud = audit_for(flag)
        if aud and aud.get("action") == "rewrite" and aud.get("zh"):
            return strip_npc(clean_entry(aud["zh"]))
        old_line, old_text = zh_entries.get(flag, ("", ""))
        if old_line.startswith("#"):
            return None
        if old_text and not gen.is_bare_flag_text(old_text):
            return strip_npc(zh_names_to_english(gen.cc.convert(old_text)))
        rec = summary_rec(flag)
        if rec and rec.get("zh"):
            return strip_npc(zh_names_to_english(gen.cc.convert(clean_entry(rec["zh"]))))
        if flag in zh_ctx:
            trad = gen.cc.convert(zh_ctx[flag][1].text)
            blk = gen.DialogBlock(zh_ctx[flag][1].speaker, [trad])
            return strip_npc(zh_names_to_english(gen.compose_zh(flag, blk)[0]))
        return None

    def npc_tag(flag, prefer_text=None):
        """[npc=X] tag for generated/rewritten lines. `prefer_text` (the
        original curated line) keeps its own inline tag when present."""
        if prefer_text:
            m = NPC_TAG_RE.search(prefer_text)
            if m and m.group(1).strip():
                return f" [npc={m.group(1).strip()}]"
        if flag in en_ctx:
            speaker = en_ctx[flag][1].speaker
            if speaker:
                return f" [npc={speaker}]"
        return ""

    if args.audit_short:
        # ---------- short-entry audit pass ----------
        # Candidates: flags whose would-be emitted EN text is short or just
        # a name - covers both curated ("I met Shamino.") and LLM-generated
        # ("Met Mama.") entries. Only audit entries with real dialogue
        # context to check against.
        todo = []
        for flag in all_flags:
            old_line, old_text = en_entries.get(flag, ("", ""))
            if old_line.startswith("#"):
                continue
            rec = summary_rec(flag)
            if old_text and not gen.is_bare_flag_text(old_text):
                emitted = strip_npc(old_text)
            elif rec and rec.get("en"):
                emitted = strip_npc(clean_entry(rec["en"]))
            else:
                continue
            if not (len(emitted) <= 40 or SHORT_RE.match(emitted)):
                continue
            scene = rec.get("scene", "") if rec else ""
            if not scene or "No dialogue transcript" in scene:
                continue
            key = generic_cache_key(args.model, AUDIT_PROMPT_VERSION, flag, entry=emitted)
            if key in audit_cache:
                continue
            curated = bool(old_text and not gen.is_bare_flag_text(old_text))
            todo.append((flag, emitted, scene, curated))
        print(f"short entries to audit: {len(todo)}")

        def audit_call(batch):
            payload = [{"index": f, "entry": e, "scene": s, "curated": int(c)}
                       for f, e, s, c in batch]
            return call_ollama(args.url, args.model, AUDIT_SYSTEM_PROMPT, None,
                               payload, json_field="entries")

        def audit_build(item, result):
            flag, emitted, scene, curated = item
            if curated and result.get("action") == "remove":
                # hand-written notes are never auto-removed
                result = {"index": result.get("index", flag),
                          "action": "keep"}
            key = generic_cache_key(args.model, AUDIT_PROMPT_VERSION, flag, entry=emitted)
            return {"cache_key": key, "index": flag, "result": result,
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}

        run_batches(todo, audit_call, audit_build, audit_cache, AUDIT_CACHE_PATH,
                    "audit done. Run --repair-zh then --emit.")
        return

    if args.repair_zh:
        # ---------- zh name-repair pass ----------
        # Repair entries whose final zh text lost names (present in en,
        # absent from zh). Keys match emit's repair_lookup exactly because
        # final_en/final_zh are shared.
        todo = []
        for flag in all_flags:
            en_t = final_en(flag)
            zh_t = final_zh(flag)
            if not en_t or not zh_t:
                continue
            missing = find_missing_names(en_t, zh_t)
            if not missing:
                continue
            key = generic_cache_key(args.model, REPAIR_PROMPT_VERSION, flag,
                                    en=en_t, zh=zh_t)
            if key in repair_cache:
                continue
            todo.append((flag, en_t, zh_t, missing))
        print(f"zh entries needing name repair: {len(todo)}")

        def repair_call(batch):
            payload = [{"index": f, "en": e, "zh": z, "names": m}
                       for f, e, z, m in batch]
            return call_ollama(args.url, args.model, REPAIR_SYSTEM_PROMPT, None,
                               payload, json_field="entries")

        def repair_build(item, result):
            flag, en_t, zh_t, missing = item
            key = generic_cache_key(args.model, REPAIR_PROMPT_VERSION, flag,
                                    en=en_t, zh=zh_t)
            return {"cache_key": key, "index": flag, "result": result,
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}

        run_batches(todo, repair_call, repair_build, repair_cache, REPAIR_CACHE_PATH,
                    "zh repair done. Run --emit.")
        return

    # ---------- emit ----------
    def repair_lookup(flag):
        en_t = final_en(flag)
        zh_t = final_zh(flag)
        if not en_t or not zh_t:
            return None
        key = generic_cache_key(args.model, REPAIR_PROMPT_VERSION, flag,
                                en=en_t, zh=zh_t)
        rec = repair_cache.get(key)
        return rec["result"]["zh"] if rec and rec.get("result", {}).get("zh") else None

    en_hdr = {l for l in gen.EN_HEADER.splitlines()}
    zh_hdr = {l for l in gen.ZH_HEADER.splitlines()}
    for cm in (en_comments, zh_comments):
        for k in list(cm):
            cm[k] = [l for l in cm[k] if l.strip() not in en_hdr | zh_hdr]

    def marker(typ):
        return "# Quest" if typ == "quest" else "# Journey"

    def append_marker(flag, typ, comments, lines):
        if any(c.strip() in ("# Quest", "# Journey") for c in comments.get(flag, ())):
            return  # marker already preserved from a previous emit
        lines.append(marker(typ))

    # Category tag the game parses: [quest]/[journey]. Injected right after
    # the "0xNN: " prefix so parse_note_category() routes the entry.
    def cat_tag(typ):
        return "[quest]" if typ == "quest" else "[journey]"

    def with_cat_tag(raw_line, typ):
        colon = raw_line.find(":")
        if colon == -1:
            return raw_line
        rest = raw_line[colon + 1:]
        stripped = rest.lstrip()
        if stripped.startswith("[quest]") or stripped.startswith("[journey]"):
            return raw_line  # already tagged (re-emit)
        return f"{raw_line[:colon + 1]}{cat_tag(typ)} {rest.lstrip()}"

    en_lines, zh_lines = [], []
    n_kept_en = n_llm_en = n_bare = n_kept_zh = n_llm_zh = n_zh_fallback = 0
    n_removed = n_refined = 0

    for flag in all_flags:
        for c in en_comments.get(flag, ()):
            en_lines.append(c)
        for c in zh_comments.get(flag, ()):
            zh_lines.append(c)

        old_line, old_text = en_entries.get(flag, ("", ""))
        is_bare = gen.is_bare_flag_text(old_text)
        if old_line.startswith("#"):
            en_lines.append(old_line)
            n_bare += 1
            continue
        rec = summary_rec(flag)
        typ = rec["type"] if rec and rec.get("type") else "journey"
        aud = audit_for(flag)
        en_t = final_en(flag)
        tag = npc_tag(flag, old_text if old_text and not is_bare else None)

        # ---- EN side ----
        if aud and aud.get("action") == "remove":
            en_lines.append(f"# 0x{flag:X}: {en_t}")
            n_removed += 1
        elif aud and aud.get("action") == "rewrite" and aud.get("en"):
            append_marker(flag, typ, en_comments, en_lines)
            en_lines.append(with_cat_tag(f"0x{flag:X}: {clean_entry(aud['en'])}{tag}", typ))
            n_refined += 1
        elif old_text and not is_bare:
            append_marker(flag, typ, en_comments, en_lines)
            en_lines.append(with_cat_tag(old_line, typ))  # hand-written sentence wins, verbatim
            n_kept_en += 1
        elif rec and rec.get("en"):
            append_marker(flag, typ, en_comments, en_lines)
            en_lines.append(with_cat_tag(f"0x{flag:X}: {clean_entry(rec['en'])}{tag}", typ))
            n_llm_en += 1
        else:
            en_lines.append(old_line if old_line else f"0x{flag:X}:FLAG_{flag:X}")
            n_bare += 1

        # ---- ZH side ----
        old_line, old_text = zh_entries.get(flag, ("", ""))
        is_bare = gen.is_bare_flag_text(old_text)
        zh_tag = npc_tag(flag, old_text if old_text and not is_bare else None)
        if old_line.startswith("#"):
            zh_lines.append(old_line)
        elif aud and aud.get("action") == "remove":
            if old_line:
                zh_lines.append(f"# {old_line}")
        else:
            zh_txt = final_zh(flag)
            if zh_txt is None:
                n_zh_fallback += 1
                continue
            repaired = repair_lookup(flag)
            final_zh_txt = apply_keep_translated(
                zh_names_to_english(gen.cc.convert(clean_entry(repaired or zh_txt))))
            append_marker(flag, typ, zh_comments, zh_lines)
            zh_lines.append(with_cat_tag(f"0x{flag:X}: {final_zh_txt}{zh_tag}", typ))
            if old_text and not is_bare:
                n_kept_zh += 1
            elif rec and rec.get("zh"):
                n_llm_zh += 1
            else:
                n_zh_fallback += 1

    for c in en_comments.get("__tail__", ()):
        en_lines.append(c)
    for c in zh_comments.get("__tail__", ()):
        zh_lines.append(c)

    def emit(path, header, lines):
        with open(path, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(header + "\n")
            for ln in lines:
                f.write(ln + "\n")

    emit(gen.EN_OUT, gen.EN_HEADER, en_lines)
    emit(gen.ZH_OUT, gen.ZH_HEADER, zh_lines)
    print(f"\nEN: kept curated {n_kept_en}, LLM {n_llm_en}, refined {n_refined}, removed {n_removed}, bare {n_bare}, total {len(en_lines)}")
    print(f"ZH: kept curated {n_kept_zh}, LLM {n_llm_zh}, en-fallback {n_zh_fallback}, total {len(zh_lines)}")


if __name__ == "__main__":
    main()
