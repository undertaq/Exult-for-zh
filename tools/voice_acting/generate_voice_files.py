#!/usr/bin/env python3
"""
Generate voice files for Exult-for-zh using ChatTTS with GPU acceleration.

Creates .ogg files in the game's voice_acting directory, named by ZH offset key.
Each NPC gets a consistent speaker seed for voice identity.
Supports batch inference and incremental resume.

Usage:
    python generate_voice_files.py
        --mapping bilingual_mapping.csv
        --output-dir "D:/Game/.../patch/voice_acting"
        --language both
        --batch-size 8
        --resume
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import scipy.io.wavfile as wavfile


# ── NPC voice profiles ──────────────────────────────────────────────
# Each named NPC gets a consistent speaker seed.
# Seeds are generated once and saved to a JSON file for reuse.

NAMED_NPCS = [
    'Iolo', 'Shamino', 'Dupre', 'Spark', 'Lord British', 'Batlin',
    'Erethian', 'Morfin', 'Dracothraxus', 'Arcadion', 'Kylista',
    'Raven', 'Petre', 'Feridwyn', 'Harns', 'Hook', 'Jaana',
    'Katrina', 'Leilana', 'Malchir', 'Nystul', 'Salkind',
    'Tseramed', 'Voldin', 'Ye Olde Shoppe', 'Zak', 'Karas',
    'Sentri', 'Mage', 'Alchemist', 'Weapon Seller',
]

NPC_ALIASES = {
    'iolo': 'Iolo', 'shamino': 'Shamino', 'dupre': 'Dupre',
    'spark': 'Spark', 'lord british': 'Lord British', 'lb': 'Lord British',
    'batlin': 'Batlin', 'erethian': 'Erethian', 'morfin': 'Morfin',
    'dracothraxus': 'Dracothraxus', 'arcadion': 'Arcadion',
    'kylista': 'Kylista', 'raven': 'Raven', 'petre': 'Petre',
    'feridwyn': 'Feridwyn', 'harns': 'Harns', 'hook': 'Hook',
    'jaana': 'Jaana', 'katrina': 'Katrina', 'leilana': 'Leilana',
    'malchir': 'Malchir', 'nystul': 'Nystul', 'salkind': 'Salkind',
    'tseramed': 'Tseramed', 'voldin': 'Voldin',
    'ye olde shoppe': 'Ye Olde Shoppe', 'zak': 'Zak', 'karas': 'Karas',
    'sentri': 'Sentri',
}

NARRATOR_INDICATORS = [
    'you see', 'you notice', 'you hear', 'you feel', 'you tell',
    'he says', 'she says', 'he nods', 'she nods', 'he shrugs',
    'she shrugs', 'he smiles', 'she smiles', 'he frowns',
    'she frowns', 'he looks', 'she looks', 'he walks', 'she walks',
    'the old man', 'the mage', 'the man', 'the woman',
    'the dragon', 'the voice', 'a rather', 'at your approach',
    'as you', 'when you', 'just as you', 'the elderly mage',
]


# ── helpers ──────────────────────────────────────────────────────────

CONTRACTIONS_EN = {
    "I'll": "I will", "i'll": "I will", "you'll": "you will",
    "he'll": "he will", "she'll": "she will", "it'll": "it will",
    "we'll": "we will", "they'll": "they will",
    "I'm": "I am", "i'm": "I am",
    "don't": "do not",
    "can't": "cannot", "cant't": "cannot",
    "won't": "will not", "wont't": "will not",
    "isn't": "is not", "aren't": "are not",
    "wasn't": "was not", "weren't": "were not",
    "hasn't": "has not", "haven't": "have not",
    "hadn't": "had not", "doesn't": "does not",
    "didn't": "did not", "couldn't": "could not",
    "wouldn't": "would not", "shouldn't": "should not",
    "mustn't": "must not", "needn't": "need not",
    "daren't": "dare not", "mightn't": "might not",
    "it's": "it is", "that's": "that is",
    "what's": "what is", "there's": "there is",
    "here's": "here is", "who's": "who is",
    "where's": "where is", "when's": "when is",
    "how's": "how is", "let's": "let us",
    "I've": "I have", "you've": "you have",
    "we've": "we have", "they've": "they have",
    "I'd": "I would", "you'd": "you would",
    "he'd": "he would", "she'd": "she would",
    "we'd": "we would", "they'd": "they would",
    "thou'rt": "thou art", "thou'll": "thou wilt",
    "thou'st": "thou hast", "dost thou": "do you",
    "doth thou": "does you",
}

def clean_text(text, lang='zh'):
    if not text:
        return ''
    text = text.strip()
    text = re.sub(r'[\u200b-\u200f\u2028-\u202f\ufeff]', '', text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    if lang == 'en':
        text = text.replace('<PLAYER_NAME>', 'Avatar')
        for contraction, expanded in CONTRACTIONS_EN.items():
            text = text.replace(contraction, expanded)
        text = text.replace("'", "")
        text = text.replace('"', '')
        text = text.replace('!', '.')
        text = text.replace('?', '')
        text = text.replace('--', ', ')
        text = text.replace('...', ' ')
        text = re.sub(r'\s+', ' ', text).strip()
    else:
        text = text.replace('<PLAYER_NAME>', '你')
        text = text.replace('\u300c', '').replace('\u300d', '')
        text = text.replace('\uff01', '\u3002')
        text = text.replace('\uff1a', '\uff0c')
        text = text.replace('\uff1b', '\uff0c')
        text = text.replace('...', ' ')
        text = text.replace('--', ', ')
        text = re.sub(r'\s+', ' ', text).strip()
    return text


def build_filename(offset_key, segment):
    seg = int(segment) if segment else 0
    return f"{offset_key}_{seg}.ogg"


def get_npc_key(npc_name, text=''):
    name_raw = (npc_name or '').strip().lower()
    if name_raw in NPC_ALIASES:
        return NPC_ALIASES[name_raw]
    text_lower = (text or '').lower().strip()
    for ind in NARRATOR_INDICATORS:
        if text_lower.startswith(ind):
            return 'narrator'
    if name_raw:
        return 'default'
    return 'narrator' if any(text_lower.startswith(ind) for ind in NARRATOR_INDICATORS) else 'default'


def load_speaker_seeds(path):
    if path and os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_speaker_seeds(seeds, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(seeds, f, ensure_ascii=False)


# ── generation ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Generate voice files with ChatTTS')
    parser.add_argument('--mapping', required=True, help='bilingual_mapping.csv path')
    parser.add_argument('--output-dir', required=True, help='Output directory')
    parser.add_argument('--seeds-json', default='voice_seeds.json',
                        help='Path to save/load speaker seed JSON')
    parser.add_argument('--language', choices=['en', 'zh', 'both'], default='both')
    parser.add_argument('--batch-size', type=int, default=4)
    parser.add_argument('--max-files', type=int, default=0,
                        help='Limit total files to generate (for testing)')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--skip-ogg', action='store_true',
                        help='Skip .wav→.ogg conversion (save .wav only)')
    args = parser.parse_args()

    def fix_encoding(s):
        if not s:
            return s
        return s.encode('latin-1').decode('utf-8')

    # ── load mapping ──
    entries = []
    with open(args.mapping, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            entries.append({k: fix_encoding(v) for k, v in r.items()})

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build generation list
    gen_list = []
    skipped = 0
    for r in entries:
        zh_text = clean_text(r.get('zh_text', ''), lang='zh')
        en_text = clean_text(r.get('en_text', ''), lang='en')
        npc = r.get('npc', '') or ''
        zh_key = r.get('zh_offset_key', '')
        zh_seg = r.get('zh_segment', '0')

        if not zh_key:
            continue

        fname = build_filename(zh_key, zh_seg)

        if args.language in ('zh', 'both') and zh_text:
            fpath = str(output_dir / fname)
            wavpath = fpath.replace('.ogg', '.wav')
            if args.resume and (os.path.exists(fpath) or os.path.exists(wavpath)):
                skipped += 1
            else:
                gen_list.append((fpath, zh_text, npc, 'zh'))

        if args.language in ('en', 'both') and en_text:
            fpath = str(output_dir / f"en_{fname}")
            wavpath = fpath.replace('.ogg', '.wav')
            if args.resume and (os.path.exists(fpath) or os.path.exists(wavpath)):
                skipped += 1
            else:
                gen_list.append((fpath, en_text, npc, 'en'))

    total = len(gen_list)
    if args.max_files > 0 and total > args.max_files:
        gen_list = gen_list[:args.max_files]
        total = len(gen_list)
    if skipped:
        print(f"Skipped {skipped} existing ({args.resume=})", file=sys.stderr)
    print(f"Files to generate: {total}", file=sys.stderr)
    if args.dry_run:
        by_npc = defaultdict(int)
        for _, _, npc, lang in gen_list:
            key = get_npc_key(npc)
            by_npc[f"{lang}/{key}"] += 1
        for k, c in sorted(by_npc.items()):
            print(f"  {k}: {c}", file=sys.stderr)
        return

    if not args.skip_ogg:
        orphan_wavs = list(output_dir.glob("*.wav"))
        if orphan_wavs:
            print(f"Converting {len(orphan_wavs)} orphan .wav → .ogg ...", file=sys.stderr)
            for wavpath in orphan_wavs:
                oggpath = wavpath.with_suffix('.ogg')
                try:
                    subprocess.run(
                        ['ffmpeg', '-y', '-i', str(wavpath),
                         '-c:a', 'libvorbis', '-q:a', '3', str(oggpath)],
                        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    wavpath.unlink()
                except Exception as e:
                    print(f"  ERROR converting {wavpath}: {e}", file=sys.stderr)

    if total == 0:
        print("Nothing to generate.", file=sys.stderr)
        return

    # ── load ChatTTS ──
    print("Loading ChatTTS...", file=sys.stderr)
    import ChatTTS
    import torch

    chat = ChatTTS.Chat()
    chat.load(source='huggingface', compile=False)
    device = next(chat.gpt.parameters()).device
    print(f"  Model on {device}", file=sys.stderr)

    # ── speaker seeds ──
    seeds = load_speaker_seeds(args.seeds_json)
    # Ensure seeds for all NPC profiles
    all_profiles = set()
    for _, _, npc, _ in gen_list:
        key = get_npc_key(npc)
        all_profiles.add(key)
    for key in all_profiles:
        if key not in seeds:
            seeds[key] = chat.sample_random_speaker()
            print(f"  New seed for '{key}'", file=sys.stderr)
    save_speaker_seeds(seeds, args.seeds_json)

    # ── group by (lang, NPC key) for language-specific params ──
    lang_voice_groups = defaultdict(list)
    for fpath, text, npc, lang in gen_list:
        key = get_npc_key(npc, text)
        lang_voice_groups[(lang, key)].append((fpath, text))

    # ── generate ──
    start = time.time()
    completed = 0
    errors = 0
    wav_queue = []

    for (lang, voice_key), items in sorted(lang_voice_groups.items()):
        spk_emb = seeds[voice_key]
        total_items = len(items)
        print(f"\n[{lang}] Voice '{voice_key}' ({total_items} lines)", file=sys.stderr)

        for batch_start in range(0, total_items, args.batch_size):
            batch = items[batch_start:batch_start + args.batch_size]
            texts = [t for t, _ in batch]

            try:
                if lang == 'zh':
                    wavs = chat.infer(
                        texts,
                        lang='zh',
                        skip_refine_text=True,
                        do_text_normalization=False,
                        do_homophone_replacement=False,
                        split_text=False,
                        params_infer_code=ChatTTS.Chat.InferCodeParams(
                            spk_emb=spk_emb,
                            temperature=0.3,
                            ensure_non_empty=False,
                        ),
                    )
                else:
                    wavs = chat.infer(
                        texts,
                        lang='en',
                        skip_refine_text=False,
                        split_text=False,
                        params_refine_text=ChatTTS.Chat.RefineTextParams(
                            prompt='[oral_2][laugh_0][break_4]',
                        ),
                        params_infer_code=ChatTTS.Chat.InferCodeParams(
                            spk_emb=spk_emb,
                            temperature=0.3,
                            ensure_non_empty=False,
                        ),
                    )

                for (fpath, _), wav in zip(batch, wavs):
                    try:
                        audio = (wav * 32767).astype(np.int16)
                        audio = np.clip(audio, -32768, 32767)
                        wavpath = fpath.replace('.ogg', '.wav')
                        wavfile.write(wavpath, 24000, audio)
                        completed += 1
                        if not args.skip_ogg:
                            wav_queue.append((wavpath, fpath))
                    except Exception as e:
                        print(f"  ERROR saving: {e}", file=sys.stderr)
                        errors += 1

            except Exception as e:
                print(f"  ERROR batch: {e}", file=sys.stderr)
                errors += len(batch)

            elapsed = time.time() - start
            rate = completed / max(elapsed, 0.01)
            eta = (total - completed) / max(rate, 0.01)
            print(f"  {completed}/{total} ({rate:.1f}/s, ETA {eta:.0f}s)", file=sys.stderr)

    # ── batch ffmpeg conversion ──
    if wav_queue:
        print(f"\nConverting {len(wav_queue)} .wav → .ogg ...", file=sys.stderr)
        for wavpath, oggpath in wav_queue:
            try:
                subprocess.run(
                    ['ffmpeg', '-y', '-i', wavpath,
                     '-c:a', 'libvorbis', '-q:a', '3', oggpath],
                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW
                )
                os.remove(wavpath)
            except Exception as e:
                print(f"  ERROR converting {wavpath}: {e}", file=sys.stderr)

    elapsed = time.time() - start
    print(f"\n{'='*50}", file=sys.stderr)
    print(f"Done! {completed} files, {errors} errors, {elapsed:.0f}s", file=sys.stderr)


if __name__ == '__main__':
    main()
