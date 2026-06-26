#!/usr/bin/env python3
"""
Qwen3-TTS Voice Generation for Exult-for-zh.

Pipeline:
  1. Load bilingual mapping (9102 entries with NPC profiles).
  2. Group entries by NPC name.
  3. For each NPC:
     a. Generate ONE reference audio via VoiceDesign model
        using the NPC's voice_prompt as instruct.
     b. Build a reusable voice clone prompt from that reference.
     c. Generate ALL lines for this NPC via voice clone in batches.
  Output: <PATCH>/voice_acting/<func_id>_<offset_key>_<segment>.wav

Usage:
  python generate_qwen3_voice.py [--dry-run] [--resume]
"""

import argparse
import json
import os
import sys
import time
import gc
from collections import defaultdict

import torch
import soundfile as sf


# ── Config ────────────────────────────────────────────────────────────
PATCH = r'D:\Game\Ultima7_BlackGate_zhTW_v1.0\Ultima_7\patch'
OUTPUT_DIR = os.path.join(PATCH, 'voice_acting')
MAPPING_PATH = os.path.join(os.path.dirname(__file__), 'bilingual_mapping_review.json')
REF_DIR = os.path.join(OUTPUT_DIR, '_references')  # NPC reference audio

VOICEDESIGN_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
BASE_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"

# sdpa (flash-attn-2 Windows build has degraded batch performance)
ATTN_IMPL = "sdpa"

BATCH_SIZE = 32         # lines per generation call (BS=32 → 285ms/line on RTX 3080)
MAX_NEW_TOKENS = 4096

# Make one-character lines work (e.g. "Hi!", "Yes?")
MIN_DURATION_MS = 1500  # pad output shorter than this


# ── helpers ───────────────────────────────────────────────────────────

def make_filename(entry):
    fid = entry.get('zh_func_id', '') or entry.get('en_func_id', '') or '0000'
    ok = entry.get('zh_offset_key', '') or '0'
    seg = entry.get('zh_segment', 0) or 0
    if fid.startswith('0x') or fid.startswith('0X'):
        fid = fid[2:]
    fid = fid.lower().zfill(4)
    return f'{fid}_{ok}_{seg}.wav'


def make_ref_filename(npc):
    safe = ''.join(c if c.isalnum() or c in ' -_' else '_' for c in npc)
    return f'ref_{safe}.wav'


