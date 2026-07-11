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
import csv
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
import shutil
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import soundfile as sf
from zhconv import convert as tc2sc

# qwen_tts imports librosa/numba; without an explicit cache dir numba can fail
# to locate package files when importing from this venv layout.
os.environ.setdefault("NUMBA_CACHE_DIR", "/tmp/numba_cache")

from qwen_tts import Qwen3TTSModel

from npc_data import NPC_NUMBERS

# ── Config ────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
OUTPUT_DIR = os.path.join(PROJECT_DIR, 'voice')
ZH_OUTPUT = os.path.join(OUTPUT_DIR, 'zh')
EN_OUTPUT = os.path.join(OUTPUT_DIR, 'en')
REFS_DIR = os.path.join(OUTPUT_DIR, 'refs')

MAPPING_PATH = os.path.join(SCRIPT_DIR, 'bilingual_mapping_review.json')
EN_LINES_PATH = os.path.join(SCRIPT_DIR, 'en_voice_lines.csv')
ZH_LINES_PATH = os.path.join(SCRIPT_DIR, 'zh_voice_lines.csv')
DESIGNS_PATH = os.path.join(SCRIPT_DIR, 'npc_voice_designs.json')
PROMPTS_ZH_PATH = os.path.join(SCRIPT_DIR, 'voice_prompt_zh.json')
CLONE_PROMPTS_PATH = os.path.join(SCRIPT_DIR, 'clone_prompts.pkl')

VOICEDESIGN_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
BASE_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
ATTN_IMPL = "sdpa"
BATCH_SIZE_PHASE_C = 4
MIN_DURATION_MS = 1500
LONG_TEXT_THRESHOLD = 100
SHORT_MAX_TOKENS = 256
LONG_MAX_TOKENS = 1024

RUNE_SIGN_CONTEXT_SPEAKERS = [
    'Iolo',
    'Spark',
    'Shamino',
    'Dupre',
    'Jaana',
    'Sentri',
    'Julia',
    'Katrina',
    'Tseramed',
]


# ── Helpers ───────────────────────────────────────────────────────────

def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def reference_fingerprint(text, instruct):
    normalized = '\n'.join([
        re.sub(r'\s+', ' ', (text or '').strip()),
        re.sub(r'\s+', ' ', (instruct or '').strip()),
    ])
    return text_hash(normalized)


def _build_base_name(entry, lang):
    """Build the base filename without NPC suffix."""
    if uses_zh_runtime_for_english_voice(entry, lang):
        fid = entry.get('zh_func_id', '') or '0000'
        ok = entry.get('zh_offset_key', '') or '0'
        seg = entry.get('zh_segment', 0) or 0
    else:
        fid_key = f'{lang}_func_id'
        ok_key = f'{lang}_offset_key'
        seg_key = f'{lang}_segment'
        fid = entry.get(fid_key, '') or entry.get('zh_func_id', '') or entry.get('en_func_id', '') or '0000'
        ok = entry.get(ok_key, '') or '0'
        seg = entry.get(seg_key, 0) or 0
    if isinstance(fid, str) and (fid.startswith('0x') or fid.startswith('0X')):
        fid = fid[2:]
    fid = str(fid).lower().zfill(4)
    return f'{fid}_{ok}_{seg}'


def uses_zh_runtime_for_english_voice(entry, lang='en'):
    """Return true for Chinese-only rows that need English audio under ZH keys."""
    if lang != 'en':
        return False
    if not (entry.get('en_text', '') or '').strip():
        return False
    if (entry.get('en_func_id', '') or '').strip() or (entry.get('en_offset_key', '') or '').strip():
        return False
    return bool(
        (entry.get('zh_func_id', '') or '').strip()
        and (entry.get('zh_offset_key', '') or '').strip()
    )


def normalize_func_id(value):
    value = str(value or '').strip().lower()
    if value.startswith('0x'):
        value = value[2:]
    return value.zfill(4)


def normalize_offset_key(value):
    parts = str(value or '0').strip().split('_')
    normalized = []
    for part in parts:
        part = part.strip().lower()
        if part.startswith('0x'):
            part = part[2:]
        normalized.append(part or '0')
    return '_'.join(normalized)


def source_meta_key(lang, func_id, offset_key, segment):
    return (
        lang,
        normalize_func_id(func_id),
        normalize_offset_key(offset_key),
        int(segment or 0),
    )


