"""
Generate bilingual_map.dat using confidence-verified pairings from
bilingual_mapping.csv. Excludes low-confidence and unpaired entries
to prevent wrong voice cross-language playback.
"""
import csv
import struct
import os
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR   = os.path.dirname(SCRIPT_DIR)

MAPPING_CSV  = os.path.join(SCRIPT_DIR, 'voice_acting', 'bilingual_mapping.csv')
JSON_PATH    = os.path.join(SCRIPT_DIR, 'voice_acting', 'bilingual_mapping_review.json')
OUTPUT_PATH  = os.path.join(REPO_DIR, 'voice', 'bilingual_map.dat')

# Confidence levels to include (verified correct)
# order_based and high are reliable; medium can be wrong due to
# length-ratio false positives; low/unpaired are always wrong.
INCLUDE_CONFIDENCE = {'order_based', 'high'}

# ── 1. Load corrected func_ids from JSON ─────────────────────────────
import json
json_data = json.load(open(JSON_PATH, encoding='utf-8'))

# Build lookup: (en_offset_key, zh_offset_key) → (en_func_id, zh_func_id)
func_id_map = {}
for d in json_data:
    en_ok = d.get('en_offset_key', '')
    zh_ok = d.get('zh_offset_key', '')
    en_fid = d.get('en_func_id', '')
    zh_fid = d.get('zh_func_id', '')
    if en_ok and zh_ok and en_fid and zh_fid:
        key = (en_ok, zh_ok)
        func_id_map[key] = (en_fid, zh_fid)

print(f'Loaded {len(func_id_map)} func_id mappings from JSON')

# ── 2. Read and filter bilingual_mapping.csv ─────────────────────────
mappings = []
conf_counts = Counter()
no_func = 0

with open(MAPPING_CSV, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        conf = row.get('confidence', '').strip()
        if conf not in INCLUDE_CONFIDENCE:
            continue
        conf_counts[conf] += 1

        func_id_raw = row.get('func_id', '').strip()
        en_ok = row.get('en_offset_key', '').strip()
        en_seg = int(row.get('en_segment', '0').strip() or 0)
        zh_ok = row.get('zh_offset_key', '').strip()
        zh_seg = int(row.get('zh_segment', row.get('en_segment', '0')).strip() or 0)

        if not func_id_raw or not en_ok or not zh_ok:
            continue

        # Get corrected func_ids from JSON if available
        # Fall back to same func_id for both
        key = (en_ok, zh_ok)
        if key in func_id_map:
            en_fid_str, zh_fid_str = func_id_map[key]
        else:
            en_fid_str = zh_fid_str = func_id_raw

        # Parse func_ids (might be '0x0401')
        try:
            en_fid = int(en_fid_str.replace('0x', '').replace('0X', ''), 16)
            zh_fid = int(zh_fid_str.replace('0x', '').replace('0X', ''), 16)
        except (ValueError, AttributeError):
            no_func += 1
            continue

        mappings.append({
            'zh_fid': zh_fid,
            'zh_key': zh_ok,
            'zh_seg': zh_seg,
            'en_fid': en_fid,
            'en_key': en_ok,
            'en_seg': en_seg,
        })

print(f'Total verified mappings: {len(mappings)}')
for conf, count in conf_counts.most_common():
    print(f'  {conf}: {count}')
print(f'  (func_id lookup fails: {no_func})')

# ── 3. Deduplicate on (zh_fid, zh_key, zh_seg) ───────────────────────
seen = {}
for m in mappings:
    key = (m['zh_fid'], m['zh_key'], m['zh_seg'])
    if key not in seen:
        seen[key] = m

print(f'Unique entries (after dedup): {len(seen)}')

# ── 4. Write BLMP ────────────────────────────────────────────────────
with open(OUTPUT_PATH, 'wb') as f:
    f.write(b'BLMP')
    f.write(struct.pack('<I', len(seen)))
    for m in seen.values():
        f.write(struct.pack('<i', m['zh_fid']))
        f.write(m['zh_key'].encode('utf-8') + b'\0')
        f.write(struct.pack('<H', m['zh_seg']))
        f.write(struct.pack('<i', m['en_fid']))
        f.write(m['en_key'].encode('utf-8') + b'\0')

size = os.path.getsize(OUTPUT_PATH)
print(f'Written {len(seen)} entries ({size} bytes) to {OUTPUT_PATH}')
