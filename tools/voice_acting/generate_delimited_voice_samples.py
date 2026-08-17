#!/usr/bin/env python3
"""Generate delimiter-aware voice samples for narration plus dialogue rows."""

import argparse
import html
import json
import os
import pickle
import re
import sys
from pathlib import Path

import numpy as np
import torch
from zhconv import convert as tc2sc

from generate_qwen3_voice import (
    ATTN_IMPL,
    BASE_MODEL,
    CLONE_PROMPTS_PATH,
    EN_OUTPUT,
    LONG_MAX_TOKENS,
    LONG_TEXT_THRESHOLD,
    MAPPING_PATH,
    PROJECT_DIR,
    SHORT_MAX_TOKENS,
    ZH_OUTPUT,
    build_npc_to_design_map,
    get_design_for_npc,
    load_designs,
    load_mapping,
    make_filename,
    text_hash,
    write_ogg_direct,
)
from qwen_tts import Qwen3TTSModel


SAMPLE_DIR = Path(PROJECT_DIR) / "voice" / "review_samples" / "delimited_dialogue"
HTML_PATH = SAMPLE_DIR / "index.html"
MANIFEST_PATH = SAMPLE_DIR / "manifest.json"
NARRATOR_DESIGN_ID = "npc_unknown"
NARRATOR_NAME = "UNKNOWN"
SPLICE_GAP_MS = 280
SPLICE_FADE_MS = 30


def split_en(text):
    return split_delimited(text, '"', '"')


def split_zh(text):
    return split_delimited(text, "「", "」")


def split_delimited(text, left, right):
    """Return [(role, text)], where role is speaker inside delimiters, narrator outside."""
    parts = []
    i = 0
    in_speaker = False
    start = 0
    while i < len(text):
        token = right if in_speaker else left
        if text.startswith(token, i):
            chunk = text[start:i].strip()
            if chunk:
                parts.append(("speaker" if in_speaker else "narrator", chunk))
            i += len(token)
            start = i
            in_speaker = not in_speaker
            continue
        i += 1
    chunk = text[start:].strip()
    if chunk:
        parts.append(("speaker" if in_speaker else "narrator", chunk))
    return parts


def has_mixed_delimited_text(text, lang):
    parts = split_zh(text) if lang == "zh" else split_en(text)
    roles = {role for role, chunk in parts if chunk.strip()}
    return "speaker" in roles and "narrator" in roles


def display_parts(parts):
    return " | ".join(f"{role}: {chunk}" for role, chunk in parts)


def prompt_for_npc(designs, clone_prompts, npc_to_design, npc, lang):
    did = npc_to_design.get(npc)
    if not did:
        design = get_design_for_npc(designs, npc)
        if design:
            for candidate_id, candidate in designs["designs"].items():
                if npc in candidate.get("npcs", []):
                    did = candidate_id
                    break
    if not did:
        return None, None
    return did, clone_prompts.get(did, {}).get(lang)


def choose_samples(by_npc, designs, clone_prompts, limit):
    npc_to_design = build_npc_to_design_map(designs)
    chosen = []
    seen = set()
    for npc_name in sorted(by_npc):
        if npc_name == NARRATOR_NAME:
            continue
        did, _ = prompt_for_npc(designs, clone_prompts, npc_to_design, npc_name, "en")
        if not did:
            continue
        for entry in by_npc[npc_name]:
            if entry.get("_invalid_runtime_keys"):
                continue
            en = (entry.get("en_text") or "").strip()
            zh = (entry.get("zh_text") or "").strip()
            if not en or not zh:
                continue
            if not has_mixed_delimited_text(en, "en"):
                continue
            if not has_mixed_delimited_text(zh, "zh"):
                continue
            key = (
                entry.get("en_func_id"),
                entry.get("en_offset_key"),
                entry.get("en_segment"),
                npc_name,
            )
            if key in seen:
                continue
            seen.add(key)
            chosen.append(entry)
            break
        if len(chosen) >= limit:
            break
    return chosen


def generate_chunks(model, parts, lang, speaker_prompt, narrator_prompt):
    lang_label = "Chinese" if lang == "zh" else "English"
    rendered_texts = []
    prompts = []
    max_tokens = SHORT_MAX_TOKENS
    for role, text in parts:
        rendered = tc2sc(text, "zh-cn") if lang == "zh" else text
        rendered_texts.append(rendered)
        prompts.append(narrator_prompt if role == "narrator" else speaker_prompt)
        if len(text) > LONG_TEXT_THRESHOLD:
            max_tokens = LONG_MAX_TOKENS
    wavs = []
    sr = None
    for text, prompt in zip(rendered_texts, prompts):
        generated, sr = model.generate_voice_clone(
            text=[text],
            language=[lang_label],
            voice_clone_prompt=prompt,
            max_new_tokens=max_tokens,
        )
        wav = generated[0] if isinstance(generated, (list, tuple)) else generated
        wavs.append(fade_splice_chunk(wav, sr))
    gap = np.zeros(int(sr * SPLICE_GAP_MS / 1000), dtype=np.float32)
    joined = []
    for idx, wav in enumerate(wavs):
        if idx:
            joined.append(gap)
        joined.append(np.asarray(wav, dtype=np.float32))
    return np.concatenate(joined), sr


