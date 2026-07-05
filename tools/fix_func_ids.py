"""
Fix en_func_id and zh_func_id in bilingual_mapping_review.json using
the authoritative offset_mapping.csv. Then rename generated voice files
to match the correct function IDs.

The JSON was generated with en_func_id == zh_func_id (always the same),
but the real EN and ZH usecode often use different function IDs for the
same conversation. This script corrects them.
"""
import csv
import json
import os
import shutil
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR   = os.path.dirname(SCRIPT_DIR)

CSV_PATH  = os.path.join(SCRIPT_DIR, 'voice_acting', 'offset_mapping.csv')
JSON_PATH = os.path.join(SCRIPT_DIR, 'voice_acting', 'bilingual_mapping_review.json')
VOICE_DIR = os.path.join(REPO_DIR, 'voice')

# ── 1. Build authoritative lookup from offset_mapping.csv ─────────────
# Key: (en_offset_key, zh_offset_key, en_segment, zh_segment)
# Value: {'en_fid': ..., 'zh_fid': ...}
lookup_exact = {}       # exact match with segments
lookup_by_key = defaultdict(set)  # (en_ok, zh_ok) -> set of (en_fid, zh_fid, en_seg, zh_seg)

with open(CSV_PATH, newline='', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        en_fid = row['en_func_id'].strip()
        en_ok  = row['en_offset_key'].strip()
        en_seg = int(row['en_segment'].strip()) if row['en_segment'].strip() else 0
        zh_fid = row['zh_func_id'].strip()
        zh_ok  = row['zh_offset_key'].strip()
        zh_seg = int(row['zh_segment'].strip()) if row['zh_segment'].strip() else 0
        if not en_fid or not en_ok:
            continue
        key_exact = (en_ok, zh_ok, en_seg, zh_seg)
        lookup_exact[key_exact] = {'en_fid': en_fid, 'zh_fid': zh_fid}
        key_loose = (en_ok, zh_ok)
        lookup_by_key[key_loose].add((en_fid, zh_fid, en_seg, zh_seg))

print(f'Loaded {len(lookup_exact)} exact-match entries from CSV')
print(f'Loaded {len(lookup_by_key)} offset-key groups from CSV')

# For offset-key pairs that have a unique func_id mapping, we can use loose match
unique_by_key = {}
for k, v in lookup_by_key.items():
    func_ids = set((fid1, fid2) for fid1, fid2, _, _ in v)
    if len(func_ids) == 1:
        fid_pair = func_ids.pop()
        unique_by_key[k] = {'en_fid': fid_pair[0], 'zh_fid': fid_pair[1]}

print(f'Offset-key pairs with unique func_id mapping: {len(unique_by_key)}')

# ── 2. Process JSON entries ──────────────────────────────────────────
data = json.load(open(JSON_PATH, encoding='utf-8'))

rename_en_ok = 0
rename_en_dup = 0
rename_en_skip = 0
rename_zh_ok = 0
rename_zh_dup = 0
rename_zh_skip = 0
fixed_en = 0
fixed_zh = 0
unmatched = 0

# Track used filenames to detect collisions
used_en = set()
used_zh = set()

def make_name(fid, ok, seg):
    fid_s = fid.replace('0x', '').replace('0X', '').lower().zfill(4) if fid else '0000'
    return f'{fid_s}_{ok}_{seg}.ogg'

for entry in data:
    en_fid_old = entry.get('en_func_id', '')
    zh_fid_old = entry.get('zh_func_id', '')
    en_ok = entry.get('en_offset_key', '')
    zh_ok = entry.get('zh_offset_key', '')
    en_seg = entry.get('en_segment', 0)
    zh_seg = entry.get('zh_segment', 0)

    # Try exact match first
    key_exact = (en_ok, zh_ok, en_seg, zh_seg)
    if key_exact in lookup_exact:
        correct = lookup_exact[key_exact]
    else:
        # Fall back to loose match by offset keys only
        key_loose = (en_ok, zh_ok)
        if key_loose in unique_by_key:
            correct = unique_by_key[key_loose]
        else:
            unmatched += 1
            continue

    en_fid_new = correct['en_fid']
    zh_fid_new = correct['zh_fid']

    # Update JSON
    if en_fid_new != en_fid_old:
        entry['en_func_id'] = en_fid_new
        fixed_en += 1
    if zh_fid_new != zh_fid_old:
        entry['zh_func_id'] = zh_fid_new
        fixed_zh += 1

    # Rename EN file
    if en_fid_old and en_ok and en_fid_new != en_fid_old:
        old_name = make_name(en_fid_old, en_ok, en_seg)
        new_name = make_name(en_fid_new, en_ok, en_seg)
        if new_name in used_en:
            rename_en_dup += 1
        else:
            old_path = os.path.join(VOICE_DIR, 'en', old_name)
            new_path = os.path.join(VOICE_DIR, 'en', new_name)
            if os.path.exists(old_path) and not os.path.exists(new_path):
                shutil.move(old_path, new_path)
                rename_en_ok += 1
            elif os.path.exists(old_path) and os.path.exists(new_path):
                # Both exist — keep the new one, delete old
                os.remove(old_path)
                rename_en_dup += 1
            else:
                rename_en_skip += 1
            used_en.add(new_name)

    # Rename ZH file
    if zh_fid_old and zh_ok and zh_fid_new != zh_fid_old:
        old_name = make_name(zh_fid_old, zh_ok, zh_seg)
        new_name = make_name(zh_fid_new, zh_ok, zh_seg)
        if new_name in used_zh:
            rename_zh_dup += 1
        else:
            old_path = os.path.join(VOICE_DIR, 'zh', old_name)
            new_path = os.path.join(VOICE_DIR, 'zh', new_name)
            if os.path.exists(old_path) and not os.path.exists(new_path):
                shutil.move(old_path, new_path)
                rename_zh_ok += 1
            elif os.path.exists(old_path) and os.path.exists(new_path):
                os.remove(old_path)
                rename_zh_dup += 1
            else:
                rename_zh_skip += 1
            used_zh.add(new_name)

print(f'\nJSON fixes:')
print(f'  en_func_id fixed: {fixed_en}')
print(f'  zh_func_id fixed: {fixed_zh}')
print(f'  unmatched (skipped): {unmatched}')
print(f'\nEN file renames:')
print(f'  OK: {rename_en_ok}')
print(f'  Dup/superseded: {rename_en_dup}')
print(f'  Skip (old file missing): {rename_en_skip}')
print(f'\nZH file renames:')
print(f'  OK: {rename_zh_ok}')
print(f'  Dup/superseded: {rename_zh_dup}')
print(f'  Skip (old file missing): {rename_zh_skip}')

# ── 3. Write fixed JSON ──────────────────────────────────────────────
json.dump(data, open(JSON_PATH, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
print(f'\nUpdated {JSON_PATH}')
