#!/usr/bin/env python3
"""
Systematic audit of func_id/offset_key collisions in bilingual_mapping_review.json.

Output: collision_audit_report.md
"""
import json, csv, os, sys
from collections import defaultdict, Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
JSON_PATH = os.path.join(SCRIPT_DIR, 'voice_acting', 'bilingual_mapping_review.json')
EN_CSV_PATH = os.path.join(SCRIPT_DIR, 'voice_acting', 'en_voice_lines.csv')
ZH_CSV_PATH = os.path.join(SCRIPT_DIR, 'voice_acting', 'zh_voice_lines.csv')

# ── Load data ──────────────────────────────────────────────────────────

mappings = json.load(open(JSON_PATH, encoding='utf-8'))

en_csv_text = {}   # (fid, key) -> (npc, text)
with open(EN_CSV_PATH, encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        fid = row['func_id'].strip()
        key = row['offset_key'].strip().replace('0x', '')
        npc = row.get('npc', '').strip()
        text = row.get('text', '')
        en_csv_text[(fid, key)] = (npc, text)

zh_csv_text = {}   # (fid, key) -> text
with open(ZH_CSV_PATH, encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        fid = row['func_id'].strip()
        key = row['offset_key'].strip().replace('0x', '')
        try:
            text = row['text'].encode('latin-1').decode('utf-8')
        except:
            text = row['text']
        zh_csv_text[(fid, key)] = text

# ── Build collision map ────────────────────────────────────────────────

# Group by zh_fid, zh_key
zh_groups = defaultdict(list)
# Group by en_fid, en_key
en_groups = defaultdict(list)

for e in mappings:
    zf = e.get('zh_func_id', '')
    zk = e.get('zh_offset_key', '')
    ef = e.get('en_func_id', '')
    ek = e.get('en_offset_key', '')
    npc = e.get('npc', '') or 'UNKNOWN'
    
    if zf and zk:
        zh_groups[(zf, zk)].append((npc, e.get('zh_text',''), ef, ek))
    if ef and ek:
        en_groups[(ef, ek)].append((npc, e.get('en_text',''), zf, zk))

# Collisions = groups with 2+ entries
zh_collisions = {k: v for k, v in zh_groups.items() if len(v) >= 2}
en_collisions = {k: v for k, v in en_groups.items() if len(v) >= 2}

# ── Per-NPC impact ─────────────────────────────────────────────────────

# For ZH collisions: count how many of each NPC's entries are overwritten
zh_npc_wins = Counter()   # NPC that would win (alphabetically last)
zh_npc_loses = Counter()  # NPC that would lose
zh_npc_total = Counter()  # Total entries in collisions

for (zf, zk), entries in zh_collisions.items():
    sorted_npcs = sorted(set(e[0] for e in entries), key=lambda x: x.lower())
    for npc in sorted_npcs:
        zh_npc_total[npc] += 1
    if sorted_npcs:
        zh_npc_wins[sorted_npcs[-1]] += 1
        for npc in sorted_npcs[:-1]:
            zh_npc_loses[npc] += 1

# ── CSV ground truth resolution ────────────────────────────────────────

zh_resolved = {}   # (zh_fid, zh_key) -> (correct_npc, notes)
for (zf, zk), entries in zh_collisions.items():
    csv_text = zh_csv_text.get((zf, zk), '')
    if csv_text:
        # Find entry(ies) whose text matches CSV
        matches = [e for e in entries if e[1] and (e[1][:30] in csv_text or csv_text[:30] in e[1][:30])]
        if len(matches) == 1:
            zh_resolved[(zf, zk)] = (matches[0][0], 'csv_match')
        elif len(matches) > 1:
            zh_resolved[(zf, zk)] = ('', 'csv_multiple_matches')
        else:
            zh_resolved[(zf, zk)] = ('', 'csv_no_match')
    else:
        zh_resolved[(zf, zk)] = ('', 'no_csv_data')

# ── Generate report ────────────────────────────────────────────────────

lines = []
def w(s=''):
    lines.append(s)

w('# Voice File Collision Audit Report')
w()
w(f'Generated from `bilingual_mapping_review.json` ({len(mappings)} entries)')
w()
w('## Summary')
w()
w(f'- **ZH collisions** (same zh_fid/zh_key, different NPCs): {len(zh_collisions)}')
w(f'- **EN collisions** (same en_fid/en_key, different NPCs): {len(en_collisions)}')
w(f'- **Total NPCs with overwritten entries**: {len(zh_npc_loses)}')

# Resolvable via CSV
csv_resolvable = sum(1 for v in zh_resolved.values() if v[0])
csv_no_match = sum(1 for v in zh_resolved.values() if v[1] == 'csv_no_match')
no_csv_data = sum(1 for v in zh_resolved.values() if v[1] == 'no_csv_data')
w(f'- **CSV-resolvable** (one NPC's text matches CSV): {csv_resolvable}')
w(f'- **CSV no-match** (text differs from CSV): {csv_no_match}')
w(f'- **No CSV data** for func_id/key: {no_csv_data}')

w()
w('## NPC Impact (most entries overwritten)')
w()
w('| NPC | Total in collisions | Would Lose (alphabetical) | Would Win (alphabetical) | Win Rate |')
w('|-----|-------------------|--------------------------|--------------------------|----------|')

# All NPCs that are in collisions
all_collision_npcs = sorted(zh_npc_total.keys(), key=lambda n: -zh_npc_total[n])
for npc in all_collision_npcs[:30]:
    total = zh_npc_total[npc]
    wins = zh_npc_wins[npc]
    loses = zh_npc_loses[npc]
    rate = f'{wins/total*100:.0f}%' if total else '-'
    w(f'| {npc} | {total} | {loses} | {wins} | {rate} |')

w()
w('## Worst Collisions (most NPCs sharing same fid/key)')
w()

# Sort by number of NPCs
sorted_zh = sorted(zh_collisions.items(), key=lambda x: -len(x[1]))
for (zf, zk), entries in sorted_zh[:30]:
    npcs = sorted(set(e[0] for e in entries), key=lambda x: x.lower())
    texts = list(dict.fromkeys(e[1][:50] for e in entries))  # unique texts
    csv_owner, csv_note = zh_resolved.get((zf, zk), ('', ''))
    csv_info = f'CSV-verified owner: {csv_owner}' if csv_owner else f'Note: {csv_note}'
    w(f'### {zf} / {zk} — {len(npcs)} NPCs')
    w(f'{csv_info}')
    w(f'Sample texts:')
    for t in texts[:3]:
        w(f'  - {t}')
    if len(texts) > 3:
        w(f'  - ... and {len(texts)-3} more unique texts')
    w(f'NPCs: {", ".join(npcs[:10])}{", ..." if len(npcs) > 10 else ""}')
    w()

w('## Legitimate vs Bad Mappings')
w()
w('Criteria for legitimate: EN CSV shows same func/key for multiple NPCs, OR >5 NPCs share the same func/key (likely game system, not mapping error)')
w()

legitimate = 0
bad_mapping = 0
for (zf, zk), entries in sorted_zh:
    npcs_list = sorted(set(e[0] for e in entries), key=lambda x: x.lower())
    num_npcs = len(npcs_list)
    num_unique_texts = len(set(e[1] for e in entries))
    
    if num_npcs >= 5 or num_unique_texts <= 2:
        legitimate += 1
    else:
        bad_mapping += 1

w(f'- **Legitimate** (many NPCs or same text): {legitimate}')
w(f'- **Bad mapping** (2-4 NPCs with different texts): {bad_mapping}')
w()

# List bad mappings
w('### Bad Mappings Detail')
w()
for (zf, zk), entries in sorted_zh:
    npcs_list = sorted(set(e[0] for e in entries), key=lambda x: x.lower())
    num_npcs = len(npcs_list)
    num_unique_texts = len(set(e[1] for e in entries))
    
    if num_npcs < 5 and num_unique_texts > 2:
        csv_owner, csv_note = zh_resolved.get((zf, zk), ('', ''))
        w(f'**{zf} / {zk}** — {num_npcs} NPCs, {num_unique_texts} unique texts')
        if csv_owner:
            w(f'  ✓ CSV owner: {csv_owner}')
        elif csv_note == 'csv_no_match':
            w(f'  ⚠ None match CSV text')
        elif csv_note == 'no_csv_data':
            w(f'  ⚠ No CSV data available')
        w(f'  NPCs: {", ".join(npcs_list)}')
        for e in entries:
            w(f'  - {e[0]}: {e[1][:60]}')
        w()

w('## High-Priority NPCs for Fix')
w()
w('Story-critical NPCs most affected by collisions:')
w()

# Check specific important NPCs
important_npcs = ['Klog', 'Finnigan', 'Batlin', 'Iolo', 'Lord British', 'Shamino', 'Dupre', 'Spark', 'Petre', 'Christopher']
for npc in important_npcs:
    total = zh_npc_total.get(npc, 0)
    loses = zh_npc_loses.get(npc, 0)
    wins = zh_npc_wins.get(npc, 0)
    if total > 0:
        w(f'- **{npc}**: {total} colliding entries, {loses} overwritten, {wins} win')
    else:
        w(f'- **{npc}**: no collisions')

w()
w('## All CSV-Resolvable Collisions')
w()
for (zf, zk), entries in sorted_zh:
    csv_owner, csv_note = zh_resolved.get((zf, zk), ('', ''))
    if csv_owner:
        npcs_list = sorted(set(e[0] for e in entries), key=lambda x: x.lower())
        if csv_owner in npcs_list:
            bad_npcs = [n for n in npcs_list if n != csv_owner]
            w(f'- **{zf}/{zk}**: owner={csv_owner}, wrong={", ".join(bad_npcs)}')
        else:
            w(f'- **{zf}/{zk}**: owner={csv_owner} (NOT in JSON!), NPCs={", ".join(npcs_list)}')

w()
w('## EN-Side Collisions (for reference)')
w()
sorted_en = sorted(en_collisions.items(), key=lambda x: -len(x[1]))
for (ef, ek), entries in sorted_en[:30]:
    npcs_list = sorted(set(e[0] for e in entries), key=lambda x: x.lower())
    csv_data = en_csv_text.get((ef, ek))
    csv_info = f'EN CSV: {csv_data[0]} / {csv_data[1][:40]}...' if csv_data else 'EN CSV: no entry'
    w(f'- **{ef}/{ek}**: {len(entries)} NPCs — {csv_info}')
    w(f'  NPCs: {", ".join(npcs_list[:8])}{", ..." if len(npcs_list) > 8 else ""}')

w()
w('---')
w(f'*Report generated by audit_collisions.py*')

# ── Save report ────────────────────────────────────────────────────────

report_path = os.path.join(PROJECT_DIR, 'collision_audit_report.md')
with open(report_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print(f'Report written to {report_path}')
print(f'ZH collisions: {len(zh_collisions)}')
print(f'EN collisions: {len(en_collisions)}')
print(f'CSV-resolvable: {csv_resolvable}')
print(f'Legitimate: {legitimate}, Bad mappings: {bad_mapping}')
print(f'NPCs with lost entries: {len(zh_npc_loses)}')
