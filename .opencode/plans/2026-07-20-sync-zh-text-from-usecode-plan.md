# Sync Chinese Text from Updated usecode.zh — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a reusable Python script that extracts Chinese text from the live `usecode.zh` binary and syncs it into `bilingual_mapping_review.json`.

**Architecture:** A single focused Python script that imports existing disassembler functions from `disassemble_usecode.py`. It parses the usecode binary, builds a ground-truth text map keyed by `(func_id, offset_key, segment)`, compares against the JSON mapping, reports diffs, and optionally applies them.

**Tech Stack:** Python 3, struct module for binary parsing, json for mapping I/O.

---

### Task 1: Create the sync script

**Files:**
- Create: `tools/voice_acting/sync_zh_text_from_usecode.py`
- Import from: `tools/voice_acting/disassemble_usecode.py` (existing)

- [ ] **Step 1: Script scaffold and argument parsing**

Create the script with argument parsing. It reads the usecode binary, the mapping JSON, and supports `--apply` and `--dry-run` flags.

```python
#!/usr/bin/env python3
"""Extract Chinese text from updated usecode.zh and sync into bilingual_mapping_review.json."""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_USECODE_ZH = SCRIPT_DIR / ".." / ".." / "Ultima_7" / "patch" / "usecode.zh"
DEFAULT_MAPPING = SCRIPT_DIR / "bilingual_mapping_review.json"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usecode-zh", type=Path, default=DEFAULT_USECODE_ZH,
                        help="Path to the compiled ZH usecode patch binary")
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING,
                        help="Path to bilingual_mapping_review.json")
    parser.add_argument("--apply", action="store_true",
                        help="Update zh_text in the mapping JSON to match extracted text")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if not args.usecode_zh.exists():
        print(f"Error: usecode.zh not found at {args.usecode_zh}", file=sys.stderr)
        return 1
    if not args.mapping.exists():
        print(f"Error: mapping not found at {args.mapping}", file=sys.stderr)
        return 1

    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    print(f"Loaded mapping: {len(mapping)} entries")
    print(f"usecode.zh: {args.usecode_zh}")
    print(f"Mode: {'APPLY (will write)' if args.apply else 'DRY-RUN (report only)'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Add text extraction from usecode.zh binary**

Import from `disassemble_usecode.py` to parse the binary and extract say-lines. Build a ground-truth map keyed by `(func_id, offset_key, segment)`.

Add to script:

```python
import struct
sys.path.insert(0, str(SCRIPT_DIR))
from disassemble_usecode import (
    parse_function, disassemble_function, extract_say_lines,
    read2, read4, read4s,
)


def skip_symbol_table(data, offset):
    """Skip Exult symbol table (magic FFFFFFFF YSCU) if present."""
    if offset + 8 > len(data):
        return offset
    magic0 = read4(data, offset)
    magic1 = read4(data, offset + 4)
    if magic0 != 0xFFFFFFFF or magic1 != 0x55435359:
        return offset

    def skip_scope(pos):
        cnt = read4(data, pos)
        pos += 8  # cnt + version
        for _ in range(cnt):
            while pos < len(data) and data[pos] != 0:
                pos += 1
            pos += 1
            kind = read2(data, pos)
            pos += 2
            pos += 4  # value
            if kind == 2:
                pos = skip_scope(pos)
                nm = read2(data, pos)
                pos += 2
                pos += 2 * nm + 2
            elif kind in (3, 6, 7):
                pos += 4
        return pos

    return skip_scope(offset + 8)


def extract_from_usecode(path):
    """Parse usecode binary and return list of say-line dicts.

    Each dict: {func_id, offset_key, segment, total_segments, text, ...}
    """
    data = path.read_bytes()

    offset = skip_symbol_table(data, 0)
    functions = {}

    while offset < len(data):
        try:
            func_id, func_data, extended, next_offset = parse_function(data, offset)
            functions[func_id] = (func_data, extended)
            offset = next_offset
        except (struct.error, IndexError):
            break

    print(f"  Parsed {len(functions)} functions", file=sys.stderr)

    lines = []
    for fid in sorted(functions.keys()):
        fdata, extended = functions[fid]
        try:
            func = disassemble_function(fid, fdata, extended)
            say_lines = extract_say_lines(func)
            lines.extend(say_lines)
        except (struct.error, IndexError, ValueError) as e:
            print(f"  Warning: skipping func 0x{fid:04X}: {e}", file=sys.stderr)

    print(f"  Extracted {len(lines)} say-lines", file=sys.stderr)
    return lines
```

- [ ] **Step 3: Add encoding fix for Chinese text**

The disassembler's `extract_data_segment()` uses `.decode("latin-1")`, but Chinese text in the binary is UTF-8 encoded. A `fix_encoding()` step converts: `s.encode("latin-1").decode("utf-8")` — the same pattern used in `generate_voice_files.py`.

Add to the script:

```python
def fix_encoding(s):
    """Fix latin-1-decoded string back to proper UTF-8."""
    if not s:
        return s
    return s.encode("latin-1").decode("utf-8")
