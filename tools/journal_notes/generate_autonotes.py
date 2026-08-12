#!/usr/bin/env python3
"""
Generate data/bg/autonotes.txt and data/bg/autonotes_zh.txt from
decompiled BG usecode (tools/ucxt/output/bg_translation).

Pipeline:
  1. Parse every EN .es script (es_scripts/*.es): collect, per function:
     - NPC faces shown (UI_show_npc_face) -> current speaker
     - message()/say() dialogue blocks
     - gflags[0xNN] = true writes (only `= true` creates a journal note)
  2. For each flag, pick the say block nearest the write site and compose a
     journal sentence, preferring the speaker's own dialogue.
  3. Repeat on the Simplified-Chinese scripts (chs_scripts/**/*_zh.es),
     convert S -> Traditional (OpenCC s2twp), compose Traditional sentences.
  4. Regenerate both output files:
     - existing curated entries with real sentences (not bare flag names)
       and all comment lines are preserved verbatim
     - bare flag-name entries are replaced by generated sentences when the
       usecode has any dialogue for them; otherwise they stay as bare names

Usage: python tools/journal_notes/generate_autonotes.py
"""

import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "voice_acting"))

from opencc import OpenCC  # noqa: E402

try:
    from npc_data import NPC_NUMBERS  # noqa: E402
except ImportError:
    NPC_NUMBERS = {}

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
ES_DIR = os.path.join(ROOT, "tools", "ucxt", "output", "bg_translation", "es_scripts")
ZH_DIR = os.path.join(ROOT, "tools", "ucxt", "output", "bg_translation", "chs_scripts")
EN_OUT = os.path.join(ROOT, "data", "bg", "autonotes.txt")
ZH_OUT = os.path.join(ROOT, "data", "bg", "autonotes_zh.txt")

# NPC number -> name (from voice_acting/npc_data.py)
NPC_NUM2NAME = {v: k for k, v in NPC_NUMBERS.items()}

cc = OpenCC("s2twp")  # Simplified -> Traditional (Taiwan standard)

FUNC_RE = re.compile(r"^void\s+Func([0-9A-F]{4})\s+object#\(0x([0-9A-F]+)\)")
FACE_RE = re.compile(r"UI_show_npc_face\(0x([0-9A-F]+)")
GFLAG_ON_RE = re.compile(r"gflags\[0x([0-9A-F]{2,4})\]\s*=\s*true;")
MESSAGE_RE = re.compile(r'message\("(.*)"\);')
SAY_RE = re.compile(r"^\s*say\(\s*\);")
PARTY_RE = re.compile(r"UI_add_to_party\(0x([0-9A-F]{4})\)")
REMOVE_PARTY_RE = re.compile(r"UI_remove_from_party\(0x([0-9A-F]{4})\)")


def signed16(v):
    """Interpret a usecode 16-bit NPC id as signed (0xFFFF == -1 == Iolo)."""
    return v - 0x10000 if v >= 0x8000 else v


def npc_name_from_id(npc_id):
    """Map a usecode NPC face id (0xFFFF style) to a name."""
    s = signed16(npc_id)
    num = abs(s) if s < 0 else npc_id
    return NPC_NUM2NAME.get(num, "")


def flatten_text(raw):
    """Clean decompiler string for journal use: quotes, ~~, *, escapes."""
    if not raw:
        return ""
    t = raw.replace('\\"', '"')
    t = t.replace("~~", " ")
    t = t.replace("~", " ")
    # strip * pause markers
    t = re.sub(r"\*+", "", t)
    # decode-level artifacts from the cp1252 decompiler output: "¸" is a
    # mangled en/em dash, "�" is a mangled smart quote char.
    t = t.replace("¸", "-").replace("\ufffd", "")
    t = t.strip()
    # merge internal whitespace runs
    t = re.sub(r"\s{2,}", " ", t)
    return t


