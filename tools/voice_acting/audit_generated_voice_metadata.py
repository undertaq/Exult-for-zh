#!/usr/bin/env python3
"""
Audit generated OGG voice files against bilingual_mapping_review.json.

This verifier uses only the source mapping and current OGG metadata. It does
not read voice_acting_log.csv.
"""
import argparse
import csv
import json
import os
import re
import struct
import sys
from collections import Counter, defaultdict

from npc_data import NPC_NUMBERS


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
DEFAULT_MAPPING = os.path.join(SCRIPT_DIR, 'bilingual_mapping_review.json')
DEFAULT_VOICE_ROOT = os.path.join(PROJECT_DIR, 'voice')


def read_ogg_comment(filepath):
    """Read Vorbis comment metadata without spawning ffprobe per file."""
    try:
        with open(filepath, 'rb') as f:
            blob = f.read()
        marker = b'\x03vorbis'
        pos = blob.find(marker)
        if pos < 0:
            return None, 'no_vorbis_comment_packet'
        p = pos + len(marker)
        vendor_len = struct.unpack_from('<I', blob, p)[0]
        p += 4 + vendor_len
        comment_count = struct.unpack_from('<I', blob, p)[0]
        p += 4
        tags = {}
        for _ in range(comment_count):
            comment_len = struct.unpack_from('<I', blob, p)[0]
            p += 4
            raw = blob[p:p + comment_len]
            p += comment_len
            text = raw.decode('utf-8', errors='replace')
            if '=' not in text:
                continue
            key, value = text.split('=', 1)
            tags[key.lower()] = value
        return tags.get('comment') or tags.get('description') or '', ''
    except Exception as ex:
        return None, f'{type(ex).__name__}: {ex}'


def normalized_text(text):
    return re.sub(r'\s+', ' ', (text or '').strip())


def mismatch_class(expected, actual):
    expected_norm = normalized_text(expected)
    actual_norm = normalized_text(actual)
    if expected_norm == actual_norm:
        return 'whitespace_only'
    expected_stripped = expected_norm.strip('"“”「」')
    actual_stripped = actual_norm.strip('"“”「」')
    if expected_stripped in actual_norm or actual_stripped in expected_norm:
        return 'substring_or_punctuation'
    return 'different_text'


def build_base_name(entry, lang):
    fid = (
        entry.get(f'{lang}_func_id', '')
        or entry.get('zh_func_id', '')
        or entry.get('en_func_id', '')
        or '0000'
    )
    offset_key = entry.get(f'{lang}_offset_key', '') or '0'
    segment = entry.get(f'{lang}_segment', 0) or 0
    if isinstance(fid, str) and fid.lower().startswith('0x'):
        fid = fid[2:]
    return f'{str(fid).lower().zfill(4)}_{offset_key}_{segment}'


def expected_filename(entry, lang):
    base = build_base_name(entry, lang)
    npc_num = NPC_NUMBERS.get(entry.get('npc', '') or '')
    if npc_num is not None:
        return f'{base}_npc{npc_num}.ogg'
    return f'{base}.ogg'


def build_expected_rows(mapping, voice_root):
    rows = []
    by_target = defaultdict(list)
    for index, entry in enumerate(mapping):
        if (entry.get('voice_generation') or '') == 'skip':
            continue
        for lang in ('zh', 'en'):
            text = (entry.get(f'{lang}_text') or '').strip()
            if not text:
                continue
            filename = expected_filename(entry, lang)
            path = os.path.join(voice_root, lang, filename)
            row = {
                'mapping_index': index,
                'lang': lang,
                'npc': entry.get('npc', '') or '',
                'filename': filename,
                'path': path,
                'expected_text': text,
            }
            rows.append(row)
            by_target[(lang, filename)].append(row)
    return rows, by_target


