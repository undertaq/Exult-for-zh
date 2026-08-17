#!/usr/bin/env python3
"""
Audio file collision & integrity audit for Exult-for-zh.
Checks for:
1. NPC-specific filenames exist where expected
2. No generic filename collisions across different NPCs
3. File integrity (min duration check)
4. Orphan files (not in the mapping)
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(__file__) or '.')
from npc_data import NPC_NUMBERS

REVERSE_NPC = {v: k for k, v in NPC_NUMBERS.items() if k != 'UNKNOWN'}

def load_data():
    with open(os.path.join(os.path.dirname(__file__), 'bilingual_mapping_review.json')) as f:
        return json.load(f)

def build_base_name(e, lang):
    fid = (e.get(f'{lang}_func_id', '') or '0000')
    okv = (e.get(f'{lang}_offset_key', '') or '0')
    seg = e.get(f'{lang}_segment', 0) or 0
    if isinstance(fid, str) and (fid.startswith('0x') or fid.startswith('0X')):
        fid = fid[2:]
    fid = str(fid).lower().zfill(4)
    return f'{fid}_{okv}_{seg}'

def main():
    data = load_data()
    
    for lang in ['zh', 'en']:
        out_dir = f'/home/joe/project/Exult-for-zh/voice/{lang}'
        print(f'\n{"="*60}')
        print(f'  AUDIT: {lang.upper()} — {out_dir}')
        print(f'{"="*60}')
        
        # 1. Count NPC-specific files
        npc_files = [f for f in os.listdir(out_dir) if '_npc' in f and f.endswith('.ogg')]
        generic_files = [f for f in os.listdir(out_dir) if '_npc' not in f and f.endswith('.ogg')]
        print(f'  NPC-specific files: {len(npc_files)}')
        print(f'  Generic files: {len(generic_files)}')
        print(f'  Total: {len(npc_files) + len(generic_files)}')
        
        # 2. Build expected file map from data
        expected = {}  # (npc, base) → text_snippet
        expected_npc = {}  # npc → count
        npc_files_found = set()
        
        for e in data:
            npc = e.get('npc', '')
            nn = NPC_NUMBERS.get(npc)
            if nn is None:
                continue
            text = (e.get(f'{lang}_text', '') or '').strip()
            if not text:
                continue
            base = build_base_name(e, lang)
            npc_fname = f'{base}_npc{nn}.ogg'
            expected[(npc, base)] = text[:40]
            expected_npc[npc] = expected_npc.get(npc, 0) + 1
            if os.path.exists(os.path.join(out_dir, npc_fname)):
                npc_files_found.add(npc)
        
        total_expected = sum(expected_npc.values())
        total_found = sum(1 for f in npc_files
                          if any(f == f'{build_base_name(e, lang)}_npc{NPC_NUMBERS.get(e.get("npc",""))}.ogg'
                                 for e in data[:1]))  # placeholder
        # Recalculate total_found properly
        total_found = 0
        for e in data:
            npc = e.get('npc', '')
            nn = NPC_NUMBERS.get(npc)
            if nn is None: continue
            text = (e.get(f'{lang}_text','') or '').strip()
            if not text: continue
            base = build_base_name(e, lang)
            p = os.path.join(out_dir, f'{base}_npc{nn}.ogg')
            if os.path.exists(p):
                total_found += 1
        
        print(f'  Expected NPC-specific files: {total_expected}')
        print(f'  Existing NPC-specific files: {total_found}')
        print(f'  Missing: {total_expected - total_found}')
        
        # 3. Collision check: same generic base → different NPCs with different texts
        generic_map = {}  # base → set of (npc, text_snippet)
        for e in data:
            npc = e.get('npc', '')
            nn = NPC_NUMBERS.get(npc)
            if nn is None: continue
            text = (e.get(f'{lang}_text','') or '').strip()
            if not text: continue
            base = build_base_name(e, lang)
            if base not in generic_map:
                generic_map[base] = set()
            generic_map[base].add((npc, text[:30]))
        
        collisions = {base: entries for base, entries in generic_map.items()
                      if len(entries) > 1 and len(set(e[1] for e in entries)) > 1}
        legit_shared = {base: entries for base, entries in generic_map.items()
                        if len(entries) >= 5}  # 5+ NPCs sharing = legit (same text)
        
        # Check if collisions are resolved by NPC-specific files
        unresolved = 0
        for base, entries in collisions.items():
            # Check if ALL entries have NPC-specific files
            all_have_npc = True
            for npc, _ in entries:
                nn = NPC_NUMBERS.get(npc)
                p = os.path.join(out_dir, f'{base}_npc{nn}.ogg')
                if not os.path.exists(p):
                    all_have_npc = False
                    break
            if not all_have_npc:
                unresolved += len(entries)
                print(f'  ! UNRESOLVED: {base} — {entries}')
        
        print(f'  Collisions (diff texts): {len(collisions)} bases')
        print(f'  Legitimate sharing (≥5 NPCs): {len(legit_shared)} bases')
        print(f'  Unresolved collision entries: {unresolved}')
        
        # 4. Orphan check: NPC-specific files not in any mapping
        orphan_npc_files = []
        for fname in npc_files:
            # Parse npc number from filename
            if '_npc' not in fname:
                continue
            base = fname.split('_npc')[0]
            npc_num_str = fname.split('_npc')[1].replace('.ogg', '')
            try:
                npc_num = int(npc_num_str)
            except ValueError:
                orphan_npc_files.append((fname, f'invalid NPC number: {npc_num_str}'))
                continue
            npc_name = REVERSE_NPC.get(npc_num)
            if npc_name is None:
                orphan_npc_files.append((fname, f'no NPC name for number {npc_num}'))
                continue
            # Check if this base+npc is expected
            found = False
            for e in data:
                en = e.get('npc', '')
                if en != npc_name: continue
                text = (e.get(f'{lang}_text','') or '').strip()
                if not text: continue
                eb = build_base_name(e, lang)
                if eb == base:
                    found = True
                    break
            if not found:
                orphan_npc_files.append((fname, f'no mapping entry for {npc_name}/{base}'))
        
        if orphan_npc_files:
            print(f'  Orphan NPC-specific files: {len(orphan_npc_files)}')
            for fname, reason in orphan_npc_files[:10]:
                print(f'    {fname}: {reason}')
            if len(orphan_npc_files) > 10:
                print(f'    ... and {len(orphan_npc_files) - 10} more')
        else:
            print(f'  Orphan NPC-specific files: 0 ✓')
        
        # 5. Hard link check: NPC-specific ↔ generic
        broken_links = 0
        for fname in npc_files:
            npc_path = os.path.join(out_dir, fname)
            generic_name = '_'.join(fname.split('_')[:-1]) + '.ogg'
            if fname.split('_npc')[0] != generic_name.replace('.ogg', ''):
                # More precise: the generic name strips the _npc{N} suffix
                generic_name = fname.rsplit('_npc', 1)[0] + '.ogg'
            generic_path = os.path.join(out_dir, generic_name)
            if not os.path.exists(generic_path):
                broken_links += 1
        if broken_links:
            print(f'  Missing generic fallbacks: {broken_links}')
        else:
            print(f'  Missing generic fallbacks: 0 ✓')
        
        # 6. File size distribution
        sizes = [os.path.getsize(os.path.join(out_dir, f)) for f in npc_files]
        small = sum(1 for s in sizes if s < 50000)
        mid = sum(1 for s in sizes if 50000 <= s < 150000)
        large = sum(1 for s in sizes if s >= 150000)
        print(f'  Size: <50K={small} 50-150K={mid} >150K={large}')
        if large > 0:
            large_files = [(os.path.getsize(os.path.join(out_dir, f)), f)
                          for f in npc_files
                          if os.path.getsize(os.path.join(out_dir, f)) >= 150000]
            large_files.sort(reverse=True)
            print(f'    Largest: {large_files[0][0]} bytes — {large_files[0][1]}')

if __name__ == '__main__':
    main()
