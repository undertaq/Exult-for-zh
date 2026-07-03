#!/usr/bin/env python3
"""
3-Stage Voice Generation Pipeline for Exult-for-zh.

Phase A: Generate VoiceDesign reference clips per NPC voice design
Phase B: Build clone prompts from reference clips
Phase C: Bulk generate ALL ZH + EN voice files via VoiceClone

Models used:
  - Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign  (Phase A)
  - Qwen/Qwen3-TTS-12Hz-1.7B-Base          (Phase B + C)
"""
import argparse
import gc
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import time
import pickle
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import soundfile as sf
from zhconv import convert as tc2sc

from qwen_tts import Qwen3TTSModel

# ── Config ────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
OUTPUT_DIR = os.path.join(PROJECT_DIR, 'voice')
ZH_OUTPUT = os.path.join(OUTPUT_DIR, 'zh')
EN_OUTPUT = os.path.join(OUTPUT_DIR, 'en')
REFS_DIR = os.path.join(SCRIPT_DIR, 'refs')

MAPPING_PATH = os.path.join(SCRIPT_DIR, 'bilingual_mapping_review.json')
DESIGNS_PATH = os.path.join(SCRIPT_DIR, 'npc_voice_designs.json')
PROMPTS_ZH_PATH = os.path.join(SCRIPT_DIR, 'voice_prompt_zh.json')
CLONE_PROMPTS_PATH = os.path.join(SCRIPT_DIR, 'clone_prompts.pkl')

VOICEDESIGN_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
BASE_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
ATTN_IMPL = "sdpa"
BATCH_SIZE_PHASE_C = 8
MIN_DURATION_MS = 1500
LONG_TEXT_THRESHOLD = 100
SHORT_MAX_TOKENS = 256
LONG_MAX_TOKENS = 1024


# ── Helpers ───────────────────────────────────────────────────────────

def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def make_filename(entry, lang='zh'):
    fid_key = f'{lang}_func_id'
    ok_key = f'{lang}_offset_key'
    seg_key = f'{lang}_segment'
    fid = entry.get(fid_key, '') or entry.get('zh_func_id', '') or entry.get('en_func_id', '') or '0000'
    ok = entry.get(ok_key, '') or '0'
    seg = entry.get(seg_key, 0) or 0
    if isinstance(fid, str) and (fid.startswith('0x') or fid.startswith('0X')):
        fid = fid[2:]
    fid = str(fid).lower().zfill(4)
    return f'{fid}_{ok}_{seg}.ogg'


def ensure_minimum_duration(wav, sr, min_ms=MIN_DURATION_MS):
    needed = int(sr * min_ms / 1000)
    if len(wav) < needed:
        repeats = int(np.ceil(needed / len(wav)))
        wav = np.tile(wav, repeats)[:needed]
    return wav


def write_ogg_direct(filepath, wav, sr, npc='', text=''):
    title = text_hash(text) if text else ''
    artist = f'qwen3:{npc}' if npc else 'qwen3'
    description = text or ''
    wav = np.asarray(wav, dtype=np.float32)

    cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
        '-f', 'f32le', '-ar', str(sr), '-ac', '1', '-i', 'pipe:0',
        '-c:a', 'libvorbis', '-q:a', '2',
    ]
    if title:
        cmd += ['-metadata', f'TITLE={title}']
    if artist:
        cmd += ['-metadata', f'ARTIST={artist}']
    if description:
        cmd += ['-metadata', f'DESCRIPTION={description}']
    cmd.append(str(filepath))

    raw = wav.tobytes()
    subprocess.run(cmd, input=raw, capture_output=True, check=True)


