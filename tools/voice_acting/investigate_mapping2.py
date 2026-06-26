#!/usr/bin/env python3
"""Compare English and Chinese CSVs for func 0x0401 to find the pairing error."""
import csv

func = '0x0401'

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

print(f"English entries for {func}: {len(en_entries)}")
print(f"Chinese entries for {func}: {len(zh_entries)}")
print()

# Print first 15 entries side by side
print(f"{'#':4s} {'EN key':20s} {'EN text':60s} | {'ZH key':20s} {'ZH text':60s}")
print('-' * 170)
for i in range(max(len(en_entries), len(zh_entries))):
    en = en_entries[i] if i < len(en_entries) else None
    zh = zh_entries[i] if i < len(zh_entries) else None
    en_str = f"{en['offset_key']:20s} {en['text']:60s}" if en else f"{'':20s} {'':60s}"
    zh_str = f"{zh['offset_key']:20s} {zh['text']:60s}" if zh else f"{'':20s} {'':60s}"
    match = ""
    if en and zh:
        # Check if text content matches (same line, different language)
        # Simple heuristic: if it's the same dialogue position
        if i < min(len(en_entries), len(zh_entries)):
            match = " <- paired"
    print(f"{i:4d} {en_str} | {zh_str}{match}")

# Show specific known mappings
print()
print("=" * 80)
print("Known ground-truth pairs from log:")
print("  EN 6bf_0='Yes, my friend?'  ->  ZH 603_0='我的老朋友'")
print()
print("Check what the CSV pairing says:")
print(f"  EN 6bf_0 is at index {[i for i,e in enumerate(en_entries) if e['offset_key']=='6bf' and e['segment']==0]}")
print(f"  ZH 603_0 is at index {[i for i,e in enumerate(zh_entries) if e['offset_key']=='603' and e['segment']==0]}")
