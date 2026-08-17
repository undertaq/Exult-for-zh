"""
Convert the offset_mapping.csv to BLMP binary format for bilingual_map.dat.
"""
import csv
import struct
import sys

csv_path = 'offset_mapping.csv'
map_path = 'D:/Project/Ultima_7/patch/voice_acting/bilingual_map.dat'

mappings = []
with open(csv_path, newline='', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        en_fid_str = row.get('en_func_id', '').strip()
        zh_fid_str = row.get('zh_func_id', '').strip()
        en_key = row.get('en_offset_key', '').strip()
        zh_key = row.get('zh_offset_key', '').strip()
        seg_str = row.get('en_segment', '0').strip()
        zh_seg_str = row.get('zh_segment', row.get('en_segment', '0')).strip()

        if not en_fid_str or not zh_fid_str or not en_key or not zh_key:
            continue

        en_fid = int(en_fid_str, 16) if en_fid_str.startswith('0x') else int(en_fid_str)
        zh_fid = int(zh_fid_str, 16) if zh_fid_str.startswith('0x') else int(zh_fid_str)
        seg = int(seg_str) if seg_str else 0

        mappings.append((zh_fid, zh_key, seg, en_fid, en_key))

print(f'Read {len(mappings)} mappings from CSV', file=sys.stderr)

# Deduplicate
seen = set()
unique = []
for m in mappings:
    key = (m[0], m[1], m[2])
    if key not in seen:
        seen.add(key)
        unique.append(m)

print(f'Unique mappings: {len(unique)}', file=sys.stderr)

# Write BLMP
with open(map_path, 'wb') as f:
    f.write(b'BLMP')
    f.write(struct.pack('<I', len(unique)))
    for zh_fid, zh_key, seg, en_fid, en_key in unique:
        f.write(struct.pack('<i', zh_fid))
        f.write(zh_key.encode('utf-8') + b'\0')
        f.write(struct.pack('<H', seg))
        f.write(struct.pack('<i', en_fid))
        f.write(en_key.encode('utf-8') + b'\0')

print(f'Written {len(unique)} mappings to {map_path}', file=sys.stderr)