def make_filename(entry, lang='zh'):
    """
    Build voice filename with NPC-specific suffix when possible.
    
    The game's VoiceActingManager tries {base}_npc{N}.ogg first, then {base}.ogg.
    By including the NPC number, we eliminate collisions where different NPCs
    share the same func_id/offset_key/segment.
    """
    base = _build_base_name(entry, lang)
    avatar_gender = entry.get('_avatar_voice_gender')
    if avatar_gender in ('male', 'female'):
        return f'{base}_avatar_{avatar_gender}.ogg'
    npc_name = entry.get('npc', '') or ''
    npc_num = NPC_NUMBERS.get(npc_name)
    if npc_num is not None:
        return f'{base}_npc{npc_num}.ogg'
    return f'{base}.ogg'


def get_generic_filename(entry, lang='zh'):
    """Get the generic (non-NPC-specific) fallback filename."""
    base = _build_base_name(entry, lang)
    return f'{base}.ogg'


def ensure_minimum_duration(wav, sr, min_ms=MIN_DURATION_MS):
    needed = int(sr * min_ms / 1000)
    if len(wav) < needed:
        repeats = int(np.ceil(needed / len(wav)))
        wav = np.tile(wav, repeats)[:needed]
    return wav


def write_ogg_direct(filepath, wav, sr, npc='', text='', metadata=None):
    title = text_hash(text) if text else ''
    artist = f'qwen3:{npc}' if npc else 'qwen3'
    description = text or ''
    metadata = metadata or {}
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
    for key, value in metadata.items():
        if key and value is not None:
            cmd += ['-metadata', f'{key}={value}']
    cmd.append(str(filepath))

    raw = wav.tobytes()
    subprocess.run(cmd, input=raw, capture_output=True, check=True)


def prepare_voice_output_path(filepath):
    """Ensure writing this path will not mutate another hard-linked voice file."""
    try:
        if os.path.exists(filepath) and os.stat(filepath).st_nlink > 1:
            os.unlink(filepath)
    except OSError:
        pass


def read_ogg_comments(filepath):
    """Read Vorbis comments generated by ffmpeg from an OGG file."""
    comments = {}
    try:
        with open(filepath, 'rb') as f:
            blob = f.read()
        marker = b'\x03vorbis'
        pos = blob.find(marker)
        if pos < 0:
            return None
        p = pos + len(marker)
        vendor_len = struct.unpack_from('<I', blob, p)[0]
        p += 4 + vendor_len
        comment_count = struct.unpack_from('<I', blob, p)[0]
        p += 4
        for _ in range(comment_count):
            comment_len = struct.unpack_from('<I', blob, p)[0]
            p += 4
            raw = blob[p:p + comment_len]
            p += comment_len
            text = raw.decode('utf-8', errors='replace')
            if '=' not in text:
                continue
            key, value = text.split('=', 1)
            comments[key.lower()] = value
    except Exception:
        return {}
    return comments


def read_ogg_comment(filepath):
    """Read the text comment generated by ffmpeg from an OGG file."""
    comments = read_ogg_comments(filepath)
    for key in ('comment', 'description'):
        if key in comments:
            return comments[key]
    return None


def reference_file_matches_design(filepath, ref_text, instruct):
    """Return true when a reference clip was generated for the same text and instruction."""
    comments = read_ogg_comments(filepath)
    return comments.get('reference_hash') == reference_fingerprint(ref_text, instruct)


def voice_file_matches_text(filepath, expected_text):
    """Return true only when an existing voice file embeds the expected text."""
    actual = read_ogg_comment(filepath)
    if actual is None:
        return False
    normalize = lambda text: re.sub(r'\s+', ' ', (text or '').strip())
    return normalize(actual) == normalize(expected_text)


def create_generic_fallback(npc_specific_path, entry, lang, out_dir):
    """
    Create a copy from NPC-specific filename to generic filename.
    
    The game's VoiceActingManager tries {base}_npc{N}.ogg first, then {base}.ogg.
    Copies avoid hard-link aliasing where a later write to one filename silently
    changes the other filename's audio and metadata.
    """
    fname = os.path.basename(npc_specific_path)
    generic_fname = get_generic_filename(entry, lang)
    if generic_fname == fname:
        return  # Not NPC-specific, nothing to do
    generic_path = os.path.join(out_dir, generic_fname)
    if os.path.exists(generic_path):
        try:
            if os.path.samefile(npc_specific_path, generic_path):
                return
        except OSError:
            pass
        print(f'  Generic fallback exists, keeping: {generic_path}')
        return
    shutil.copy2(npc_specific_path, generic_path)


