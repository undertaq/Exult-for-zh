"""Generate Breeze TTS 2 Voice Design references for the complete U6 NPC catalog.

The model's streaming codec is single-request, so the batch is sharded across
two independent GPU workers. The parent process refreshes the review page as
workers finish jobs.
"""

from __future__ import annotations

import argparse
import html
import json
import multiprocessing as mp
import os
import queue
import re
import traceback
from pathlib import Path
from urllib.parse import quote

import soundfile as sf
from opencc import OpenCC

from breeze_infer.runtime import (
    load_runtime,
    set_all_seeds,
    update_generation_config_for_breeze,
)
from breeze_infer.templates import get_template, prepare_inputs
from models.fast_streaming import FastBreezeStreamingRuntime, FastStreamingConfig


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "u6_voice" / "breeze_tts2_reference_review"
CATALOG = ROOT / "u6_voice" / "u6_npc_voice_designs.json"
PORTRAIT_MAP = OUT / "portrait_map.json"
MODEL = Path("/home/joe/project/breeze-tts/models/Breeze-TTS-2")
S2T = OpenCC("s2twp")
DRY_ZH_SUFFIX = " 錄音請使用近距離、乾淨的錄音棚人聲；不要回聲、混響、重複人聲、背景音樂或環境聲。"

SHARED_REFERENCE_DEFINITIONS = (
    {
        "key": "avatar_male",
        "label": "Avatar · Male",
        "description": "Male Avatar reference voice for player-character dialogue.",
        "files": {
            "en": ROOT / "u6_voice" / "refs" / "npc_avatar_male_en_ref.ogg",
            "zh": ROOT / "u6_voice" / "refs" / "npc_avatar_male_zh_ref.ogg",
        },
    },
    {
        "key": "avatar_female",
        "label": "Avatar · Female",
        "description": "Female Avatar reference voice for player-character dialogue.",
        "files": {
            "en": ROOT / "u6_voice" / "refs" / "npc_avatar_female_en_ref.ogg",
            "zh": ROOT / "u6_voice" / "refs" / "npc_avatar_female_zh_ref.ogg",
        },
    },
    {
        "key": "narrator_male",
        "label": "Narrator · Male",
        "description": "Male narrator reference voice for narration and non-NPC lines.",
        "files": {
            "en": ROOT / "u6_voice" / "refs" / "npc_narrator_male_en_ref.ogg",
            "zh": ROOT / "u6_voice" / "refs" / "npc_narrator_male_zh_ref.ogg",
        },
    },
    {
        "key": "narrator_female",
        "label": "Narrator · Female",
        "description": "Female narrator reference voice for narration and non-NPC lines.",
        "files": {
            # npc_unknown is the established runtime design ID for narrator_female.
            "en": ROOT / "u6_voice" / "refs" / "npc_unknown_en_ref.ogg",
            "zh": ROOT / "u6_voice" / "refs" / "npc_unknown_zh_ref.ogg",
        },
    },
)


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _usable_audio(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size <= 1000:
        return False
    try:
        info = sf.info(path)
    except RuntimeError:
        return False
    return info.samplerate == 24000 and info.channels == 1 and info.frames >= 3 * info.samplerate


def _existing_reference(npc: str, voice_id: str, lang: str, design: dict) -> str:
    override = design.get("reference_overrides", {}).get(lang, {}).get("filename", "")
    candidates = []
    if override:
        candidates.append(ROOT / "voice" / "refs" / Path(override).name)
    candidates.extend(
        [
            ROOT / "voice" / "refs" / f"npc_{_slug(npc)}_{lang}_ref.ogg",
            ROOT / "u6_voice" / "refs" / f"{voice_id}_{lang}_ref.ogg",
        ]
    )
    for path in candidates:
        if path.is_file() and path.stat().st_size > 100:
            return str(path)
    return ""


def _shared_reference_voices() -> list[dict]:
    return [
        {
            "key": definition["key"],
            "label": definition["label"],
            "description": definition["description"],
            "source": "U7 shared runtime reference set",
            "files": {lang: str(path) for lang, path in definition["files"].items()},
        }
        for definition in SHARED_REFERENCE_DEFINITIONS
    ]


def _resolve_casting(design: dict) -> tuple[str, str, str, str, str]:
    """Prefer the character description over conditional transcript labels."""
    casting = design.get("casting_inference", {})
    gender = casting.get("gender", "unknown")
    age = casting.get("age", "adult")
    role = casting.get("role", "NPC")
    description = (design.get("u6_description") or "an Ultima VI NPC").strip()
    primary = description.split(" If ", 1)[0].split(" if ", 1)[0].lower()
    inferred = None
    if re.search(r"\b(man|male|gentleman|boy|king)\b", primary):
        inferred = "male"
    elif re.search(r"\b(woman|female|lady|girl|queen)\b", primary):
        inferred = "female"
    source_gender = gender
    if inferred and gender in {"male", "female"} and inferred != gender:
        gender = inferred
    if "gypsy" in primary:
        role = "gypsy traveler"
    voice_en = design["voice_desc_en"]
    voice_zh = design["voice_desc_zh"]
    if source_gender != gender:
        voice_en = voice_en.replace(source_gender, gender, 1)
        voice_zh = voice_zh.replace("女性" if source_gender == "female" else "男性", "女性" if gender == "female" else "男性", 1)
    return gender, age, role, voice_en, voice_zh


def _load_manifest() -> list[dict]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    designs = catalog["designs"]
    portrait_map = json.loads(PORTRAIT_MAP.read_text(encoding="utf-8")).get("matched", {}) if PORTRAIT_MAP.is_file() else {}
    rows: list[dict] = []
    for index, (voice_id, design) in enumerate(sorted(designs.items(), key=lambda item: item[1]["npc"].casefold())):
        npc = design["npc"]
        casting_status = design.get("casting_status", "approved")
        gender, age, role, voice_en, voice_zh = _resolve_casting(design)
        category = f"{gender}, {role}"
        description = (design.get("u6_description") or "an Ultima VI NPC").strip()
        description_for_prompt = description.split(" If ", 1)[0].split(" if ", 1)[0].rstrip(" :")
        prompt_en = (
            f"{voice_en} Character context from Ultima VI: {description_for_prompt}. "
            "Use a clean close-microphone studio recording with no echo, reverb, duplicated voice, "
            "background music, or ambience."
        )
        gender_constraint = {
            "male": "請明確使用成年男性聲線（男聲），不要使用女性聲線或女聲。",
            "female": "請明確使用成年女性聲線（女聲），不要使用男性聲線或男聲。",
        }.get(gender, "")
        prompt_zh = gender_constraint + S2T.convert(voice_zh) + DRY_ZH_SUFFIX
        portrait = {} if casting_status == "provisional" else portrait_map.get(voice_id, {})
        wiki_url = design.get("wiki_url")
        if wiki_url is None:
            wiki_url = "" if casting_status == "provisional" else f"https://wiki.ultimacodex.com/wiki/{quote(npc.replace(' ', '_'))}"
        for lang, prompt, text in (
            ("en", prompt_en, design["ref_en_text"]),
            ("zh", prompt_zh, S2T.convert(design["ref_zh_text"])),
        ):
            rows.append(
                {
                    "index": len(rows),
                    "npc": npc,
                    "slug": _slug(npc),
                    "voice_id": voice_id,
                    "category": category,
                    "wiki_url": wiki_url,
                    "u6_description": description,
                    "display_description": description_for_prompt + ("." if not description_for_prompt.endswith(".") else ""),
                    "u6_description_source": design.get("u6_description_source", "U6 catalog"),
                    "casting_status": casting_status,
                    "casting_assumption": design.get("casting_assumption", ""),
                    "casting_evidence": design.get("casting_evidence", ""),
                    "provisional_reason": design.get("provisional_reason", ""),
                    "lang": lang,
                    "instruction": prompt,
                    "text": text,
                    "breeze_audio": str(OUT / lang / f"{voice_id}.wav"),
                    "omnivoice_reference": _existing_reference(npc, voice_id, lang, design),
                    "portrait": str(OUT / portrait["file"]) if portrait.get("file") else "",
                    "portrait_source": portrait.get("source_url", ""),
                    "seed": 60000 + index * 2 + (lang == "zh"),
                }
            )
    return rows


def _uri(path: str | Path) -> str:
    return os.path.relpath(Path(path).resolve(), OUT.resolve()).replace(os.sep, "/")


def _write_review(rows: list[dict], completed: int, total: int) -> None:
    shared_references = _shared_reference_voices()
    metadata = {
        "model": "BreezeBlue/Breeze-TTS-2",
        "mode": "Voice Design",
        "voice_design_uses_reference_audio": False,
        "cfg_scale": 4.0,
        "catalog": str(CATALOG.relative_to(ROOT)),
        "portrait_category_url": "https://wiki.ultimacodex.com/wiki/Category:Ultima_VI_Portraits",
        "catalog_designs": len({row["voice_id"] for row in rows}),
        "languages": ["en", "zh"],
        "input_policy": "English uses English design/text input. Chinese uses Traditional Chinese converted with OpenCC s2twp, with close-mic dry-studio/no-echo constraints.",
        "shared_reference_voices": shared_references,
        "provisional_profiles": sorted({row["npc"] for row in rows if row["casting_status"] == "provisional"}, key=str.casefold),
        "clone_generation_gate": "Profiles marked provisional are review-only and excluded from clone routing until explicitly approved.",
        "completed": completed,
        "total": total,
        "rows": rows,
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shared_cards: list[str] = []
    for shared in shared_references:
        sections = []
        for lang, label in (("en", "English"), ("zh", "Traditional Chinese")):
            reference = Path(shared["files"].get(lang, ""))
            if reference.is_file():
                audio = f'<audio controls preload="none" src="{html.escape(_uri(reference))}"></audio>'
            else:
                audio = "<em>Missing reference</em>"
            sections.append(
                f'<p><strong>{label} reference</strong><br>{audio}</p>'
            )
        shared_cards.append(
            f'<div class=shared-card><h3>{html.escape(shared["label"])}</h3>'
            f'<p>{html.escape(shared["description"])} · {html.escape(shared["source"])}</p>'
            f'{"".join(sections)}</div>'
        )
    cards: list[str] = []
    for npc in sorted({row["npc"] for row in rows}, key=str.casefold):
        npc_rows = [row for row in rows if row["npc"] == npc]
        first = npc_rows[0]
        portrait = Path(first["portrait"]) if first["portrait"] else None
        portrait_html = (
            f'<img class=portrait src="{html.escape(_uri(portrait))}" alt="{html.escape(npc)} portrait">'
            if portrait and portrait.is_file() else ""
        )
        provisional_html = ""
        if first["casting_status"] == "provisional":
            provisional_html = f"""
<aside class=provisional><strong>PROVISIONAL CASTING — REVIEW BEFORE CLONING</strong>
<p><b>Temporary casting choice:</b> {html.escape(first['casting_assumption'])}</p>
<p><b>Usecode evidence:</b> {html.escape(first['casting_evidence'])}</p>
<p><b>Why provisional:</b> {html.escape(first['provisional_reason'])}</p>
<p>Reference clips are for review only; clone generation is blocked until this profile is approved.</p>
</aside>"""
        source_links = []
        if first["wiki_url"]:
            source_links.append(f'<a href="{html.escape(first["wiki_url"])}">NPC wiki page</a>')
        if first["portrait_source"]:
            source_links.append(f'<a href="{html.escape(first["portrait_source"])}">portrait source</a>')
        source_line = " · ".join(source_links)
        if not source_line:
            source_line = "No verified NPC wiki or portrait source is available"
        source_line += f" · source: {html.escape(first['u6_description_source'])}"
        if first["casting_status"] == "provisional":
            source_line += " · no verified portrait available"
        sections = []
        for lang, label in (("en", "English"), ("zh", "Traditional Chinese")):
            row = next(item for item in npc_rows if item["lang"] == lang)
            breeze = Path(row["breeze_audio"])
            ready = _usable_audio(breeze)
            omni = Path(row["omnivoice_reference"]) if row["omnivoice_reference"] else None
            omni_html = (
                f'<audio controls preload="none" src="{html.escape(_uri(omni))}"></audio>'
                if omni else "<em>No existing OmniVoice reference</em>"
            )
            breeze_html = (
                f'<audio controls preload="none" src="{html.escape(_uri(breeze))}"></audio>'
                if ready else "<em class=pending>Pending generation</em>"
            )
            sections.append(f"""
<section class=lang><h3>{label} <small>{'ready' if ready else 'pending'}</small></h3>
<p><strong>Design instruction:</strong> {html.escape(row['instruction'])}</p>
<p><strong>Design text:</strong> {html.escape(row['text'])}</p>
<p><strong>Breeze TTS 2 Voice Design</strong><br>{breeze_html}</p>
<p><strong>Existing OmniVoice reference</strong><br>{omni_html}</p>
</section>""")
        cards.append(f"""
<article>{portrait_html}<h2>{html.escape(npc)} <small>{html.escape(first['category'])} · {first['voice_id']}</small></h2>
<p>{html.escape(first['display_description'])}</p>
{provisional_html}
<p>{source_line}</p>
{''.join(sections)}</article>""")
    page = f"""<!doctype html>
<meta charset=utf-8><title>Breeze TTS 2 · Complete U6 NPC Reference Review</title>
<style>
body{{max-width:1200px;margin:2rem auto;padding:0 1rem;font:15px system-ui,sans-serif;line-height:1.5;color:#222}}
header{{position:sticky;top:0;background:#fff;padding:.75rem 0;border-bottom:1px solid #ccc;z-index:2}}
input{{width:20rem;padding:.45rem}}article{{border:1px solid #ccc;border-radius:9px;padding:1rem;margin:1rem 0;min-height:150px}}
.portrait{{float:left;width:112px;height:128px;object-fit:contain;margin:0 1rem .5rem 0;background:#eee;border-radius:5px}}
h2{{margin:.1rem 0}}small{{font-size:.72em;color:#666;font-weight:normal}}.lang{{background:#f7f7f7;border-radius:7px;padding:.7rem;margin-top:.8rem}}
.shared-card{{border:1px solid #9ab;border-radius:9px;padding:1rem;margin:1rem 0;background:#f4f8fb}}
.provisional{{display:block;clear:both;border:2px solid #b45309;background:#fff7ed;color:#7c2d12;border-radius:7px;padding:.75rem;margin:.75rem 0}}
audio{{width:100%}}.pending{{color:#a60}}code{{word-break:break-all}}
</style>
<header><h1>Breeze TTS 2 · Complete U6 NPC Voice Design Review</h1>
<p>Progress: <strong>{completed}/{total}</strong> clips. Refresh this page during generation. This batch contains all {len({row['voice_id'] for row in rows})} catalog NPC designs in English and Traditional Chinese. The shared runtime references below include both Avatar genders and both narrator genders. Portraits come from the <a href="https://wiki.ultimacodex.com/wiki/Category:Ultima_VI_Portraits">Ultima VI portrait category</a>. Breeze Voice Design uses no reference audio and <code>cfg_scale=4</code>. Chinese instructions request dry close-mic speech without echo/reverb and explicitly enforce the catalog gender. Profiles marked provisional are review-only and cannot enter clone generation until approved.</p>
<input id=q placeholder="Filter NPC or role" oninput="filterCards()"></header>
<section id=shared-voices><h2>Shared runtime reference voices</h2>
{''.join(shared_cards)}
</section>
{''.join(cards)}
<script>function filterCards(){{const q=document.getElementById('q').value.toLowerCase();for(const a of document.querySelectorAll('article'))a.hidden=!a.innerText.toLowerCase().includes(q);}}</script>
"""
    (OUT / "index.html").write_text(page, encoding="utf-8")


def _worker(rows: list[dict], gpu: int, events: mp.Queue, force: bool, force_npcs: set[str]) -> None:
    try:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu)
        tokenizer, model, audio_tokenizer = load_runtime(MODEL, device="cuda:0", attn_implementation="eager")
        update_generation_config_for_breeze(model)
        runtime = FastBreezeStreamingRuntime(
            model,
            audio_tokenizer,
            FastStreamingConfig(max_new_tokens=1500, max_seq_len=2048, repetition_penalty=1.1),
            tokenizer=tokenizer,
        )
        template = get_template("tts_instruction")
        for row in rows:
            output = Path(row["breeze_audio"])
            output.parent.mkdir(parents=True, exist_ok=True)
            if not force and row["npc"] not in force_npcs and _usable_audio(output):
                events.put({"kind": "done", "index": row["index"], "status": "exists", "gpu": gpu})
                continue
            request = {
                "id": f"full-{row['voice_id']}-{row['lang']}",
                "text": row["text"],
                "speaker": "S0",
                "instruction": row["instruction"],
            }
            set_all_seeds(row["seed"])
            inputs = prepare_inputs(
                tokenizer, audio_tokenizer, model, [request], template,
                guidance_scale=4.0, guidance_scale_ref=None, guidance_scale_ins=None,
            )
            partial = output.with_name(f".{output.stem}.{os.getpid()}.partial.wav")
            try:
                with sf.SoundFile(partial, mode="w", samplerate=runtime.sample_rate, channels=1, subtype="PCM_16") as out:
                    for chunk in runtime.iter_audio_chunks(inputs, request_id=request["id"], seed=row["seed"]):
                        out.write(chunk.audio)
                os.replace(partial, output)
            except BaseException:
                partial.unlink(missing_ok=True)
                raise
            events.put({"kind": "done", "index": row["index"], "status": "saved", "gpu": gpu})
        events.put({"kind": "worker_done", "gpu": gpu})
    except BaseException:
        events.put({"kind": "error", "gpu": gpu, "error": traceback.format_exc()})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-every", type=int, default=4)
    parser.add_argument("--resume", action="store_true", help="reuse valid existing clips instead of regenerating all")
    parser.add_argument("--force-npc", action="append", default=[], help="regenerate this NPC when resuming; repeatable")
    args = parser.parse_args()
    if args.review_every < 1:
        parser.error("--review-every must be at least 1")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "en").mkdir(parents=True, exist_ok=True)
    (OUT / "zh").mkdir(parents=True, exist_ok=True)
    rows = _load_manifest()
    _write_review(rows, 0, len(rows))
    shards = [rows[0::2], rows[1::2]]
    ctx = mp.get_context("spawn")
    events = ctx.Queue()
    force_npcs = set(args.force_npc)
    workers = [ctx.Process(target=_worker, args=(shard, gpu, events, not args.resume, force_npcs), daemon=False) for gpu, shard in enumerate(shards)]
    for worker in workers:
        worker.start()
    completed = 0
    finished_workers = 0
    try:
        while finished_workers < len(workers):
            try:
                event = events.get(timeout=30)
            except queue.Empty:
                print("waiting for GPU workers...", flush=True)
                continue
            if event["kind"] == "done":
                completed += 1
                print(f"[{completed}/{len(rows)}] gpu={event['gpu']} {event['status']} row={event['index']}", flush=True)
                if completed % args.review_every == 0:
                    _write_review(rows, completed, len(rows))
                    print(f"review refreshed: {OUT / 'index.html'}", flush=True)
            elif event["kind"] == "worker_done":
                finished_workers += 1
                print(f"GPU {event['gpu']} worker complete", flush=True)
            elif event["kind"] == "error":
                raise RuntimeError(f"GPU {event['gpu']} worker failed:\n{event['error']}")
    except BaseException:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
        raise
    finally:
        for worker in workers:
            worker.join()
    _write_review(rows, completed, len(rows))
    print(f"complete: {completed}/{len(rows)} clips; review: {OUT / 'index.html'}", flush=True)


if __name__ == "__main__":
    mp.freeze_support()
    main()
