#!/usr/bin/env python3
"""Rename ZH voice files and update metadata to match bilingual_mapping_review.json.

Looks up each ogg file by (func_id, offset_key, segment), reads the
current zh_func_id/zh_offset_key/zh_segment/npc from the mapping,
builds the expected filename, renames if different, and updates
vorbis-comment metadata (artist, description, en_text, refs).

Usage:
    .venv/bin/python rename_zh_voices.py [--dry-run]
"""

import json
import os
import re
import sys
from pathlib import Path

import mutagen

sys.path.insert(0, str(Path(__file__).parent))
from npc_data import NPC_NUMBERS

MAPPING = Path(__file__).parent / 'bilingual_mapping_review.json'
ZH_DIR = Path(__file__).parent.parent.parent / 'voice' / 'zh'

NPC_BY_NUMBER = {v: k for k, v in NPC_NUMBERS.items()}

FILE_PAT = re.compile(
    r'^([0-9a-f]+)_([0-9a-f_]+)_(\d+)(?:_npc(\d+))?(?:\.ogg)?$'
)


def normalize_key(fid: str, off: str, seg: int) -> str:
    fid_clean = fid.lower().replace('0x', '').lstrip('0') or '0'
    parts = off.lower().split('_')
    off_clean = '_'.join(p.lstrip('0x').lstrip('0') or '0' for p in parts)
    return f"{fid_clean}_{off_clean}_{seg}"


def build_index(data):
    idx = {}
    for e in data:
        fid = e.get('zh_func_id', '')
        off = e.get('zh_offset_key', '')
        seg = e.get('zh_segment', 0)
        if not fid or off is None:
            continue
        key = normalize_key(fid, off, seg)
        if key not in idx:
            idx[key] = e
        elif e.get('npc', '').strip() and not idx[key].get('npc', '').strip():
            idx[key] = e
    return idx


def get_npc_number(npc_name: str) -> int:
    name = npc_name.strip()
    if not name or name.upper() == 'UNKNOWN':
        return 0
    return NPC_NUMBERS.get(name, 0)


def resolve_npc(entry, file_npc: int = 0) -> tuple[int, str]:
    """Resolve NPC number and name for this file.
    
    If the file has an NPC number and it differs from the mapping's,
    the file's NPC is kept (different speaker for the same line).
    """
    mapping_npc_name = entry.get('npc', '').strip()
    mapping_npc_num = get_npc_number(mapping_npc_name)
    if file_npc and mapping_npc_num and file_npc != mapping_npc_num:
        return (file_npc, NPC_BY_NUMBER.get(file_npc, ''))
    if mapping_npc_num:
        return (mapping_npc_num, mapping_npc_name)
    if file_npc:
        return (file_npc, NPC_BY_NUMBER.get(file_npc, ''))
    return (0, '')


def build_expected_filename(entry, file_npc: int = 0) -> str | None:
    fid = entry.get('zh_func_id', '')
    off = entry.get('zh_offset_key', '')
    seg = entry.get('zh_segment', 0)
    if not fid or off is None:
        return None
    fid_clean = fid.lower().replace('0x', '').lstrip('0') or '0'
    off_clean = '_'.join(
        p.lower().replace('0x', '').lstrip('0') or '0'
        for p in off.split('_')
    )
    npc_num, _ = resolve_npc(entry, file_npc)
    if npc_num:
        return f"{fid_clean}_{off_clean}_{seg}_npc{npc_num}.ogg"
    else:
        return f"{fid_clean}_{off_clean}_{seg}.ogg"


def build_metadata_tags(entry, file_npc: int = 0) -> dict:
    _, npc = resolve_npc(entry, file_npc)
    npc = npc.strip()
    artist_val = f"qwen3:{npc}" if npc and npc.upper() != 'UNKNOWN' else 'qwen3'
    en_text = entry.get('en_text', '') or ''
    zh_text = entry.get('zh_text', '') or ''
    fid = entry.get('zh_func_id', '')
    off = entry.get('zh_offset_key', '')
    seg = entry.get('zh_segment', 0)
    fid_clean = fid.lower().replace('0x', '').lstrip('0') or '0' if fid else ''
    off_clean = '_'.join(
        p.lower().replace('0x', '').lstrip('0') or '0'
        for p in off.split('_')
    ) if off else ''

    tags = {}
    if zh_text:
        tags['description'] = [zh_text]
    if en_text:
        tags['en_text'] = [en_text]
    if artist_val:
        tags['artist'] = [artist_val]
    if fid_clean:
        tags['func_id'] = [fid_clean]
    if off_clean:
        tags['offset_key'] = [off_clean]
    tags['segment'] = [str(seg)]
    if npc:
        tags['npc'] = [npc]
    return tags


