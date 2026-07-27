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
CANDIDATE_DIR = os.path.join(SCRIPT_DIR, 'reference_candidates')

MAPPING_PATH = os.path.join(SCRIPT_DIR, 'bilingual_mapping_review.json')
EN_LINES_PATH = os.path.join(SCRIPT_DIR, 'en_voice_lines.csv')
ZH_LINES_PATH = os.path.join(SCRIPT_DIR, 'zh_voice_lines.csv')
DESIGNS_PATH = os.path.join(SCRIPT_DIR, 'npc_voice_designs.json')
PROMPTS_ZH_PATH = os.path.join(SCRIPT_DIR, 'voice_prompt_zh.json')
CLONE_PROMPTS_PATH = os.path.join(SCRIPT_DIR, 'clone_prompts.pkl')

VOICEDESIGN_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
BASE_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
ATTN_IMPL = "sdpa"
MAX_LINES_PER_CALL = 8
MIN_DURATION_MS = 1500
LONG_TEXT_THRESHOLD = 100
SHORT_MAX_TOKENS = 256
LONG_MAX_TOKENS = 1024
NARRATOR_FEMALE_DESIGN_ID = "npc_unknown"
NARRATOR_FEMALE_NAME = "UNKNOWN"
NARRATOR_MALE_DESIGN_ID = "npc_narrator_male"

COMPANION_NPCS = ['Iolo', 'Dupre', 'Spark', 'Katrina', 'Jaana', 'Tseramed', 'Shamino']
NARRATOR_MALE_NAME = "Narrator male"
NARRATOR_DESIGN_ID = NARRATOR_FEMALE_DESIGN_ID
NARRATOR_NAME = NARRATOR_FEMALE_NAME
SPLICE_GAP_MS = 280
SPLICE_FADE_MS = 30

# Fixed seed for deterministic TTS sampling. Qwen3-TTS uses stochastic sampling
# (do_sample=True, temperature=0.9) by default, so the same name (e.g. "Rudyom")
# can be voiced differently across runs. Pinning a generator seed makes each
# character's pronunciation stable run-to-run. Change only if you want to
# re-roll the entire voice cast.
TTS_SEED = 20240718

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
    if uses_en_runtime_for_zh_voice(entry, lang):
        fid = entry.get('en_func_id', '') or '0000'
        ok = entry.get('en_offset_key', '') or '0'
        seg = entry.get('en_segment', 0) or 0
    elif uses_zh_runtime_for_english_voice(entry, lang):
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


