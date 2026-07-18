#!/usr/bin/env python3
"""
Generate bilingual mapping table pairing English ↔ Chinese voice lines.

Strategy:
- Order-based offset-key GROUP pairing (all groups, same structure)
- Within each group, pair segments 1-to-1 by order
- Each group pair gets a similarity score → confidence level
- Functions with matching group counts: all pairs marked 'order_based'
- Functions with mismatched counts: pairs marked with similarity-based confidence
- Unpaired segment extras → 'unpaired_en' / 'unpaired_zh'

Output: bilingual_mapping.csv — one row per segment pair.

Usage:
    python generate_bilingual_mapping.py \
        --en en_voice_lines.csv --zh zh_voice_lines.csv \
        -o bilingual_mapping.csv
"""

import argparse
import csv
import re
import sys
from collections import Counter, OrderedDict


# ── parsing ──────────────────────────────────────────────────────────

def read_csv(path):
    funcs = OrderedDict()
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get('offset_key', '').strip()
            if not key:
                continue
            key = key.replace('0x', '').strip()
            fid = row.get('func_id', '').strip()
            seg_str = row.get('segment', '0').strip()
            seg = int(seg_str) if seg_str else 0
            text = row.get('text', '')
            npc = row.get('npc', '') or row.get('speaker', '') or ''
            caller_guess = row.get('caller_guess', '') or ''

            if fid not in funcs:
                funcs[fid] = []
            groups = funcs[fid]
            grp = next((g for g in groups if g['offset_key'] == key), None)
            if grp is None:
                grp = {'offset_key': key, 'segs': [], 'texts': [],
                       'npc': npc, 'caller_guess': caller_guess, 'has_var': False}
                groups.append(grp)
            grp['segs'].append(seg)
            grp['texts'].append(text)
            if '<' in text:
                grp['has_var'] = True
    return funcs


# ── group similarity ─────────────────────────────────────────────────

_LATIN_RE = re.compile(r"[A-Za-z']+")

def group_similarity(en_grp, zh_grp):
    en_text = ' '.join(en_grp['texts'])
    zh_text = ' '.join(zh_grp['texts'])
    if not en_text or not zh_text:
        return 0.0

    en_len = len(en_text)
    zh_len = len(zh_text)
    expected_zh = en_len / 2.8
    len_score = 1.0 - min(abs(expected_zh - zh_len) / max(expected_zh, zh_len, 1), 1.0)

    en_words = {w for w in _LATIN_RE.findall(en_text) if len(w) > 1}
    zh_words = {w for w in _LATIN_RE.findall(zh_text) if len(w) > 1}
    shared = en_words & zh_words
    union = en_words | zh_words
    latin_score = len(shared) / max(len(union), 1) if union else 0.0

    en_var = '<' in en_text
    zh_var = '<' in zh_text
    var_score = 1.0 if en_var == zh_var else 0.0

    en_q = en_text.strip().startswith(('"', '\u201c'))
    zh_q = any(zh_text.strip().startswith(q)
               for q in ('"', '\u201c', '\u300c', '\u300e', '\u300a'))
    quote_score = 1.0 if en_q == zh_q else 0.0

    return len_score * 0.20 + latin_score * 0.45 + var_score * 0.20 + quote_score * 0.15


