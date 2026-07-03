"""Compare EN and ZH offset key ordering from the SOURCE CSVs."""
import csv, sys
from collections import defaultdict, OrderedDict

sys.stdout.reconfigure(encoding='utf-8')

def read_source_csv(path):
    """Read CSV, group by func_id preserving insertion order, return OrderedDict."""
    funcs = OrderedDict()
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get('offset_key', '').strip()
            if not key:
                continue
            fid = row.get('func_id', '').strip()
            seg = int(row.get('segment', '0').strip() or 0)
            text = row.get('text', '')
            
            if fid not in funcs:
                funcs[fid] = []
            
            # Use (offset_key, segment) as unique key to avoid merging multi-seg
            funcs[fid].append((key, seg, text))
    
    return funcs

en_funcs = read_source_csv('tools/voice_acting/en_voice_lines.csv')
zh_funcs = read_source_csv('tools/voice_acting/zh_voice_lines.csv')

common = sorted(set(en_funcs.keys()) & set(zh_funcs.keys()))
print(f"Common functions: {len(common)}")

# For each function, compare the order of (offset_key, segment) pairs
# between EN and ZH
print("\n=== FUNCTIONS WITH MISMATCHED OFFSET ORDER ===")
print("(EN pair[i] != ZH pair[i] even after accounting for key differences)")
print()

mismatched = []
for fid in common:
    en_list = en_funcs[fid]
    zh_list = zh_funcs[fid]
    
    # Check order: compare the sequence of (offset_key, segment)
    en_keys = [(e[0], e[1]) for e in en_list]
    zh_keys = [(z[0], z[1]) for z in zh_list]
    
    # Check if both have the same keys
    en_set = set(en_keys)
    zh_set = set(zh_keys)
    
    shared = en_set & zh_set
    en_only = en_set - zh_set
    zh_only = zh_set - en_set
    
    # Check ordering: for shared keys, do they appear in the same relative order?
    en_order = {k: i for i, k in enumerate(en_keys)}
    zh_order = {k: i for i, k in enumerate(zh_keys)}
    
    # Find keys that are out of order
    shared_in_both = [k for k in en_keys if k in zh_set]
    reordered = False
    for i in range(1, len(shared_in_both)):
        prev_zh = zh_order[shared_in_both[i-1]]
        curr_zh = zh_order[shared_in_both[i]]
        if curr_zh < prev_zh:
            reordered = True
            break
    
    if reordered or en_only or zh_only:
        mismatched.append((fid, len(en_set), len(zh_set), len(en_only), len(zh_only), en_keys[:5], zh_keys[:5]))
        if len(mismatched) <= 30:
            print(f"  {fid}: EN keys={len(en_set)}, ZH keys={len(zh_set)}, "
                  f"EN-only={len(en_only)}, ZH-only={len(zh_only)}")
            if en_only:
                print(f"    EN-only: {list(en_only)[:5]}")
            if zh_only:
                print(f"    ZH-only: {list(zh_only)[:5]}")

print(f"\nTotal functions with any ordering/key mismatch: {len(mismatched)}")

# Now do a TEXT-based similarity check for a specific function
# to verify the pairing is correct
print("\n=== TEXT-BASED PAIRING VERIFICATION ===")
print("Checking if position-paired entries actually have related text...")

# For each function, read the ALREADY PAIRED offset_mapping.csv
# and check if paired texts seem related
paired_rows = []
with open('tools/voice_acting/offset_mapping.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        paired_rows.append(row)

paired_by_func = defaultdict(list)
for r in paired_rows:
    paired_by_func[r['en_func_id']].append(r)

# Check for obvious mismatches: look at first word of EN and ZH texts
# They should be similar in sentiment/type
question_mismatch = 0
total_checked = 0
for fid, entries in sorted(paired_by_func.items()):
    for e in entries:
        en_text = e['en_text']
        zh_text = e['zh_text']
        total_checked += 1
        
        en_question = '?' in en_text
        zh_question = '?' in zh_text
        
        # Check for "He ignores you" type narration vs dialog mismatch
        en_he_says = 'he says' in en_text.lower() or 'he said' in en_text.lower()
        zh_he_says = '他' in zh_text[:10] if zh_text else False  # rough check
        
        if en_question != zh_question:
            question_mismatch += 1

print(f"Total checked: {total_checked}")
print(f"Question-mark mismatches: {question_mismatch}")
print()

# Detailed look at a specific function where ZH-only keys exist
print("=== DETAILED: Functions with ZH-only keys ===")
for fid, ec, zc, eo, zo, en5, zh5 in mismatched:
    if zo > 0:
        # Get full key lists
        en_list = en_funcs[fid]
        zh_list = zh_funcs[fid]
        en_keys = [(e[0], e[1]) for e in en_list]
        zh_keys = [(z[0], z[1]) for z in zh_list]
        
        zh_only_keys = set(zh_keys) - set(en_keys)
        print(f"\n{fid}: {zo} ZH-only keys")
        for zok in sorted(zh_only_keys)[:10]:
            # Find the ZH text
            zh_text = next(t for k, s, t in zh_list if k == zok[0] and s == zok[1])
            # Find what EN index it paired with (position-based)
            zh_idx = zh_keys.index(zok)
            if zh_idx < len(en_keys):
                en_text = en_list[zh_idx][2]
                print(f"  ZH key={zok[0]}, seg={zok[1]} (at pos {zh_idx}):")
                print(f"    PAIRED with EN key={en_list[zh_idx][0]}: {en_text[:60]}")
                print(f"    ACTUAL ZH text: {zh_text[:60]}")
        break  # Just show first one
