#!/usr/bin/env python3
"""
One-time migration: rename existing generic voice files to NPC-specific names.

The game's VoiceActingManager tries {base}_npc{N}.ogg first, then {base}.ogg.
By including the NPC number, we eliminate collisions where different NPCs
share the same func_id/offset_key/segment.

For entries with known NPC numbers:
- If NPC-specific file already exists → ensure generic hard link exists
- If generic file exists → verify DESCRIPTION metadata matches expected text
- If correct → rename to NPC-specific, create generic hard link (zero extra space)
- If wrong → delete wrong file (Phase C will regenerate)

Does NOT import torch, so runs quickly even without GPU.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from npc_data import NPC_NUMBERS

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
ZH_OUTPUT = os.path.join(PROJECT_DIR, 'voice', 'zh')
EN_OUTPUT = os.path.join(PROJECT_DIR, 'voice', 'en')
MAPPING_PATH = os.path.join(SCRIPT_DIR, 'bilingual_mapping_review.json')


def _build_base_name(entry, lang):
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


def build_description_cache(out_dir):
    cache = {}
    ogg_files = glob.glob(os.path.join(out_dir, '*.ogg'))
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


def main():
    parser = argparse.ArgumentParser(description='Migrate voice files to NPC-specific names')
    parser.add_argument('--dry-run', action='store_true', help='Report only, no changes')
    args = parser.parse_args()

    print(f'Loading mapping from {MAPPING_PATH}')
    with open(MAPPING_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    renamed = 0
    wrong = 0
    missing = 0
    skipped = 0

    for lang in ['zh', 'en']:
        out_dir = ZH_OUTPUT if lang == 'zh' else EN_OUTPUT
        text_key = f'{lang}_text'
        lang_label = 'ZH' if lang == 'zh' else 'EN'

        print(f'\n--- {lang_label} ---')
        print(f'  Building description cache from {out_dir}...')
        desc_cache = build_description_cache(out_dir)

        # Track processed generic bases to avoid double-counting
        processed = set()

        for entry in data:
            npc_name = entry.get('npc', '') or ''
            npc_num = NPC_NUMBERS.get(npc_name)
            if npc_num is None:
                continue  # UNKNOWN → keep generic name

            base = _build_base_name(entry, lang)
            if base in processed:
                continue
            processed.add(base)

            npc_fname = f'{base}_npc{npc_num}.ogg'
            generic_fname = f'{base}.ogg'
            npc_path = os.path.join(out_dir, npc_fname)
            generic_path = os.path.join(out_dir, generic_fname)

            if os.path.exists(npc_path):
                skipped += 1
                if not os.path.exists(generic_path) and not args.dry_run:
                    os.link(npc_path, generic_path)
                    print(f'  [{npc_name}] {lang}: restored missing generic link')
                continue

            if not os.path.exists(generic_path):
                missing += 1
                continue

            # Verify generic file content
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
                    print(f'  [{npc_name}] {lang}: WRONG content, would delete')
                else:
                    os.remove(generic_path)
                wrong += 1

    print(f'\n{"="*60}')
    print(f'Migration complete.')
    print(f'  Already NPC-specific: {skipped}')
    print(f'  Renamed (correct):    {renamed}')
    print(f'  Wrong content (del):  {wrong}')
    print(f'  Missing (need gen):   {missing}')
    print(f'{"="*60}')
    if args.dry_run and (wrong > 0 or missing > 0):
        print(f'\nRun Phase C to regenerate {wrong + missing} entries with wrong/missing content.')


if __name__ == '__main__':
    main()
