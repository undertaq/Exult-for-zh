#!/usr/bin/env python3
"""Verify mapping: compare English and Chinese texts for each mapped pair."""
import csv
import sys
from collections import OrderedDict

def read_csv_texts(path):
    funcs = {}
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get('offset_key', '').strip()
            if not key:
                continue
            fid = row.get('func_id', '').strip()
            key = key.replace('0x', '')
            seg_str = row.get('segment', '0').strip()
            seg = int(seg_str) if seg_str else 0
            if fid not in funcs:
                funcs[fid] = {}
            dk = (key, seg)
            if dk not in funcs[fid]:
                funcs[fid][dk] = {
                    'text': row.get('text', ''),
                    'npc': row.get('npc', ''),
                    'caller': row.get('caller_guess', ''),
                }
    return funcs

mapping = []
with open('tools/voice_acting/offset_mapping.csv', newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for r in reader:
        mapping.append(r)

en_texts = read_csv_texts('tools/voice_acting/en_voice_lines.csv')
zh_texts = read_csv_texts('tools/voice_acting/zh_voice_lines.csv')

by_func = OrderedDict()
for r in mapping:
    fid = r['en_func_id']
    if fid not in by_func:
        by_func[fid] = []
    by_func[fid].append(r)

target_funcs = sys.argv[1:] if len(sys.argv) > 1 else ['0x0401']

all_out = []
for func_id in target_funcs:
    if func_id not in by_func:
        all_out.append(f"\nFunc {func_id} not in mapping")
        continue

    entries = by_func[func_id]
    en_text_db = en_texts.get(func_id, {})
    zh_text_db = zh_texts.get(func_id, {})

    all_out.append(f"\n{'='*80}")
    all_out.append(f"VERIFICATION for {func_id} ({len(entries)} mapped entries)")
    all_out.append(f"{'='*80}")

    for i, r in enumerate(entries):
        en_key = r['en_offset_key']
        en_seg = int(r['en_segment'])
        zh_key = r['zh_offset_key']
        zh_seg = int(r['zh_segment'])

        en_info = en_text_db.get((en_key, en_seg), {})
        zh_info = zh_text_db.get((zh_key, zh_seg), {})

        en_text = en_info.get('text', '')
        zh_text = zh_info.get('text', '')

        en_short = en_text[:80].replace('\n', ' ')
        zh_short = zh_text[:80].replace('\n', ' ')

        all_out.append(f"\n{i:4d}. [{en_key:20s} seg{en_seg}] -> [{zh_key:20s} seg{zh_seg}]")
        all_out.append(f"     EN: {en_short}")
        all_out.append(f"     ZH: {zh_short}")

    all_out.append(f"\n--- Func {func_id} summary: {len(entries)} entries ---")

out_path = 'tools/voice_acting/verify_0401.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(all_out))
print(f"Written to {out_path}")