def load_mapping():
    with open(MAPPING_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    # Group by NPC name
    by_npc = defaultdict(list)
    for entry in data:
        npc = entry.get('npc', '') or 'UNKNOWN'
        by_npc[npc].append(entry)
    return data, by_npc


def load_designs():
    with open(DESIGNS_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_prompt_zh():
    with open(PROMPTS_ZH_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_design_for_npc(designs, npc_name):
    """Find the design entry that contains this NPC."""
    for did, design in designs['designs'].items():
        if npc_name in design['npcs']:
            return design
    return None


# ── Phase A: VoiceDesign Reference Generation ─────────────────────────

def phase_a_generate_refs(designs, args):
    """Generate reference clips for each voice design using VoiceDesign."""
    os.makedirs(REFS_DIR, exist_ok=True)
    prompt_zh = load_prompt_zh()

    print(f'\n{"="*60}')
    print('Phase A: Generating VoiceDesign reference clips')
    print(f'{"="*60}')

    print(f'\nLoading {VOICEDESIGN_MODEL}...')
    model = Qwen3TTSModel.from_pretrained(
        VOICEDESIGN_MODEL,
        device_map=args.device,
        dtype=torch.bfloat16,
        attn_implementation=ATTN_IMPL,
    )

    total = 0
    skipped = 0
    errors = 0

    try:
        for did, design in sorted(designs['designs'].items()):
            npc_label = design.get('npc', did)
            ref_zh_path = os.path.join(REFS_DIR, f'{did}_zh_ref.ogg')
            ref_en_path = os.path.join(REFS_DIR, f'{did}_en_ref.ogg')

            # ZH reference
            zh_text = design.get('ref_zh_text', '')
            if not zh_text:
                print(f'  [{npc_label}] No ZH ref text, skipping')
                skipped += 1
            elif os.path.exists(ref_zh_path) and not args.force_refs:
                print(f'  [{npc_label}] ZH ref exists, skipping')
                skipped += 1
            else:
                zh_desc = design.get('voice_desc_zh', '')
                if not zh_desc:
                    zh_desc = '用標準的普通話朗讀'
                # Convert to Simplified Chinese
                zh_text_sc = tc2sc(zh_text, 'zh-cn')
                if args.dry_run:
                    print(f'  [{npc_label}] Would generate ZH ref: {zh_text_sc[:60]}...')
                    continue
                try:
                    wavs, sr = model.generate_voice_design(
                        text=zh_text_sc,
                        language='Chinese',
                        instruct=zh_desc,
                        max_new_tokens=SHORT_MAX_TOKENS,
                        non_streaming_mode=True,
                    )
                    wav_out = ensure_minimum_duration(wavs[0], sr)
                    write_ogg_direct(ref_zh_path, wav_out, sr, npc_label, zh_text_sc)
                    total += 1
                    print(f'  [{npc_label}] ZH ref generated ({len(wav_out)/sr:.1f}s)')
                except Exception as ex:
                    print(f'  [{npc_label}] ZH ref ERROR: {ex}')
                    errors += 1

            # EN reference
            en_text = design.get('ref_en_text', '')
            if not en_text:
                print(f'  [{npc_label}] No EN ref text, skipping')
                skipped += 1
            elif os.path.exists(ref_en_path) and not args.force_refs:
                print(f'  [{npc_label}] EN ref exists, skipping')
                skipped += 1
            else:
                en_desc = design.get('voice_desc_en', '')
                if not en_desc:
                    en_desc = 'Neutral clear speaking voice, natural and pleasant'
                if args.dry_run:
                    print(f'  [{npc_label}] Would generate EN ref: {en_text[:60]}...')
                    continue
                try:
                    wavs, sr = model.generate_voice_design(
                        text=en_text,
                        language='English',
                        instruct=en_desc,
                        max_new_tokens=SHORT_MAX_TOKENS,
                        non_streaming_mode=True,
                    )
                    wav_out = ensure_minimum_duration(wavs[0], sr)
                    write_ogg_direct(ref_en_path, wav_out, sr, npc_label, en_text)
                    total += 1
                    print(f'  [{npc_label}] EN ref generated ({len(wav_out)/sr:.1f}s)')
                except Exception as ex:
                    print(f'  [{npc_label}] EN ref ERROR: {ex}')
                    errors += 1

            gc.collect()
            torch.cuda.empty_cache()

    finally:
        del model
        gc.collect()
        torch.cuda.empty_cache()

    print(f'\nPhase A complete. Generated: {total}, Skipped: {skipped}, Errors: {errors}')
    return total, skipped, errors


# ── Phase B + C: Clone Prompts + Bulk Generation ──────────────────────

def build_npc_to_design_map(designs):
    """Build a reverse mapping from NPC name -> design ID."""
    npc_to_design = {}
    for did, design in designs['designs'].items():
        for npc_name in design['npcs']:
            npc_to_design[npc_name] = did
    return npc_to_design


def phase_b_build_prompts(designs, args):
    """Build clone prompts from reference clips."""
    os.makedirs(REFS_DIR, exist_ok=True)

    print(f'\n{"="*60}')
    print('Phase B: Building clone prompts from reference clips')
    print(f'{"="*60}')

    print(f'\nLoading {BASE_MODEL}...')
    model = Qwen3TTSModel.from_pretrained(
        BASE_MODEL,
        device_map=args.device,
        dtype=torch.bfloat16,
        attn_implementation=ATTN_IMPL,
    )

    clone_prompts = {}
    total = 0
    errors = 0

    try:
        for did, design in sorted(designs['designs'].items()):
            npc_label = design.get('npc', did)
            ref_zh_path = os.path.join(REFS_DIR, f'{did}_zh_ref.ogg')
            ref_en_path = os.path.join(REFS_DIR, f'{did}_en_ref.ogg')

            prompt = {'zh': None, 'en': None}

            for lang, ref_path, ref_text_key in [
                ('zh', ref_zh_path, 'ref_zh_text'),
                ('en', ref_en_path, 'ref_en_text'),
            ]:
                ref_text = design.get(ref_text_key, '')
                if not ref_text:
                    print(f'  [{npc_label}] {lang}: No ref text, skipping')
                    continue
                if not os.path.exists(ref_path):
                    print(f'  [{npc_label}] {lang}: Ref file not found: {ref_path}')
                    errors += 1
                    continue

                if args.dry_run:
                    print(f'  [{npc_label}] {lang}: Would build prompt from {ref_path}')
                    continue

                try:
                    prompt_data = model.create_voice_clone_prompt(
                        ref_audio=ref_path,
                        ref_text=ref_text,
                    )
                    prompt[lang] = prompt_data
                    total += 1
                    print(f'  [{npc_label}] {lang}: Prompt built')
                except Exception as ex:
                    print(f'  [{npc_label}] {lang}: Prompt ERROR: {ex}')
                    errors += 1

            clone_prompts[did] = prompt

            gc.collect()
            torch.cuda.empty_cache()

    finally:
        del model
        gc.collect()
        torch.cuda.empty_cache()

    # Save prompts
    with open(CLONE_PROMPTS_PATH, 'wb') as f:
        pickle.dump(clone_prompts, f)
    print(f'\nClone prompts saved to {CLONE_PROMPTS_PATH}')

    print(f'Phase B complete. Built: {total}, Errors: {errors}')
    return clone_prompts, total, errors


def phase_c_generate_voice(designs, clone_prompts, by_npc, args):
    """Bulk generate all ZH + EN voice files via VoiceClone."""
    os.makedirs(ZH_OUTPUT, exist_ok=True)
    os.makedirs(EN_OUTPUT, exist_ok=True)

    print(f'\n{"="*60}')
    print('Phase C: Bulk generating voice files via VoiceClone')
    print(f'{"="*60}')

    print(f'\nLoading {BASE_MODEL}...')
    model = Qwen3TTSModel.from_pretrained(
        BASE_MODEL,
        device_map=args.device,
        dtype=torch.bfloat16,
        attn_implementation=ATTN_IMPL,
    )

    total_gen = 0
    total_skip = 0
    total_err = 0

    # Build NPC → design lookup
    npc_to_design = build_npc_to_design_map(designs)

    try:
        for lang in ['zh', 'en']:
            lang_label = 'Chinese' if lang == 'zh' else 'English'
            out_dir = ZH_OUTPUT if lang == 'zh' else EN_OUTPUT
            text_key = f'{lang}_text'

            print(f'\n{"-"*50}')
            print(f'Generating {lang_label} lines')
            print(f'{"-"*50}')

            npcs_in_lang = sorted([n for n in by_npc.keys()])
            progress_npc = 0

            for npc_name in npcs_in_lang:
                entries = by_npc[npc_name]
                design = get_design_for_npc(designs, npc_name)
                if not design:
                    print(f'  [{npc_name}] No voice design found, skipping {len(entries)} lines')
                    total_err += len(entries)
                    continue

                did = None
                for d_id, d in designs['designs'].items():
                    if npc_name in d['npcs']:
                        did = d_id
                        break

                prompt_data = clone_prompts.get(did, {}).get(lang)
                if prompt_data is None:
                    print(f'  [{npc_name}] No clone prompt for {lang}, skipping {len(entries)} lines')
                    total_err += len(entries)
                    continue

                # Filter entries with text for this language
                lang_entries = [e for e in entries if e.get(text_key, '').strip()]
                if not lang_entries:
                    continue

                progress_npc += 1
                if args.max_npcs and progress_npc > args.max_npcs:
                    break

                # Process in batches
                lang_entries.sort(key=lambda e: len(e.get(text_key, '')))
                generated = 0
                skipped = 0
                errors = 0

                for i in range(0, len(lang_entries), BATCH_SIZE_PHASE_C):
                    batch = lang_entries[i:i + BATCH_SIZE_PHASE_C]
                    to_generate = []

                    for e in batch:
                        fname = make_filename(e, lang)
                        ogg_path = os.path.join(out_dir, fname)
                        if os.path.exists(ogg_path) and not args.force:
                            skipped += 1
                        else:
                            e['_ogg_path'] = ogg_path
                            to_generate.append(e)

                    if not to_generate:
                        continue

                    texts = []
                    max_tokens = SHORT_MAX_TOKENS
                    for e in to_generate:
                        t = e.get(text_key, '') or '...'
                        if lang == 'zh':
                            t = tc2sc(t, 'zh-cn')
                        texts.append(t)
                        if len(e.get(text_key, '')) > LONG_TEXT_THRESHOLD:
                            max_tokens = LONG_MAX_TOKENS

                    # VoiceClone batch generation
                    try:
                        wavs, sr = model.generate_voice_clone(
                            text=texts,
                            language=[lang_label] * len(texts),
                            voice_clone_prompt=prompt_data,
                            max_new_tokens=max_tokens,
                        )
                    except Exception as ex:
                        print(f'  [{npc_name}] Batch ERROR: {ex}')
                        errors += len(to_generate)
                        continue

                    for j, e in enumerate(to_generate):
                        try:
                            wav_out = wavs[j] if j < len(wavs) else wavs[0]
                            wav_out = ensure_minimum_duration(wav_out, sr)
                            write_ogg_direct(
                                e['_ogg_path'], wav_out, sr,
                                npc_name, e.get(text_key, '')
                            )
                            generated += 1
                        except Exception as ex:
                            print(f'  [{npc_name}] Write ERROR {e["_ogg_path"]}: {ex}')
                            errors += 1

                    del wavs, sr, texts
                    if i > 0 and (i // BATCH_SIZE_PHASE_C) % 4 == 0:
                        gc.collect()
                        torch.cuda.empty_cache()

                total_gen += generated
                total_skip += skipped
                total_err += errors

                if generated > 0 or skipped > 0:
                    status = f'  [{npc_name}] Gen:{generated} Skip:{skipped} Err:{errors}'
                    if args.dry_run:
                        status = f'  [{npc_name}] Would generate {len(lang_entries)} lines'
                    print(status)

                gc.collect()
                torch.cuda.empty_cache()

    finally:
        del model
        gc.collect()
        torch.cuda.empty_cache()

    print(f'\nPhase C complete. Generated: {total_gen}, Skipped: {total_skip}, Errors: {total_err}')

    # File size summary
    print(f'\nFile size summary:')
    for label, d in [('ZH', ZH_OUTPUT), ('EN', EN_OUTPUT)]:
        if not os.path.isdir(d):
            continue
        files = [f for f in os.listdir(d) if f.endswith('.ogg')]
        if files:
            sizes = [os.path.getsize(os.path.join(d, f)) for f in files]
            small = sum(1 for s in sizes if s < 50000)
            mid = sum(1 for s in sizes if 50000 <= s < 150000)
            large = sum(1 for s in sizes if s >= 150000)
            print(f'  {label}: {len(files)} files | <50K:{small} 50-150K:{mid} >150K:{large}')

    return total_gen, total_skip, total_err


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='3-stage Qwen3-TTS voice generation')
    parser.add_argument('--phase', type=str, default='all',
                        choices=['all', 'refs', 'prompts', 'voice'],
                        help='Which phase to run (default: all)')
    parser.add_argument('--dry-run', action='store_true', help='Scan and report only')
    parser.add_argument('--force', action='store_true', help='Force regenerate existing files')
    parser.add_argument('--force-refs', action='store_true', help='Force regenerate reference clips')
    parser.add_argument('--device', type=str, default='cuda:0', help='CUDA device')
    parser.add_argument('--npc', type=str, default=None, help='Single NPC to generate (Phase C only)')
    parser.add_argument('--max-npcs', type=int, default=None, help='Limit number of NPCs to process')
    args = parser.parse_args()

    # Load data
    designs = load_designs()
    data, by_npc = load_mapping()

    print(f'Loaded {len(data)} entries across {len(by_npc)} NPCs')
    print(f'Voice designs: {designs["_meta"]["total_designs"]} total')
    print(f'  Unique: {designs["_meta"]["unique_designs"]}')
    print(f'  Groups: {designs["_meta"]["group_designs"]}')
    print(f'  Narrator: {designs["_meta"]["narrator_designs"]}')

    if args.npc:
        by_npc = {args.npc: by_npc.get(args.npc, [])}
        if not list(by_npc.values())[0]:
            print(f'NPC "{args.npc}" not found!')
            sys.exit(1)
        print(f'Filtered to single NPC: {args.npc} ({len(by_npc[args.npc])} lines)')

    # Phase A: Generate reference clips
    if args.phase in ('all', 'refs'):
        phase_a_generate_refs(designs, args)

    # Phase B + C: Build prompts and generate voice
    if args.phase in ('all', 'prompts', 'voice'):
        clone_prompts = {}

        if args.phase == 'all' or args.phase == 'prompts':
            clone_prompts_result = phase_b_build_prompts(designs, args)
            clone_prompts = clone_prompts_result[0]
        else:
            # Load existing prompts
            if not os.path.exists(CLONE_PROMPTS_PATH):
                print(f'No clone prompts found at {CLONE_PROMPTS_PATH}')
                print('Run phase "prompts" first')
                sys.exit(1)
            with open(CLONE_PROMPTS_PATH, 'rb') as f:
                clone_prompts = pickle.load(f)
            print(f'Loaded {len(clone_prompts)} clone prompts from {CLONE_PROMPTS_PATH}')

        if args.phase in ('all', 'voice'):
            phase_c_generate_voice(designs, clone_prompts, by_npc, args)


if __name__ == '__main__':
    main()
