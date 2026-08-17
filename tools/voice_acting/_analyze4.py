"""Verify position-based pairing by cross-referencing EN/ZH texts."""
import csv, sys
from collections import defaultdict, OrderedDict

sys.stdout.reconfigure(encoding='utf-8')

# Build zh_text lookup: (func_id, offset_key, segment) -> text
zh_text_map = {}
with open('tools/voice_acting/zh_voice_lines.csv', 'r', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        fid = row['func_id'].strip()
        key = row['offset_key'].strip()
        seg = int(row.get('segment', '0').strip() or 0)
        if fid and key:
            zh_text_map[(fid, key, seg)] = row['text']

# Build en_text lookup as well
en_text_map = {}
with open('tools/voice_acting/en_voice_lines.csv', 'r', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        fid = row['func_id'].strip()
        key = row['offset_key'].strip()
        seg = int(row.get('segment', '0').strip() or 0)
        if fid and key:
            en_text_map[(fid, key, seg)] = row['text']

# Read offset mapping
paired = []
with open('tools/voice_acting/offset_mapping.csv', 'r', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        paired.append(row)

by_func = defaultdict(list)
for r in paired:
    by_func[r['en_func_id']].append(r)

print(f"Total paired entries: {len(paired)}")
print()

# Now analyze: for each paired entry, fetch both EN and ZH text
# and compare structure
print("=" * 60)
print("FUNCTIONS WITH STRUCTURAL MISMATCHES (first 30)")
print("=" * 60)

# Known NPC names for name-checking
known_npcs = ['Avatar', 'Erethian', 'Arcadion', 'Batlin', 'Lord British', 'LB',
              'Iolo', 'Shamino', 'Dupre', 'Spark', 'Frigidazzi', 'Devra',
              'Hawkwind', 'Nelson', 'Jaana', 'Katrina', 'Petra', 'Sellia',
              'Mordea', 'Alagner', 'Tonda', 'Marlsin', 'Rollo', 'Feridwyn',
              'Kylgan', 'Cantra', 'Foran', 'Egbert', 'Karend',
              'Treloan', 'Fanton', 'Gorm', 'Shelana', 'Tristan',
              'Tseramed', 'Volk', 'Kilandra', 'Gribbel',
              'Pavel', 'Melek', 'Columna', 'Alyssand', 'Ariana',
              'Captain Blood', 'Bane', 'Fisk', 'Sutek', 'Baron',
              'Torrissio', 'Freedonia', 'Rafkin', 'Shepherd',
              'Vigil', 'Rita', 'Reese', 'Quintin',
              'Harnna', 'Maxwell', 'Sir Simon', 'Weston', 'Tenda',
              'Vincenzo', 'Shepherd', 'Tseramad']

show_count = 0
for fid in sorted(by_func.keys()):
    if show_count >= 30:
        break
    entries = by_func[fid]
    
    for i, e in enumerate(entries):
        en_fid = e['en_func_id']
        en_key = e['en_offset_key']
        en_seg = int(e['en_segment'])
        zh_fid = e['zh_func_id']
        zh_key = e['zh_offset_key']
        zh_seg = int(e['zh_segment'])
        
        en_text = en_text_map.get((en_fid, en_key, en_seg), '')
        zh_text = zh_text_map.get((zh_fid, zh_key, zh_seg), '')
        
        if not en_text or not zh_text:
            continue
        
        en_q = '?' in en_text
        zh_q = '?' in zh_text
        en_ex = '!' in en_text
        zh_ex = '!' in zh_text
        en_quote = '"' in en_text
        zh_quote = '\u300c' in zh_text
        
        flags = []
        if en_q != zh_q: flags.append(f'Q(en={en_q},zh={zh_q})')
        if en_ex != zh_ex: flags.append(f'!(en={en_ex},zh={zh_ex})')
        
        if flags:
            show_count += 1
            en_preview = en_text[:70].replace('\n', ' ')
            zh_preview = zh_text[:70].replace('\n', ' ')
            print(f"\n{fid}[{i}] EN({en_key},{en_seg}) <-> ZH({zh_key},{zh_seg})")
            for f in flags:
                print(f"  MISMATCH: {f}")
            print(f"  EN: {en_preview}")
            print(f"  ZH: {zh_preview}")
            if show_count >= 30:
                break

print(f"\n\nTotal structural mismatches shown: {show_count}")

# Now check: for each entry, identify what NPCs are mentioned
# and see if the paired text addresses the same NPC
print("\n" + "=" * 60)
print("NPC NAME VERIFICATION")
print("=" * 60)

bad_mappings = []
for fid in sorted(by_func.keys()):
    entries = by_func[fid]
    for i, e in enumerate(entries):
        en_fid = e['en_func_id']
        en_key = e['en_offset_key']
        en_seg = int(e['en_segment'])
        zh_fid = e['zh_func_id']
        zh_key = e['zh_offset_key']
        zh_seg = int(e['zh_segment'])
        
        en_text = en_text_map.get((en_fid, en_key, en_seg), '')
        zh_text = zh_text_map.get((zh_fid, zh_key, zh_seg), '')
        
        if not en_text or not zh_text:
            continue
        
        # Check if known NPC names appear in both
        en_npcs = [n for n in known_npcs if n.lower() in en_text.lower()]
        zh_npcs_en = [n for n in known_npcs if n.lower() in zh_text.lower()]
        
        if en_npcs and not zh_npcs_en:
            # Check if the zh_text has the NPC as transliteration
            # Skip short texts (responses) and NPCs that commonly don't appear in Chinese translation
            if len(en_text) > 30:
                bad_mappings.append((fid, i, en_key, zh_key, en_npcs, 
                                    en_text[:60], zh_text[:60]))

print(f"\nPaired entries where EN has NPC name(s) but ZH doesn't: {len(bad_mappings)}")
print("Showing matching-pair quality issues: (NPC mentioned in EN but missing in paired ZH)")
for fid, i, ek, zk, npcs, en_t, zh_t in bad_mappings[:20]:
    print(f"\n  {fid}[{i}] EN({ek}) -> ZH({zk})")
    print(f"    EN NPCs: {npcs}")
    print(f"    EN: {en_t}")
    print(f"    ZH: {zh_t}")

# SUMMARY
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"Total paired entries in BLMP source: {len(paired)}")
print(f"Functions checked: {len(by_func)}")
print(f"Entries with question-mark mismatch (top 30 shown): {show_count}")
print(f"Entries with NPC name mismatch: {len(bad_mappings)}")
print()
print("The position-based pairing is correct IF the ZH usecode preserves")
print("the same dialog order as EN within each function. The structural")
print("mismatches above indicate places where the order may differ.")
