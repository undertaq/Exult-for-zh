import csv
from collections import defaultdict

rows = []
with open('tools/voice_acting/offset_mapping.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

by_func = defaultdict(list)
for r in rows:
    fid = r['en_func_id']
    by_func[fid].append(r)

print(f'Total rows: {len(rows)}')
print(f'Total functions: {len(by_func)}')
print()

# Check for duplicate offset keys within same function
print('=== Duplicate EN offset keys (wrong mapping) ===')
dup_count = 0
for fid, entries in sorted(by_func.items()):
    seen = {}
    for e in entries:
        ek = (e['en_offset_key'], e['en_segment'])
        if ek not in seen:
            seen[ek] = e
        else:
            dup_count += 1
            if dup_count <= 10:
                print(f'  {fid} EN({ek[0]},{ek[1]}):')
                print(f'    => ZH keys: {seen[ek]["zh_offset_key"]} and {e["zh_offset_key"]}')
                print(f'    EN text: {seen[ek]["en_text"][:80]}')
print(f'Total EN dups: {dup_count}')
print()

print('=== Duplicate ZH offset keys (wrong mapping) ===')
dup_count = 0
for fid, entries in sorted(by_func.items()):
    seen = {}
    for e in entries:
        ek = (e['zh_offset_key'], e['zh_segment'])
        if ek not in seen:
            seen[ek] = e
        else:
            dup_count += 1
            if dup_count <= 10:
                print(f'  {fid} ZH({ek[0]},{ek[1]}):')
                print(f'    => EN keys: {seen[ek]["en_offset_key"]} and {e["en_offset_key"]}')
                print(f'    ZH text: {seen[ek]["zh_text"][:80]}')
print(f'Total ZH dups: {dup_count}')
print()

# Check: for each function, see if offset keys are in same relative order
# between EN and ZH. If they differ, position-based pairing produced a wrong mapping.
print('=== Offset order mismatch within functions ===')
order_mismatches = []
for fid, entries in sorted(by_func.items()):
    en_offsets = [(e['en_offset_key'], e['en_segment']) for e in entries]
    zh_offsets = [(e['zh_offset_key'], e['zh_segment']) for e in entries]
    
    # Compare the relative ordering. We can't easily compare non-numeric offsets,
    # but we can check if the ranking is very different
    rank_en = {ok: i for i, ok in enumerate(en_offsets)}
    rank_zh = {ok: i for i, ok in enumerate(zh_offsets)}
    
    # For each ZH offset, find WHERE it appears in the EN order vs ZH order
    # If they're paired by position, entry[i] has en_offsets[i] paired with zh_offsets[i]
    # Check if zh_offsets[i] would normally appear earlier or later in the ZH order
    
    swapped_pairs = 0
    for i in range(min(len(entries), 20)):
        zh_ok = zh_offsets[i]
        zh_natural_pos = i  # In ZH order, this item is at position i
        
        # Find where this ZH offset appears in the ZH_SORTED order
        zh_sorted_pos = sorted(zh_offsets).index(zh_ok)
        
        if abs(zh_natural_pos - zh_sorted_pos) > 2:
            swapped_pairs += 1
    
    if swapped_pairs > 3:
        order_mismatches.append((fid, swapped_pairs, len(entries)))

print(f'Functions with suspicious offset ordering: {len(order_mismatches)}')
for fid, swaps, total in sorted(order_mismatches, key=lambda x: -x[1])[:20]:
    print(f'  {fid}: {swaps}/{total} entries with unusual ordering')
print()

# NEW APPROACH: Check for text-based mismatches directly by looking at
# semantically unconnected EN and ZH texts
print('=== Text-based mismatch detection ===')
# For each function, check if the EN texts and ZH texts appear to be
# in the same order by looking at the first few characters
mismatch_candidates = []
for fid, entries in sorted(by_func.items()):
    if len(entries) < 2:
        continue
    
    # Simple heuristic: check if consecutive EN entries have consecutive ZH counterparts
    # that seem related
    for i in range(len(entries)):
        e = entries[i]
        en_text = e['en_text'].strip()
        zh_text = e['zh_text'].strip()
        
        # If EN text contains a question but ZH doesn't (or vice versa)
        en_question = '?' in en_text
        zh_question = '?' in zh_text
        en_exclaim = '!' in en_text
        zh_exclaim = '!' in zh_text
        
        # Check for basic sentence-type mismatch
        if (en_question and not zh_question) or (not en_question and zh_question):
            pass  # This can happen naturally
        if (en_exclaim and not zh_exclaim) or (not en_exclaim and zh_exclaim):
            pass  # This can also happen naturally

# Look at specific function with most entries to see pattern
print('Function 0x009A has %d entries - checking first 10:' % len(by_func.get('0x009A', [])))
for e in by_func.get('0x009A', [])[:10]:
    print(f'  EN[{e["en_offset_key"]}]: {e["en_text"][:70]}')
    print(f'  ZH[{e["zh_offset_key"]}]: {e["zh_text"][:70]}')
    print()