def read_script(path):
    """Read a decompiled .es file, handling both UTF-8 (zh) and cp1252
    (en with mangled dashes) encodings."""
    with open(path, "rb") as f:
        data = f.read()
    for enc in ("utf-8", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def first_sentence(text, limit=180):
    """Take up to the first sentence-ish chunk, capped at ~limit chars."""
    if not text:
        return ""
    # collapse doubled quote marks that come from dialogue wrapping
    while '""' in text or '「「' in text:
        text = text.replace('""', '"').replace('「「', '「')
    # find the first sentence-ending punctuation (prefer over quote-space)
    end = len(text)
    for sep in (". ", "! ", "? ", "。」", "！", "？", "。", "！？"):
        i = text.find(sep)
        if 0 < i < end:
            end = i + (1 if sep.endswith(" ") else 0)
    # keep a closing quote that directly follows the punctuation
    if end < len(text) and text[end] in '」"':
        end += 1
    if end > limit:
        # cut at last word boundary under limit
        cut = text.rfind(" ", 0, limit)
        if cut == -1:
            cut = limit
        return text[:cut].rstrip(" ,.;：:，。") + "..."
    return text[:end].rstrip(" ,.;：")


def strip_dialogue_quotes(text):
    """Remove one layer of surrounding quote marks (game dialogue strings
    are wrapped in «» or ""); inner quotes are kept."""
    t = text.strip()
    if t.startswith("「") and t.endswith("」"):
        t = t[1:-1]
    elif len(t) >= 2 and t.startswith('"') and t.endswith('"'):
        t = t[1:-1]
    elif len(t) >= 2 and t.startswith("'") and t.endswith("'"):
        t = t[1:-1]
    # a stray opening quote (truncated string) is removed
    if t.startswith('"') and not t.endswith('"'):
        t = t[1:]
    if t.startswith("「") and not t.endswith("」"):
        t = t[1:]
    if t.endswith('"') and not t.startswith('"'):
        t = t[:-1]
    if t.endswith("」") and not t.startswith("「"):
        t = t[:-1]
    return t.strip()


class DialogBlock:
    def __init__(self, speaker, texts):
        self.speaker = speaker   # NPC name or None
        self.texts = texts       # cleaned message strings (already flattened)

    @property
    def text(self):
        return " ".join(t for t in self.texts if t)


def parse_script(path):
    """Return per-function dict: func_id -> list of
    {'blocks': [DialogBlock...], 'writes': [(flag, block_index_or_None), ...]}
    with flag writes referring to the block present at that moment (or None).
    """
    funcs = {}
    try:
        lines = read_script(path).splitlines()
    except OSError:
        return funcs

    cur_func = None
    speaker = None
    accum = []          # message texts pending a say()
    blocks = []         # completed DialogBlocks
    writes = []         # (flag_int, 'pending' | idx_of_last_completed | None)

    def flush():
        nonlocal accum
        if accum:
            blocks.append(DialogBlock(speaker, accum))
        accum = []

    for line in lines:
        m = FUNC_RE.search(line)
        if m:
            # if we were mid-function, we shouldn't be (EOF/return happened) -
            # but a stray flag write before 'return' is still valid; flush.
            if cur_func is not None:
                flush()
                funcs[cur_func]["blocks"].extend(blocks)
                funcs[cur_func]["writes"].extend(writes)
            cur_func = int(m.group(2), 16)
            speaker = None
            accum = []
            blocks = []
            writes = []
            continue
        if cur_func is None:
            continue
        m = FACE_RE.search(line)
        if m:
            name = npc_name_from_id(int(m.group(1), 16))
            if name:
                speaker = name
            continue
        m = GFLAG_ON_RE.search(line)
        if m:
            # If a say() block is currently being assembled, the flag belongs
            # to that block; otherwise to the last completed block (or None
            # if the write precedes any dialogue in this function).
            if accum:
                writes.append((int(m.group(1), 16), "pending"))
            else:
                writes.append((int(m.group(1), 16), len(blocks) - 1 if blocks else None))
            continue
        m = MESSAGE_RE.search(line)
        if m:
            flat = flatten_text(m.group(1))
            if flat:
                accum.append(flat)
            continue
        if SAY_RE.search(line):
            flush()
        if PARTY_RE.search(line) or REMOVE_PARTY_RE.search(line):
            # party change usually follows the meeting dialogue
            flush()

    def resolve(func_writes):
        """Resolve 'pending'/index write refs against the block list."""
        out = []
        for flag, ref in func_writes:
            if ref == "pending":
                out.append((flag, len(blocks) - 1))      # just-flushed block
            elif ref is None:
                out.append((flag, 0 if blocks else None))
            else:
                out.append((flag, ref))
        return out

    flush()
    if cur_func is not None:
        funcs[cur_func] = {"blocks": list(blocks), "writes": resolve(writes)}
    return funcs


def collect_all_scripts(scripts_dir, zh=False):
    """Parse every .es file under scripts_dir; return func_id -> data."""
    funcs = {}
    for root, _, names in os.walk(scripts_dir):
        for name in names:
            if not name.endswith(".es"):
                continue
            data = parse_script(os.path.join(root, name))
            for fid, d in data.items():
                funcs.setdefault(fid, {"blocks": [], "writes": []})
                funcs[fid]["blocks"].extend(d["blocks"])
                funcs[fid]["writes"].extend(d["writes"])
    return funcs


def build_flag_context(funcs):
    """flag -> best DialogBlock for a journal sentence.

    Prefer: a block that has text, spoken by a named NPC, closest to the
    flag write (the block containing the write first, then the block just
    before it, then the first block of the function).
    """
    best = {}  # flag -> (score, DialogBlock)
    for func in funcs.values():
        blocks = func["blocks"]
        if not blocks:
            continue
        for flag, blk_ref in func["writes"]:
            candidates = []
            if blk_ref is not None and 0 <= blk_ref < len(blocks):
                for delta in (0, -1):
                    i = blk_ref + delta
                    if 0 <= i < len(blocks) and blocks[i].text:
                        candidates.append((abs(delta), blocks[i]))
            if not candidates:
                for i in range(len(blocks)):  # fall back to first with text
                    if blocks[i].text:
                        candidates.append((1, blocks[i]))
                        break
            if not candidates:
                continue
            score = 0
            chosen = None
            for dist, blk in candidates:
                s = 2 - dist  # containing/previous block preferred
                if blk.speaker and len(blk.text) < 400:
                    s += 3
                if s > score:
                    score, chosen = s, blk
            if chosen and (flag not in best or score > best[flag][0]):
                best[flag] = (score, chosen)
    return best


def compose_en(flag, blk):
    """Compose an English journal sentence from a dialogue block."""
    text = strip_dialogue_quotes(first_sentence(blk.text))
    if blk.speaker:
        return f'{blk.speaker} told me, "{text}"', blk.speaker
    return f'I was told, "{text}"', None


def compose_zh(flag, blk):
    """Compose a Traditional Chinese journal sentence from a dialogue block."""
    text = strip_dialogue_quotes(first_sentence(blk.text))
    if blk.speaker:
        return f"{blk.speaker} 對我說：「{text}」", blk.speaker
    return f"有人對我說：「{text}」", None


EN_HEADER = """# List of flags, found by Alun Bestor (?), Marzo, SB-X and Malignant Maynor.
# Adapted from https://github.com/marzojr/u7-usecode fov/include/globals.uc.
# Lists ALL known flags, regardless of whether they make sense in the autonotes.
"""

ZH_HEADER = """# Chinese translations of the journal auto-notes.
# Missing entries fall back to the English text in autonotes.txt.
# [npc=...] names are the game's English names; they double as a search key.
"""


def load_existing(path):
    """Load existing autonotes file: {index: (line, text)} preserving
    comment lines and reporting which entries have real text vs bare flag
    names. Returns (entries, comments) where comments maps an entry index ->
    comment lines that appeared directly before that entry (and a leading /
    trailing section for non-entry comments at the file edges)."""
    entries = {}
    comments = {"__lead__": [], "__tail__": []}
    pending = []
    last_idx = None
    with open(path, encoding="utf-8") as f:
        for line in f.read().splitlines():
            m = re.match(r"^(#?\s*)(0x[0-9A-Fa-f]+)\s*:\s*(.*)$", line)
            if m:
                idx = int(m.group(2), 16)
                entries[idx] = (line, m.group(3).strip())
                if pending:
                    comments[idx] = pending
                    pending = []
                last_idx = idx
            else:
                if line.strip():
                    pending.append(line)
                else:
                    pending.append(line)
    if pending:
        comments["__tail__"] = pending
    return entries, comments


def is_bare_flag_text(text):
    """True when the entry text is just a flag mnemonic (e.g. SEEN_TETRA,
    HaveTrinsicPassword) rather than a journal sentence. A sentence always
    contains whitespace, CJK characters, or sentence punctuation."""
    if not text:
        return True
    return not any(ch.isspace() or ord(ch) > 0x2E80 or ch in ".,;:!?''\"" for ch in text)


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--en-baseline", default=None,
                        help="existing autonotes.txt to preserve curated entries from "
                             "(default: the output file itself)")
    parser.add_argument("--zh-baseline", default=None,
                        help="existing autonotes_zh.txt to preserve curated entries from "
                             "(default: the output file itself)")
    args = parser.parse_args()

    en_funcs = collect_all_scripts(ES_DIR)
    zh_funcs = collect_all_scripts(ZH_DIR)

    print(f"EN functions parsed: {len(en_funcs)}")
    print(f"ZH functions parsed: {len(zh_funcs)}")
    print(f"EN flag writes: {sum(len(f['writes']) for f in en_funcs.values())}")

    en_ctx = build_flag_context(en_funcs)
    zh_ctx = build_flag_context(zh_funcs)
    print(f"EN flags with context: {len(en_ctx)}")
    print(f"ZH flags with context: {len(zh_ctx)}")

    existing_en = load_existing(args.en_baseline or EN_OUT)
    existing_zh = load_existing(args.zh_baseline or ZH_OUT)
    en_entries, en_comments = existing_en
    zh_entries, zh_comments = existing_zh

    # the standard header is re-emitted by emit(); drop it from preserved comments
    en_hdr = {l for l in EN_HEADER.splitlines()}
    zh_hdr = {l for l in ZH_HEADER.splitlines()}
    for cm in (en_comments, zh_comments):
        for k in list(cm):
            cm[k] = [l for l in cm[k] if l.strip() not in en_hdr | zh_hdr]

    all_flags = sorted(set(en_entries) | set(en_ctx) | set(zh_ctx))

    en_lines = []
    zh_lines = []
    n_en_gen = n_zh_gen = n_zh_fallback = n_kept_en = n_kept_zh = n_bare = 0

    def emit_en_comments(flag):
        for c in en_comments.get(flag, ()):
            en_lines.append(c)

    def emit_zh_comments(flag):
        for c in zh_comments.get(flag, ()):
            zh_lines.append(c)

    for flag in all_flags:
        emit_en_comments(flag)
        # ------ EN side ------
        en_txt, npc_en = None, None
        if flag in en_ctx:
            en_txt, npc_en = compose_en(flag, en_ctx[flag][1])
        old_line, old_text = en_entries.get(flag, ("", ""))
        is_bare = is_bare_flag_text(old_text)
        if old_line.startswith("#"):
            en_lines.append(old_line)  # commented-out mechanical flag
            n_bare += 1
        elif old_text and not is_bare:
            en_lines.append(old_line)  # hand-written sentence wins
            n_kept_en += 1
        elif en_txt:
            tag = f" [npc={npc_en}]" if npc_en else ""
            en_lines.append(f"0x{flag:X}: {en_txt}{tag}")
            n_en_gen += 1
        else:
            # keep the bare name (or mnemonic) when no dialogue context
            en_lines.append(old_line if old_line else f"0x{flag:X}:FLAG_{flag:X}")
            n_bare += 1

        # ------ ZH side ------
        emit_zh_comments(flag)
        zh_txt, npc_zh = None, None
        if flag in zh_ctx:
            raw = zh_ctx[flag][1].text
            trad = cc.convert(raw)
            blk_copy = DialogBlock(zh_ctx[flag][1].speaker, [trad])
            zh_txt, npc_zh = compose_zh(flag, blk_copy)
        old_line, old_text = zh_entries.get(flag, ("", ""))
        is_bare = is_bare_flag_text(old_text)
        if old_line.startswith("#"):
            zh_lines.append(old_line)
        elif old_text and not is_bare:
            # convert existing curated zh entry to Traditional
            zh_lines.append(f"0x{flag:X}: {cc.convert(old_text)}")
            n_kept_zh += 1
        elif zh_txt:
            tag = f" [npc={npc_zh}]" if npc_zh else ""
            zh_lines.append(f"0x{flag:X}: {zh_txt}{tag}")
            n_zh_gen += 1
        else:
            n_zh_fallback += 1  # no zh entry -> engine falls back to EN

    # Preserve any header/EOF comments from the existing files.
    for c in en_comments.get("__tail__", ()):
        en_lines.append(c)
    for c in zh_comments.get("__tail__", ()):
        zh_lines.append(c)

    def emit(path, header, lines):
        with open(path, "w", encoding="utf-8") as f:
            f.write(header)
            f.write("\n")
            for ln in lines:
                f.write(ln + "\n")

    emit(EN_OUT, EN_HEADER, en_lines)
    emit(ZH_OUT, ZH_HEADER, zh_lines)

    print(f"\nEN: kept curated {n_kept_en}, generated {n_en_gen}, bare {n_bare}, total {len(en_lines)}")
    print(f"ZH: kept curated {n_kept_zh}, generated {n_zh_gen}, en-fallback {n_zh_fallback}, total {len(zh_lines)}")


if __name__ == "__main__":
    main()