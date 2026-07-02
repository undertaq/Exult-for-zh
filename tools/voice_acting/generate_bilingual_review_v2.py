#!/usr/bin/env python3
"""
Rebuild bilingual_mapping_review_v2.json:

Key insight: the static CSV concatenates consecutive ADDSI ops into combined keys
(e.g., "113_15d_22e") with combined EN+ZH text. The review JSON stores individual
offsets separately. We match review entries to static entries by checking if the
review EN text is a SUBSTRING of the static EN text.

For combined-key static entries matched by multiple review entries, we concatenate
the review ZH texts in order to produce the full translation.

Output format follows bilingual_mapping_review.json structure.
"""

import csv
import json
import re
import sys
from collections import defaultdict

STATIC_CSV = r"D:\Project\Exult-for-zh\tools\voice_acting\bilingual_mapping_static.csv"
REVIEW_JSON = r"D:\Project\Exult-for-zh\tools\voice_acting\bilingual_mapping_review.json"
OUTPUT = r"D:\Project\Exult-for-zh\tools\voice_acting\bilingual_mapping_review_v2.json"


def norm(t):
    if not t:
        return ""
    t = re.sub(r'["""\u201c\u201d\u201e\u201f]', '', t)
    t = re.sub(r'\s+', ' ', t).strip().lower()
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
                '_match_review': [],    # list of matched review zh_texts in order
                '_matched_exact': False,
            }
            rows.append(entry)
            keyed[(fid, en_key, en_seg)] = entry
    return rows, keyed