def load_mapping():
    with open(MAPPING_PATH, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)
    source_metadata = load_source_line_metadata()
    source_runtime_keys = load_source_runtime_keys()
    data = []
    for entry in raw_data:
        invalid_langs = audit_entry_runtime_keys(entry, source_runtime_keys)
        enriched = attach_source_metadata(entry, source_metadata)
        if invalid_langs:
            enriched['_invalid_runtime_keys'] = invalid_langs
            print(
                'WARNING: mapping row has noncanonical runtime key(s), '
                f'skipping generation for {",".join(invalid_langs)}: '
                f'npc={entry.get("npc", "")} '
                f'en={entry.get("en_func_id", "")}/{entry.get("en_offset_key", "")}/{entry.get("en_segment", 0)} '
                f'zh={entry.get("zh_func_id", "")}/{entry.get("zh_offset_key", "")}/{entry.get("zh_segment", 0)}'
            )
        data.extend(expand_entry_for_voice_speakers(enriched))

    # Group by voice NPC name.
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


def expand_npc_filter_name(npc_name):
    """Expand user-facing NPC filter aliases to generation NPC names."""
    if npc_name == 'Avatar':
        return ['Avatar male', 'Avatar female']
    return [npc_name]


def filter_designs_by_npc(designs, npc_names):
    """Return voice designs whose NPC list intersects the requested generation names."""
    requested = set(npc_names)
    filtered = {
        did: design
        for did, design in designs.get('designs', {}).items()
        if requested.intersection(design.get('npcs', []))
        or design.get('npc') in requested
    }
    result = dict(designs)
    result['designs'] = filtered
    meta = dict(designs.get('_meta', {}))
    meta['total_designs'] = len(filtered)
    meta['unique_designs'] = sum(1 for d in filtered.values() if d.get('type') == 'unique')
    meta['group_designs'] = sum(1 for d in filtered.values() if d.get('type') == 'group')
    meta['narrator_designs'] = sum(1 for d in filtered.values() if d.get('type') == 'narrator')
    result['_meta'] = meta
    return result


