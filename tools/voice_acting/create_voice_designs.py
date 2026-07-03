#!/usr/bin/env python3
"""
Create npc_voice_designs.json from bilingual_mapping_review.json.

Groups NPCs by voice characteristics and assigns per-group voice designs
with Chinese and English voice descriptions + reference texts.
"""
import json
import os
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAPPING_PATH = os.path.join(SCRIPT_DIR, 'bilingual_mapping_review.json')
PROMPT_ZH_PATH = os.path.join(SCRIPT_DIR, 'voice_prompt_zh.json')
OUTPUT_PATH = os.path.join(SCRIPT_DIR, 'npc_voice_designs.json')

def load_mapping():
    with open(MAPPING_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_prompt_zh():
    with open(PROMPT_ZH_PATH, 'r', encoding='utf-8') as f:
        return {k.strip(): v for k, v in json.load(f).items()}

def find_reference_texts(entries):
    """Find best reference texts for ZH and EN from first entries."""
    ref_zh = ''
    ref_en = ''
    for e in entries:
        if not ref_zh and e.get('zh_text', ''):
            t = e['zh_text'].strip().strip('"').strip('\u300c').strip('\u300d')
            if len(t) > 5 and len(t) < 100:
                ref_zh = t
        if not ref_en and e.get('en_text', ''):
            t = e['en_text'].strip().strip('"')
            if len(t) > 5 and len(t) < 100:
                ref_en = t
        if ref_zh and ref_en:
            break
    return ref_zh, ref_en

def extract_ages(entries):
    """Collect unique voice_age values."""
    ages = set()
    for e in entries:
        a = e.get('voice_age', '') or ''
        if a:
            ages.add(a)
    return ages

def main():
    data = load_mapping()
    prompt_zh = load_prompt_zh()

    npc_map = defaultdict(list)
    for entry in data:
        npc = entry.get('npc', '') or 'UNKNOWN'
        npc_map[npc].append(entry)

    print(f"Loaded {len(data)} entries across {len(npc_map)} NPCs")

    # Analyze each NPC
    npc_info = {}
    for npc_name, entries in sorted(npc_map.items(), key=lambda x: -len(x[1])):
        first = entries[0]
        ref_zh, ref_en = find_reference_texts(entries)
        npc_info[npc_name] = {
            'count': len(entries),
            'gender': first.get('voice_gender', '') or '',
            'age': first.get('voice_age', '') or '',
            'prompt': first.get('voice_prompt', '') or '',
            'prompt_zh': '',
            'ref_zh': ref_zh,
            'ref_en': ref_en,
            'ages': extract_ages(entries),
        }
        # Look up Chinese prompt
        key = npc_info[npc_name]['prompt'].strip()
        if key in prompt_zh:
            npc_info[npc_name]['prompt_zh'] = prompt_zh[key]
        else:
            # Try fuzzy match
            matched = False
            for pk, pv in prompt_zh.items():
                if pk in key or key in pk:
                    npc_info[npc_name]['prompt_zh'] = pv
                    matched = True
                    break
            if not matched:
                # Fallback: basic gender/age translation
                g = npc_info[npc_name]['gender']
                a = npc_info[npc_name]['age']
                npc_info[npc_name]['prompt_zh'] = f"{'男性' if g == 'male' else '女性' if g == 'female' else '中性'}，用標準的普通話朗讀"

    # Build voice designs
    designs = {}
    design_groups = defaultdict(list)

    # NPCs that get unique voice designs (30+ lines or special)
    unique_npcs = set()
    special_keywords = ['gargoyle', 'ghost', 'dragon', 'hydra', 'troll', 'cyclops',
                        'ape', 'rat', 'horse', 'fox', 'unicorn', 'elemental',
                        'will-o-wisp', 'shrine', 'fairy']

    # Also gets unique designs regardless of line count
    notable_npcs = {
        'Lord British', 'Batlin', 'Nystul', 'Chuckles', 'Nicodemus', 'Rudyom',
        'Lord Heather', 'Mariah', 'Margareta', 'Avatar',
        'Dell', 'Geoffrey', 'Hook', 'Time Lord', 'Stone Guardian',
        'Dracothraxus', 'Adjhar', 'Dark Core', 'Erethian', 'Ferryman',
    }

    for npc_name, info in sorted(npc_info.items(), key=lambda x: -x[1]['count']):
        prompt = info['prompt'].lower()

        # UNKNOWN -> narrator (always unique)
        if npc_name == 'UNKNOWN':
            unique_npcs.add(npc_name)
            continue

        # Special characters
        is_special = any(kw in prompt for kw in special_keywords)
        # High line count NPCs
        is_major = info['count'] >= 28
        # Main companions
        is_companion = npc_name in {'Iolo', 'Shamino', 'Dupre', 'Jaana', 'Spark',
                                     'Sentri', 'Trellek', 'Julia', 'Katrina', 'Petre',
                                     'Tseramed', 'Battles', 'Mariah'}
        is_notable = npc_name in notable_npcs

        if is_special or is_major or is_companion or is_notable:
            unique_npcs.add(npc_name)

    print(f"Unique voice NPCs: {len(unique_npcs)}")
    print(f"Remaining NPCs to group: {len(npc_info) - len(unique_npcs) - 1}")

    # Assign unique designs
    for npc_name in sorted(unique_npcs):
        info = npc_info[npc_name]
        design_id = f"npc_{npc_name.lower().replace(' ', '_')}"
        ref_zh = info['ref_zh']
        ref_en = info['ref_en']

        voice_desc_en = info['prompt']
        voice_desc_zh = info['prompt_zh'] if info['prompt_zh'] else voice_desc_en

        designs[design_id] = {
            'npc': npc_name,
            'type': 'unique' if npc_name != 'UNKNOWN' else 'narrator',
            'npcs': [npc_name],
            'voice_desc_en': voice_desc_en,
            'voice_desc_zh': voice_desc_zh,
            'ref_zh_text': ref_zh,
            'ref_en_text': ref_en,
        }
        design_groups[design_id].append(npc_name)

    # Group remaining NPCs by gender + age bucket
    remaining = {n: info for n, info in npc_info.items()
                 if n not in unique_npcs and n != 'UNKNOWN'}

    # Define grouping buckets
    buckets = {
        'young_male_energetic': {
            'match': lambda g, a, p: g == 'male' and a in ('young', 'teen', 'child', '20s', '20s-30s', 'teen-20s'),
            'voice_desc_en': 'Male, 20s-30s, young man, warm and friendly voice, energetic and bright, speaks in standard Mandarin',
            'voice_desc_zh': '男性，20-30歲，年輕開朗，溫暖友善，充滿活力，用標準的普通話朗讀',
            'ref_source': 'young',
        },
        'middle_male_friendly': {
            'match': lambda g, a, p: g == 'male' and a in ('middle', '30s', '30s-40s', '40s', '40s-50s') and any(k in p for k in ['friendly', 'warm', 'cheerful', 'kind', 'nice', 'gentle', 'happy', 'calm', 'peaceful', 'polite', 'wandering monk']),
            'voice_desc_en': 'Male, 30s-50s, friendly and warm-hearted man, pleasant conversational voice, speaks in standard Mandarin',
            'voice_desc_zh': '男性，30-50歲，友善溫暖，愉快的談話聲音，用標準的普通話朗讀',
            'ref_source': 'middle',
        },
        'middle_male_serious': {
            'match': lambda g, a, p: g == 'male' and a in ('middle', '30s', '30s-40s', '40s', '40s-50s') and any(k in p for k in ['serious', 'stern', 'firm', 'gruff', 'strict', 'tough', 'focused', 'professional', 'dignified', 'broad-shouldered', 'confident', 'strong proud', 'authoritative']),
            'voice_desc_en': 'Male, 30s-50s, serious and professional man, steady authoritative voice, speaks in standard Mandarin',
            'voice_desc_zh': '男性，30-50歲，嚴肅專業的男人，沉穩權威的聲音，用標準的普通話朗讀',
            'ref_source': 'middle',
        },
        'middle_male_rough': {
            'match': lambda g, a, p: g == 'male' and a in ('middle', '30s', '30s-40s', '40s', '40s-50s') and any(k in p for k in ['rough', 'gruff', 'angry', 'bitter', 'hostile', 'mean', 'suspicious', 'annoyed', 'booming', 'thunderous', 'loud', 'sullen', 'gloomy', 'resentful', 'displeased', 'disapproving']),
            'voice_desc_en': 'Male, 30s-50s, rough gruff man, harsh and irritated voice, speaks in standard Mandarin',
            'voice_desc_zh': '男性，30-50歲，粗獷的男人，刺耳惱怒的聲音，用標準的普通話朗讀',
            'ref_source': 'middle',
        },
        'middle_male_worried': {
            'match': lambda g, a, p: g == 'male' and a in ('middle', '30s', '30s-40s', '40s', '40s-50s') and any(k in p for k in ['worried', 'anxious', 'concerned', 'distracted', 'nervous', 'fearful', 'grumpy', 'irritated', 'tired', 'weary']),
            'voice_desc_en': 'Male, 30s-50s, worried and anxious man, concerned hesitant voice, speaks in standard Mandarin',
            'voice_desc_zh': '男性，30-50歲，憂慮不安的男人，關切猶豫的聲音，用標準的普通話朗讀',
            'ref_source': 'middle',
        },
        'middle_male_mischievous': {
            'match': lambda g, a, p: g == 'male' and a in ('middle', '30s', '30s-40s', '40s', '40s-50s') and any(k in p for k in ['prankster', 'mischievous', 'con artist', 'sly', 'playful', 'smiling', 'lively', 'theatrical']),
            'voice_desc_en': 'Male, 30s-40s, playful and mischievous man, lively theatrical voice with a sly charm, speaks in standard Mandarin',
            'voice_desc_zh': '男性，30-40歲，頑皮愛玩的男人，生動活潑的聲音，用標準的普通話朗讀',
            'ref_source': 'middle',
        },
        'elderly_male': {
            'match': lambda g, a, p: g == 'male' and a in ('elderly', 'old', 'aged'),
            'voice_desc_en': 'Male, elderly man, warm weathered voice with wisdom and patience, speaks slowly in standard Mandarin',
            'voice_desc_zh': '男性，年長，溫暖滄桑的聲音，充滿智慧和耐心，慢慢地說，用標準的普通話朗讀',
            'ref_source': 'elderly',
        },
        'young_female_bright': {
            'match': lambda g, a, p: g == 'female' and a in ('young', '20s', '20s-30s', 'adult') and any(k in p for k in ['cheerful', 'bright', 'sweet', 'warm', 'friendly', 'polite', 'happy', 'lively', 'welcoming', 'nice', 'kind']),
            'voice_desc_en': 'Female, 20s-30s, bright and cheerful young woman, warm friendly voice, speaks in standard Mandarin',
            'voice_desc_zh': '女性，20-30歲，開朗明亮的年輕女子，溫暖友善的聲音，用標準的普通話朗讀',
            'ref_source': 'young',
        },
        'young_female_serious': {
            'match': lambda g, a, p: g == 'female' and a in ('young', '20s', '20s-30s', 'adult') and any(k in p for k in ['serious', 'stern', 'cold', 'tough', 'fierce', 'sly', 'husky', 'hushed', 'focused', 'wry', 'sneaky', 'wicked', 'confident', 'capable', 'firm', 'strong', 'muscular']),
            'voice_desc_en': 'Female, 20s-30s, serious and composed young woman, steady confident voice, speaks in standard Mandarin',
            'voice_desc_zh': '女性，20-30歲，嚴肅沈著的年輕女子，沉穩自信的聲音，用標準的普通話朗讀',
            'ref_source': 'young',
        },
        'young_female_sad': {
            'match': lambda g, a, p: g == 'female' and a in ('young', '20s', '20s-30s') and any(k in p for k in ['sad', 'shy', 'soft', 'quiet', 'gentle', 'melancholy', 'delicate', 'worried', 'concerned', 'anxious', 'nervous', 'worried', 'distracted', 'preoccupied', 'thoughtful', 'worried']),
            'voice_desc_en': 'Female, 20s-30s, gentle and soft-spoken young woman, quiet tender voice, speaks in standard Mandarin',
            'voice_desc_zh': '女性，20-30歲，溫柔輕聲細語的年輕女子，安靜柔和的聲音，用標準的普通話朗讀',
            'ref_source': 'young',
        },
        'young_female_exotic': {
            'match': lambda g, a, p: g == 'female' and a in ('young', '20s', '20s-30s') and any(k in p for k in ['exotic', 'mysterious', 'gypsy', 'deep', 'formal', 'dreamy', 'confused', 'sleepy']),
            'voice_desc_en': 'Female, 20s, mysterious and exotic young woman, deep knowing voice with a hypnotic quality, speaks in standard Mandarin',
            'voice_desc_zh': '女性，20多歲，神秘異域的年輕女子，深邃的知性聲音，用標準的普通話朗讀',
            'ref_source': 'young',
        },
        'middle_female_warm': {
            'match': lambda g, a, p: g == 'female' and a in ('middle', '30s', '30s-40s', '40s', '40s-50s') and any(k in p for k in ['warm', 'kind', 'friendly', 'gentle', 'sweet', 'caring', 'motherly', 'musical', 'noblewoman', 'refined', 'curtsy']),
            'voice_desc_en': 'Female, 40s-50s, warm and maternal woman, kind gentle voice with wisdom, speaks in standard Mandarin',
            'voice_desc_zh': '女性，40-50歲，溫暖慈祥的女人，善良溫柔的聲音，用標準的普通話朗讀',
            'ref_source': 'middle',
        },
        'middle_female_firm': {
            'match': lambda g, a, p: g == 'female' and a in ('middle', '30s', '30s-40s', '40s', '40s-50s') and any(k in p for k in ['stern', 'cold', 'tough', 'efficient', 'icy', 'strong', 'proud', 'flat', 'worried', 'anxious', 'concerned', 'nervous', 'warm apologetic']),
            'voice_desc_en': 'Female, 40s-50s, firm and capable woman, no-nonsense professional voice, speaks in standard Mandarin',
            'voice_desc_zh': '女性，40-50歲，堅定能幹的女人，務實專業的聲音，用標準的普通話朗讀',
            'ref_source': 'middle',
        },
        'middle_female_troubled': {
            'match': lambda g, a, p: g == 'female' and a in ('middle', '30s', '30s-40s', '40s', '40s-50s') and any(k in p for k in ['sad', 'grief', 'pleading', 'desperate', 'tearful', 'tired', 'annoyed', 'overworked']),
            'voice_desc_en': 'Female, 40s-50s, weary but resilient woman, tired concerned voice, speaks in standard Mandarin',
            'voice_desc_zh': '女性，40-50歲，疲憊但堅韌的女人，憂心忡忡的聲音，用標準的普通話朗讀',
            'ref_source': 'middle',
        },
        'elderly_female': {
            'match': lambda g, a, p: g == 'female' and a in ('elderly', 'old', 'aged'),
            'voice_desc_en': 'Female, elderly woman, warm grandmotherly voice, gentle and loving, speaks slowly in standard Mandarin',
            'voice_desc_zh': '女性，年長，慈祥的老奶奶的聲音，溫柔慈愛，慢慢地說，用標準的普通話朗讀',
            'ref_source': 'elderly',
        },
        'actor_entertainer': {
            'match': lambda g, a, p: any(k in p for k in ['actor', 'actress', 'performer', 'musician', 'theatrical', 'bard', 'juggler']),
            'voice_desc_en': 'Theatrical performer, expressive and dramatic voice, with a flair for entertainment, speaks in standard Mandarin',
            'voice_desc_zh': '戲劇表演者，富於表情和戲劇性的聲音，愛好娛樂，用標準的普通話朗讀',
            'ref_source': 'young',
        },
        'child': {
            'match': lambda g, a, p: a in ('child', 'toddler', 'baby'),
            'voice_desc_en': 'Young child, innocent and curious voice, high-pitched and playful, speaks in standard Mandarin',
            'voice_desc_zh': '小孩，天真好奇的聲音，高音調俏皮，用標準的普通話朗讀',
            'ref_source': 'young',
        },
    }

    # Assign remaining NPCs to buckets
    bucketed = set()
    for bucket_id, bucket in sorted(buckets.items()):
        for npc_name in sorted(remaining.keys()):
            if npc_name in bucketed:
                continue
            info = remaining[npc_name]
            g, a, p = info['gender'], info['age'], info['prompt'].lower()
            if bucket['match'](g, a, p):
                design_id = f"group_{bucket_id}"
                if design_id not in designs:
                    designs[design_id] = {
                        'npc': bucket_id,
                        'type': 'group',
                        'npcs': [],
                        'voice_desc_en': bucket['voice_desc_en'],
                        'voice_desc_zh': bucket['voice_desc_zh'],
                        'ref_zh_text': '',
                        'ref_en_text': '',
                    }
                designs[design_id]['npcs'].append(npc_name)
                bucketed.add(npc_name)

    # Any remaining NPCs that didn't match any bucket
    unmatched = set(remaining.keys()) - bucketed
    if unmatched:
        print(f"\nWARNING: {len(unmatched)} NPCs unmatched:")
        for n in sorted(unmatched):
            info = remaining[n]
            print(f"  {n:25s} ({info['count']:3d} lines) {info['gender']:10s} {info['age']:20s} {info['prompt'][:50]}")
        # Add them to a catch-all bucket
        for npc_name in sorted(unmatched):
            info = remaining[npc_name]
            design_id = 'group_other'
            if design_id not in designs:
                designs[design_id] = {
                    'npc': 'other',
                    'type': 'group',
                    'npcs': [],
                    'voice_desc_en': 'Neutral clear speaking voice, natural and pleasant, speaks in standard Mandarin',
                    'voice_desc_zh': '中性清晰的說話聲音，自然悅耳，用標準的普通話朗讀',
                    'ref_zh_text': '',
                    'ref_en_text': '',
                }
            designs[design_id]['npcs'].append(npc_name)

    # Pick reference texts for shared groups from their member NPCs
    for design_id, design in designs.items():
        if design['type'] != 'group':
            continue
        if design['ref_zh_text'] and design['ref_en_text']:
            continue
        for npc_name in design['npcs']:
            if npc_name in npc_info:
                info = npc_info[npc_name]
                if not design['ref_zh_text'] and info['ref_zh']:
                    design['ref_zh_text'] = info['ref_zh']
                if not design['ref_en_text'] and info['ref_en']:
                    design['ref_en_text'] = info['ref_en']
            if design['ref_zh_text'] and design['ref_en_text']:
                break

        # Fallback texts if none found
        if not design['ref_zh_text']:
            design['ref_zh_text'] = '你好，請問有什麼可以幫你的嗎？'
        if not design['ref_en_text']:
            design['ref_en_text'] = 'Hello there, how may I help you?'

    # Sort: unique NPCs first, then groups
    sorted_designs = {}
    for did in sorted(designs.keys()):
        sorted_designs[did] = designs[did]

    # Write output
    output = {
        '_meta': {
            'total_entries': len(data),
            'total_npcs': len(npc_info),
            'total_designs': len(sorted_designs),
            'unique_designs': sum(1 for d in sorted_designs.values() if d['type'] == 'unique'),
            'narrator_designs': sum(1 for d in sorted_designs.values() if d['type'] == 'narrator'),
            'group_designs': sum(1 for d in sorted_designs.values() if d['type'] == 'group'),
        },
        'designs': sorted_designs,
    }

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nWrote {OUTPUT_PATH}")
    print(f"  Designs: {output['_meta']['total_designs']} total")
    print(f"    Unique NPC designs: {output['_meta']['unique_designs']}")
    print(f"    Narrator designs: {output['_meta']['narrator_designs']}")
    print(f"    Group designs: {output['_meta']['group_designs']}")

    # Summary stats
    total_refs_needed = sum(1 for d in sorted_designs.values() if d['ref_zh_text'] and d['ref_en_text'])
    missing_ref_zh = sum(1 for d in sorted_designs.values() if not d['ref_zh_text'])
    missing_ref_en = sum(1 for d in sorted_designs.values() if not d['ref_en_text'])
    print(f"  Reference: {total_refs_needed} have both ZH/EN refs")
    if missing_ref_zh:
        print(f"    Missing ZH ref: {missing_ref_zh}")
    if missing_ref_en:
        print(f"    Missing EN ref: {missing_ref_en}")

if __name__ == '__main__':
    main()
