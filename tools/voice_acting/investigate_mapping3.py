#!/usr/bin/env python3
"""Compare English and Chinese CSVs for func 0x0401, write to file."""
import csv
import sys

func = '0x0401'

out = []

# Read English CSV
en_entries = []
with open('tools/voice_acting/en_voice_lines.csv', newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for r in reader:
        if r['func_id'] == func:
            en_entries.append({
                'offset_key': r['offset_key'],
                'segment': int(r['segment']),
                'text': r['text'][:80],
                'npc': r['npc'],
            })

# Read Chinese CSV
zh_entries = []
with open('tools/voice_acting/zh_voice_lines.csv', newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for r in reader:
        if r['func_id'] == func:
            zh_entries.append({
                'offset_key': r['offset_key'],
                'segment': int(r['segment']),
                'text': r['text'][:80],
                'npc': r['npc'],
            })

out.append(f"English entries for {func}: {len(en_entries)}")
out.append(f"Chinese entries for {func}: {len(zh_entries)}")
out.append("")

# Print all entries with their index
out.append("--- ENGLISH ---")
for i, e in enumerate(en_entries):
    out.append(f"  {i:3d} key={e['offset_key']:20s} seg={e['segment']} npc={e['npc']:5s}  {e['text']}")

out.append("")
out.append("--- CHINESE ---")
for i, e in enumerate(zh_entries):
    out.append(f"  {i:3d} key={e['offset_key']:20s} seg={e['segment']} npc={e['npc']:5s}  {e['text']}")

# Find specific entries
out.append("")
out.append("--- SPECIFIC LOOKUPS ---")
for i, e in enumerate(en_entries):
    if e['offset_key'] == '6bf' and e['segment'] == 0:
        out.append(f"EN 6bf_0 is at index {i}: {e['text']}")
for i, e in enumerate(zh_entries):
    if e['offset_key'] == '603' and e['segment'] == 0:
        out.append(f"ZH 603_0 is at index {i}: {e['text']}")
    if e['offset_key'] == '6af' and e['segment'] == 0:
        out.append(f"ZH 6af_0 is at index {i}: {e['text']}")

with open('tools/voice_acting/investigation_0401.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))

print("Written to investigation_0401.txt")