def load_source_line_metadata():
    """Load original per-line speaker/caller metadata from voice CSV files."""
    metadata = {}
    for lang, path in [('en', EN_LINES_PATH), ('zh', ZH_LINES_PATH)]:
        if not os.path.exists(path):
            continue
        with open(path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                key = source_meta_key(
                    lang,
                    row.get('func_id', ''),
                    row.get('offset_key', ''),
                    row.get('segment', 0),
                )
                metadata.setdefault(key, {
                    'npc': row.get('npc', '') or '',
                    'speaker': row.get('speaker', '') or '',
                    'caller_guess': row.get('caller_guess', '') or '',
                })
    return metadata


def load_source_runtime_keys():
    """Load canonical runtime identity keys from source voice CSV files."""
    keys = {'en': set(), 'zh': set()}
    for lang, path in [('en', EN_LINES_PATH), ('zh', ZH_LINES_PATH)]:
        if not os.path.exists(path):
            continue
        with open(path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                keys[lang].add(source_meta_key(
                    lang,
                    row.get('func_id', ''),
                    row.get('offset_key', ''),
                    row.get('segment', 0),
                ))
    return keys


def audit_entry_runtime_keys(entry, source_runtime_keys):
    """Return languages whose manifest runtime keys do not exist in source CSVs."""
    invalid = []
    for lang in ('zh', 'en'):
        if not (entry.get(f'{lang}_text', '') or '').strip():
            continue
        if uses_zh_runtime_for_english_voice(entry, lang):
            continue
        func_id = (
            entry.get(f'{lang}_func_id', '')
            or entry.get('func_id', '')
            or entry.get('zh_func_id', '')
            or entry.get('en_func_id', '')
            or '0000'
        )
        key = source_meta_key(
            lang,
            func_id,
            entry.get(f'{lang}_offset_key', '') or '0',
            entry.get(f'{lang}_segment', 0) or 0,
        )
        if key not in source_runtime_keys.get(lang, set()):
            invalid.append(lang)
    return invalid


def attach_source_metadata(entry, source_metadata):
    entry = dict(entry)
    source_meta = {}
    for lang in ('zh', 'en'):
        func_id = (
            entry.get(f'{lang}_func_id', '')
            or entry.get('zh_func_id', '')
            or entry.get('en_func_id', '')
            or '0000'
        )
        key = source_meta_key(
            lang,
            func_id,
            entry.get(f'{lang}_offset_key', '') or '0',
            entry.get(f'{lang}_segment', 0) or 0,
        )
        if key in source_metadata:
            source_meta[lang] = source_metadata[key]
    if source_meta:
        entry['_source_meta'] = source_meta
    return entry


def _append_unique_known_npc(names, name):
    name = (name or '').strip()
    if not name or name not in NPC_NUMBERS or name in names:
        return
    names.append(name)


def voice_speaker_candidates(entry):
    """Return NPC names whose own voice should be generated for this row."""
    if normalize_func_id(entry.get('zh_func_id', '')) == '095f':
        return RUNE_SIGN_CONTEXT_SPEAKERS, 'contextual_sign_reader'

    source_meta = entry.get('_source_meta', {})
    explicit_speakers = []
    caller_guess_speakers = []
    source_npcs = []

    for meta in source_meta.values():
        _append_unique_known_npc(explicit_speakers, meta.get('speaker', ''))
        for name in (meta.get('caller_guess', '') or '').split('|'):
            _append_unique_known_npc(caller_guess_speakers, name)
        _append_unique_known_npc(source_npcs, meta.get('npc', ''))

    if explicit_speakers:
        return explicit_speakers, 'speaker'
    if caller_guess_speakers:
        return caller_guess_speakers, 'caller_guess'
    if source_npcs:
        return source_npcs, 'source_npc'

    npc = entry.get('npc', '') or ''
    return ([npc] if npc else ['UNKNOWN']), 'mapping_npc'


def expand_entry_for_voice_speakers(entry):
    """Expand one mapping row into per-speaker generation rows."""
    speakers, reason = voice_speaker_candidates(entry)
    original_npc = entry.get('npc', '') or ''
    if speakers == ['Avatar']:
        speakers = ['Avatar male', 'Avatar female']
        reason = 'avatar_gender_variant'
    expanded = []
    for speaker in speakers:
        e = dict(entry)
        e['npc'] = speaker
        e['_voice_source_npc'] = original_npc
        e['_voice_speaker_reason'] = reason
        if speaker == 'Avatar male':
            e['_avatar_voice_gender'] = 'male'
        elif speaker == 'Avatar female':
            e['_avatar_voice_gender'] = 'female'
        e['_suppress_generic_fallback'] = (
            len(speakers) > 1
            or reason == 'caller_guess'
            or reason == 'contextual_sign_reader'
            or (reason == 'speaker' and speaker != original_npc)
        )
        expanded.append(e)
    return expanded


# ── Phase A: VoiceDesign Reference Generation ─────────────────────────

def phase_a_generate_refs(designs, args):
    """Generate reference clips for each voice design using VoiceDesign."""
    os.makedirs(REFS_DIR, exist_ok=True)

    print(f'\n{"="*60}')
    print('Phase A: Generating VoiceDesign reference clips')
    print(f'{"="*60}')

    if args.dry_run:
        would_generate = 0
        skipped = 0
        for did, design in sorted(designs['designs'].items()):
            npc_label = design.get('npc', did)
            for lang, text_key, desc_key, default_desc in [
                ('ZH', 'ref_zh_text', 'voice_desc_zh', '用標準的普通話朗讀'),
                ('EN', 'ref_en_text', 'voice_desc_en', 'Neutral clear speaking voice, natural and pleasant'),
            ]:
                ref_path = os.path.join(REFS_DIR, f'{did}_{lang.lower()}_ref.ogg')
                ref_text = design.get(text_key, '')
                ref_desc = design.get(desc_key, '') or default_desc
                if not ref_text:
                    print(f'  [{npc_label}] No {lang} ref text, skipping')
                    skipped += 1
                elif (
                    os.path.exists(ref_path)
                    and not args.force_refs
                    and reference_file_matches_design(ref_path, ref_text, ref_desc)
                ):
                    print(f'  [{npc_label}] {lang} ref exists, skipping')
                    skipped += 1
                else:
                    print(f'  [{npc_label}] Would generate {lang} ref: {ref_text[:60]}...')
                    would_generate += 1
        print(f'\nPhase A dry-run complete. Would generate: {would_generate}, Skipped: {skipped}, Errors: 0')
        return 0, skipped, 0

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
            zh_desc = design.get('voice_desc_zh', '') or '用標準的普通話朗讀'
            if not zh_text:
                print(f'  [{npc_label}] No ZH ref text, skipping')
                skipped += 1
            elif (
                os.path.exists(ref_zh_path)
                and not args.force_refs
                and reference_file_matches_design(ref_zh_path, zh_text, zh_desc)
            ):
                print(f'  [{npc_label}] ZH ref exists, skipping')
                skipped += 1
            else:
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
                    write_ogg_direct(
                        ref_zh_path, wav_out, sr, npc_label, zh_text_sc,
                        metadata={'REFERENCE_HASH': reference_fingerprint(zh_text, zh_desc)},
                    )
                    total += 1
                    print(f'  [{npc_label}] ZH ref generated ({len(wav_out)/sr:.1f}s)')
                except Exception as ex:
                    print(f'  [{npc_label}] ZH ref ERROR: {ex}')
                    errors += 1

            # EN reference
            en_text = design.get('ref_en_text', '')
            en_desc = design.get('voice_desc_en', '') or 'Neutral clear speaking voice, natural and pleasant'
            if not en_text:
                print(f'  [{npc_label}] No EN ref text, skipping')
                skipped += 1
            elif (
                os.path.exists(ref_en_path)
                and not args.force_refs
                and reference_file_matches_design(ref_en_path, en_text, en_desc)
            ):
                print(f'  [{npc_label}] EN ref exists, skipping')
                skipped += 1
            else:
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
                    write_ogg_direct(
                        ref_en_path, wav_out, sr, npc_label, en_text,
                        metadata={'REFERENCE_HASH': reference_fingerprint(en_text, en_desc)},
                    )
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

    if args.dry_run:
        clone_prompts = {}
        total = 0
        errors = 0
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
                print(f'  [{npc_label}] {lang}: Would build prompt from {ref_path}')
            clone_prompts[did] = prompt
        print('\nPhase B dry-run complete. Clone prompts were not modified.')
        print(f'Phase B complete. Built: {total}, Errors: {errors}')
        return clone_prompts, total, errors

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

    total_gen = 0
    total_skip = 0
    total_err = 0
    total_would_gen = 0

    # Build NPC → design lookup
    npc_to_design = build_npc_to_design_map(designs)
    model = None

    if not args.dry_run:
        print(f'\nLoading {BASE_MODEL}...')
        model = Qwen3TTSModel.from_pretrained(
            BASE_MODEL,
            device_map=args.device,
            dtype=torch.bfloat16,
            attn_implementation=ATTN_IMPL,
        )

    try:
        langs = [args.lang] if args.lang else ['zh', 'en']
        for lang in langs:
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

                # Filter entries with text for this language, refusing stale runtime keys.
                all_lang_entries = [e for e in entries if e.get(text_key, '').strip()]
                invalid_lang_entries = [
                    e for e in all_lang_entries
                    if lang in e.get('_invalid_runtime_keys', [])
                ]
                lang_entries = [
                    e for e in all_lang_entries
                    if lang not in e.get('_invalid_runtime_keys', [])
                ]
                if not all_lang_entries:
                    continue

                progress_npc += 1
                if args.max_npcs and progress_npc > args.max_npcs:
                    break

                # Process in batches
                lang_entries.sort(key=lambda e: len(e.get(text_key, '')))
                generated = 0
                would_generate = 0
                skipped = 0
                errors = len(invalid_lang_entries)

                if invalid_lang_entries:
                    print(
                        f'  [{npc_name}] {lang}: skipped {len(invalid_lang_entries)} '
                        'line(s) with noncanonical runtime keys'
                    )

                for i in range(0, len(lang_entries), BATCH_SIZE_PHASE_C):
                    batch = lang_entries[i:i + BATCH_SIZE_PHASE_C]
                    to_generate = []

                    for e in batch:
                        fname = make_filename(e, lang)
                        ogg_path = os.path.join(out_dir, fname)
                        expected_text = e.get(text_key, '') or ''
                        if (
                            os.path.exists(ogg_path)
                            and not args.force
                            and voice_file_matches_text(ogg_path, expected_text)
                        ):
                            skipped += 1
                            if (
                                getattr(args, 'generic_fallbacks', False)
                                and not args.dry_run
                                and not e.get('_suppress_generic_fallback')
                            ):
                                create_generic_fallback(ogg_path, e, lang, out_dir)
                        else:
                            e['_ogg_path'] = ogg_path
                            to_generate.append(e)

                    if not to_generate:
                        continue

                    if args.dry_run:
                        would_generate += len(to_generate)
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
                            prepare_voice_output_path(e['_ogg_path'])
                            write_ogg_direct(
                                e['_ogg_path'], wav_out, sr,
                                npc_name, e.get(text_key, '')
                            )
                            generated += 1
                            if (
                                getattr(args, 'generic_fallbacks', False)
                                and not e.get('_suppress_generic_fallback')
                            ):
                                # Create generic fallback without hard-link aliasing.
                                create_generic_fallback(e['_ogg_path'], e, lang, out_dir)
                        except Exception as ex:
                            print(f'  [{npc_name}] Write ERROR {e["_ogg_path"]}: {ex}')
                            errors += 1

                    del wavs, sr, texts
                    if i > 0 and (i // BATCH_SIZE_PHASE_C) % 4 == 0:
                        gc.collect()
                        torch.cuda.empty_cache()

                total_gen += generated
                total_would_gen += would_generate
                total_skip += skipped
                total_err += errors

                if generated > 0 or skipped > 0 or would_generate > 0:
                    status = f'  [{npc_name}] Gen:{generated} Skip:{skipped} Err:{errors}'
                    if args.dry_run:
                        status = f'  [{npc_name}] Would generate {would_generate} lines Skip:{skipped}'
                    print(status)

                gc.collect()
                torch.cuda.empty_cache()

    finally:
        if model is not None:
            del model
        gc.collect()
        torch.cuda.empty_cache()

    if args.dry_run:
        print(f'\nPhase C dry-run complete. Would generate: {total_would_gen}, Skipped: {total_skip}, Errors: {total_err}')
    else:
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


# ── Migration ─────────────────────────────────────────────────────────

def build_description_cache(out_dir):
    """
    Bulk-read DESCRIPTION metadata from all .ogg files in a directory.
    Returns dict: {filename_without_ext: description_text}
    """
    import glob as glob_module
    cache = {}
    ogg_files = glob_module.glob(os.path.join(out_dir, '*.ogg'))
    if not ogg_files:
        return cache

    import concurrent.futures

    def read_comment(f):
        try:
            result = subprocess.run(
                ['ffprobe', '-hide_banner', '-loglevel', 'error',
                 '-show_entries', 'stream_tags=comment',
                 '-of', 'default=noprint_wrappers=1:nokey=1',
                 str(f)],
                capture_output=True, text=True, timeout=10
            )
            desc = result.stdout.strip()
            base = os.path.basename(f)[:-4]
            return (base, desc) if desc else None
        except Exception:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(read_comment, f) for f in ogg_files]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                base, desc = result
                cache[base] = desc

    print(f'  Cached {len(cache)} descriptions from {len(ogg_files)} files')
    return cache


def phase_migrate_existing(data, by_npc, args):
    """
    One-time migration: rename existing (correct) generic files to NPC-specific names.
    
    For entries with known NPC numbers:
    - If NPC-specific file already exists → skip
    - If generic file exists → verify DESCRIPTION metadata matches expected text
    - If correct → rename to NPC-specific, create generic hard link
    - If wrong → flag for regeneration
    """
    os.makedirs(ZH_OUTPUT, exist_ok=True)
    os.makedirs(EN_OUTPUT, exist_ok=True)

    print(f'\n{"="*60}')
    print('Migration: Renaming existing files to NPC-specific names')
    print(f'{"="*60}')

    renamed = 0
    verified = 0
    wrong = 0
    missing = 0
    skipped = 0

    for lang in ['zh', 'en']:
        out_dir = ZH_OUTPUT if lang == 'zh' else EN_OUTPUT
        text_key = f'{lang}_text'
        lang_label = 'ZH' if lang == 'zh' else 'EN'

        print(f'\n--- {lang_label} ---')
        print('  Building description cache...')
        desc_cache = build_description_cache(out_dir)
        print(f'  Processing entries...')

        for entry in data:
            npc_name = entry.get('npc', '') or ''
            npc_num = NPC_NUMBERS.get(npc_name)
            if npc_num is None:
                continue  # UNKNOWN or unmapped → keep generic name

            # Check if NPC-specific file already exists
            base = _build_base_name(entry, lang)
            npc_fname = f'{base}_npc{npc_num}.ogg'
            generic_fname = f'{base}.ogg'
            npc_path = os.path.join(out_dir, npc_fname)
            generic_path = os.path.join(out_dir, generic_fname)

            if os.path.exists(npc_path):
                skipped += 1
                # Ensure generic hard link exists
                if not os.path.exists(generic_path) and not args.dry_run:
                    os.link(npc_path, generic_path)
                    print(f'  [{npc_name}] {lang}: missing generic link restored')
                continue

            if not os.path.exists(generic_path):
                missing += 1
                continue

            # Verify generic file content from cache
            description = desc_cache.get(base)
            expected_text = entry.get(text_key, '') or ''

            if description and description == expected_text:
                if args.dry_run:
                    print(f'  [{npc_name}] {lang}: would rename {generic_fname} -> {npc_fname}')
                else:
                    os.rename(generic_path, npc_path)
                    os.link(npc_path, generic_path)
                    print(f'  [{npc_name}] {lang}: {generic_fname} -> {npc_fname}')
                renamed += 1
            else:
                if args.dry_run:
                    print(f'  [{npc_name}] {lang}: WRONG content, would delete and regenerate')
                else:
                    os.remove(generic_path)
                wrong += 1

        if args.dry_run:
            print(f'  {lang_label} dry-run complete')

    print(f'\nMigration complete.')
    print(f'  Renamed (correct): {renamed}')
    print(f'  Already NPC-specific: {skipped}')
    print(f'  Verified correct (kept): {verified}')
    print(f'  Wrong content (deleted): {wrong}')
    print(f'  Missing (need generation): {missing}')
    print(f'\nRun Phase C to regenerate {wrong + missing} entries with wrong/missing content.')

    return renamed, wrong, missing


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
    parser.add_argument('--npc', type=str, default=None, help='Single NPC to process')
    parser.add_argument('--max-npcs', type=int, default=None, help='Limit number of NPCs to process')
    parser.add_argument('--lang', type=str, default=None, choices=['zh', 'en'],
                        help='Language to process (default: both)')
    parser.add_argument('--generic-fallbacks', action='store_true',
                        help='Also create generic non-NPC fallback copies for generated/skipped NPC-specific files')
    parser.add_argument('--migrate', action='store_true', help='One-time migration: rename existing generic files to NPC-specific names')
    args = parser.parse_args()

    # Load data
    designs = load_designs()
    data, by_npc = load_mapping()

    # Migration mode: rename existing generic files to NPC-specific names
    if args.migrate:
        phase_migrate_existing(data, by_npc, args)
        print('\nMigration done. Run Phase C to regenerate wrong/missing entries.\n')
        return

    print(f'Loaded {len(data)} entries across {len(by_npc)} NPCs')
    print(f'Voice designs: {designs["_meta"]["total_designs"]} total')
    print(f'  Unique: {designs["_meta"]["unique_designs"]}')
    print(f'  Groups: {designs["_meta"]["group_designs"]}')
    print(f'  Narrator: {designs["_meta"]["narrator_designs"]}')

    if args.npc:
        npc_names = []
        for name in [n.strip() for n in args.npc.split(',') if n.strip()]:
            npc_names.extend(expand_npc_filter_name(name))
        by_npc = {n: by_npc.get(n, []) for n in npc_names}
        designs = filter_designs_by_npc(designs, npc_names)
        found = [n for n, v in by_npc.items() if v]
        missing = [n for n, v in by_npc.items() if not v]
        if missing:
            print(f'NPC(s) not found: {", ".join(missing)}')
        if not found:
            sys.exit(1)
        print(f'Filtered to {len(found)} NPC(s): {", ".join(found)} ({sum(len(v) for v in by_npc.values())} lines total)')

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
