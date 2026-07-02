#!/usr/bin/env python3
"""
Fix double-encoded UTF-8 mojibake in bilingual_mapping.csv.

The CSV was produced by reading UTF-8 Chinese bytes as Latin-1 and
re-encoding as UTF-8. Fix: encode each zh_text back to Latin-1 to get
the original raw bytes, then decode as UTF-8.
"""
import csv
import os
import sys

csv_path = 'tools/voice_acting/bilingual_mapping.csv'
tmp_path = csv_path + '.fixed'
backup_path = csv_path + '.bak'

with open(csv_path, encoding='utf-8', newline='') as fin, \
     open(tmp_path, 'w', encoding='utf-8', newline='') as fout:
    reader = csv.DictReader(fin)
    writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
    writer.writeheader()

    fixed = 0
    total = 0
    for row in reader:
        total += 1
        zh = row.get('zh_text', '').strip()
        if zh:
            try:
                # Fix double-encoding: latin-1 encode, then utf-8 decode
                fixed_zh = zh.encode('latin-1').decode('utf-8')
                if fixed_zh != zh:
                    fixed += 1
                row['zh_text'] = fixed_zh
            except (UnicodeEncodeError, UnicodeDecodeError) as e:
                print(f'Row {total}: Fix failed for func_id={row.get("func_id")}: {e}')
        writer.writerow(row)

print(f'Total rows: {total}, fixed: {fixed}')

# Verify the fix
print('\nVerification (first 3 entries):')
with open(csv_path, encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        if i < 3:
            zh = row.get('zh_text', '').strip()
            print(f'  Row {i} (OLD): hex={zh.encode("utf-8")[:20].hex()}')

with open(tmp_path, encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        if i < 3:
            zh = row.get('zh_text', '').strip()
            print(f'  Row {i} (NEW): hex={zh.encode("utf-8")[:20].hex()} zh={zh[:30]}')

# Replace original with fixed
os.replace(csv_path, backup_path)
os.replace(tmp_path, csv_path)
print(f'\nBackup saved to: {backup_path}')
print(f'Fixed file: {csv_path}')