def load_mapping():
    with open(MAPPING_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Group by NPC
    by_npc = defaultdict(list)
    for entry in data:
        npc = entry.get('npc', '') or 'UNKNOWN'
        by_npc[npc].append(entry)
    return data, by_npc


def generate_reference(model, npc, entries):
    """Generate one reference audio for this NPC using VoiceDesign."""
    prof = entries[0]
    instruct = prof.get('voice_prompt', '')
    lang = 'English'  # instruct in English works for any language

    # Pick a good reference text (~5 seconds of speech)
    ref_text = None
    for e in entries:
        zh = e.get('zh_text', '')
        if len(zh) > 15 and len(zh) < 100:
            ref_text = zh
            break
    if not ref_text:
        for e in entries:
            zh = e.get('zh_text', '')
            if zh:
                ref_text = zh
                break
    if not ref_text:
        ref_text = f'你好，我是{npc}。'

    print(f'  Reference text ({len(ref_text)} chars): {ref_text[:60]}...')
    print(f'  Instruct: {instruct[:80]}...')

    wavs, sr = model.generate_voice_design(
        text=ref_text,
        language='Chinese',
        instruct=instruct,
        max_new_tokens=MAX_NEW_TOKENS,
    )
    return wavs[0], sr


def ensure_minimum_duration(wav, sr, min_ms=MIN_DURATION_MS):
    """If the generated audio is very short (common for 1-word lines),
    gently pad it by looping so the game doesn't clip it instantly."""
    import numpy as np
    needed_samples = int(sr * min_ms / 1000)
    if len(wav) < needed_samples:
        repeats = int(np.ceil(needed_samples / len(wav)))
        wav = np.tile(wav, repeats)[:needed_samples]
    return wav


def generate_npc_lines(model, npc, entries, prompt_items, sr):
    """Generate all voice lines for one NPC using the clone prompt."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    generated = 0
    skipped = 0
    errors = 0

    for i in range(0, len(entries), BATCH_SIZE):
        batch = entries[i:i + BATCH_SIZE]

        # Check which files already exist
        to_generate = []
        for e in batch:
            fname = make_filename(e)
            fpath = os.path.join(OUTPUT_DIR, fname)
            if os.path.exists(fpath):
                skipped += 1
            else:
                to_generate.append(e)

        if not to_generate:
            continue

        texts = [e.get('zh_text', '') or '...' for e in to_generate]
        langs = ['Chinese'] * len(texts)

        try:
            wavs, out_sr = model.generate_voice_clone(
                text=texts,
                language=langs,
                voice_clone_prompt=prompt_items,
                max_new_tokens=MAX_NEW_TOKENS,
            )
        except Exception as ex:
            print(f'  ERROR generating batch starting at index {batch[0].get("index", "?")}: {ex}')
            errors += len(to_generate)
            continue

        for j, e in enumerate(to_generate):
            fname = make_filename(e)
            fpath = os.path.join(OUTPUT_DIR, fname)
            try:
                wav_out = wavs[j] if j < len(wavs) else wavs[0]
                wav_out = ensure_minimum_duration(wav_out, out_sr)
                sf.write(fpath, wav_out, out_sr)
                generated += 1
            except Exception as ex:
                print(f'  ERROR writing {fname}: {ex}')
                errors += 1

    return generated, skipped, errors


# ── main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Qwen3-TTS voice generation')
    parser.add_argument('--dry-run', action='store_true', help='Scan and report only')
    parser.add_argument('--resume', action='store_true', help='Skip existing files')
    parser.add_argument('--npc', type=str, default=None, help='Single NPC to generate (for testing)')
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(REF_DIR, exist_ok=True)

    data, by_npc = load_mapping()
    print(f'Loaded {len(data)} entries across {len(by_npc)} NPCs')

    if args.npc:
        by_npc = {args.npc: by_npc.get(args.npc, [])}
        if not list(by_npc.values())[0]:
            print(f'NPC "{args.npc}" not found!')
            sys.exit(1)
        print(f'Filtered to single NPC: {args.npc} ({len(by_npc[args.npc])} lines)')

    total_gen = 0
    total_skipped = 0
    total_errors = 0

    voice_design_model = None
    base_model = None

    try:
        # ── Phase 1: VoiceDesign for all NPCs ──
        print('\n=== Phase 1: Generating reference audio via VoiceDesign ===')
        print(f'Loading {VOICEDESIGN_MODEL}...')
        voice_design_model = Qwen3TTSModel.from_pretrained(
            VOICEDESIGN_MODEL,
            device_map='cuda:0',
            dtype=torch.bfloat16,
            attn_implementation=ATTN_IMPL,
        )

        for npc_name, entries in by_npc.items():
            ref_path = os.path.join(REF_DIR, make_ref_filename(npc_name))
            if args.resume and os.path.exists(ref_path):
                print(f'[{npc_name}] Reference exists, skipping')
                continue

            print(f'\n[{npc_name}] Generating reference ({len(entries)} lines)...')
            if args.dry_run:
                continue

            wav, sr = generate_reference(voice_design_model, npc_name, entries)
            sf.write(ref_path, wav, sr)
            print(f'  Saved reference: {ref_path} ({len(wav)/sr:.1f}s)')

        # Free VoiceDesign model
        print('\nUnloading VoiceDesign model...')
        del voice_design_model
        voice_design_model = None
        gc.collect()
        torch.cuda.empty_cache()

        if args.dry_run:
            print('\nDry-run complete. No files generated.')
            return

        # ── Phase 2: Voice Clone for all lines ──
        print('\n=== Phase 2: Generating voice lines via Voice Clone ===')
        print(f'Loading {BASE_MODEL}...')
        base_model = Qwen3TTSModel.from_pretrained(
            BASE_MODEL,
            device_map='cuda:0',
            dtype=torch.bfloat16,
            attn_implementation=ATTN_IMPL,
        )

        for npc_name, entries in by_npc.items():
            ref_path = os.path.join(REF_DIR, make_ref_filename(npc_name))

            if not os.path.exists(ref_path):
                print(f'[WARN] No reference for [{npc_name}], skipping')
                continue

            print(f'\n[{npc_name}] Generating {len(entries)} lines...')

            # Load reference and build clone prompt
            ref_wav, ref_sr = sf.read(ref_path)
            ref_text = None
            for e in entries:
                zh = e.get('zh_text', '')
                if len(zh) > 15 and len(zh) < 100:
                    ref_text = zh
                    break
            if not ref_text:
                ref_text = entries[0].get('zh_text', '') or f'你好，我是{npc_name}。'

            prompt_items = base_model.create_voice_clone_prompt(
                ref_audio=(ref_wav, ref_sr),
                ref_text=ref_text,
            )

            gen, skip, err = generate_npc_lines(base_model, npc_name, entries, prompt_items, ref_sr)
            total_gen += gen
            total_skipped += skip
            total_errors += err
            print(f'  Generated: {gen}, Skipped: {skip}, Errors: {err}')

    finally:
        for m in ['voice_design_model', 'base_model']:
            obj = locals().get(m)
            if obj is not None:
                del obj
        gc.collect()
        torch.cuda.empty_cache()

    print(f'\n{"="*50}')
    print(f'Done! Generated: {total_gen}, Skipped: {total_skipped}, Errors: {total_errors}')
    print(f'Output: {OUTPUT_DIR}')


from qwen_tts import Qwen3TTSModel

if __name__ == '__main__':
    main()
