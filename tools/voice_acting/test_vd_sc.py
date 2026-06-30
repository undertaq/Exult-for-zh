#!/usr/bin/env python3
"""
Test VoiceDesign + Simplified Chinese for extreme NPCs.
Hypothesis: VoiceDesign with SC text produces Mandarin output,
avoiding the Cantonese-like prosody that characterful prompts cause on CustomVoice.
"""
import json, os, sys, gc, re
from pathlib import Path
from collections import defaultdict
from zhconv import convert as tc2sc

import torch
import soundfile as sf
from qwen_tts import Qwen3TTSModel

sys.path.insert(0, os.path.dirname(__file__))
from generate_qwen3_voice import (
    PROJECT_DIR, OUTPUT_DIR, REF_DIR, MAPPING_PATH,
    CUSTOMVOICE_MODEL, VOICEDESIGN_MODEL, BASE_MODEL,
    ATTN_IMPL, BATCH_SIZE, MAX_NEW_TOKENS,
    make_filename, make_ref_filename, get_ref_text,
    ensure_minimum_duration, convert_wav_dir,
)

# ── test config ─────────────────────────────────────────────────────

TEST_OUTPUT = os.path.join(OUTPUT_DIR, 'test_zh')
TEST_REF_DIR = os.path.join(OUTPUT_DIR, '_test_refs')

# NPCs with extreme non-human character prompts
TEST_NPCS = [
    'Dracothraxus',   # dragon
    'Horance',        # ghost
    'Time Lord',      # ancient being
    'Shrine',         # entity/spirit
    'Caine',          # ghost/spirit
    'Stone Guardian', # elemental
    'Hydra',          # creature/monster
]

SHORT_MAX_TOKENS = 256
LONG_MAX_TOKENS = 1024
LONG_TEXT_THRESHOLD = 100
REF_MAX_TOKENS = 192


def _sc_ref_text(entries):
    """Pick a short ref text and convert it to Simplified Chinese."""
    for e in entries:
        t = e.get('zh_text', '')
        if 20 <= len(t) <= 60:
            return tc2sc(t, 'zh-cn')
    for e in entries:
        t = e.get('zh_text', '')
        if t:
            return tc2sc(t, 'zh-cn')
    return '你好。'


def generate_vd_ref(model, npc, entries):
    """Generate a VoiceDesign reference using Simplified Chinese text."""
    prof = entries[0]
    instruct = prof.get('voice_prompt', '')
    ref_text = _sc_ref_text(entries)
    print(f'  Ref text (SC, {len(ref_text)} chars): {ref_text[:60]}...')
    print(f'  Instruct: {instruct[:80]}...')
    wavs, sr = model.generate_voice_design(
        text=ref_text,
        language='Chinese',
        instruct=instruct,
        max_new_tokens=REF_MAX_TOKENS,
    )
    return wavs[0], sr, ref_text