def audit(mapping_path, voice_root):
    with open(mapping_path, encoding='utf-8') as f:
        mapping = json.load(f)

    expected_rows, by_target = build_expected_rows(mapping, voice_root)
    comment_cache = {}
    problem_rows = []
    counts = Counter()

    for row in expected_rows:
        target_rows = by_target[(row['lang'], row['filename'])]
        unique_texts = {target['expected_text'] for target in target_rows}
        unique_normalized_texts = {normalized_text(text) for text in unique_texts}
        collision = len(unique_texts) > 1
        path = row['path']

        if not os.path.exists(path):
            status = 'missing'
            actual = ''
            error = ''
            stale_class = ''
        else:
            if path not in comment_cache:
                comment_cache[path] = read_ogg_comment(path)
            actual, error = comment_cache[path]
            stale_class = ''
            if error:
                status = 'probe_error'
            elif normalized_text(actual) == normalized_text(row['expected_text']):
                status = 'fresh_but_collision' if collision else 'fresh'
            elif collision and normalized_text(actual) in unique_normalized_texts:
                status = 'collision_other_text'
            else:
                status = 'stale_text'
                stale_class = mismatch_class(row['expected_text'], actual)

        counts[(row['lang'], status)] += 1
        if status != 'fresh':
            problem_rows.append({
                **row,
                'status': status,
                'actual_comment': actual or '',
                'error': error,
                'collision_count': len(target_rows),
                'collision_unique_texts': len(unique_texts),
                'stale_class': stale_class,
            })

    expected_path_set = {row['path'] for row in expected_rows}
    orphans = []
    for lang in ('zh', 'en'):
        lang_dir = os.path.join(voice_root, lang)
        if not os.path.isdir(lang_dir):
            continue
        for filename in os.listdir(lang_dir):
            if not filename.endswith('.ogg'):
                continue
            path = os.path.join(lang_dir, filename)
            if path not in expected_path_set:
                orphans.append({'lang': lang, 'filename': filename, 'path': path})

    collision_targets = sum(
        1
        for rows in by_target.values()
        if len({row['expected_text'] for row in rows}) > 1
    )
    return {
        'expected_rows': expected_rows,
        'by_target': by_target,
        'comment_cache': comment_cache,
        'problem_rows': problem_rows,
        'counts': counts,
        'orphans': orphans,
        'collision_targets': collision_targets,
    }


def write_csv(path, problem_rows):
    fields = [
        'status',
        'stale_class',
        'lang',
        'mapping_index',
        'npc',
        'filename',
        'path',
        'collision_count',
        'collision_unique_texts',
        'expected_text',
        'actual_comment',
        'error',
    ]
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in problem_rows:
            writer.writerow({field: row.get(field, '') for field in fields})


def format_summary(result):
    expected_rows = result['expected_rows']
    counts = result['counts']
    problem_rows = result['problem_rows']
    stale_classes = Counter(
        row['stale_class'] for row in problem_rows if row['status'] == 'stale_text'
    )

    lines = [
        f"expected dialogue rows: {len(expected_rows)}",
        f"unique expected target files: {len(result['by_target'])}",
        f"existing expected target files parsed: {len(result['comment_cache'])}",
        f"collision target files: {result['collision_targets']}",
        f"problem rows: {len(problem_rows)}",
        f"orphans: {len(result['orphans'])}",
        '',
    ]
    for lang in ('zh', 'en'):
        lines.append(f'[{lang}]')
        lines.append(f"  expected rows: {sum(1 for row in expected_rows if row['lang'] == lang)}")
        for status in sorted(status for (status_lang, status) in counts if status_lang == lang):
            lines.append(f"  {status}: {counts[(lang, status)]}")
    lines.append('')
    lines.append('stale_text classes:')
    for name, count in sorted(stale_classes.items()):
        lines.append(f'  {name}: {count}')
    lines.append('')
    lines.append('problem samples:')
    for row in problem_rows[:50]:
        lines.append(
            f"  {row['status']} {row['lang']} {row['filename']} "
            f"idx={row['mapping_index']} npc={row['npc']} "
            f"expected={row['expected_text'][:80]!r} "
            f"actual={row['actual_comment'][:80]!r}"
        )
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='Audit generated voice OGG metadata against the mapping JSON.'
    )
    parser.add_argument('--mapping', default=DEFAULT_MAPPING)
    parser.add_argument('--voice-root', default=DEFAULT_VOICE_ROOT)
    parser.add_argument('--output', default='/tmp/voice_metadata_audit.csv')
    parser.add_argument('--summary-output', default='/tmp/voice_metadata_audit_summary.txt')
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Exit non-zero when real stale/collision/probe problems are found.',
    )
    args = parser.parse_args()

    result = audit(args.mapping, args.voice_root)
    write_csv(args.output, result['problem_rows'])
    summary = format_summary(result)
    with open(args.summary_output, 'w', encoding='utf-8') as f:
        f.write(summary + '\n')
    print(summary)
    print(f'\nCSV: {args.output}')
    print(f'Summary: {args.summary_output}')

    if args.strict:
        serious = [
            row for row in result['problem_rows']
            if row['status'] in ('probe_error', 'collision_other_text')
            or (row['status'] == 'stale_text' and row['stale_class'] == 'different_text')
        ]
        return 1 if serious else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