# ── main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Generate bilingual EN-ZH mapping')
    parser.add_argument('--en', required=True, help='English CSV')
    parser.add_argument('--zh', required=True, help='Chinese CSV')
    parser.add_argument('-o', '--output', required=True, help='Output CSV')
    args = parser.parse_args()

    en_funcs = read_csv(args.en)
    zh_funcs = read_csv(args.zh)

    common = sorted(set(en_funcs.keys()) & set(zh_funcs.keys()))
    print(f"Common functions: {len(common)}", file=sys.stderr)

    all_rows = []
    same_count = 0
    diff_count = 0

    for fid in common:
        en_grps = en_funcs[fid]
        zh_grps = zh_funcs[fid]
        npc = en_grps[0]['npc'] or en_grps[0].get('caller_guess', '') or ''
        if not npc:
            for grp in en_grps[1:] + (zh_grps if zh_grps else []):
                val = grp.get('npc', '') or grp.get('caller_guess', '') or ''
                if val:
                    npc = val
                    break

        counts_match = (len(en_grps) == len(zh_grps))
        same_count += counts_match
        diff_count += not counts_match

        paired_count = min(len(en_grps), len(zh_grps))

        for i in range(paired_count):
            eg = en_grps[i]
            zg = zh_grps[i]
            sim = group_similarity(eg, zg) if not counts_match else 1.0

            if not counts_match:
                if sim > 0.40:
                    conf = 'high'
                elif sim > 0.12:
                    conf = 'medium'
                else:
                    conf = 'low'
            else:
                conf = 'order_based'

            seg_count = min(len(eg['segs']), len(zg['segs']))
            for j in range(seg_count):
                all_rows.append({
                    'func_id': fid, 'npc': npc,
                    'en_offset_key': eg['offset_key'],
                    'en_segment': eg['segs'][j] if j < len(eg['segs']) else 0,
                    'en_text': eg['texts'][j] if j < len(eg['texts']) else '',
                    'zh_offset_key': zg['offset_key'],
                    'zh_segment': zg['segs'][j] if j < len(zg['segs']) else 0,
                    'zh_text': zg['texts'][j] if j < len(zg['texts']) else '',
                    'confidence': conf,
                })
            for j in range(seg_count, len(eg['segs'])):
                all_rows.append({
                    'func_id': fid, 'npc': npc,
                    'en_offset_key': eg['offset_key'], 'en_segment': eg['segs'][j],
                    'en_text': eg['texts'][j] if j < len(eg['texts']) else '',
                    'zh_offset_key': '', 'zh_segment': 0, 'zh_text': '',
                    'confidence': 'unpaired_en',
                })
            for j in range(seg_count, len(zg['segs'])):
                all_rows.append({
                    'func_id': fid, 'npc': npc,
                    'en_offset_key': '', 'en_segment': 0, 'en_text': '',
                    'zh_offset_key': zg['offset_key'], 'zh_segment': zg['segs'][j],
                    'zh_text': zg['texts'][j] if j < len(zg['texts']) else '',
                    'confidence': 'unpaired_zh',
                })

        # Extra groups beyond paired_count → unpaired
        for i in range(paired_count, len(en_grps)):
            for j, txt in enumerate(en_grps[i]['texts']):
                all_rows.append({
                    'func_id': fid, 'npc': npc,
                    'en_offset_key': en_grps[i]['offset_key'], 'en_segment': en_grps[i]['segs'][j],
                    'en_text': txt,
                    'zh_offset_key': '', 'zh_segment': 0, 'zh_text': '',
                    'confidence': 'unpaired_en',
                })
        for i in range(paired_count, len(zh_grps)):
            for j, txt in enumerate(zh_grps[i]['texts']):
                all_rows.append({
                    'func_id': fid, 'npc': npc,
                    'en_offset_key': '', 'en_segment': 0, 'en_text': '',
                    'zh_offset_key': zh_grps[i]['offset_key'], 'zh_segment': zh_grps[i]['segs'][j],
                    'zh_text': txt,
                    'confidence': 'unpaired_zh',
                })

    # write output
    fieldnames = [
        'func_id', 'npc',
        'en_offset_key', 'en_segment', 'en_text',
        'zh_offset_key', 'zh_segment', 'zh_text',
        'confidence',
    ]
    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    confs = Counter(r['confidence'] for r in all_rows)
    print(f"Total entries: {len(all_rows)}", file=sys.stderr)
    print(f"Functions: {same_count} same count, {diff_count} diff count", file=sys.stderr)
    print(f"Confidence: {dict(confs)}", file=sys.stderr)
    print(f"Written to {args.output}", file=sys.stderr)


if __name__ == '__main__':
    main()