def generate_test_lines(model, npc, entries, prompt_items, sr):
    """Generate all ZH lines for one NPC using voice clone."""
    text_key = 'zh_text'
    os.makedirs(TEST_OUTPUT, exist_ok=True)
    lang_entries = [e for e in entries if e.get(text_key, '')]
    generated = 0
    skipped = 0
    errors = 0

    short_entries = [e for e in lang_entries if len(e.get(text_key, '')) <= LONG_TEXT_THRESHOLD]
    long_entries  = [e for e in lang_entries if len(e.get(text_key, '')) > LONG_TEXT_THRESHOLD]

    for batch_entries, max_tokens, label in [
        (short_entries, SHORT_MAX_TOKENS, 'short'),
        (long_entries, LONG_MAX_TOKENS, 'long'),
    ]:
        if not batch_entries:
            continue

        for i in range(0, len(batch_entries), BATCH_SIZE):
            batch = batch_entries[i:i + BATCH_SIZE]
            to_generate = []
            for e in batch:
                fname = make_filename(e, 'zh').replace('.ogg', '.wav')
                wav_path = os.path.join(TEST_OUTPUT, fname)
                if os.path.exists(wav_path):
                    skipped += 1
                else:
                    e['_wav_path'] = wav_path
                    to_generate.append(e)

            if not to_generate:
                continue

            texts = [e.get(text_key, '') or '...' for e in to_generate]

            try:
                wavs, out_sr = model.generate_voice_clone(
                    text=texts,
                    language=['Chinese'] * len(texts),
                    voice_clone_prompt=prompt_items,
                    max_new_tokens=max_tokens,
                )
            except Exception as ex:
                print(f'  ERROR [{label}] batch: {ex}')
                errors += len(to_generate)
                continue

            for j, e in enumerate(to_generate):
                try:
                    wav_out = wavs[j] if j < len(wavs) else wavs[0]
                    wav_out = ensure_minimum_duration(wav_out, out_sr)
                    sf.write(e['_wav_path'], wav_out, out_sr)
                    generated += 1
                except Exception as ex:
                    print(f'  ERROR writing {e["_wav_path"]}: {ex}')
                    errors += 1

            del wavs, out_sr, texts
            if i > 0 and (i // BATCH_SIZE) % 4 == 0:
                gc.collect()
                torch.cuda.empty_cache()

    return generated, skipped, errors


def main():
    os.makedirs(TEST_REF_DIR, exist_ok=True)
    os.makedirs(TEST_OUTPUT, exist_ok=True)

    # Load data
    with open(MAPPING_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    by_npc = defaultdict(list)
    for e in data:
        by_npc[e.get('npc', '')].append(e)

    # Filter to test NPCs
    for npc in TEST_NPCS:
        if npc not in by_npc:
            print(f'[WARN] NPC "{npc}" not in mapping')

    # ── Phase 1: Generate VoiceDesign refs with SC text ──
    print('=' * 60)
    print('Phase 1: VD refs with Simplified Chinese text')
    print('=' * 60)
    print(f'Loading {VOICEDESIGN_MODEL}...')
    vd_model = Qwen3TTSModel.from_pretrained(
        VOICEDESIGN_MODEL,
        device_map='cuda',
        dtype=torch.bfloat16,
        attn_implementation=ATTN_IMPL,
    )

    ref_texts = {}  # store SC ref text for voice clone phase
    for npc in TEST_NPCS:
        entries = by_npc.get(npc, [])
        if not entries:
            continue
        ref_path = os.path.join(TEST_REF_DIR, make_ref_filename(npc, 'zh'))
        if os.path.exists(ref_path):
            print(f'[{npc}] Ref exists, skipping')
            continue
        print(f'\n[{npc}] ({len(entries)} lines) — VD+SC ref...')
        wav, sr, sc_text = generate_vd_ref(vd_model, npc, entries)
        ref_texts[npc] = sc_text
        sf.write(ref_path, wav, sr)
        print(f'  Saved: {ref_path} ({len(wav)/sr:.1f}s)')

    # Free VD model
    print('\nUnloading VoiceDesign model...')
    del vd_model
    for _ in range(3):
        gc.collect()
        torch.cuda.empty_cache()

    # ── Phase 2: Generate voice clone lines ──
    print('\n' + '=' * 60)
    print('Phase 2: Voice clone from VD refs')
    print('=' * 60)
    print(f'Loading {BASE_MODEL}...')
    base_model = Qwen3TTSModel.from_pretrained(
        BASE_MODEL,
        device_map='cuda',
        dtype=torch.bfloat16,
        attn_implementation=ATTN_IMPL,
    )

    total_gen = 0
    total_skip = 0
    total_err = 0

    for npc in TEST_NPCS:
        entries = by_npc.get(npc, [])
        if not entries:
            continue
        ref_path = os.path.join(TEST_REF_DIR, make_ref_filename(npc, 'zh'))
        if not os.path.exists(ref_path):
            print(f'[WARN] [{npc}] No ref found')
            continue
        print(f'\n[{npc}] Generating ZH lines ({len(entries)} total)...')

        ref_wav, ref_sr = sf.read(ref_path)
        ref_text = ref_texts.get(npc) or get_ref_text(entries, 'zh')

        prompt_items = base_model.create_voice_clone_prompt(
            ref_audio=(ref_wav, ref_sr),
            ref_text=ref_text,
        )

        gen, skip, err = generate_test_lines(base_model, npc, entries, prompt_items, ref_sr)
        total_gen += gen
        total_skip += skip
        total_err += err
        print(f'  Generated: {gen}, Skipped: {skip}, Errors: {err}')

        gc.collect()
        torch.cuda.empty_cache()

    # ── Convert to OGG ──
    print(f'\nConverting to OGG...')
    count = convert_wav_dir(TEST_OUTPUT, TEST_OUTPUT)
    print(f'  Converted: {count} files')

    print(f'\nDone! Generated: {total_gen}, Skipped: {total_skip}, Errors: {total_err}')
    print(f'Output: {TEST_OUTPUT}')


if __name__ == '__main__':
    main()
