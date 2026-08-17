#!/usr/bin/env python3
"""
Generate mapping from English to Chinese voice offset keys.

Pairs entries by offset_key order within each function_id, then
maps segments 1-to-1 within each paired offset_key group.

Usage:
    python generate_offset_mapping.py
        --en en_voice_lines.csv
        --zh zh_voice_lines.csv
        -o offset_mapping.csv
"""

import argparse
import csv
import sys
from collections import OrderedDict


def read_csv(path):
    """Read CSV, group entries by func_id, preserving insertion order.
    Returns dict: func_id -> list of groups, where each group is:
      {'offset_key': str, 'segments': [int, ...], 'texts': [str, ...]}"""
    funcs = OrderedDict()
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get('offset_key', '').strip()
            if not key:
                continue
            key = key.replace('0x', '')
            fid = row.get('func_id', '').strip()
            seg_str = row.get('segment', '0').strip()
            seg = int(seg_str) if seg_str else 0
            text = row.get('text', '')

            if fid not in funcs:
                funcs[fid] = OrderedDict()

            if key not in funcs[fid]:
                funcs[fid][key] = {'offset_key': key, 'segments': [], 'texts': []}
            funcs[fid][key]['segments'].append(seg)
            funcs[fid][key]['texts'].append(text)

    # Convert OrderedDict of groups to list of groups (preserving offset_key order)
    result = OrderedDict()
    for fid, groups in funcs.items():
        result[fid] = list(groups.values())
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate offset key mapping from English to Chinese")
    parser.add_argument('--en', required=True,
                        help='English CSV from disassemble_usecode.py --format csv')
    parser.add_argument('--zh', required=True,
                        help='Chinese CSV')
    parser.add_argument('-o', '--output', required=True,
                        help='Output mapping CSV')
    args = parser.parse_args()

    en_funcs = read_csv(args.en)
    zh_funcs = read_csv(args.zh)

    mapping = []

    common_fids = sorted(set(en_funcs.keys()) & set(zh_funcs.keys()))

    for fid in common_fids:
        en_groups = en_funcs[fid]
        zh_groups = zh_funcs[fid]

        count = min(len(en_groups), len(zh_groups))
        if len(en_groups) != len(zh_groups):
            print(f"  WARNING: func {fid}: {len(en_groups)} English offset_key groups vs "
                  f"{len(zh_groups)} Chinese groups — only pairing {count}",
                  file=sys.stderr)

        for i in range(count):
            en_grp = en_groups[i]
            zh_grp = zh_groups[i]

            en_segs = en_grp['segments']
            zh_segs = zh_grp['segments']
            en_texts = en_grp['texts']

            seg_count = min(len(en_segs), len(zh_segs))
            if len(en_segs) != len(zh_segs):
                print(f"  NOTE: func {fid}: {en_grp['offset_key']} has {len(en_segs)} EN segs vs "
                      f"{zh_grp['offset_key']} has {len(zh_segs)} ZH segs — pairing {seg_count}",
                      file=sys.stderr)

            for j in range(seg_count):
                en_text = en_texts[j] if j < len(en_texts) else ''
                mapping.append((
                    fid, en_grp['offset_key'], en_segs[j], en_text,
                    fid, zh_grp['offset_key'], zh_segs[j],
                ))

    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'en_func_id', 'en_offset_key', 'en_segment', 'en_text',
            'zh_func_id', 'zh_offset_key', 'zh_segment',
        ])
        for row in mapping:
            writer.writerow(row)

    print(f"Written {len(mapping)} mappings to {args.output}")
    print(f"  (from {len(common_fids)} common function IDs)")


if __name__ == '__main__':
    main()