def load_review_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def make_clean(text):
    """Normalize for substring matching: strip quotes and variables."""
    if not text:
        return ""
    t = norm(text)
    t = re.sub(r'<[^>]+>', '', t)
    t = re.sub(r'[^a-z0-9\s]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


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
            # Merge confidence info
            for existing in deduped:
                ek = (existing['func_id'], existing['en_offset_key'], existing['en_segment'])
                if ek == k:
                    # Prefer matched_ over static_ confidence
                    if 'matched' in entry['confidence'] and 'static' in existing['confidence']:
                        existing['confidence'] = entry['confidence']
                    break
    static_rows = deduped
    print(f"  {len(static_rows)} after dedup", file=sys.stderr)

    # Build index of static rows by cleaned text for fast substring lookup
    static_by_fid = defaultdict(list)
    for entry in static_rows:
        static_by_fid[entry['func_id']].append(entry)

    # Also build a full-text index for content matching
    static_all = []
    for entry in static_rows:
        clean = make_clean(entry['en_text'])
        if clean:
            static_all.append((clean, entry))

    print("Loading review JSON...", file=sys.stderr)
    review_entries = load_review_json(REVIEW_JSON)
    print(f"  {len(review_entries)} entries", file=sys.stderr)

    # ── Phase 1: Match review entries to static entries ────────────────
    matched_count = 0
    exact_count = 0
    substring_count = 0
    jaccard_count = 0
    unmatched_both = []   # has en+zh but no match
    unmatched_zhonly = [] # has zh only

    for rev in review_entries:
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
                # Try within same func_id first
                if en_func in static_by_fid:
                    for s_entry in static_by_fid[en_func]:
                        s_clean = make_clean(s_entry['en_text'])
                        if rev_clean in s_clean:
                            matched_static = s_entry
                            match_type = 'substr'
                            break

                # Try all entries if not found in same func
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
                for s_clean, s_entry in static_all:
                    s_words = set(s_clean.split())
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
            # Store match with position in combined text for ordering
            pos = matched_static['en_text'].lower().find(en_text.lower())
            matched_static['_match_review'].append({
                'zh_text': zh_text,
                '_en_text': en_text,
                'offset_key': en_key,
                'match_type': match_type,
                'pos': pos if pos >= 0 else 999999,
            })
            matched_count += 1
            if match_type == 'exact':
                exact_count += 1
            elif match_type and match_type.startswith('substr'):
                substring_count += 1
            else:
                jaccard_count += 1
        else:
            unmatched_both.append(rev)

    print(f"  Total matched: {matched_count}", file=sys.stderr)
    print(f"    Exact:    {exact_count}", file=sys.stderr)
    print(f"    Substr:   {substring_count}", file=sys.stderr)
    print(f"    Jaccard:  {jaccard_count}", file=sys.stderr)
    print(f"  Unmatched en+zh: {len(unmatched_both)}", file=sys.stderr)
    print(f"  Unmatched zh-only: {len(unmatched_zhonly)}", file=sys.stderr)

    # ── Phase 2: Build output ─────────────────────────────────────────
    output = []
    index = 0
    stat_matched_exact = 0
    stat_matched_substr = 0
    stat_matched_jaccard = 0
    stat_static_keep = 0
    stat_needs_xlat = 0
    stat_unpaired_zh = 0

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
        }

        if matches:
            matches_sorted = sorted(matches, key=lambda m: m['pos'])

            en_clean = make_clean(en_text)
            if en_clean:
                coverage = [False] * len(en_clean)
                for m in matches:
                    r_clean = make_clean(m.get('_en_text', ''))
                    if r_clean:
                        idx = en_clean.find(r_clean)
                        if idx >= 0:
                            for k in range(idx, min(idx + len(r_clean), len(coverage))):
                                coverage[k] = True
                covered_ratio = sum(coverage) / len(coverage) if coverage else 0
            else:
                covered_ratio = 1.0

            if covered_ratio >= 0.85:
                if len(matches_sorted) == 1:
                    out['zh_text'] = matches_sorted[0]['zh_text']
                else:
                    out['zh_text'] = ''.join(m['zh_text'] for m in matches_sorted)
                match_types = [m['match_type'] for m in matches_sorted]
                if any(t == 'exact' for t in match_types):
                    out['confidence'] = 'review_v2_matched_exact'
                elif any(t and t.startswith('substr') for t in match_types):
                    out['confidence'] = 'review_v2_matched_substr'
                else:
                    out['confidence'] = 'review_v2_matched_jaccard'
            else:
                out['zh_text'] = zh_text
                out['confidence'] = 'review_v2_partial'

            # Count statistics per actual confidence
            if out['confidence'] == 'review_v2_matched_exact':
                stat_matched_exact += 1
            elif out['confidence'] == 'review_v2_matched_substr':
                stat_matched_substr += 1
            elif out['confidence'] == 'review_v2_matched_jaccard':
                stat_matched_jaccard += 1
        elif en_text and zh_text:
            out['confidence'] = 'static_keep'
            stat_static_keep += 1
        elif en_text and not zh_text:
            out['confidence'] = 'needs_translation'
            stat_needs_xlat += 1
        elif not en_text and zh_text:
            out['confidence'] = 'unpaired_zh_v2'
            stat_unpaired_zh += 1
        else:
            out['confidence'] = 'empty_entry'

        output.append(out)
        index += 1

    # Phase 3: Add unmatched review entries
    for rev in unmatched_both:
        zh_text = rev.get('zh_text', '').strip() or rev.get('zh_text_raw', '').strip()
        en_text = rev.get('en_text', '').strip()
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
            'zh_text': f"##M## {zh_text}" if zh_text else '##M##',
            'confidence': 'review_v2_unverified_pair',
        }
        output.append(out)
        index += 1

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
        }
        output.append(out)
        index += 1

    # Summary
    total_matched = stat_matched_exact + stat_matched_substr + stat_matched_jaccard
    print(f"\nSummary:", file=sys.stderr)
    print(f"  total entries:       {len(output)}", file=sys.stderr)
    print(f"  review_v2_matched:   {total_matched}", file=sys.stderr)
    print(f"    exact:     {stat_matched_exact}", file=sys.stderr)
    print(f"    substring: {stat_matched_substr}", file=sys.stderr)
    print(f"    jaccard:   {stat_matched_jaccard}", file=sys.stderr)
    print(f"  static_keep:         {stat_static_keep}", file=sys.stderr)
    print(f"  needs_translation:   {stat_needs_xlat}", file=sys.stderr)
    print(f"  unpaired_zh_v2:      {stat_unpaired_zh}", file=sys.stderr)
    print(f"  ##M## unverified:    {len(unmatched_both)}", file=sys.stderr)
    print(f"  ##M## zh-only:       {len(unmatched_zhonly)}", file=sys.stderr)

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=1)

    print(f"\nWritten to {OUTPUT}", file=sys.stderr)


if __name__ == '__main__':
    main()