def uses_en_runtime_for_zh_voice(entry, lang='zh'):
    """Return true for English-only rows that need Chinese audio under EN keys."""
    if lang != 'zh':
        return False
    if not (entry.get('zh_text', '') or '').strip():
        return False
    if (entry.get('zh_func_id', '') or '').strip() or (entry.get('zh_offset_key', '') or '').strip():
        return False
    return bool(
        (entry.get('en_func_id', '') or '').strip()
        and (entry.get('en_offset_key', '') or '').strip()
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


def split_voice_parts(text, lang, default_role='narrator'):
    """Split text into narrator/speaker parts using language dialogue delimiters."""
    text = text or ''
    if lang == 'zh':
        stripped = text.strip()
        if (
            default_role == 'speaker'
            and (
                (
                    stripped.endswith('"')
                    and stripped.count('"') == 1
                    and '「' not in stripped
                    and '」' not in stripped
                )
                or (
                    stripped.endswith('」')
                    and stripped.count('」') == 1
                    and '「' not in stripped
                )
            )
        ):
            return [('speaker', stripped[:-1].strip())]
        return split_delimited_voice_parts(
            text,
            [('「', '」'), ('"', '"')],
            default_role=default_role,
        )
    return split_delimited_voice_parts(text, [('"', '"')], default_role=default_role)


def split_delimited_voice_parts(text, delimiter_pairs, default_role='narrator'):
    parts = []
    text = text or ''
    i = 0
    start = 0
    active_right = None
    saw_delimiter = False
    while i < len(text):
        token = None
        closing = False
        if active_right is not None:
            if text.startswith(active_right, i):
                token = active_right
                closing = True
        else:
            for left, right in delimiter_pairs:
                if text.startswith(left, i):
                    token = left
                    active_right = right
                    break
        if token is not None:
            saw_delimiter = True
            chunk = text[start:i].strip()
            if chunk:
                parts.append(('speaker' if closing else 'narrator', chunk))
            i += len(token)
            start = i
            if closing:
                active_right = None
            continue
        i += 1
    chunk = text[start:].strip()
    if chunk:
        role = 'speaker' if active_right is not None else ('narrator' if saw_delimiter else default_role)
        parts.append((role, chunk))
    return parts or [(default_role, text.strip() or '...')]


def default_voice_role(entry, lang):
    """Default role for text without explicit dialogue delimiters."""
    role = (
        entry.get(f'{lang}_voice_default_role')
        or entry.get('voice_default_role')
        or ''
    )
    if role in ('speaker', 'narrator'):
        return role
    text = (entry.get(f'{lang}_text', '') or '').strip()
    source_meta = entry.get('_source_meta', {}) or {}
    meta = source_meta.get(lang, {}) or {}
    try:
        segment = int(meta.get('segment', entry.get(f'{lang}_segment', 0)) or 0)
        total_segments = int(meta.get('total_segments', 1) or 1)
    except (TypeError, ValueError):
        segment = int(entry.get(f'{lang}_segment', 0) or 0)
        total_segments = 1
    if segment > 0 and total_segments > 1:
        if (
            text.endswith('"')
            and text.count('"') == 1
            and '「' not in text
            and '」' not in text
        ):
            return 'speaker'
        if (
            text.endswith('」')
            and text.count('」') == 1
            and '「' not in text
        ):
            return 'speaker'
    return 'narrator'


def fade_splice_chunk(wav, sr):
    """Shape a generated chunk for concatenation without repeating short phrases."""
    wav = np.asarray(wav, dtype=np.float32)
    if wav.size == 0:
        return wav
    fade = min(int(sr * SPLICE_FADE_MS / 1000), wav.size // 2)
    if fade <= 1:
        return wav
    wav = wav.copy()
    wav[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)
    wav[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
    return wav


def generate_delimited_voice(model, parts, lang, speaker_prompt, narrator_prompt, generator=None):
    """Generate one output waveform from narrator/speaker chunks."""
    lang_label = 'Chinese' if lang == 'zh' else 'English'
    max_tokens = SHORT_MAX_TOKENS
    rendered_parts = []
    for role, text in parts:
        rendered = tc2sc(text, 'zh-cn') if lang == 'zh' else text
        rendered_parts.append((role, rendered))
        if len(text) > LONG_TEXT_THRESHOLD:
            max_tokens = LONG_MAX_TOKENS

    wavs = []
    sr = None
    for role, text in rendered_parts:
        prompt = narrator_prompt if role == 'narrator' and narrator_prompt is not None else speaker_prompt
        generated, sr = model.generate_voice_clone(
            text=[text],
            language=[lang_label],
            voice_clone_prompt=prompt,
            max_new_tokens=max_tokens,
            generator=generator,
        )
        wav = generated[0] if isinstance(generated, (list, tuple)) else generated
        wavs.append(fade_splice_chunk(wav, sr))

    gap = np.zeros(int(sr * SPLICE_GAP_MS / 1000), dtype=np.float32)
    joined = []
    for idx, wav in enumerate(wavs):
        if idx:
            joined.append(gap)
        joined.append(np.asarray(wav, dtype=np.float32))
    wav = np.concatenate(joined) if joined else np.zeros(int(sr * 0.5), dtype=np.float32)
    return wav, sr


def prepare_voice_jobs(entries, lang, text_key, prompt_data, narrator_prompt, narrator_id):
    """Split generation entries into single-part batch jobs and multi-part entries.

    A "single-part" entry has exactly one narrator/speaker span and is emitted as a
    batch job carrying its (text, clone prompt, length class). Multi-part entries
    (mixed narrator/speaker dialogue) are returned separately and generated
    per-line with fade-splicing so delimiter handling is preserved.
    """
    single_jobs = []
    multi_entries = []
    for e in entries:
        original_text = e.get(text_key, '') or '...'
        parts = split_voice_parts(
            original_text, lang, default_role=default_voice_role(e, lang)
        )
        if len(parts) != 1:
            multi_entries.append(e)
            continue
        role, text = parts[0]
        prompt = narrator_prompt if (role == 'narrator' and narrator_prompt is not None) else prompt_data
        length_class = 'long' if len(text) > LONG_TEXT_THRESHOLD else 'short'
        single_jobs.append({
            'entry': e,
            'text': text,
            'prompt': prompt,
            'length_class': length_class,
            'narrator_id': narrator_id,
        })
    return single_jobs, multi_entries


def bucket_single_part_jobs(single_jobs, max_lines):
    """Group single-part jobs by (prompt identity, length class), capped at max_lines each.

    Bucketing by prompt identity keeps one consistent clone prompt per model call;
    bucketing by length class keeps one consistent ``max_new_tokens`` per call.
    """
    buckets = {}
    for job in single_jobs:
        key = (id(job['prompt']), job['length_class'])
        buckets.setdefault(key, []).append(job)
    result = []
    for jobs in buckets.values():
        for i in range(0, len(jobs), max_lines):
            result.append(jobs[i:i + max_lines])
    return result


def generate_single_part_batch(model, bucket, lang_label, lang, out_dir, args, npc_name, review_since_mtime, last_review_update, stats, generator=None):
    """Generate one ``generate_voice_clone`` call PER LINE, then write outputs.

    Each job is synthesized with its own model call so that distinct utterances
    never share a batched ``generate_voice_clone`` invocation. Voice-clone
    cross-contaminates when multiple different texts are passed in one call,
    bleeding words from one line into a neighbour (spurious prefixes). Issuing
    one call per line eliminates that bleed. On OOM a job is retried; if it
    keeps failing the bucket is split in half and retried recursively. Returns
    the (possibly updated) ``last_review_update`` timestamp.
    """
    if not bucket:
        return last_review_update
    failed = []
    for j in bucket:
        prompt = j['prompt']
        text = tc2sc(j['text'], 'zh-cn') if lang == 'zh' else j['text']
        max_tokens = LONG_MAX_TOKENS if j['length_class'] == 'long' else SHORT_MAX_TOKENS
        try:
            wavs, sr = model.generate_voice_clone(
                text=[text],
                language=[lang_label],
                voice_clone_prompt=prompt,
                max_new_tokens=max_tokens,
                generator=generator,
            )
        except Exception:
            failed.append(j)
            continue
        if not isinstance(wavs, (list, tuple)):
            wavs = [wavs]
        wav = wavs[0]
        e = j['entry']
        try:
            prepare_voice_output_path(e['_ogg_path'])
            write_ogg_direct(
                e['_ogg_path'], wav, sr, npc_name, j['text'],
                metadata={'VOICE_MODE': 'single_clone', 'NARRATOR': j['narrator_id']},
            )
            stats['generated'] += 1
            if (
                getattr(args, 'generic_fallbacks', False)
                and not e.get('_suppress_generic_fallback')
            ):
                create_generic_fallback(e['_ogg_path'], e, lang, out_dir)
            last_review_update = maybe_update_full_voice_review(
                args, review_since_mtime, last_review_update, force=False
            )
        except Exception as ex:
            print(f"  [{npc_name}] Write ERROR {e.get('_ogg_path')}: {ex}")
            stats['errors'] += 1
    # Retry OOM-failed jobs by splitting the bucket in half (recurses to size 1).
    if failed:
        if len(failed) > 1:
            mid = len(failed) // 2
            last_review_update = generate_single_part_batch(
                model, failed[:mid], lang_label, lang, out_dir, args,
                npc_name, review_since_mtime, last_review_update, stats, generator
            )
            last_review_update = generate_single_part_batch(
                model, failed[mid:], lang_label, lang, out_dir, args,
                npc_name, review_since_mtime, last_review_update, stats, generator
            )
        else:
            e = failed[0]['entry']
            print(f"  [{npc_name}] Line ERROR {e.get('_ogg_path')}: {failed[0]}")
            stats['errors'] += 1
    return last_review_update


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
    """Return true whenever an existing voice file is on disk and non-empty."""
    return os.path.exists(filepath) and os.path.getsize(filepath) > 0


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
        npc = entry.get('npc', '') or ''
        if not npc:
            gender = (entry.get('voice_gender') or '').strip().lower()
            npc = NARRATOR_MALE_NAME if gender == 'male' else NARRATOR_FEMALE_NAME
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
                    'segment': row.get('segment', '') or '',
                    'total_segments': row.get('total_segments', '') or '',
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
        if uses_en_runtime_for_zh_voice(entry, lang):
            continue
        func_id = (
            entry.get(f'{lang}_func_id', '')
            or entry.get('func_id', '')
            or entry.get('zh_func_id', '')
            or entry.get('en_func_id', '')
            or '0000'
        )
        seg = entry.get(f'{lang}_segment', 0) or 0
        key = source_meta_key(
            lang,
            func_id,
            entry.get(f'{lang}_offset_key', '') or '0',
            seg,
        )
        base_key = source_meta_key(
            lang,
            func_id,
            entry.get(f'{lang}_offset_key', '') or '0',
            0,
        )
        valid_keys = source_runtime_keys.get(lang, set())
        if key not in valid_keys and base_key not in valid_keys:
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
    if '|' in npc:
        names = [n.strip() for n in npc.split('|') if n.strip()]
        if names:
            return names, 'mapping_npc_group'

    # Empty / UNKNOWN → try to identify from function context
    if not npc or npc == 'UNKNOWN':
        fid = normalize_func_id(entry.get('en_func_id', ''))
        COMPANION_BARK_FUNCS = {'0622', '0623', '0800', '08D5'}
        if fid in COMPANION_BARK_FUNCS:
            return list(COMPANION_NPCS), 'companion_bark'
        if fid == '06f6':
            return ['Arcadion'], 'mapping_npc'

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

def backup_legacy_voice_state(args):
    """Back up mutable legacy inputs once per invocation before replacing them."""
    if getattr(args, 'dry_run', False):
        return None
    existing = getattr(args, '_legacy_voice_backup_dir', None)
    if existing is not None:
        return Path(existing)

    backup_root = Path(PROJECT_DIR) / 'voice_backup'
    timestamp = time.strftime('%Y%m%d-%H%M%S')
    backup_dir = backup_root / timestamp
    suffix = 1
    while backup_dir.exists():
        backup_dir = backup_root / f'{timestamp}-{suffix}'
        suffix += 1
    backup_dir.mkdir(parents=True)

    refs_dir = Path(REFS_DIR)
    if refs_dir.exists():
        shutil.copytree(refs_dir, backup_dir / 'refs')
    prompts_path = Path(CLONE_PROMPTS_PATH)
    if prompts_path.exists():
        shutil.copy2(prompts_path, backup_dir / prompts_path.name)
    args._legacy_voice_backup_dir = str(backup_dir)
    print(f'Legacy voice inputs backed up to {backup_dir}')
    return backup_dir

def phase_a_generate_refs(designs, args):
    """Generate reference clips for each voice design using VoiceDesign."""
    backup_legacy_voice_state(args)
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


def phase_a_generate_candidates(designs, args):
    """Generate review candidates without touching approved voice/refs clips."""
    from generate_reference_candidates import (
        build_candidate_jobs,
        generate_jobs,
        load_model as load_candidate_model,
        load_designs_or_voice_bibles,
    )

    candidate_designs = designs
    voice_bibles = getattr(args, 'voice_bibles', None)
    if voice_bibles:
        candidate_designs = load_designs_or_voice_bibles(Path(DESIGNS_PATH), Path(voice_bibles))
    jobs = build_candidate_jobs(
        candidate_designs,
        Path(getattr(args, 'candidate_output_dir', CANDIDATE_DIR)),
        getattr(args, 'candidates', 10),
    )
    if args.dry_run:
        for job in jobs:
            print(f'  [{job.npc}] Would generate candidate {job.output}')
        return 0, 0, 0

    model = load_candidate_model(args.device)
    generated = generate_jobs(
        model,
        jobs,
        getattr(args, 'candidate_seed_base', 1000),
        getattr(args, 'candidate_batch_size', 16),
        getattr(args, 'skip_existing_candidates', False) and not getattr(args, 'overwrite_candidates', False),
    )
    print(f'Candidate Phase A complete. Generated: {len(generated)}, output: {getattr(args, "candidate_output_dir", CANDIDATE_DIR)}')
    return len(generated), 0, 0


# ── Phase B + C: Clone Prompts + Bulk Generation ──────────────────────

def build_npc_to_design_map(designs):
    """Build a reverse mapping from NPC name -> design ID."""
    npc_to_design = {}
    for did, design in designs['designs'].items():
        for npc_name in design['npcs']:
            npc_to_design[npc_name] = did
    return npc_to_design


def infer_design_gender(design_id, design):
    """Infer voice gender from design metadata used by voice generation."""
    identity = ' '.join([
        str(design_id or ''),
        str(design.get('npc', '') or ''),
    ]).lower()
    if re.search(r'(^|[_\W])female([_\W]|$)', identity):
        return 'female'
    if re.search(r'(^|[_\W])male([_\W]|$)', identity):
        return 'male'

    blob = ' '.join([
        str(design.get('voice_desc_en', '') or ''),
        str(design.get('voice_desc_zh', '') or ''),
    ]).lower()
    female_noise_patterns = [
        r'not(?:\s+\w+){0,4}\s+feminine',
        r'not\s+feminine',
        r'don[’\']?t(?:\s+\w+){0,4}\s+feminine',
        r'do\s+not(?:\s+\w+){0,4}\s+feminine',
        r'不要女性化',
        r'不女性化',
        r'非女性',
        r'female\s+roles?',
        r'woman[’\']?s\s+wig',
        r'in\s+drag',
        r'[飾饰][演演]女性(?:角色)?',
        r'女性角色',
    ]
    cleaned = blob
    for pattern in female_noise_patterns:
        cleaned = re.sub(pattern, ' ', cleaned)
    if (
        re.search(r'(^|[^a-z])female([^a-z]|$)', cleaned)
        or re.search(r'(^|[^a-z])feminine([^a-z]|$)', cleaned)
        or '女性' in cleaned
    ):
        return 'female'
    if (
        re.search(r'(^|[^a-z])male([^a-z]|$)', blob)
        or re.search(r'(^|[^a-z])masculine([^a-z]|$)', blob)
        or '男性' in blob
        or '男聲' in blob
        or '男中音' in blob
    ):
        return 'male'
    return None


def voice_gender_for_npc(designs, npc_to_design, npc_name):
    if npc_name == 'Avatar female':
        return 'female'
    if npc_name == 'Avatar male':
        return 'male'
    did = npc_to_design.get(npc_name)
    if not did:
        return None
    design = designs.get('designs', {}).get(did, {})
    return infer_design_gender(did, design)


def narrator_design_id_for_npc(designs, npc_to_design, npc_name):
    gender = voice_gender_for_npc(designs, npc_to_design, npc_name)
    if gender == 'male':
        return NARRATOR_MALE_DESIGN_ID
    return NARRATOR_FEMALE_DESIGN_ID


def phase_b_build_prompts(designs, args):
    """Build clone prompts from reference clips."""
    backup_legacy_voice_state(args)
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


def maybe_update_full_voice_review(args, since_mtime, last_update, force=False):
    out_dir = getattr(args, 'review_out_dir', None)
    if not out_dir:
        return last_update
    interval = getattr(args, 'review_update_interval', 120) or 120
    now = time.time()
    if not force and last_update and now - last_update < interval:
        return last_update
    if not force and last_update == 0 and now - since_mtime < interval:
        return last_update
    try:
        from generate_voice_review_html import rows_from_full_voice, write_report

        rows = rows_from_full_voice(
            Path(OUTPUT_DIR),
            Path(MAPPING_PATH),
            since_mtime=since_mtime,
            only_new=getattr(args, 'review_only_new', True),
        )
        html_path, data_path = write_report(
            rows,
            Path(out_dir),
            'Generated Voice Review - Current Run',
            review_id=str(since_mtime),
        )
        print(f'  Review HTML updated: {html_path} ({len(rows)} rows)')
        return now
    except Exception as ex:
        print(f'  Review HTML update ERROR: {ex}')
        return last_update


def phase_c_generate_voice(designs, clone_prompts, by_npc, args):
    """Bulk generate all ZH + EN voice files via VoiceClone."""
    print("DIAG: phase_c_generate_voice ENTERED", flush=True)
    os.makedirs(ZH_OUTPUT, exist_ok=True)
    os.makedirs(EN_OUTPUT, exist_ok=True)

    print(f'\n{"="*60}', flush=True)
    print('Phase C: Bulk generating voice files via VoiceClone', flush=True)
    print(f'{"="*60}', flush=True)

    total_gen = 0
    total_skip = 0
    total_err = 0
    total_would_gen = 0

    # Build NPC → design lookup
    npc_to_design = build_npc_to_design_map(designs)
    model = None
    generation_started_at = int(time.time())
    review_since_mtime = getattr(args, 'review_since_mtime', 0) or generation_started_at
    last_review_update = 0

    if not args.dry_run:
        print(f'\nLoading {BASE_MODEL}...', flush=True)
        model = Qwen3TTSModel.from_pretrained(
            BASE_MODEL,
            device_map=args.device,
            dtype=torch.bfloat16,
            attn_implementation=ATTN_IMPL,
        )
        # Deterministic sampling so each character's name is pronounced
        # identically across runs (see TTS_SEED). Guarded so environments
        # without a real torch (e.g. unit-test fakes) still run.
        tts_generator = None
        if hasattr(torch, "Generator") and not os.environ.get("OPCODE_DISABLE_TTS_SEED"):
            tts_generator = torch.Generator(device=args.device).manual_seed(TTS_SEED)

    try:
        langs = [args.lang] if args.lang else ['zh', 'en']
        for lang in langs:
            lang_label = 'Chinese' if lang == 'zh' else 'English'
            out_dir = ZH_OUTPUT if lang == 'zh' else EN_OUTPUT
            text_key = f'{lang}_text'
            narrator_prompts = {
                NARRATOR_FEMALE_DESIGN_ID: clone_prompts.get(NARRATOR_FEMALE_DESIGN_ID, {}).get(lang),
                NARRATOR_MALE_DESIGN_ID: clone_prompts.get(NARRATOR_MALE_DESIGN_ID, {}).get(lang),
            }

            print(f'\n{"-"*50}')
            print(f'Generating {lang_label} lines')
            print(f'{"-"*50}')

            if not args.dry_run:
                for narrator_id, prompt in narrator_prompts.items():
                    if prompt is None:
                        print(f'  [{narrator_id}] No narrator clone prompt for {lang}; matching narration falls back to speaker voice')

            npcs_in_lang = sorted([n for n in by_npc.keys()])
            progress_npc = 0

            for npc_name in npcs_in_lang:
                print(f'  [DIAG] NPC: {npc_name}', flush=True)
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
                narrator_id = narrator_design_id_for_npc(designs, npc_to_design, npc_name)
                narrator_prompt = narrator_prompts.get(narrator_id) or prompt_data
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

                for i in range(0, len(lang_entries), MAX_LINES_PER_CALL):
                    batch = lang_entries[i:i + MAX_LINES_PER_CALL]
                    to_generate = []

                    for e in batch:
                        fname = make_filename(e, lang)
                        generic_fname = get_generic_filename(e, lang)
                        ogg_path = os.path.join(out_dir, fname)
                        generic_path = os.path.join(out_dir, generic_fname)
                        expected_text = e.get(text_key, '') or ''
                        file_exists = (
                            (os.path.exists(ogg_path) and voice_file_matches_text(ogg_path, expected_text))
                            or (os.path.exists(generic_path) and voice_file_matches_text(generic_path, expected_text))
                        )
                        if file_exists and not args.force:
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

                    # Multi-part (narrator/speaker) lines: keep per-line fade-splice path.
                    single_jobs, multi_entries = prepare_voice_jobs(
                        to_generate, lang, text_key, prompt_data, narrator_prompt, narrator_id
                    )
                    stats = {'generated': 0, 'errors': 0}
                    for e in multi_entries:
                        try:
                            original_text = e.get(text_key, '') or '...'
                            parts = split_voice_parts(
                                original_text,
                                lang,
                                default_role=default_voice_role(e, lang),
                            )
                            wav_out, sr = generate_delimited_voice(
                                model,
                                parts,
                                lang,
                                prompt_data,
                                narrator_prompt,
                                generator=tts_generator,
                            )
                            prepare_voice_output_path(e['_ogg_path'])
                            write_ogg_direct(
                                e['_ogg_path'], wav_out, sr,
                                npc_name, original_text,
                                metadata={
                                    'VOICE_MODE': 'delimited_narrator_speaker',
                                    'NARRATOR': narrator_id,
                                },
                            )
                            generated += 1
                            if (
                                getattr(args, 'generic_fallbacks', False)
                                and not e.get('_suppress_generic_fallback')
                            ):
                                # Create generic fallback without hard-link aliasing.
                                create_generic_fallback(e['_ogg_path'], e, lang, out_dir)
                            last_review_update = maybe_update_full_voice_review(
                                args,
                                review_since_mtime,
                                last_review_update,
                                force=False,
                            )
                        except Exception as ex:
                            print(f'  [{npc_name}] Write ERROR {e["_ogg_path"]}: {ex}')
                            errors += 1

                    # Single-part lines: one batched model call per bucket.
                    for bucket in bucket_single_part_jobs(single_jobs, MAX_LINES_PER_CALL):
                        last_review_update = generate_single_part_batch(
                            model, bucket, lang_label, lang, out_dir, args, npc_name,
                            review_since_mtime, last_review_update, stats, tts_generator
                        )
                    generated += stats['generated']
                    errors += stats['errors']

                    if i > 0 and (i // MAX_LINES_PER_CALL) % 4 == 0:
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
                    print(status, flush=True)

                last_review_update = maybe_update_full_voice_review(
                    args,
                    review_since_mtime,
                    last_review_update,
                    force=False,
                )
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

    maybe_update_full_voice_review(args, review_since_mtime, last_review_update, force=True)

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

def build_parser():
    parser = argparse.ArgumentParser(description='3-stage Qwen3-TTS voice generation')
    parser.add_argument('--phase', type=str, default='all',
                        choices=['all', 'refs', 'prompts', 'voice'],
                        help='Which phase to run (default: all)')
    parser.add_argument('--dry-run', action='store_true', help='Scan and report only')
    parser.add_argument('--force', action='store_true', help='Force regenerate existing files')
    parser.add_argument('--force-refs', action='store_true', help='Force regenerate reference clips')
    parser.add_argument('--reference-workflow', choices=['candidates', 'legacy'], default='candidates',
                        help='Use review candidates by default; legacy writes approved voice/refs directly')
    parser.add_argument('--voice-bibles', type=str, default=None,
                        help='Optional per-NPC voice-bible directory for candidate generation')
    parser.add_argument('--candidate-output-dir', type=str, default=CANDIDATE_DIR,
                        help='Review-only candidate output directory (never voice/refs)')
    parser.add_argument('--candidates', type=int, default=10,
                        help='Reference candidates per NPC and language')
    parser.add_argument('--candidate-batch-size', type=int, default=16,
                        help='VoiceDesign candidate batch size; OOM batches split automatically')
    parser.add_argument('--candidate-seed-base', type=int, default=1000,
                        help='Base seed for candidate generation batches')
    parser.add_argument('--skip-existing-candidates', action='store_true',
                        help='Resume candidate generation by retaining existing candidate files')
    parser.add_argument('--overwrite-candidates', action='store_true',
                        help='Overwrite candidate files even with --skip-existing-candidates')
    parser.add_argument('--device', type=str, default='cuda:0', help='CUDA device')
    parser.add_argument('--npc', type=str, default=None, help='Single NPC to process')
    parser.add_argument('--max-npcs', type=int, default=None, help='Limit number of NPCs to process')
    parser.add_argument('--lang', type=str, default=None, choices=['zh', 'en'],
                        help='Language to process (default: both)')
    parser.add_argument('--generic-fallbacks', action='store_true',
                        help='Also create generic non-NPC fallback copies for generated/skipped NPC-specific files')
    parser.add_argument('--migrate', action='store_true', help='One-time migration: rename existing generic files to NPC-specific names')
    parser.add_argument('--review-out-dir', type=str, default=None,
                        help='Periodically write full generated voice review HTML to this directory')
    parser.add_argument('--review-update-interval', type=int, default=120,
                        help='Seconds between review HTML refreshes during Phase C')
    parser.add_argument('--review-since-mtime', type=int, default=0,
                        help='Unix mtime threshold for marking current-run generated files')
    parser.add_argument('--review-all', action='store_true',
                        help='Show all generated voice files in review HTML instead of only current-run files')
    return parser


def main():
    args = build_parser().parse_args()
    args.review_only_new = not args.review_all

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
        if args.reference_workflow == 'legacy':
            phase_a_generate_refs(designs, args)
        else:
            phase_a_generate_candidates(designs, args)
            if args.phase == 'all':
                print('Candidate workflow stops before prompts/voice; select and approve references first.')
                return

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
