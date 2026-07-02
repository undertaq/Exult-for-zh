#!/usr/bin/env python3
"""
Generate bilingual mapping binary data file (.dat) for Exult's Chinese text overlay.

Reads bilingual_mapping.csv and bilingual_mapping_review.json, outputs a BLMP-format
binary file that BilingualMapping::load() reads.

Usage:
    python generate_bilingual_mapping_data.py \
        --csv tools/voice_acting/bilingual_mapping.csv \
        --json tools/voice_acting/bilingual_mapping_review.json \
        --output patch/voice_acting/bilingual_map.dat

If --json is omitted, only --csv is used.
If --csv is omitted, only --json is used (for testing with small data).
"""

import argparse
import csv
import json
import os
import struct
import sys


def load_csv(path):
    """Load bilingual mapping CSV, return dict keyed by (func_id, en_offset_key, en_segment)."""
    mapping = {}
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            zh_text = row.get('zh_text', '').strip()
            if not zh_text:
                continue

            # Normalize func_id: strip 0x prefix, parse as int
            func_id_str = row.get('func_id', '').strip().lower().replace('0x', '')
            try:
                func_id = int(func_id_str, 16) if func_id_str else 0
            except ValueError:
                continue

            en_offset_key = row.get('en_offset_key', '').strip()
            if not en_offset_key:
                continue

            try:
                en_segment = int(row.get('en_segment', '0').strip())
            except ValueError:
                en_segment = 0

            key = (func_id, en_offset_key, en_segment)
            mapping[key] = zh_text
    return mapping


def load_json(path):
    """Load bilingual mapping review JSON, return dict keyed by (en_func_id, en_offset_key, en_segment)."""
    mapping = {}
    with open(path, 'r', encoding='utf-8') as f:
        entries = json.load(f)

    for entry in entries:
        # Use English func_id and offset_key as the key
        func_id_str = entry.get('en_func_id', '').strip().lower().replace('0x', '')
        try:
            func_id = int(func_id_str, 16) if func_id_str else 0
        except ValueError:
            continue

        en_offset_key = entry.get('en_offset_key', '').strip()
        if not en_offset_key:
            continue

        en_segment = entry.get('en_segment', 0)

        zh_text = entry.get('zh_text', '').strip()
        if not zh_text:
            # Try zh_text_raw if available
            zh_text = entry.get('zh_text_raw', '').strip()

        if not zh_text:
            continue

        key = (func_id, en_offset_key, en_segment)
        mapping[key] = zh_text
    return mapping


def write_binary(mapping, output_path):
    """Write mapping as BLMP binary file."""
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # Sort entries for deterministic output
    sorted_keys = sorted(mapping.keys(), key=lambda k: (k[0], k[1], k[2]))

    with open(output_path, 'wb') as f:
        # Header
        f.write(b'BLMP')                          # magic
        f.write(struct.pack('<H', 1))              # version
        f.write(struct.pack('<I', len(sorted_keys)))  # num_entries

        for func_id, offset_key, segment in sorted_keys:
            text = mapping[(func_id, offset_key, segment)]
            text_bytes = text.encode('utf-8')
            offset_key_bytes = offset_key.encode('ascii')

            f.write(struct.pack('<H', func_id & 0xFFFF))
            f.write(struct.pack('<H', len(offset_key_bytes)))
            f.write(offset_key_bytes)
            f.write(struct.pack('<H', segment & 0xFFFF))
            f.write(struct.pack('<I', len(text_bytes)))
            f.write(text_bytes)

    print(f"Written {len(sorted_keys)} entries to {output_path}", file=sys.stderr)
    total_bytes = os.path.getsize(output_path)
    print(f"File size: {total_bytes} bytes ({total_bytes / 1024:.1f} KB)", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='Generate bilingual mapping binary data file')
    parser.add_argument('--csv', action='append', dest='csv_files',
                        help='Path(s) to bilingual_mapping CSV (can be specified multiple times)')
    parser.add_argument('--json', help='Path to bilingual_mapping_review.json')
    parser.add_argument('--output', required=True, help='Output .dat file path')
    args = parser.parse_args()

    # Load from CSV files first (lowest priority, won't overwrite JSON)
    mapping = {}
    csv_loaded = 0
    if args.csv_files:
        for csv_path in args.csv_files:
            csv_mapping = load_csv(csv_path)
            csv_loaded += len(csv_mapping)
            for key, value in csv_mapping.items():
                if key not in mapping:
                    mapping[key] = value
            print(f"Loaded {len(csv_mapping)} entries from {csv_path}", file=sys.stderr)
        print(f"Total CSV entries loaded: {csv_loaded}", file=sys.stderr)

    # Load from JSON (hand-validated, higher priority — overwrites CSV)
    if args.json:
        before = len(mapping)
        mapping.update(load_json(args.json))
        print(f"Loaded {len(mapping) - before} net new entries from JSON", file=sys.stderr)

    if not mapping:
        print("Error: no entries found", file=sys.stderr)
        sys.exit(1)

    if not mapping:
        print("Error: no entries found", file=sys.stderr)
        sys.exit(1)

    write_binary(mapping, args.output)


if __name__ == '__main__':
    main()
