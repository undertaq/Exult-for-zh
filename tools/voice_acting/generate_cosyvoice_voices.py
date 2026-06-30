#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import time

COSYVOICE_REPO = '/home/joe/project/CosyVoice'
sys.path.insert(0, COSYVOICE_REPO)
sys.path.insert(0, os.path.join(COSYVOICE_REPO, 'third_party', 'Matcha-TTS'))

from cosyvoice.cli.cosyvoice import AutoModel
import torchaudio


MODELS_DIR = '/home/joe/project/cosyvoice_models'
PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
OUTPUT_DIR = os.path.join(PROJECT_DIR, 'cosyvoice')
MAPPING_PATH = os.path.join(os.path.dirname(__file__), 'bilingual_mapping_review.json')

REF_DIR = os.path.join(MODELS_DIR, 'reference_voices')

SAMPLE_RATE = 24000

# NPC reference voice mapping
NPC_REF_MAP = {
    'erethian': 'longlaobo.wav',
    'ferryman': 'longlaobo.wav',
    'iolo': 'longsanshu.wav',
    'shamino': 'longsanshu.wav',
    'dupre': 'longanzhi.wav',
    'spark': 'longanhuan_v3.wav',
    'default_male': 'longsanshu.wav',
    'default_female': 'longanhuan_v3.wav',
}


def build_instruct_text(entry):
    tone = entry.get('tone', '').strip().lower()
    valid_emotions = ('neutral', 'happy', 'sad', 'angry', 'fearful', 'surprised', 'disgusted')
    if tone in valid_emotions:
        return f'你說話的情感是{tone}。<|endofprompt|>'
    return '<|endofprompt|>'


def build_filename(entry, lang):
    npc = entry.get('npc', 'unknown').replace(' ', '_')
    offset_key = entry.get('zh_offset_key', 'unknown')
    segment = entry.get('zh_segment', 0)
    return f'{npc}/{offset_key}_{segment}_{lang}.ogg'


def wav_to_ogg(wav_path, ogg_path):
    subprocess.run(
        ['ffmpeg', '-y', '-i', wav_path,
         '-c:a', 'libvorbis', '-q:a', '3', ogg_path],
        capture_output=True, check=True
    )
    os.remove(wav_path)


def generate_npc(entries, model, npc_name, ref_wav):
    npc_entries = [e for e in entries if e.get('npc', '').lower() == npc_name.lower()]
    if not npc_entries:
        print(f'No entries found for NPC: {npc_name}')
        return True

    os.makedirs(os.path.join(OUTPUT_DIR, npc_name), exist_ok=True)
    print(f'Generating {len(npc_entries)} entries for NPC: {npc_name}')

    completed = 0
    errors = 0
    start_time = time.time()

    for entry in npc_entries:
        for lang, text_key in [('zh', 'zh_text'), ('en', 'en_text')]:
            text = (entry.get(text_key) or '').strip()
            if not text:
                continue

            fname = build_filename(entry, lang)
            ogg_path = os.path.join(OUTPUT_DIR, fname)
            wav_path = ogg_path.replace('.ogg', '.wav')

            if os.path.exists(ogg_path):
                continue

            instruct_text = build_instruct_text(entry)
            text_preview = text[:60].replace('\n', ' ')

            try:
                results = list(model.inference_instruct2(text, instruct_text, ref_wav, stream=False))
                if not results:
                    print(f'  ERROR no output: {fname}')
                    errors += 1
                    continue
                speech = results[0]['tts_speech']
                os.makedirs(os.path.dirname(wav_path), exist_ok=True)
                torchaudio.save(wav_path, speech.cpu(), SAMPLE_RATE)
                wav_to_ogg(wav_path, ogg_path)
                elapsed = time.time() - start_time
                print(f'  OK [{elapsed:.1f}s] {fname}: {text_preview}')
                completed += 1
            except Exception as e:
                print(f'  ERROR {fname}: {e}')
                if os.path.exists(wav_path):
                    try:
                        os.remove(wav_path)
                    except OSError:
                        pass
                errors += 1

    elapsed = time.time() - start_time
    print(f'{npc_name}: {completed} OK, {errors} errors in {elapsed:.1f}s')
    return errors == 0


def main():
    parser = argparse.ArgumentParser(description='Generate voices with CosyVoice3 instruct2')
    parser.add_argument('--ref', default='longlaobo', help='Reference voice filename (without extension)')
    parser.add_argument('--npc', nargs='+', default=['erethian'], help='NPC names to generate')
    parser.add_argument('--sample', type=int, default=0, help='Generate first N entries only')
    args = parser.parse_args()

    with open(MAPPING_PATH, 'r', encoding='utf-8') as f:
        entries = json.load(f)
    print(f'Loaded {len(entries)} entries')

    if args.sample > 0:
        entries = entries[:args.sample]

    ref_wav = os.path.join(REF_DIR, args.ref + '.wav')
    if not os.path.exists(ref_wav):
        ref_wav = os.path.join(REF_DIR, args.ref + '.mp3')
    print(f'Reference: {args.ref} -> {ref_wav}')

    model_dir = os.path.join(MODELS_DIR, 'Fun-CosyVoice3-0.5B')
    print('Loading Fun-CosyVoice3-0.5B...')
    model = AutoModel(model_dir=model_dir)
    print(f'Model loaded. SR={model.sample_rate}')

    all_ok = True
    for npc_name in args.npc:
        ref = NPC_REF_MAP.get(npc_name.lower(), ref_wav)
        if isinstance(ref, str) and not ref.startswith('/'):
            ref = os.path.join(REF_DIR, ref)
        ok = generate_npc(entries, model, npc_name, ref)
        all_ok = all_ok and ok

    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()
