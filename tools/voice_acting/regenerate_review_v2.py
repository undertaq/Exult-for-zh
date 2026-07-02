#!/usr/bin/env python3
"""
Regenerate bilingual_mapping_review_v2.json by merging static CSV and review JSON,
verifying static matches using heuristics, and translating untranslated lines.
Preserves voice acting metadata from review JSON.
"""

import os
import re
import csv
import json
import urllib.parse
import urllib.request
import time
import sys
from collections import defaultdict

# Paths
STATIC_CSV = r"bilingual_mapping_static.csv"
REVIEW_JSON = r"bilingual_mapping_review.json"
OUTPUT_JSON = r"bilingual_mapping_review_v2.json"

# Named Entities for Translation post-processing and verification
ENTITIES = {
    r"\bavatar\b": "聖者",
    r"\bbritannia\b": "不列顛尼亞",
    r"\blord\s+british\b": "不列顛王",
    r"\blb\b": "不列顛王",
    r"\bbatlin\b": "巴特林",
    r"\bfellowship\b": "友誼會",
    r"\bmilord\b": "大人",
    r"\bmilady\b": "女士",
    r"\bmoongate\b": "月之門",
    r"\bblackrock\b": "黑石",
    r"\bthe\s+guardian\b": "守護者",
    r"\bguardian\b": "守護者",
    r"\bblackrock\s+sword\b": "黑石劍",
    r"\bemps\b": "森靈",
    r"\bemp\b": "森靈",
    r"\bshrine\b": "神殿",
    r"\bshrine\s+of\s+principle\b": "原則神殿",
    r"\bshrine\s+of\s+courage\b": "勇氣神殿",
    r"\bshrine\s+of\s+love\b": "愛之神殿",
    r"\bshrine\s+of\s+truth\b": "真理神殿",
    r"\bshrine\s+of\s+compassion\b": "慈悲神殿",
    r"\bbuccaneer's\s+den\b": "Buccaneer's Den",
    r"\bbuccaneers\s+den\b": "Buccaneer's Den",
    r"\bwisps\b": "鬼火",
    r"\bwisp\b": "鬼火",
    r"\btime\s+lord\b": "時間領主",
    r"\berethian\b": "Erethian",
    r"\bmondain\b": "Mondain",
    r"\bminax\b": "Minax",
    r"\bexodus\b": "Exodus",
    r"\barcadion\b": "Arcadion",
    r"\bgargoyles\b": "石像鬼",
    r"\bgargoyle\b": "石像鬼",
    r"\bbalrons\b": "炎魔",
    r"\bbalron\b": "炎魔",
    r"\bdaemons\b": "惡魔",
    r"\bdaemon\b": "惡魔",
    r"\biolo\b": "Iolo",
    r"\bshamino\b": "Shamino",
    r"\bdupre\b": "Dupre",
    r"\bgwenno\b": "Gwenno",
    r"\bspark\b": "Spark",
    r"\btrinsic\b": "Trinsic",
    r"\bbritain\b": "Britain",
    r"\bjhelom\b": "Jhelom",
    r"\bminoc\b": "Minoc",
    r"\bmoonglow\b": "Moonglow",
    r"\bserpent's\s+hold\b": "Serpent's Hold",
    r"\bskara\s+brae\b": "Skara Brae",
    r"\byew\b": "Yew",
}

def norm(t):
    if not t:
        return ""
    t = re.sub(r'["""\u201c\u201d\u201e\u201f]', '', t)
    t = re.sub(r'\s+', ' ', t).strip().lower()
    return t

