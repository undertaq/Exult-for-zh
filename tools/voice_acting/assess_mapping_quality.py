#!/usr/bin/env python3
"""Assess mapping quality by checking how many functions have matching group counts."""
import csv
from collections import OrderedDict

def count_groups(path):
    funcs = OrderedDict()
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get('offset_key', '').strip()
            if not key:
                continue
            fid = row.get('func_id', '').strip()
            key = key.replace('0x', '')
            if fid not in funcs:
                funcs[fid] = OrderedDict()
            if key not in funcs[fid]:
                funcs[fid][key] = 0
            funcs[fid][key] += 1
    return {fid: list(g.keys()) for fid, g in funcs.items()}

en_groups = count_groups('tools/voice_acting/en_voice_lines.csv')
zh_groups = count_groups('tools/voice_acting/zh_voice_lines.csv')

common = sorted(set(en_groups.keys()) & set(zh_groups.keys()))
exact = 0
mismatched = 0
total_en = 0
total_zh = 0
mismatch_details = []

for fid in common:
    en_keys = en_groups[fid]
    zh_keys = zh_groups[fid]
    total_en += len(en_keys)
    total_zh += len(zh_keys)
    if len(en_keys) == len(zh_keys):
        exact += 1
    else:
        mismatched += 1
        mismatch_details.append((fid, len(en_keys), len(zh_keys)))

print(f"Total common functions: {len(common)}")
print(f"Exact group count match: {exact}")
print(f"Group count mismatch: {mismatched}")
print(f"Total EN groups: {total_en}")
print(f"Total ZH groups: {total_zh}")
print()

print("Functions with mismatched group counts (top 30):")
for fid, en_c, zh_c in mismatch_details[:30]:
    print(f"  {fid}: EN={en_c} groups, ZH={zh_c} groups")
    if en_c != zh_c:
        # Show how many match
        en_keys = en_groups[fid]
        zh_keys = zh_groups[fid]
        common_prefix = 0
        for i in range(min(en_c, zh_c)):
            if en_keys[i] == zh_keys[i]:
                common_prefix += 1
            else:
                break
        print(f"       Groups match at same position: {common_prefix} / {min(en_c, zh_c)}")

# Even for functions with exact group count, check if the actual keys match
same_keys = 0
diff_keys = 0
for fid in common:
    en_keys = en_groups[fid]
    zh_keys = zh_groups[fid]
    if en_keys == zh_keys:
        same_keys += 1
    elif len(en_keys) == len(zh_keys):
        diff_keys += 1

print()
print(f"Functions with exact same offset keys (in order): {same_keys}")
print(f"Functions with same count but different keys: {diff_keys}")
