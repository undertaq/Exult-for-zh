#!/usr/bin/env python3
"""
Sync voice acting WAV files to match the manifest.

For every WAV file in the voice directory:
  1. Read its embedded metadata (voice_id, text_hash)
  2. Find the matching manifest entry
  3. Rename the file if the filename doesn't match
  4. Prefix unmatched files with "unknown_"

Run this before generation to ensure the directory is clean and
filenames match the current manifest/key scheme.

Usage:
    python sync_voice_files.py \
        --manifest manifest.csv \
        --wav-dir "path/to/patch/voice_acting" \
        --dry-run
"""

import argparse
import csv
import os
import shutil
import sys

from audio_metadata import (text_hash, make_artist_tag, parse_artist_tag,
                            read_audio_metadata)


def main():
    parser = argparse.ArgumentParser(
        description="Sync OGG filenames to match the manifest"
    )
    parser.add_argument("--manifest", "-m", required=True,
                        help="Path to manifest CSV")
    parser.add_argument("--audio-dir", "-d", required=True,
                        help="Directory containing OGG files")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Show what would be done without modifying files")
    args = parser.parse_args()

    # Load manifest: build lookup by (voice_id, text_hash) -> [filenames]
    with open(args.manifest, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        manifest = list(reader)

    manifest_by_key = {}  # (voice_id, thash) -> list of expected filenames
    for entry in manifest:
        thash = text_hash(entry["text"])
        key = (entry["voice_id"], thash)
        manifest_by_key.setdefault(key, []).append(entry["filename"])

    expected_filenames = {entry["filename"] for entry in manifest}

    print(f"Loaded {len(manifest)} manifest entries "
          f"({len(manifest_by_key)} unique voice+text pairs)")

    # Scan OGG files
    audio_files = [f for f in os.listdir(args.audio_dir)
                   if f.endswith(".ogg") and not f.startswith("unknown_")]
    unknown_files = [f for f in os.listdir(args.audio_dir)
                     if f.startswith("unknown_") and f.endswith(".ogg")]
    print(f"Found {len(audio_files)} OGG files, "
          f"{len(unknown_files)} unknown files")

    renamed = 0
    correct = 0
    unmatched = 0
    errors = 0
    already_filled = set()  # filenames that already exist (avoid overwrites)

    # First pass: check which expected filenames already exist correctly
    for filename in audio_files:
        if filename in expected_filenames:
            already_filled.add(filename)

    for filename in sorted(audio_files):
        filepath = os.path.join(args.audio_dir, filename)
        meta = read_audio_metadata(filepath)

        if not meta["title"] or not meta["artist"]:
            print(f"  NO METADATA: {filename}")
            unmatched += 1
            # Rename to unknown_ prefix
            new_name = f"unknown_{filename}"
            if not args.dry_run:
                new_path = os.path.join(args.audio_dir, new_name)
                if not os.path.exists(new_path):
                    os.rename(filepath, new_path)
                    print(f"    -> {new_name}")
            else:
                print(f"    WOULD RENAME -> {new_name}")
            continue

        # Extract voice_id from artist tag
        _, voice_id = parse_artist_tag(meta["artist"])
        thash = meta["title"]
        key = (voice_id, thash)

        if key not in manifest_by_key:
            print(f"  NOT IN MANIFEST: {filename} "
                  f"(voice={voice_id[:12]}.. hash={thash})")
            unmatched += 1
            new_name = f"unknown_{filename}"
            if not args.dry_run:
                new_path = os.path.join(args.audio_dir, new_name)
                if not os.path.exists(new_path):
                    os.rename(filepath, new_path)
                    print(f"    -> {new_name}")
            else:
                print(f"    WOULD RENAME -> {new_name}")
            continue

        # Find expected filename(s) for this voice+text pair
        expected_names = manifest_by_key[key]

        if filename in expected_names:
            correct += 1
            continue

        # File needs renaming - find an expected name that isn't taken
        target_name = None
        for name in expected_names:
            if name not in already_filled:
                target_name = name
                break

        if not target_name:
            # All expected names are already filled (by other files)
            # This is a duplicate - keep it but mark as unknown
            print(f"  DUPLICATE: {filename} (all targets filled)")
            new_name = f"unknown_{filename}"
            if not args.dry_run:
                new_path = os.path.join(args.audio_dir, new_name)
                if not os.path.exists(new_path):
                    os.rename(filepath, new_path)
            unmatched += 1
            continue

        print(f"  RENAME: {filename} -> {target_name}")
        if not args.dry_run:
            target_path = os.path.join(args.audio_dir, target_name)
            os.rename(filepath, target_path)
            already_filled.add(target_name)
        renamed += 1

    # Also check unknown_ files - they might now match the manifest
    for filename in sorted(unknown_files):
        filepath = os.path.join(args.audio_dir, filename)
        meta = read_audio_metadata(filepath)

        if not meta["title"] or not meta["artist"]:
            continue

        _, voice_id = parse_artist_tag(meta["artist"])
        thash = meta["title"]
        key = (voice_id, thash)

        if key in manifest_by_key:
            for name in manifest_by_key[key]:
                if name not in already_filled:
                    print(f"  RECOVER: {filename} -> {name}")
                    if not args.dry_run:
                        target_path = os.path.join(args.audio_dir, name)
                        os.rename(filepath, target_path)
                        already_filled.add(name)
                    renamed += 1
                    break

    print(f"\nDone: {correct} correct, {renamed} renamed, "
          f"{unmatched} unmatched")


if __name__ == "__main__":
    main()
