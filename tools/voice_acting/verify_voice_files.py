#!/usr/bin/env python3
"""
Verify that all voice files in a manifest are present on disk and have
up-to-date embedded metadata.

Reports per-file status (missing / stale_voice / stale_text / fresh /
no_metadata) and, optionally, any files in the directory that are not
referenced by the manifest (orphans from prior generations).

Usage (single directory):
    python verify_voice_files.py \\
        --manifest csvs/manifest.csv \\
        --source "C:/.../Ultima 7/patch/voice_acting"

Usage (multiple directories with fallback, matching the runtime lookup):
    python verify_voice_files.py \\
        --manifest csvs/manifest.csv \\
        --source "C:/.../Ultima 7/patch/voice_acting" \\
        --source "C:/.../Ultima 7/patch/voice_acting/second_source"

When more than one --source is given, each manifest row is checked against
each directory in order and the first match wins. This matches the engine's
fallback behavior, so you can verify that the union of primary + secondary
covers the manifest.
"""

import argparse
import csv
import os
import sys
from collections import Counter

from generate_voices import existing_file_state, normalize_output_filename


def main():
    parser = argparse.ArgumentParser(
        description="Verify voice files against a manifest")
    parser.add_argument("--manifest", "-m", required=True,
                        help="Path to manifest CSV")
    parser.add_argument("--source", "-s", required=True, action="append",
                        help="Directory containing WAV files to verify. "
                             "May be passed multiple times; directories are "
                             "searched in order, mirroring the engine's "
                             "primary + secondary source fallback.")
    parser.add_argument("--show", choices=["missing", "stale", "all"],
                        default="missing",
                        help='Which problem files to list '
                             '(default "missing"; "stale" adds voice/text '
                             'mismatches; "all" lists every row)')
    parser.add_argument("--orphans", action="store_true",
                        help="Also list files in the source dir that are not "
                             "in the manifest")
    parser.add_argument("--output", "-o", default=None,
                        help="Optional CSV output with the full per-file table")
    args = parser.parse_args()

    for d in args.source:
        if not os.path.isdir(d):
            print(f"error: source dir not found: {d}", file=sys.stderr)
            return 1

    with open(args.manifest, newline="", encoding="utf-8") as f:
        manifest = list(csv.DictReader(f))

    counts = Counter()
    per_dir_hits = Counter()
    rows = []                 # (state, resolved_dir_or_None, item)
    missing_rows = []
    stale_rows = []
    referenced = set()
    for item in manifest:
        filename = normalize_output_filename(item["filename"])
        referenced.add(filename)
        # Walk the source list, first non-missing wins.
        resolved_state = "missing"
        resolved_dir = None
        for d in args.source:
            state = existing_file_state(
                os.path.join(d, filename),
                item["voice_id"], item["text"])
            if state != "missing":
                resolved_state = state
                resolved_dir = d
                break
        counts[resolved_state] += 1
        if resolved_dir is not None:
            per_dir_hits[resolved_dir] += 1
        rows.append((resolved_state, resolved_dir, item))
        if resolved_state == "missing":
            missing_rows.append(item)
        elif resolved_state in ("stale_voice", "stale_text"):
            stale_rows.append((resolved_state, item))

    total = len(manifest)
    fresh = counts["fresh"] + counts["no_metadata"]
    print(f"Manifest: {total} rows")
    print(f"Sources:")
    for d in args.source:
        print(f"  {d}")
    print()
    print(f"  fresh        : {counts['fresh']}")
    if counts["no_metadata"]:
        print(f"  no_metadata  : {counts['no_metadata']}  "
              f"(file exists but has no LIST-INFO chunk)")
    print(f"  stale_voice  : {counts['stale_voice']}")
    print(f"  stale_text   : {counts['stale_text']}")
    print(f"  missing      : {counts['missing']}")
    print()
    coverage = 100.0 * fresh / total if total else 0
    print(f"  coverage     : {fresh}/{total} ({coverage:.1f}%)")
    if len(args.source) > 1:
        print()
        print("  Resolved from:")
        for d in args.source:
            print(f"    {per_dir_hits[d]:6d}  {d}")

    if args.show in ("missing", "stale", "all"):
        if missing_rows and args.show != "all":
            print(f"\n--- missing ({len(missing_rows)}) ---")
            for it in missing_rows[:50]:
                print(f"  {it['filename']:<40} "
                      f"{it.get('speaker','?'):<15} "
                      f"{it['text'][:60]}")
            if len(missing_rows) > 50:
                print(f"  ...and {len(missing_rows) - 50} more")
    if args.show in ("stale", "all"):
        if stale_rows:
            print(f"\n--- stale ({len(stale_rows)}) ---")
            for state, it in stale_rows[:50]:
                tag = "voice" if state == "stale_voice" else "text"
                print(f"  [{tag}] {it['filename']:<40} "
                      f"{it.get('speaker','?'):<15} "
                      f"{it['text'][:50]}")
            if len(stale_rows) > 50:
                print(f"  ...and {len(stale_rows) - 50} more")
    if args.show == "all":
        print(f"\n--- all rows ---")
        for state, d, it in rows[:200]:
            src_tag = "-" if d is None else os.path.basename(os.path.normpath(d))
            print(f"  {state:<12} {src_tag:<15} {it['filename']:<40} "
                  f"{it.get('speaker','?')}")
        if len(rows) > 200:
            print(f"  ...and {len(rows) - 200} more")

    if args.orphans:
        for d in args.source:
            on_disk = {f for f in os.listdir(d)
                       if f.lower().endswith(".ogg")}
            orphans = sorted(on_disk - referenced)
            print(f"\n--- orphans in {d} ({len(orphans)}) ---")
            print("(files in this dir not referenced by manifest)")
            for fn in orphans[:100]:
                print(f"  {fn}")
            if len(orphans) > 100:
                print(f"  ...and {len(orphans) - 100} more")

    if args.output:
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["status", "resolved_from", "filename", "speaker",
                        "voice_id", "voice_desc", "text"])
            for state, d, it in rows:
                w.writerow([state, d or "", it["filename"],
                            it.get("speaker", ""), it["voice_id"],
                            it.get("voice_desc", ""), it["text"]])
        print(f"\nWrote per-file table: {args.output}")

    # Exit non-zero if anything isn't fresh - useful for scripting.
    problems = counts["missing"] + counts["stale_voice"] + counts["stale_text"]
    return 0 if problems == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
