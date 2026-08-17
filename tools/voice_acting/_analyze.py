"""Analyze offset_mapping.csv for position-based pairing errors."""
import csv, sys
from collections import defaultdict

# Force UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

rows = []
with open('tools/voice_acting/offset_mapping.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

by_func = defaultdict(list)
for r in rows:
    by_func[r['en_func_id']].append(r)

# 1. Find duplicate ZH offset keys (same ZH entry mapped to multiple EN entries)
print("=" * 60)
print("DUPLICATE ZH OFFSETS (same ZH line paired with multiple EN lines)")
print("=" * 60)
zh_dup_count = 0
for fid, entries in sorted(by_func.items()):
    seen = {}
    for e in entries:
        ek = (e['zh_offset_key'], e['zh_segment'])
        if ek not in seen:
            seen[ek] = [e]
        else:
            seen[ek].append(e)
    for ek, matches in seen.items():
        if len(matches) > 1:
            zh_dup_count += 1
            if zh_dup_count <= 20:
                print(f'\n{fid}: ZH({ek[0]},{ek[1]}) maps to {len(matches)} EN entries:')
                for m in matches:
                    print(f'  EN({m["en_offset_key"]},{m["en_segment"]}): {m["en_text"][:80]}')

print(f'\nTotal ZH duplicate entries: {zh_dup_count}')

# 2. Count total mismatches
total_wrong = 0
for fid, entries in sorted(by_func.items()):
    en_oks = [(e['en_offset_key'], e['en_segment']) for e in entries]
    zh_oks = [(e['zh_offset_key'], e['zh_segment']) for e in entries]
    
    # Check for shifted pairings
    for i in range(len(entries)):
        en_ok = en_oks[i]
        zh_ok = zh_oks[i]
        
        # Check if this ZH offset appears elsewhere in the ZH list
        zh_count = zh_oks.count(zh_ok)
        if zh_count > 1:
            total_wrong += 1

# 3. Summary stats
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
all_zh_keys = [(e['zh_offset_key'], e['zh_segment']) for e in rows]
all_en_keys = [(e['en_offset_key'], e['en_segment']) for e in rows]

en_dup = len(all_en_keys) - len(set(all_en_keys))
zh_dup = len(all_zh_keys) - len(set(all_zh_keys))

print(f'Total mapping entries: {len(rows)}')
print(f'Unique EN (offset,seg) pairs: {len(set(all_en_keys))}')
print(f'Unique ZH (offset,seg) pairs: {len(set(all_zh_keys))}')
print(f'Duplicate EN entries: {en_dup}')
print(f'Duplicate ZH entries: {zh_dup}')
print()

# Show which functions are affected
print("Functions with ZH duplicates (wrong EN->ZH mapping):")
for fid, entries in sorted(by_func.items()):
    zh_oks = [(e['zh_offset_key'], e['zh_segment']) for e in entries]
    dups = [k for k, v in defaultdict(list, {k: [] for k in zh_oks}).items() if zh_oks.count(k) > 1]
    if dups:
        unique_dups = set(dups)
        print(f'  {fid}: {len(unique_dups)} duplicate ZH keys')
        for d in sorted(unique_dups)[:3]:
            matching = [e for e in entries if e['zh_offset_key'] == d[0] and e['zh_segment'] == d[1]]
            print(f'    ZH({d[0]},{d[1]}): {len(matching)} EN matches')
            for m in matching:
                print(f'      EN({m["en_offset_key"]}): {m["en_text"][:60]}')