def make_clean(text):
    if not text:
        return ""
    t = norm(text)
    t = re.sub(r'<[^>]+>', '', t)
    t = re.sub(r'[^a-z0-9\s]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def load_static_csv(path):
    rows = []
    keyed = {}
    with open(path, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            fid = row['func_id'].strip()
            en_key = row['en_offset_key'].strip()
            en_seg = int(row.get('en_segment', '0').strip() or '0')
            entry = {
                'func_id': fid,
                'npc': row.get('npc', '').strip(),
                'en_offset_key': en_key,
                'en_segment': en_seg,
                'en_text': row.get('en_text', '').strip(),
                'zh_offset_key': row.get('zh_offset_key', '').strip(),
                'zh_segment': int(row.get('zh_segment', '0').strip() or '0'),
                'zh_text': row.get('zh_text', '').strip(),
                'confidence': row.get('confidence', '').strip(),
                '_match_review': [],
            }
            rows.append(entry)
            keyed[(fid, en_key, en_seg)] = entry
    return rows, keyed

def google_translate(text, target_lang='zh-TW'):
    """Translate text using the free Google Translate API endpoint with retry."""
    if not text.strip() or not any(c.isalnum() for c in text):
        return text # Don't translate punctuation/whitespace-only strings

    url = "https://translate.google.com/translate_a/single?client=gtx&sl=en&tl=" + target_lang + "&dt=t&q=" + urllib.parse.quote(text)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
    }
    req = urllib.request.Request(url, headers=headers)
    
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                res = response.read().decode('utf-8')
                data = json.loads(res)
                translated = "".join(seg[0] for seg in data[0] if seg[0])
                return translated
        except Exception as e:
            print(f"Translation warning: attempt {attempt+1} failed for text '{text[:30]}...': {e}", file=sys.stderr)
            time.sleep(1.5)
    return ""

def post_process_translation(zh_text):
    """Post-process translated Traditional Chinese to match guidelines."""
    if not zh_text:
        return ""
        
    # 1. Standard entity terms replacement
    for pattern, zh_term in ENTITIES.items():
        # Match case-insensitive English word in the Chinese text (sometimes the translation leaves English names)
        # and replace them with standard Chinese terms
        en_word = re.sub(r'\\b', '', pattern)
        zh_text = re.sub(en_word, zh_term, zh_text, flags=re.IGNORECASE)
    
    # Also replace machine-translated ones
    replacements = {
        "阿凡達": "聖者",
        "不列顛王": "不列顛王",
        "監護人": "守護者",
        "聯誼會": "友誼會",
        "月門": "月之門",
        "月球門": "月之門",
    }
    for old, new in replacements.items():
        zh_text = zh_text.replace(old, new)

    # 2. Quote replacement: replace double quotes with full-width quotes sequentially
    # "Hello" -> 「Hello」
    processed = []
    quote_open = False
    for ch in zh_text:
        if ch == '"':
            if not quote_open:
                processed.append('「')
                quote_open = True
            else:
                processed.append('」')
                quote_open = False
        else:
            processed.append(ch)
    zh_text = "".join(processed)

    # Ensure quotes are closed if mismatched
    if quote_open:
        zh_text += '」'

    # 3. Clean up spaces around punctuation
    zh_text = zh_text.replace(" 。", "。").replace(" ，", "，").replace(" ！", "！").replace(" ？", "？")
    
    return zh_text

def verify_match(en, zh):
    """Run heuristics to verify if English and Chinese texts match."""
    if not en or not zh:
        return False, "empty"
    
    en_clean = en.strip()
    zh_clean = zh.strip()

    # 1. Number check
    en_nums = set(re.findall(r'\d+', en_clean))
    for num in en_nums:
        if num not in zh_clean:
            return False, f"number_mismatch_{num}"

    # 2. Named entities check
    en_lower = en_clean.lower()
    zh_lower = zh_clean.lower()
    for pattern, zh_term in ENTITIES.items():
        if re.search(pattern, en_lower):
            en_term = re.sub(r'\\b', '', pattern)
            if zh_term.lower() not in zh_lower and en_term not in zh_lower:
                return False, f"entity_mismatch_{zh_term}"

    # 3. Length check
    en_words = len(re.findall(r'\b\w+\b', en_clean))
    zh_chars = len(re.sub(r'[^\u4e00-\u9fff]', '', zh_clean))
    
    if en_words > 5 and zh_chars > 0:
        ratio = en_words / zh_chars
        if ratio < 0.15 or ratio > 4.0:
            return False, f"length_ratio_{ratio:.2f}"
    elif en_words > 5 and zh_chars == 0:
        # Long English text with no Chinese characters is likely a mismatch unless it is formatting
        if not zh_clean.isascii():
            return False, "long_en_no_zh_chars"

    # 4. Control characters check
    for char in ['@', '*']:
        if (char in en_clean) != (char in zh_clean):
            if char == '*' and (en_clean.startswith('"') or zh_clean.startswith('「')):
                pass
            else:
                return False, f"control_char_mismatch_{char}"

    return True, "ok"

def main():
    print("Loading static CSV...", file=sys.stderr)
    static_rows, static_keyed = load_static_csv(STATIC_CSV)
    print(f"  {len(static_rows)} rows", file=sys.stderr)

    # Deduplicate: keep only first entry per (func_id, en_offset_key, en_segment)
    seen_keys = set()
    deduped = []
    for entry in static_rows:
        k = (entry['func_id'], entry['en_offset_key'], entry['en_segment'])
        if k not in seen_keys:
            seen_keys.add(k)
            deduped.append(entry)
        else:
            for existing in deduped:
                ek = (existing['func_id'], existing['en_offset_key'], existing['en_segment'])
                if ek == k:
                    if 'matched' in entry['confidence'] and 'static' in existing['confidence']:
                        existing['confidence'] = entry['confidence']
                    break
    static_rows = deduped
    print(f"  {len(static_rows)} after dedup", file=sys.stderr)

    static_by_fid = defaultdict(list)
    for entry in static_rows:
        static_by_fid[entry['func_id']].append(entry)

    static_all = []
    for entry in static_rows:
        clean = make_clean(entry['en_text'])
        if clean:
            static_all.append((clean, entry))

    print("Pre-splitting static words for Jaccard...", file=sys.stderr)
    static_all_words = [(set(clean.split()), entry) for clean, entry in static_all]

    print("Loading review JSON...", file=sys.stderr)
    with open(REVIEW_JSON, 'r', encoding='utf-8') as f:
        review_entries = json.load(f)
    print(f"  {len(review_entries)} entries", file=sys.stderr)

    # ── Phase 1: Match review entries to static entries ────────────────
    print("Matching review entries to static rows...", file=sys.stderr)
    matched_count = 0
    unmatched_both = []   # has en+zh but no match
    unmatched_zhonly = [] # has zh only

    for idx, rev in enumerate(review_entries):
        if idx > 0 and idx % 2000 == 0:
            print(f"  Processed {idx} review entries...", file=sys.stderr)
        en_func = rev.get('en_func_id', '').strip()
        en_key = rev.get('en_offset_key', '').strip()
        en_seg = rev.get('en_segment', 0)
        en_text = rev.get('en_text', '').strip()
        zh_text = rev.get('zh_text', '').strip() or rev.get('zh_text_raw', '').strip()

        if not en_text:
            unmatched_zhonly.append(rev)
            continue
        if not zh_text:
            continue

        matched_static = None
        match_type = None

        # Strategy 1: Exact match by (func, offset, segment)
        if en_func and en_key:
            matched_static = static_keyed.get((en_func, en_key, en_seg))
            if matched_static:
                match_type = 'exact'

        # Strategy 2: Content match by substring
        if not matched_static:
            rev_clean = make_clean(en_text)
            if rev_clean:
                if en_func in static_by_fid:
                    for s_entry in static_by_fid[en_func]:
                        s_clean = make_clean(s_entry['en_text'])
                        if rev_clean in s_clean:
                            matched_static = s_entry
                            match_type = 'substr'
                            break
                if not matched_static:
                    for s_clean, s_entry in static_all:
                        if rev_clean in s_clean:
                            matched_static = s_entry
                            match_type = 'substr_cross_func'
                            break

        # Strategy 3: Jaccard similarity (for near-matches)
        if not matched_static:
            rev_words = set(make_clean(en_text).split()) if make_clean(en_text) else set()
            if rev_words:
                best_entry = None
                best_score = 0.0
                for s_words, s_entry in static_all_words:
                    if not s_words:
                        continue
                    inter = rev_words & s_words
                    union = rev_words | s_words
                    score = len(inter) / len(union) if union else 0
                    if score > best_score:
                        best_score = score
                        best_entry = s_entry
                if best_score >= 0.5:
                    matched_static = best_entry
                    match_type = f'jaccard_{best_score:.2f}'

        if matched_static:
            pos = matched_static['en_text'].lower().find(en_text.lower())
            matched_static['_match_review'].append({
                'zh_text': zh_text,
                'en_text': en_text,
                'match_type': match_type,
                'pos': pos if pos >= 0 else 999999,
                'voice_gender': rev.get('voice_gender'),
                'voice_age': rev.get('voice_age'),
                'voice_prompt': rev.get('voice_prompt'),
                'voice_lang': rev.get('voice_lang'),
                'tone': rev.get('tone'),
                'tone_instruct': rev.get('tone_instruct'),
            })
            matched_count += 1
        else:
            unmatched_both.append(rev)

    print(f"  Matched review entries: {matched_count}", file=sys.stderr)

    # ── Phase 2: Build final output list ──────────────────────────────
    print("Building final mapping list...", file=sys.stderr)
    output = []
    index = 0
    translation_cache = {}

    stats = defaultdict(int)

    for entry in static_rows:
        en_text = entry['en_text']
        zh_text = entry['zh_text']
        matches = entry['_match_review']

        out = {
            'index': index,
            'npc': entry['npc'],
            'en_func_id': entry['func_id'],
            'en_offset_key': entry['en_offset_key'],
            'en_segment': entry['en_segment'],
            'en_text': en_text,
            'zh_func_id': entry['func_id'],
            'zh_offset_key': entry['zh_offset_key'],
            'zh_segment': entry['zh_segment'],
            'zh_text': zh_text,
            'confidence': entry['confidence'],
            'voice_gender': None,
            'voice_age': None,
            'voice_prompt': None,
            'voice_lang': 'en',
            'tone': 'neutral',
            'tone_instruct': '',
        }

        # Check for standard option override
        STANDARD_OPTIONS = {
            "name": "姓名",
            "job": "職業",
            "bye": "告辭",
            "avatar": "聖者",
            "gold": "金幣",
            "magic": "魔法",
            "join": "加入",
            "leave": "離隊",
            "stables": "馬廄",
            "murder": "謀殺",
            "fellowship": "友誼會",
        }
        en_lower_clean = en_text.strip().strip('"').strip("'").strip().lower()
        if en_lower_clean in STANDARD_OPTIONS:
            out['zh_text'] = STANDARD_OPTIONS[en_lower_clean]
            out['confidence'] = 'standard_option_override'
            stats['standard_override'] += 1
        elif matches:
            matches_sorted = sorted(matches, key=lambda m: m['pos'])
            # Check coverage of matched segments
            en_clean = make_clean(en_text)
            if en_clean:
                coverage = [False] * len(en_clean)
                for m in matches:
                    r_clean = make_clean(m.get('en_text', ''))
                    if r_clean:
                        idx_pos = en_clean.find(r_clean)
                        if idx_pos >= 0:
                            for k in range(idx_pos, min(idx_pos + len(r_clean), len(coverage))):
                                coverage[k] = True
                covered_ratio = sum(coverage) / len(coverage) if coverage else 0
            else:
                covered_ratio = 1.0

            if covered_ratio >= 0.85:
                # Reconstruct full Chinese translation
                if len(matches_sorted) == 1:
                    out['zh_text'] = matches_sorted[0]['zh_text']
                else:
                    out['zh_text'] = ''.join(m['zh_text'] for m in matches_sorted)
                
                # Copy voice acting fields from the longest matched segment
                longest_match = max(matches_sorted, key=lambda m: len(m['en_text']))
                out['voice_gender'] = longest_match['voice_gender']
                out['voice_age'] = longest_match['voice_age']
                out['voice_prompt'] = longest_match['voice_prompt']
                out['voice_lang'] = longest_match['voice_lang'] or 'en'
                out['tone'] = longest_match['tone'] or 'neutral'
                out['tone_instruct'] = longest_match['tone_instruct'] or ''

                match_types = [m['match_type'] for m in matches_sorted]
                if any(t == 'exact' for t in match_types):
                    out['confidence'] = 'review_v2_matched_exact'
                elif any(t and t.startswith('substr') for t in match_types):
                    out['confidence'] = 'review_v2_matched_substr'
                else:
                    out['confidence'] = 'review_v2_matched_jaccard'
                stats['matched_review'] += 1
            else:
                # Partial match, verify and mark
                if len(matches_sorted) == 1:
                    out['zh_text'] = matches_sorted[0]['zh_text']
                else:
                    out['zh_text'] = ''.join(m['zh_text'] for m in matches_sorted)
                out['zh_text'] = "##M## " + out['zh_text']
                out['confidence'] = 'review_v2_partial'
                stats['partial_review'] += 1
        elif en_text and zh_text:
            # Statically paired, verify with heuristics
            ok, reason = verify_match(en_text, zh_text)
            if ok:
                out['confidence'] = 'static_keep'
                stats['static_keep'] += 1
            else:
                out['zh_text'] = "##M## " + zh_text
                out['confidence'] = f'review_v2_unverified_{reason}'
                stats['unverified_pair'] += 1
        elif en_text and not zh_text:
            # Untranslated English text: translate!
            if en_text in translation_cache:
                out['zh_text'] = translation_cache[en_text]
            else:
                print(f"Translating: '{en_text[:40]}...'", file=sys.stderr)
                raw_translation = google_translate(en_text)
                processed_translation = post_process_translation(raw_translation)
                translation_cache[en_text] = processed_translation
                out['zh_text'] = processed_translation
                
            if out['zh_text']:
                out['confidence'] = 'review_v2_translated'
                stats['translated'] += 1
            else:
                out['confidence'] = 'needs_translation'
                stats['translation_failed'] += 1
        elif not en_text and zh_text:
            out['zh_text'] = "##M## " + zh_text
            out['confidence'] = 'review_v2_unmatched_zh'
            stats['unmatched_zh'] += 1
        else:
            out['confidence'] = 'empty_entry'
            stats['empty'] += 1

        output.append(out)
        index += 1

    # ── Phase 3: Add remaining unmatched review entries ──────────────
    print("Appending unmatched review entries...", file=sys.stderr)
    for rev in unmatched_both:
        zh_text = rev.get('zh_text', '').strip() or rev.get('zh_text_raw', '').strip()
        en_text = rev.get('en_text', '').strip()
        if not zh_text:
            continue
        out = {
            'index': index,
            'npc': rev.get('npc', ''),
            'en_func_id': rev.get('en_func_id', ''),
            'en_offset_key': '',
            'en_segment': 0,
            'en_text': en_text,
            'zh_func_id': rev.get('zh_func_id', ''),
            'zh_offset_key': rev.get('zh_offset_key', ''),
            'zh_segment': rev.get('zh_segment', 0),
            'zh_text': f"##M## {zh_text}",
            'confidence': 'review_v2_unverified_pair',
            'voice_gender': rev.get('voice_gender'),
            'voice_age': rev.get('voice_age'),
            'voice_prompt': rev.get('voice_prompt'),
            'voice_lang': rev.get('voice_lang') or 'en',
            'tone': rev.get('tone') or 'neutral',
            'tone_instruct': rev.get('tone_instruct') or '',
        }
        output.append(out)
        index += 1
        stats['unverified_pair_unmatched'] += 1

    for rev in unmatched_zhonly:
        zh_text = rev.get('zh_text', '').strip() or rev.get('zh_text_raw', '').strip()
        if not zh_text:
            continue
        out = {
            'index': index,
            'npc': rev.get('npc', ''),
            'en_func_id': rev.get('en_func_id', ''),
            'en_offset_key': '',
            'en_segment': 0,
            'en_text': '',
            'zh_func_id': rev.get('zh_func_id', ''),
            'zh_offset_key': rev.get('zh_offset_key', ''),
            'zh_segment': rev.get('zh_segment', 0),
            'zh_text': f"##M## {zh_text}",
            'confidence': 'review_v2_unmatched_zh',
            'voice_gender': rev.get('voice_gender'),
            'voice_age': rev.get('voice_age'),
            'voice_prompt': rev.get('voice_prompt'),
            'voice_lang': rev.get('voice_lang') or 'en',
            'tone': rev.get('tone') or 'neutral',
            'tone_instruct': rev.get('tone_instruct') or '',
        }
        output.append(out)
        index += 1
        stats['unmatched_zh_only'] += 1

    print("\nSummary Statistics:")
    for k, v in stats.items():
        print(f"  {k}: {v}", file=sys.stderr)

    # Write Output JSON
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=1)

    print(f"\nSuccessfully generated {len(output)} entries in {OUTPUT_JSON}", file=sys.stderr)

if __name__ == '__main__':
    main()
