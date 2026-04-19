#!/usr/bin/env python3
"""
Back up stale WAV files before regenerating them.

Scans the manifest, identifies WAV files whose embedded metadata no longer
matches the current voice_id or text, and moves them into a backup directory.
This preserves any files generate_voices.py would otherwise overwrite.

Usage:
    python backup_stale_voices.py \\
        --manifest csvs/manifest.csv \\
        --source "C:/.../Ultima 7/patch/voice_acting" \\
        --dest "C:/.../Ultima 7/patch/voice_acting/backup2"

Behavior:
- Detects "stale_voice" and "stale_text" files using the same check as
  generate_voices.py (shared via existing_file_state).
- Moves each stale file from <source>/<filename> to <dest>/<filename>.
- Does not overwrite existing files in <dest> - prints a warning and
  leaves both in place. Use --force to overwrite instead.
- Prompts for confirmation before moving unless --yes is passed.
- --dry-run shows what would move without touching anything.
"""

import argparse
import csv
import os
import shutil
import sys

from generate_voices import existing_file_state


def main():
    parser = argparse.ArgumentParser(
        description="Back up stale WAV files before regenerating")
    parser.add_argument("--manifest", "-m", required=True,
                        help="Path to manifest CSV (the one about to be "
                             "regenerated)")
    parser.add_argument("--source", "-s", required=True,
                        help="Directory where the WAV files live")
    parser.add_argument("--dest", "-d", required=True,
                        help="Backup directory to move stale files into")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Show what would move without touching files")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip confirmation prompt")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite files already in the backup dir")
    args = parser.parse_args()

    with open(args.manifest, newline="", encoding="utf-8") as f:
        manifest = list(csv.DictReader(f))
    print(f"Loaded {len(manifest)} lines from {args.manifest}")

    stale_voice = []
    stale_text = []
    for item in manifest:
        src = os.path.join(args.source, item["filename"])
        state = existing_file_state(src, item["voice_id"], item["text"])
        if state == "stale_voice":
            stale_voice.append(item)
        elif state == "stale_text":
            stale_text.append(item)

    total = len(stale_voice) + len(stale_text)
    print(f"\nFound {total} stale files:")
    print(f"  voice changed: {len(stale_voice)}")
    print(f"  text changed:  {len(stale_text)}")

    if total == 0:
        print("Nothing to back up.")
        return 0

    # Sample preview
    print("\nSample of voice-changed files:")
    for item in stale_voice[:5]:
        print(f"  {item['filename']:<40} {item['speaker']:<15} "
              f"{item['voice_desc']}")
    if len(stale_voice) > 5:
        print(f"  ...and {len(stale_voice) - 5} more")
    if stale_text:
        print("\nText-changed files:")
        for item in stale_text:
            preview = item["text"][:50] + (".." if len(item["text"]) > 50 else "")
            print(f"  {item['filename']:<40} {item['speaker']:<15} {preview!r}")

    if args.dry_run:
        print("\n(dry-run - no files moved)")
        return 0

    if not args.yes:
        resp = input(f"\nMove {total} files to {args.dest}? [y/N] ").strip().lower()
        if resp != "y":
            print("Aborted.")
            return 1

    os.makedirs(args.dest, exist_ok=True)

    moved = 0
    collided = 0
    missing = 0
    for item in stale_voice + stale_text:
        src = os.path.join(args.source, item["filename"])
        dst = os.path.join(args.dest, item["filename"])
        if not os.path.exists(src):
            # Shouldn't happen given the staleness check already confirmed
            # existence, but belt and suspenders.
            print(f"  MISSING: {item['filename']}")
            missing += 1
            continue
        if os.path.exists(dst) and not args.force:
            print(f"  COLLISION (already backed up): {item['filename']}")
            collided += 1
            continue
        shutil.move(src, dst)
        moved += 1

    print(f"\nMoved {moved} files to {args.dest}")
    if collided:
        print(f"Skipped {collided} files already present in backup "
              f"(use --force to overwrite)")
    if missing:
        print(f"Warning: {missing} source files were missing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
