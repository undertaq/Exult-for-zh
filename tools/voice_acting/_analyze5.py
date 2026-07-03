"""Deep investigate the mapping + voice file coverage."""
import csv, sys, os
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

# ============ 1. Read source CSVs to compare offset ordering ============
def read_source(path):
    funcs = defaultdict(list)
    with open(path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            key = row.get('offset_key', '').strip()
            if not key: continue
            fid = row.get('func_id', '').strip()
            seg = int(row.get('segment', '0').strip() or 0)
            text = row.get('text', '')
            funcs[fid].append((key, seg, text))
    return funcs

en_src = read_source('tools/voice_acting/en_voice_lines.csv')
zh_src = read_source('tools/voice_acting/zh_voice_lines.csv')

# ============ 2. Read mapping ============
mapping = []
with open('tools/voice_acting/offset_mapping.csv', 'r', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        mapping.append(row)

# ============ 3. Build ZH text lookup ============
zh_text = {}
with open('tools/voice_acting/zh_voice_lines.csv', 'r', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        fid = row['func_id'].strip()
        key = row['offset_key'].strip()
        seg = int(row.get('segment', '0').strip() or 0)
        if fid and key:
            zh_text[(fid, key, seg)] = row['text']

en_text = {}
with open('tools/voice_acting/en_voice_lines.csv', 'r', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        fid = row['func_id'].strip()
        key = row['offset_key'].strip()
        seg = int(row.get('segment', '0').strip() or 0)
        if fid and key:
            en_text[(fid, key, seg)] = row['text']

# ============ 4. Check actual files in zh/ ============
zh_dir = r'../Ultima_7/patch/voice_acting/zh'
actual_files = set()
if os.path.isdir(zh_dir):
    for fname in os.listdir(zh_dir):
        if fname.endswith('.ogg'):
            actual_files.add(fname)

# ============ 5. Cross-reference: for each mapping entry, check if file exists ============
print("=" * 70)
print("VOICE FILE COVERAGE ANALYSIS")
print("=" * 70)

missing_coverage = []
existing_coverage = []
for e in mapping:
    zh_fid = e['zh_func_id'].replace('0x', '').lower().zfill(4)
    zh_key = e['zh_offset_key']
    zh_seg = e['zh_segment']
    fname = f"{zh_fid}_{zh_key}_{zh_seg}.ogg"
    
    en_fid = e['en_func_id'].replace('0x', '').lower().zfill(4)
    en_key = e['en_offset_key']
    en_seg = e['en_segment']
    en_fname = f"{en_fid}_{en_key}_{en_seg}.ogg"
    
    en_t = en_text.get((e['en_func_id'], e['en_offset_key'], int(e['en_segment'])), '')
    zh_t = zh_text.get((e['zh_func_id'], e['zh_offset_key'], int(e['zh_segment'])), '')
    
    if fname in actual_files:
        existing_coverage.append((fname, en_t[:50], zh_t[:50]))
    else:
        missing_coverage.append((fname, en_fname, en_t[:50], zh_t[:50]))

print(f"Total mapping entries: {len(mapping)}")
print(f"ZH voice files EXIST: {len(existing_coverage)}")
print(f"ZH voice files MISSING: {len(missing_coverage)}")
print()

# Show some missing file examples by function
print("=== MISSING FILES (first 30) ===")
for fname, en_fname, en_t, zh_t in missing_coverage[:30]:
    print(f"  ZH: {fname}")
    print(f"  EN: {en_fname}")
    print(f"  EN text: {en_t}")
    print(f"  ZH text: {zh_t}")
    print()

# ============ 6. Check: are the MISSING files in en/? ============
en_dir = r'../Ultima_7/patch/voice_acting/en'
en_actual = set()
if os.path.isdir(en_dir):
    for fname in os.listdir(en_dir):
        if fname.endswith('.ogg'):
            en_actual.add(fname)

missing_but_in_en = [(f, en_f) for f, en_f, _, _ in missing_coverage if en_f in en_actual]
print(f"\nMissing ZH files that exist in EN/: {len(missing_but_in_en)}")
print("(These will fall back to English audio when voice=Chinese)")

# ============ 7. Show TOP FUNCTIONS with most missing files ============
missing_by_func = defaultdict(int)
total_by_func = defaultdict(int)
for e in mapping:
    fid = e['zh_func_id']
    total_by_func[fid] += 1
    fname = f"{fid.replace('0x', '').lower().zfill(4)}_{e['zh_offset_key']}_{e['zh_segment']}.ogg"
    if fname not in actual_files:
        missing_by_func[fid] += 1

print(f"\n=== FUNCTIONS WITH MOST MISSING VOICE FILES ===")
sorted_funcs = sorted(total_by_func.keys(), key=lambda f: missing_by_func.get(f, 0), reverse=True)
for fid in sorted_funcs[:15]:
    total = total_by_func[fid]
    missing = missing_by_func.get(fid, 0)
    pct = 100 * missing / total if total > 0 else 0
    print(f"  {fid}: {missing}/{total} missing ({pct:.0f}%)")
