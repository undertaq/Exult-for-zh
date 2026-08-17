#!/usr/bin/env python3
"""Investigate offset mapping vs runtime log discrepancies."""
import csv
import sys

# Read mapping
mapping = {}
with open('tools/voice_acting/offset_mapping.csv', newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for r in reader:
        fid = r['en_func_id']
        en_key = r['en_offset_key']
        en_seg = r['en_segment']
        key = (fid, en_key, int(en_seg))
        mapping[key] = (r['zh_offset_key'], int(r['zh_segment']))

# Read runtime log - extract ground-truth pairs
# "played" entries = English file that existed and played
# "missing" entries = Chinese file that was missing
en_played = {}  # (fid, offset_key, segment) -> text
zh_missing = {}  # (fid, offset_key, segment) -> text

with open(r'D:\Game\Ultima7_BlackGate_zhTW_v1.0\Ultima_7\patch\voice_acting\voice_acting_log.csv', newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for r in reader:
        fid = r['func_id']
        offset_key = r['offset_key']
        seg = int(r['segment'])
        text = r['text']
        status = r['status']
        fname = r['filename']
        if status == 'played':
            # Only take the first session to avoid duplicates
            key = (fid, offset_key, seg)
            if key not in en_played:
                en_played[key] = (text, fname)
        elif status == 'missing':
            key = (fid, offset_key, seg)
            if key not in zh_missing:
                zh_missing[key] = (text, fname)

# For each English "played" entry, check what our mapping says and what the log says
print("=" * 80)
print("ENGLISH PLAYED -> what mapping pairs, vs what Chinese was actually missing")
print("=" * 80)
for (fid, en_key, en_seg), (en_text, en_fname) in sorted(en_played.items()):
    map_result = mapping.get((fid, en_key, en_seg))
    if map_result:
        zh_mapped_key, zh_mapped_seg = map_result
        zh_fname_expected = f"{fid.lower().replace('0x','')}_{zh_mapped_key}_{zh_mapped_seg}.ogg"
        
        # Check if there's a ground-truth Chinese missing entry for this func
        zh_actual = None
        for (zfid, zkey, zseg), (ztext, zfname) in zh_missing.items():
            if zfid == fid:
                zh_actual = (zkey, zseg, ztext[:60], zfname)
                break
        
        match = "MATCH" if (zh_actual and zh_actual[0] == zh_mapped_key and zh_actual[1] == zh_mapped_seg) else "MISMATCH"
        
        print(f"\n{fid} en={en_key}_{en_seg}")
        print(f"  EN text:    {en_text[:80]}")
        if zh_actual:
            print(f"  ZH log:     {zh_actual[0]}_{zh_actual[1]}  text={zh_actual[2]}")
        else:
            print(f"  ZH log:     (no entry)")
        print(f"  MAPPING ->  {zh_mapped_key}_{zh_mapped_seg}  [{match}]")
    else:
        print(f"\n{fid} en={en_key}_{en_seg}")
        print(f"  EN text:    {en_text[:80]}")
        print(f"  MAPPING:    (no mapping entry)")
