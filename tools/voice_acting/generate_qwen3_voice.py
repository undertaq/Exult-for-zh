#!/usr/bin/env python3
"""
Qwen3-TTS Voice Generation for Exult-for-zh.

Bilingual pipeline using VoiceDesign direct (no voice clone):

  Phase 1: ZH — VoiceDesign + Simplified Chinese text
  Phase 2: EN — VoiceDesign + simplified prompts (no character roles)

Output: Ogg Vorbis directly (no intermediate WAV).
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import gc
import struct
from collections import defaultdict
from pathlib import Path
import numpy as np
import torch
import soundfile as sf

from qwen_tts import Qwen3TTSModel

# ── Config ────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
OUTPUT_DIR = os.path.join(PROJECT_DIR, 'voice')
ZH_OUTPUT = os.path.join(OUTPUT_DIR, 'zh')
EN_OUTPUT  = os.path.join(OUTPUT_DIR, 'en')
MAPPING_PATH = os.path.join(SCRIPT_DIR, 'bilingual_mapping_review.json')
VOICEDESIGN_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
ATTN_IMPL = "sdpa"
BATCH_SIZE = 16
MIN_DURATION_MS = 1500
LONG_TEXT_THRESHOLD = 100
SHORT_MAX_TOKENS = 256
LONG_MAX_TOKENS = 1024

# ── Instruct simplification for English ─────────────────────────
_VOICE_QUALITY_WORDS = frozenset({
    'voice', 'tone', 'warm', 'friendly', 'polite', 'deep', 'calm',
    'serious', 'cheerful', 'gentle', 'confident', 'professional',
    'bright', 'welcoming', 'gruff', 'authoritative', 'dignified',
    'concerned', 'worried', 'tired', 'angry', 'slow', 'fast',
    'smooth', 'intense', 'philosophical', 'mysterious', 'hollow',
    'rumbling', 'resonant', 'soft', 'firm', 'strong', 'eager',
    'nervous', 'playful', 'mischievous', 'sly', 'knowing', 'weary',
    'proud', 'cracking', 'insecure', 'desperate', 'pleading',
    'pitiful', 'jovial', 'robust', 'loyal', 'brave', 'earnest',
    'emotional', 'husky', 'whispered', 'haunting', 'ethereal',
    'monotonous', 'bored', 'mechanical', 'nasal', 'shouting',
    'booming', 'loud', 'crisp', 'clear', 'articulate', 'unhurried',
    'descriptive', 'mild', 'passionate', 'dramatic', 'sing-song',
    'melodic', 'cultured', 'refined', 'proper', 'no-nonsense',
    'down-to-earth', 'simple', 'low', 'quick', 'sweet', 'kind',
    'shy', 'curious', 'delicate', 'sorrowful', 'exotic', 'hushed',
    'focused', 'capable', 'challenging', 'conspiratorial', 'approving',
    'thoughtful', 'preoccupied', 'busy', 'motherly', 'maternal',
    'giggly', 'wistful', 'soothing', 'breathless', 'mature',
    'sultry', 'sleepy', 'dreamy', 'distant', 'confused', 'grating',
    'scratchy', 'creaky', 'cackling', 'sarcastic', 'wry',
    'dry', 'flat', 'nasal', 'tight', 'rich', 'velvety', 'honeyed',
    'silken', 'smooth', 'musical', 'lyrical', 'resonant',
    'chuckle', 'laugh', 'chuckling', 'laughing', 'grumbling',
    'muttering', 'murmuring', 'whisper', 'whispering',
})

_AGE_WORDS = frozenset({
    'elderly', 'ancient', 'old', 'young', 'teenage', 'middle-aged',
    'aged', 'youthful', 'mature',
})

_AGE_PATTERN = re.compile(r'^\d+s(-\d+s)?$')
_GENDER_WORDS = frozenset({'male', 'female', 'neutral', 'creature', 'entity'})


def _simplify_prompt(prompt):
    if not prompt:
        return ''
    parts = [p.strip() for p in prompt.split(',')]
    kept = []
    for p in parts:
        pl = p.lower().strip()
        if pl in _GENDER_WORDS:
            kept.append(p)
        elif pl in _AGE_WORDS or _AGE_PATTERN.match(pl):
            kept.append(p)
        elif any(kw in pl for kw in _VOICE_QUALITY_WORDS):
            kept.append(p)
    if len(kept) < 2:
        kept = parts[:2]
    return ', '.join(kept)


# ── helpers ───────────────────────────────────────────────────────────

def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def make_filename(entry, lang='zh'):
    fid_key = f'{lang}_func_id'
    ok_key  = f'{lang}_offset_key'
    seg_key = f'{lang}_segment'
    fid = entry.get(fid_key, '') or entry.get('zh_func_id', '') or entry.get('en_func_id', '') or '0000'
    ok  = entry.get(ok_key, '') or '0'
    seg = entry.get(seg_key, 0) or 0
    if fid.startswith('0x') or fid.startswith('0X'):
        fid = fid[2:]
    fid = fid.lower().zfill(4)
    return f'{fid}_{ok}_{seg}.ogg'


def load_mapping():
    with open(MAPPING_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    by_npc = defaultdict(list)
    for entry in data:
        npc = entry.get('npc', '') or 'UNKNOWN'
        by_npc[npc].append(entry)
    return data, by_npc


def ensure_minimum_duration(wav, sr, min_ms=MIN_DURATION_MS):
    needed = int(sr * min_ms / 1000)
    if len(wav) < needed:
        repeats = int(np.ceil(needed / len(wav)))
        wav = np.tile(wav, repeats)[:needed]
    return wav


def write_ogg_direct(filepath, wav, sr, npc='', text=''):
    """Write PCM audio directly as OGG via ffmpeg stdin pipe, no WAV."""
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


# ── VoiceDesign line generation ──────────────────────────────────────

def generate_npc_lines(model, npc, entries, lang):
    from zhconv import convert as tc2sc
    text_key = f'{lang}_text'
    lang_output = ZH_OUTPUT if lang == 'zh' else EN_OUTPUT
    os.makedirs(lang_output, exist_ok=True)

    prof = entries[0]
    prompt = prof.get('voice_prompt', '')

    if lang == 'zh':
        instruct = prompt
        language = 'Chinese'
    else:
        instruct = _simplify_prompt(prompt)
        language = 'English'

    lang_entries = [e for e in entries if e.get(text_key, '')]
    lang_entries.sort(key=lambda e: len(e.get(text_key, '')))
    generated = 0
    skipped = 0
    errors = 0

    for i in range(0, len(lang_entries), BATCH_SIZE):
        batch = lang_entries[i:i + BATCH_SIZE]
        to_generate = []

        for e in batch:
            fname = make_filename(e, lang)
            ogg_path = os.path.join(lang_output, fname)
            if os.path.exists(ogg_path):
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

        instructs = [instruct] * len(texts)

        try:
            wavs, sr = model.generate_voice_design(
                text=texts,
                language=language,
                instruct=instructs,
                max_new_tokens=max_tokens,
                non_streaming_mode=True,
            )
        except Exception as ex:
            print(f'  ERROR batch: {ex}')
            errors += len(to_generate)
            continue

        for j, e in enumerate(to_generate):
            try:
                wav_out = wavs[j] if j < len(wavs) else wavs[0]
                wav_out = ensure_minimum_duration(wav_out, sr)
                write_ogg_direct(e['_ogg_path'], wav_out, sr, npc, e.get(text_key, ''))
                generated += 1
            except Exception as ex:
                print(f'  ERROR writing {e["_ogg_path"]}: {ex}')
                errors += 1

        del wavs, sr, texts, instructs
        if i > 0 and (i // BATCH_SIZE) % 4 == 0:
            gc.collect()
            torch.cuda.empty_cache()

    return generated, skipped, errors


# ── main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Qwen3-TTS bilingual voice generation')
    parser.add_argument('--dry-run', action='store_true', help='Scan and report only')
    parser.add_argument('--resume', action='store_true', help='Skip existing files')
    parser.add_argument('--npc', type=str, default=None, help='Single NPC to generate')
    parser.add_argument('--npc-start', type=str, default=None, help='Start NPC at this name (inclusive)')
    parser.add_argument('--npc-end', type=str, default=None, help='Stop after this NPC (inclusive)')
    parser.add_argument('--device', type=str, default='cuda:0', help='CUDA device')
    args = parser.parse_args()

    data, by_npc = load_mapping()
    print(f'Loaded {len(data)} entries across {len(by_npc)} NPCs')

    if args.npc:
        by_npc = {args.npc: by_npc.get(args.npc, [])}
        if not list(by_npc.values())[0]:
            print(f'NPC "{args.npc}" not found!')
            sys.exit(1)
        print(f'Filtered to single NPC: {args.npc} ({len(by_npc[args.npc])} lines)')

    if args.npc_start or args.npc_end:
        all_npcs = sorted(by_npc.keys())
        start_idx = 0
        end_idx = len(all_npcs)
        if args.npc_start:
            start_idx = next((i for i, n in enumerate(all_npcs) if n >= args.npc_start), 0)
        if args.npc_end:
            end_idx = next((i for i, n in enumerate(all_npcs) if n > args.npc_end), end_idx)
        by_npc = {n: by_npc[n] for n in all_npcs[start_idx:end_idx]}
        print(f'Filtered to NPCs {start_idx}-{end_idx-1} ({len(by_npc)} NPCs)')

    total_gen = 0
    total_skip = 0
    total_err = 0

    print(f'\nLoading {VOICEDESIGN_MODEL}...')
    model = Qwen3TTSModel.from_pretrained(
        VOICEDESIGN_MODEL,
        device_map=args.device,
        dtype=torch.bfloat16,
        attn_implementation=ATTN_IMPL,
    )

    try:
        for lang in ['zh', 'en']:
            label = 'Chinese' if lang == 'zh' else 'English'
            out_dir = ZH_OUTPUT if lang == 'zh' else EN_OUTPUT
            print(f'\n{"="*50}')
            print(f'Phase: {label} lines via VoiceDesign')
            print(f'{"="*50}')
            os.makedirs(out_dir, exist_ok=True)

            for npc_name, entries in by_npc.items():
                if args.dry_run:
                    print(f'[{npc_name}] ({len(entries)} lines)')
                    continue

                print(f'\n[{npc_name}] ({len(entries)} lines)')
                gen, skip, err = generate_npc_lines(model, npc_name, entries, lang)
                total_gen += gen
                total_skip += skip
                total_err += err
                print(f'  Generated: {gen}, Skipped: {skip}, Errors: {err}')

                gc.collect()
                torch.cuda.empty_cache()

    finally:
        del model
        gc.collect()
        torch.cuda.empty_cache()

    if args.dry_run:
        print(f'\nDry-run complete. Would generate ~{total_gen} files.')
        return

    print(f'\n{"="*50}')
    print(f'Done! Generated: {total_gen}, Skipped: {total_skip}, Errors: {total_err}')
    print(f'Output:')
    print(f'  ZH: {ZH_OUTPUT}')
    print(f'  EN: {EN_OUTPUT}')

    # Check filesizes
    print(f'\nFile size summary:')
    for label, d in [('ZH', ZH_OUTPUT), ('EN', EN_OUTPUT)]:
        sizes = [os.path.getsize(os.path.join(d, f)) for f in os.listdir(d) if f.endswith('.ogg')]
        if sizes:
            small = sum(1 for s in sizes if s < 50000)
            mid = sum(1 for s in sizes if 50000 <= s < 150000)
            large = sum(1 for s in sizes if s >= 150000)
            print(f'  {label}: {len(sizes)} files | <50K:{small} 50-150K:{mid} >150K:{large}')


if __name__ == '__main__':
    main()
