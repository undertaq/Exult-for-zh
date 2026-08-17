#!/usr/bin/env python3
"""
Audit NPCs from bilingual_mapping_review.json:
- Group by NPC name
- Collect voice_gender, voice_age, voice_prompt
- Find representative ZH/EN text per NPC
- Identify special characters for unique voice treatments
"""
import json
import csv
from collections import defaultdict

SCRIPT_DIR = __file__ if not __file__.startswith('\\\\') else __file__[1:]
MAPPING_PATH = __file__ if not __file__.startswith('\\\\') else __file__[1:]
MAPPING_PATH = __file__

import os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAPPING_PATH = os.path.join(SCRIPT_DIR, 'bilingual_mapping_review.json')

def main():
    with open(MAPPING_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    npcs = defaultdict(list)
    for entry in data:
        npc = entry.get('npc', '') or 'UNKNOWN'
        npcs[npc].append(entry)

    print(f"Total entries: {len(data)}")
    print(f"Unique NPCs: {len(npcs)}")
    print()

    # Sort NPCs by line count (most lines first)
    sorted_npcs = sorted(npcs.items(), key=lambda x: -len(x[1]))

    print(f"{'NPC':25s} {'Lines':6s} {'Gender':10s} {'Age':20s} {'Voice Prompt'}")
    print(f"{'-'*25} {'-'*6} {'-'*10} {'-'*20} {'-'*40}")

    voice_groups = defaultdict(list)

    for npc_name, entries in sorted_npcs:
        count = len(entries)
        first = entries[0]
        gender = first.get('voice_gender', '') or ''
        age = first.get('voice_age', '') or ''
        prompt = first.get('voice_prompt', '') or ''

        # Find best ZH and EN reference texts (first non-empty, short enough)
        ref_zh = ''
        ref_en = ''
        for e in entries:
            if not ref_zh and e.get('zh_text', ''):
                ref_zh = e['zh_text']
            if not ref_en and e.get('en_text', ''):
                ref_en = e['en_text']
            if ref_zh and ref_en:
                break

        key = (gender, age, prompt)
        voice_groups[key].append((npc_name, count, ref_zh, ref_en))

        prompt_short = prompt[:40] if len(prompt) > 40 else prompt
        print(f"{npc_name:25s} {count:6d} {gender:10s} {age:20s} {prompt_short}")

    print(f"\n{'='*80}")
    print(f"Voice groups (unique gender+age+prompt combinations): {len(voice_groups)}")
    print()

    # Write detailed CSV
    csv_path = os.path.join(SCRIPT_DIR, 'npc_audit.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['npc', 'line_count', 'gender', 'age', 'voice_prompt', 'ref_zh', 'ref_en'])
        for npc_name, entries in sorted_npcs:
            first = entries[0]
            ref_zh = ''
            ref_en = ''
            for e in entries:
                if not ref_zh and e.get('zh_text', ''):
                    ref_zh = e['zh_text']
                if not ref_en and e.get('en_text', ''):
                    ref_en = e['en_text']
                if ref_zh and ref_en:
                    break
            w.writerow([
                npc_name, len(entries),
                first.get('voice_gender', ''),
                first.get('voice_age', ''),
                first.get('voice_prompt', ''),
                ref_zh, ref_en
            ])

    print(f"CSV written to: {csv_path}")

    # Print voice groups summary
    print(f"\nVoice Groups Summary:")
    for (gender, age, prompt), members in sorted(voice_groups.items(), key=lambda x: -sum(m[1] for m in x[1])):
        total_lines = sum(m[1] for m in members)
        print(f"\n  [{gender:10s}] [{age:20s}] ({len(members):3d} NPCs, {total_lines:5d} lines)")
        print(f"    Prompt: {prompt[:80]}")
        npc_list = ', '.join(m[0] for m in members[:10])
        if len(members) > 10:
            npc_list += f' ... (+{len(members)-10} more)'
        print(f"    NPCs: {npc_list}")

if __name__ == '__main__':
    main()