```

- [ ] **Step 4: Build comparison logic and produce diff report**

Add the comparison function and wire it into main:

```python
def build_ground_truth(lines):
    """Build (func_id, offset_key, segment) → text map from extracted lines."""
    gt = {}
    for line in lines:
        key = (line['func_id'], line['offset_key'], line['segment'])
        if key not in gt:
            gt[key] = fix_encoding(line['text'])
    return gt


def compare_mapping(mapping, ground_truth):
    """Compare mapping entries against ground truth. Returns diff records."""
    diffs = []
    matching = 0
    missing_in_binary = 0

    for entry in mapping:
        try:
            func_id_str = entry.get('zh_func_id', '')
            if func_id_str.startswith('0x'):
                func_id = int(func_id_str, 16)
            else:
                func_id = int(func_id_str, 0) if func_id_str else None

            offset_key = entry.get('zh_offset_key', '')
            segment_raw = entry.get('zh_segment')
            segment = int(segment_raw) if segment_raw is not None else None

            if func_id is None or not offset_key or segment is None:
                continue

            key = (func_id, offset_key, segment)
            old_text = entry.get('zh_text', '')

            if key not in ground_truth:
                missing_in_binary += 1
                continue

            new_text = ground_truth[key]
            if old_text != new_text:
                diffs.append({
                    'key': f"0x{func_id:04X}_{offset_key}_{segment}",
                    'npc': entry.get('npc', ''),
                    'old_text': old_text,
                    'new_text': new_text,
                })
            else:
                matching += 1

        except (ValueError, TypeError):
            continue

    return diffs, matching, missing_in_binary


def print_diff_report(diffs, matching, missing_in_binary):
    """Print diff report to stdout."""
    print(f"\n{'='*60}")
    print(f"Matching (unchanged): {matching}")
    print(f"Differences found:    {len(diffs)}")
    print(f"Missing in binary:    {missing_in_binary}")
    print(f"{'='*60}\n")

    for d in diffs:
        print(f"\n--- {d['key']}  (NPC: {d['npc']})")
        print(f"- {d['old_text']}")
        print(f"+ {d['new_text']}")


def apply_diffs(mapping, diffs, ground_truth):
    """Update zh_text in mapping entries that have diffs."""
    updated = 0
    for entry in mapping:
        try:
            func_id_str = entry.get('zh_func_id', '')
            if func_id_str.startswith('0x'):
                func_id = int(func_id_str, 16)
            else:
                func_id = int(func_id_str, 0) if func_id_str else None

            offset_key = entry.get('zh_offset_key', '')
            segment_raw = entry.get('zh_segment')
            segment = int(segment_raw) if segment_raw is not None else None

            if func_id is None or not offset_key or segment is None:
                continue

            key = (func_id, offset_key, segment)
            if key in ground_truth:
                new_text = ground_truth[key]
                if entry.get('zh_text', '') != new_text:
                    entry['zh_text'] = new_text
                    updated += 1
        except (ValueError, TypeError):
            continue
    return updated
```

- [ ] **Step 5: Wire main() with comparison pipeline**

Update `main()` to use the comparison pipeline. Note: the `--apply` flag controls whether writes happen; without it, the script runs in dry-run (report-only) mode.

```python
def main(argv=None):
    args = parse_args(argv)

    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    print(f"Loaded mapping: {len(mapping)} entries")
    print(f"usecode.zh: {args.usecode_zh}")
    print(f"Mode: {'APPLY (will write)' if args.apply else 'DRY-RUN (report only)'}")

    lines = extract_from_usecode(args.usecode_zh)
    ground_truth = build_ground_truth(lines)
    print(f"Ground truth map: {len(ground_truth)} unique keys")

    diffs, matching, missing_in_binary = compare_mapping(mapping, ground_truth)
    print_diff_report(diffs, matching, missing_in_binary)

    if args.apply and diffs:
        updated = apply_diffs(mapping, diffs, ground_truth)
        args.mapping.write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\nUpdated {updated} entries in {args.mapping}")
    elif args.apply and not diffs:
        print("\nNo differences found. Nothing to update.")

    return 0 if missing_in_binary == 0 else 1
```

- [ ] **Step 6: Run a quick smoke test**

Run without `--apply` (default dry-run mode). Expected: Script parses usecode.zh, loads mapping, reports diff counts and individual changes.

```bash
python tools/voice_acting/sync_zh_text_from_usecode.py
```

If the diff output looks correct, run again with `--apply` to update the JSON:

```bash
python tools/voice_acting/sync_zh_text_from_usecode.py --apply
```

- [ ] **Step 7: Run the existing tests to verify no regressions**

Run: `python -m pytest tools/voice_acting/ -v --timeout=30`
Expected: All pass. The new script is self-contained and shouldn't break existing tests.

- [ ] **Step 8: Commit**

```bash
git add tools/voice_acting/sync_zh_text_from_usecode.py
git commit -m "feat: add script to sync zh_text from updated usecode.zh binary"
```