STALE_TAGS = {'narrator', 'voice_mode', 'voice_type'}


def update_file_metadata(audio_path: str, entry: dict, dry_run: bool, file_npc: int = 0) -> bool:
    needed_tags = build_metadata_tags(entry, file_npc=file_npc)
    try:
        audio = mutagen.File(audio_path)
    except Exception:
        return False
    if audio is None:
        return False

    changed = False

    if dry_run:
        return True

    current = {}
    if hasattr(audio, 'tags') and audio.tags:
        for key in audio.tags.keys():
            current[key] = [str(v) for v in audio.tags[key]]
    else:
        audio.add_tags()
        current = {}

    # Remove stale tags
    for stale in STALE_TAGS:
        if stale in current:
            del audio.tags[stale]
            changed = True

    # Set / update tags
    for key, val in needed_tags.items():
        if current.get(key) != val:
            audio.tags[key] = val
            changed = True

    if changed:
        audio.save()
    return True


def main():
    dry_run = '--dry-run' in sys.argv

    with open(MAPPING) as f:
        data = json.load(f)

    idx = build_index(data)
    print(f"Built index from {len(data)} entries ({len(idx)} unique keys)")

    if not ZH_DIR.exists():
        print(f"ERROR: ZH directory not found: {ZH_DIR}")
        return 1

    ogg_files = [f for f in os.listdir(ZH_DIR) if f.endswith('.ogg')]
    print(f"ZH ogg files: {len(ogg_files)}")

    renamed = 0
    meta_updated = 0
    skipped = 0
    not_found = 0
    errors = 0

    # Process NPC-labeled files first so generic (no _npcN) files
    # don't claim the target name before the NPC-specific one
    ogg_files.sort(key=lambda f: (1 if '_npc' not in f else 0, f))
    for filename in ogg_files:
        m = FILE_PAT.match(filename.replace('.ogg', ''))
        if not m:
            m = FILE_PAT.match(filename)
        if not m:
            print(f"  SKIP (cannot parse): {filename}")
            skipped += 1
            continue

        fid, off, seg_str, npc_num_str = m.groups()
        seg = int(seg_str)
        key = normalize_key(fid, off, seg)

        entry = idx.get(key)
        if entry is None:
            alt_key = normalize_key(fid, off.rstrip('0') or '0', seg)
            entry = idx.get(alt_key)

        if entry is None:
            print(f"  NOT FOUND in JSON: {filename} (key={key})")
            not_found += 1
            continue

        file_npc = int(npc_num_str) if npc_num_str else 0
        expected = build_expected_filename(entry, file_npc=file_npc)
        if expected is None:
            print(f"  ERROR building expected name for: {filename}")
            errors += 1
            continue

        needs_rename = filename != expected
        current_path = ZH_DIR / filename
        target_path = ZH_DIR / expected

        if needs_rename and target_path.exists():
            # Generic file (no _npcN) colliding with NPC-labeled file → skip generic
            if not npc_num_str or file_npc == 0:
                print(f"  SKIP (generic, target exists): {filename}")
                skipped += 1
                continue
            else:
                print(f"  CONFLICT: {expected} already exists (from {filename})")
                errors += 1
                continue

        # Rename
        if needs_rename:
            if dry_run:
                print(f"  WOULD RENAME: {filename} → {expected}")
            else:
                os.rename(current_path, target_path)
                print(f"  RENAMED: {filename} → {expected}")
            renamed += 1

        # Update metadata (always, for matched entries)
        meta_path = str(target_path if not dry_run else current_path)
        meta_ok = update_file_metadata(meta_path, entry, dry_run, file_npc=file_npc)
        if meta_ok:
            meta_updated += 1
        else:
            print(f"  WARN: metadata update failed for: {filename}")

    print(f"\n{'='*60}")
    print(f"  Dry run: {dry_run}")
    print(f"  Renamed: {renamed}")
    print(f"  Metadata updated: {meta_updated}")
    print(f"  Skipped (unparsed): {skipped}")
    print(f"  Not found in JSON: {not_found}")
    print(f"  Errors: {errors}")
    print(f"{'='*60}")

    if not_found:
        print(f"\nTIP: {not_found} files had no matching JSON entry.")
        print("     These may be outdated voice files that need regeneration.")

    return 0 if errors == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
