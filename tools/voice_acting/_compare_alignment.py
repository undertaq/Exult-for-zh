"""Compare EN and ZH offset ordering within functions to detect position-based pairing errors."""

import csv
from collections import defaultdict

# Read EN voice lines
en_rows = []
with open('tools/voice_acting/en_voice_lines.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        en_rows.append(row)

# Read ZH voice lines
zh_rows = []
with open('tools/voice_acting/zh_voice_lines.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        zh_rows.append(row)

# Group by function
en_by_func = defaultdict(list)
for r in en_rows:
    fid = r['func_id']
    en_by_func[fid].append(r)

zh_by_func = defaultdict(list)
for r in zh_rows:
    fid = r['func_id']
    zh_by_func[fid].append(r)

# Find common functions
common_fids = sorted(set(en_by_func.keys()) & set(zh_by_func.keys()))
print(f'EN functions: {len(en_by_func)}')
print(f'ZH functions: {len(zh_by_func)}')
print(f'Common functions: {len(common_fids)}')
print()

# For each common function, compare offset key order
print('=== Functions where EN and ZH offset order differs significantly ===')
print()

def extract_offsets(entries, lang_label):
    """Get ordered list of (offset_key, segment, text_preview)."""
    result = []
    for e in entries:
        ok = e['offset_key']
        seg = e['segment']
        text = e['text'][:80]
        result.append((ok, seg, text))
    return result

# Check a few specific functions in detail
for fid in ['0x009A', '0x009B', '0x0096']:
    if fid in en_by_func and fid in zh_by_func:
        print(f'=== Function {fid} comparison ===')
        en_offsets = extract_offsets(en_by_func[fid], 'EN')
        zh_offsets = extract_offsets(zh_by_func[fid], 'ZH')
        
        print(f'  EN count: {len(en_offsets)}, ZH count: {len(zh_offsets)}')
        
        # Show EN order vs ZH order side by side (first 20)
        max_show = min(20, max(len(en_offsets), len(zh_offsets)))
        print(f'  {"#":>3} | {"EN offset":<20} | {"ZH offset":<20}')
        print(f'  {"-"*3} | {"-"*20} | {"-"*20}')
        for i in range(max_show):
            en_str = f'{en_offsets[i][0]},{en_offsets[i][1]}' if i < len(en_offsets) else ''
            zh_str = f'{zh_offsets[i][0]},{zh_offsets[i][1]}' if i < len(zh_offsets) else ''
            match = '✓' if (i < len(en_offsets) and i < len(zh_offsets) and 
                          en_offsets[i][0] == zh_offsets[i][0]) else ''
            print(f'  {i:>3} | {en_str:<20} | {zh_str:<20}  {match}')
        print()
        # Show text samples for first 5
        print('  Text samples:')
        for i in range(min(5, len(en_offsets), len(zh_offsets))):
            en_text_short = en_offsets[i][2][:60]
            zh_text_short = zh_offsets[i][2][:60]
            print(f'  #{i}:')
            print(f'    EN: {en_text_short}')
            print(f'    ZH: {zh_text_short}')
        print()

# Now find ALL functions that don't have identical offset order
print('=== Functions with different offset ordering ===')
mismatch_count = 0
for fid in common_fids:
    en_oks = [(e['offset_key'], e['segment']) for e in en_by_func[fid]]
    zh_oks = [(e['offset_key'], e['segment']) for e in zh_by_func[fid]]
    
    # Normalize: convert to comparable form (handle non-numeric keys like "b8_113")
    # Check simple case: different count
    if len(en_oks) != len(zh_oks):
        mismatch_count += 1
        if mismatch_count <= 20:
            print(f'  COUNT MISMATCH {fid}: EN={len(en_oks)}, ZH={len(zh_oks)}')
    
    # Check if the offset keys appear in the SAME relative order
    # by checking pairwise
    pos_en = {ok: i for i, ok in enumerate(en_oks)}
    pos_zh = {ok: i for i, ok in enumerate(zh_oks)}
    
    for i in range(min(len(en_oks), len(zh_oks))):
        en_ok = en_oks[i]
        zh_ok = zh_oks[i]
        
        if en_ok != zh_ok:
            # This pair is position-paired but has different offsets
            # Check where zh_ok appears in the EN order (if at all)
            en_pos_of_zh = pos_en.get(zh_ok, -1)
            zh_pos_of_en = pos_zh.get(en_ok, -1)
            
            if en_pos_of_zh >= 0 and abs(en_pos_of_zh - i) > 2:
                mismatch_count += 1
                if mismatch_count <= 30:
                    print(f'  SHIFT {fid}: EN[{i}]={en_ok} paired with ZH[{i}]={zh_ok}, '
                          f'but ZH key appears at EN position {en_pos_of_zh}')
                break

print(f'\nTotal functions with some mismatch indicator: {mismatch_count}')
