"""Verify mapping quality by comparing text content between paired entries."""
import csv, sys, re
from collections import defaultdict, OrderedDict

sys.stdout.reconfigure(encoding='utf-8')

def read_source(path):
    """Read source CSV and group by func_id, preserving order."""
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
            funcs[fid].append((key, seg, text))
    return funcs

en_src = read_source('tools/voice_acting/en_voice_lines.csv')
zh_src = read_source('tools/voice_acting/zh_voice_lines.csv')

# Also read the offset_mapping.csv (the paired output)
paired = []
with open('tools/voice_acting/offset_mapping.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        paired.append(row)

# Group paired rows by function
by_func = defaultdict(list)
for r in paired:
    by_func[r['en_func_id']].append(r)

common = sorted(set(en_src.keys()) & set(zh_src.keys()))

# For each function, compare position-paired texts and look for clear mismatches
# Simple heuristic: extract NPC name from text and check if same NPC is referenced
def extract_npcs(text):
    """Extract potential NPC names from text."""
    # Common U7 NPC names
    known_npcs = ['Avatar', 'Erethian', 'Arcadion', 'Batlin', 'Lord British', 'LB',
                  'Iolo', 'Shamino', 'Dupre', 'Spark', 'Frigidazzi', 'Devra',
                  'Hawkwind', 'Nelson', 'Jaana', 'Katrina', 'Petra', 'Sellia',
                  'Mordea', 'Alagner', 'Tonda', 'Marlsin', 'Rollo', 'Feridwyn',
                  'Kylgan', 'Cantra', 'Foran', 'Egbert', 'Karend',
                  'Treloan', 'Fanton', 'Gorm', 'Shelana', 'Tristan',
                  'Tseramed', 'Tseremad', 'Volk', 'Kilandra', 'Gribbel',
                  'Pavel', 'Mad Iolo', 'Clockwork Iolo',
                  'Melek', 'Columna', 'Alyssand', 'Ariana',
                  'Captain Blood', 'Bane', 'Fisk', 'Sutek', 'Baron',
                  'Torrissio', 'Freedonia', 'Rafkin', 'Shepherd',
                  'Vigil', 'Rita', 'Reese', 'Quintin', 'Mage',
                  'guard', 'Guard', 'Beggar', 'beggar', 'Vendor', 'vendor',
                  'Tavern Keeper', 'Inn Keeper', 'Healer']
    found = []
    for npc in known_npcs:
        if npc.lower() in text.lower():
            found.append(npc)
    return found

def extract_dialog_markers(text):
    """Extract dialog markers to compare sentence structure."""
    has_quote = '"' in text or '\u300c' in text or '\u300d' in text  # Chinese quotes
    has_colon = ':' in text or '\uff1a' in text  # Chinese colon
    has_question = '?' in text or '\uff1f' in text  # Chinese question mark
    has_exclaim = '!' in text or '\uff01' in text  # Chinese exclaim
    is_narration = not has_quote and not has_colon
    return has_quote, has_colon, has_question, has_exclaim, is_narration

print("=" * 60)
print("TEXT-BASED PAIRING VERIFICATION")
print("=" * 60)

# Check specific functions in detail
check_fids = ['0x009A', '0x0401', '0x009B', '0x0096']
for fid in check_fids:
    if fid not in by_func:
        continue
    entries = by_func[fid]
    print(f"\n--- {fid}: {len(entries)} paired entries ---")
    
    mismatch_count = 0
    for i, e in enumerate(entries[:30]):  # Check first 30
        en_text = e['en_text']
        zh_text = e['zh_text']
        
        # Basic structure comparison
        en_q = '?' in en_text
        zh_q = '?' in zh_text
        en_ex = '!' in en_text
        zh_ex = '!' in zh_text
        en_quote = '"' in en_text
        zh_quote = '\u300c' in zh_text
        
        # Print every entry with structural info
        flags = ''
        if en_q != zh_q: flags += ' Q'
        if en_ex != zh_ex: flags += ' !'
        if en_quote != zh_quote: flags += ' QTE'
        
        en_preview = en_text[:50]
        zh_preview = zh_text[:50]
        
        if flags:
            mismatch_count += 1
            print(f"  [{i}] {flags}")
            print(f"       EN: {en_preview}")
            print(f"       ZH: {zh_preview}")
    
    print(f"  Structural mismatches: {mismatch_count}/{min(30, len(entries))}")

# Now do thorough text similarity check for a few functions
print("\n" + "=" * 60)
print("DETAILED NPC-NAME-BASED CHECK")
print("=" * 60)

fids_with_npc_mismatch = []
for fid in common:
    en_list = en_src[fid]
    zh_list = zh_src[fid]
    paired_entries = by_func.get(fid, [])
    
    npc_mismatches = 0
    for i, e in enumerate(paired_entries):
        en_text = e['en_text']
        zh_text = e['zh_text']
        en_npcs = extract_npcs(en_text)
        
        # For zh_text, check for transliterated NPC names
        zh_has_en_npc = any(n.lower() in zh_text.lower() for n in en_npcs)
        
        # If EN text mentions a specific NPC but ZH doesn't contain that name,
        # and both sides have meaningful content, flag it
        if en_npcs and not zh_has_en_npc and len(en_text) > 20:
            npc_mismatches += 1
            if npc_mismatches <= 3 and len(fids_with_npc_mismatch) < 20:
                fids_with_npc_mismatch.append((fid, i, en_npcs, en_text[:60], zh_text[:60]))

print(f"\nFunctions with potential NPC mismatches: {len(set(f[0] for f in fids_with_npc_mismatch))}")
print("Examples:")
for fid, idx, npcs, en_t, zh_t in fids_with_npc_mismatch[:15]:
    print(f"\n  {fid}[{idx}]: mentions {npcs}")
    print(f"    EN: {en_t}")
    print(f"    ZH: {zh_t}")