def fade_splice_chunk(wav, sr):
    """Shape a generated chunk for concatenation without repeating short phrases."""
    wav = np.asarray(wav, dtype=np.float32)
    if wav.size == 0:
        return wav
    fade = min(int(sr * SPLICE_FADE_MS / 1000), wav.size // 2)
    if fade <= 1:
        return wav
    in_curve = np.linspace(0.0, 1.0, fade, dtype=np.float32)
    out_curve = np.linspace(1.0, 0.0, fade, dtype=np.float32)
    wav = wav.copy()
    wav[:fade] *= in_curve
    wav[-fade:] *= out_curve
    return wav


def sample_filename(entry, lang):
    base = Path(make_filename(entry, lang)).stem
    return f"{lang}_{base}_{text_hash(entry.get(lang + '_text', ''))}.ogg"


def write_html(rows):
    rows_html = []
    for row in rows:
        rel_audio = os.path.relpath(row["audio"], HTML_PATH.parent).replace(os.sep, "/")
        rows_html.append(
            f"""
            <tr>
              <td>{html.escape(row['lang'])}</td>
              <td>{html.escape(row['npc'])}</td>
              <td><audio controls preload="metadata" src="{html.escape(rel_audio)}"></audio></td>
              <td><code>{html.escape(row['filename'])}</code></td>
              <td><pre>{html.escape(row['parts'])}</pre></td>
            </tr>
            """
        )
    HTML_PATH.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Delimited Dialogue Voice Samples</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; background: #f7f7f4; color: #202020; }}
    table {{ width: 100%; border-collapse: collapse; background: white; }}
    th, td {{ border: 1px solid #d6d6d0; padding: 8px; vertical-align: top; }}
    th {{ text-align: left; background: #ededE7; }}
    audio {{ width: 280px; }}
    pre {{ white-space: pre-wrap; margin: 0; font-family: ui-monospace, monospace; font-size: 12px; }}
  </style>
</head>
<body>
  <h1>Delimited Dialogue Voice Samples</h1>
  <p>Quoted English text and Chinese 「quoted text」 use the mapped speaker voice. Outside text uses the narrator voice.</p>
  <table>
    <thead><tr><th>Lang</th><th>Speaker</th><th>Audio</th><th>File</th><th>Split Parts</th></tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
  </table>
</body>
</html>
""",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()

    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    designs = load_designs()
    data, by_npc = load_mapping()
    with open(CLONE_PROMPTS_PATH, "rb") as f:
        clone_prompts = pickle.load(f)

    npc_to_design = build_npc_to_design_map(designs)
    narrator_prompt = {
        lang: clone_prompts.get(NARRATOR_DESIGN_ID, {}).get(lang)
        for lang in ("en", "zh")
    }
    missing_narrator = [lang for lang, prompt in narrator_prompt.items() if prompt is None]
    if missing_narrator:
        raise RuntimeError(f"Missing narrator clone prompt for: {', '.join(missing_narrator)}")

    entries = choose_samples(by_npc, designs, clone_prompts, args.limit)
    if not entries:
        raise RuntimeError("No mixed narration/dialogue sample rows found.")

    print(f"Selected {len(entries)} sample rows")
    print(f"Loading {BASE_MODEL}...")
    model = Qwen3TTSModel.from_pretrained(
        BASE_MODEL,
        device_map=args.device,
        dtype=torch.bfloat16,
        attn_implementation=ATTN_IMPL,
    )

    manifest = []
    try:
        for entry in entries:
            npc = entry.get("npc", "") or "UNKNOWN"
            for lang in ("en", "zh"):
                text = (entry.get(f"{lang}_text") or "").strip()
                if not text:
                    continue
                parts = split_zh(text) if lang == "zh" else split_en(text)
                if not has_mixed_delimited_text(text, lang):
                    continue
                _, speaker_prompt = prompt_for_npc(designs, clone_prompts, npc_to_design, npc, lang)
                if speaker_prompt is None:
                    print(f"Skipping {npc} {lang}: missing speaker prompt")
                    continue
                out_path = SAMPLE_DIR / sample_filename(entry, lang)
                if args.force or not out_path.exists():
                    wav, sr = generate_chunks(
                        model,
                        parts,
                        lang,
                        speaker_prompt,
                        narrator_prompt[lang],
                    )
                    write_ogg_direct(
                        out_path,
                        wav,
                        sr,
                        npc=f"delimited:{npc}",
                        text=text,
                        metadata={
                            "VOICE_MODE": "delimited_narrator_speaker",
                            "SPEAKER": npc,
                            "NARRATOR": NARRATOR_DESIGN_ID,
                        },
                    )
                    print(f"Wrote {out_path}")
                manifest.append({
                    "lang": lang,
                    "npc": npc,
                    "filename": out_path.name,
                    "audio": str(out_path),
                    "text": text,
                    "parts": display_parts(parts),
                })
    finally:
        del model
        torch.cuda.empty_cache()

    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_html(manifest)
    print(f"Manifest: {MANIFEST_PATH}")
    print(f"HTML: {HTML_PATH}")


if __name__ == "__main__":
    sys.exit(main())
