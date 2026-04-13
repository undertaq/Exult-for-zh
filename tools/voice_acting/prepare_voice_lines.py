#!/usr/bin/env python3
"""
Prepare a voice generation manifest from extracted voice lines.

Reads the extracted CSV (from disassemble_usecode.py), resolves placeholders,
expands multi-NPC shared lines into per-NPC variants, assigns voices, and
outputs a generation manifest CSV ready for generate_voices.py.

Usage:
    python prepare_voice_lines.py \
        --csv scope_voice_lines.csv \
        --player-name Avatar --player-gender female \
        -o manifest.csv
"""

import argparse
import csv
import os
import re
import sys

from npc_data import NPC_NUMBERS
from voice_assignments import VOICE_MAP, get_voice


def resolve_placeholders(text, player_name, player_gender):
    """Replace labeled placeholders with actual values."""
    gender_map = {
        "male": {"<PRONOUN>": "him", "<HONORIFIC>": "milord"},
        "female": {"<PRONOUN>": "her", "<HONORIFIC>": "milady"},
    }
    replacements = gender_map.get(player_gender, gender_map["male"])
    replacements["<PLAYER_NAME>"] = player_name

    result = text
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)
    return result


def has_unresolved_placeholders(text):
    """Check for any remaining unresolved <...> placeholders."""
    return bool(re.findall(r'<[A-Z_]+>', text))


def voice_filename(func_id, offset_key, segment, npc_num=None):
    """Compute the voice filename."""
    fid = func_id.lower().replace("0x", "")
    okey = offset_key.replace("0x", "")
    base = f"{fid}_{okey}_{segment}"
    if npc_num is not None:
        return f"{base}_npc{npc_num}.wav"
    return f"{base}.wav"


MANIFEST_FIELDS = [
    "filename", "func_id", "offset_key", "segment",
    "speaker", "speaker_source", "npc_num",
    "voice_id", "voice_desc",
    "prev_text", "next_text", "text",
]


def main():
    parser = argparse.ArgumentParser(
        description="Prepare voice generation manifest from extracted voice lines"
    )
    parser.add_argument("--csv", required=True,
                        help="Path to extracted voice lines CSV")
    parser.add_argument("--output", "-o", required=True,
                        help="Output manifest CSV path")
    parser.add_argument("--issues", default=None,
                        help="Output issues CSV path (default: <output>_issues.csv)")
    parser.add_argument("--overrides", default=None,
                        help="Path to overrides CSV (manual corrections)")
    parser.add_argument("--player-name", default="Avatar",
                        help="Player character name for <PLAYER_NAME>")
    parser.add_argument("--player-gender", choices=["male", "female"],
                        default="male",
                        help="Player gender for <PRONOUN> and <HONORIFIC>")
    args = parser.parse_args()

    # Load extracted CSV
    with open(args.csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        all_lines = list(reader)

    print(f"Loaded {len(all_lines)} lines from {args.csv}")

    # Load and apply overrides
    overrides = {}
    appended_lines = []
    if args.overrides and os.path.exists(args.overrides):
        with open(args.overrides, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row["func_id"].strip(), row["offset_key"].strip(),
                       row["segment"].strip())
                overrides[key] = row

        # Apply overrides to existing lines.
        # Overrides match by (func_id, offset_key, segment).
        # Blank offset_key or segment acts as a wildcard.
        applied = 0
        used_override_keys = set()
        for line in all_lines:
            lfid = line["func_id"].strip()
            lokey = line["offset_key"].strip()
            lseg = line["segment"].strip()

            # Try exact match first, then wildcards
            candidates = [
                (lfid, lokey, lseg),      # exact
                (lfid, lokey, ""),         # any segment
                (lfid, "", lseg),          # any offset_key
                (lfid, "", ""),            # any in function
            ]
            for candidate in candidates:
                if candidate in overrides:
                    override = overrides[candidate]
                    used_override_keys.add(candidate)
                    for field, value in override.items():
                        if field and isinstance(value, str) and value.strip():
                            line[field] = value.strip()
                    applied += 1
                    break

        # Remaining overrides with non-blank offset_key are new lines to append
        for key, override in overrides.items():
            if key not in used_override_keys:
                # Only append if it has enough info to be a real line
                if override.get("offset_key", "").strip():
                    appended_lines.append(override)

        print(f"Overrides: {applied} applied, {len(appended_lines)} appended "
              f"(from {args.overrides})")

        all_lines.extend(appended_lines)

    # Expand into generation manifest, tracking issues
    manifest = []
    issues = []  # (row, speaker, issue_type, detail)

    for row in all_lines:
        speaker = row.get("speaker", "")
        caller_guess = row.get("caller_guess", "")

        if speaker:
            speakers = [speaker]
            speaker_source = "speaker"
        elif caller_guess:
            if "|" in caller_guess:
                speakers = caller_guess.split("|")
            else:
                speakers = [caller_guess]
            speaker_source = "caller_guess"
        else:
            speakers = [""]
            speaker_source = "unknown"

        is_multi_npc = len(speakers) > 1

        for spk in speakers:
            text = resolve_placeholders(
                row["text"], args.player_name, args.player_gender)

            line_issues = []

            # Check for explicit skip marker
            if text == "SKIP":
                continue

            # Check for unresolved placeholders
            unresolved = re.findall(r'<[A-Z_]+>', text)
            if unresolved:
                line_issues.append(("UNRESOLVED_VAR", ", ".join(unresolved)))

            # Check for missing speaker
            if not spk:
                line_issues.append(("NO_SPEAKER", "no speaker or caller_guess"))

            # Check for missing voice assignment
            if spk and spk not in VOICE_MAP:
                line_issues.append(("NO_VOICE_ASSIGNED",
                                    f"using default voice for '{spk}'"))

            if line_issues:
                for issue_type, detail in line_issues:
                    issues.append((row, spk, issue_type, detail))

            # Skip lines with unresolved vars from the manifest
            if unresolved:
                continue

            voice_id, voice_desc = get_voice(spk)
            npc_num = NPC_NUMBERS.get(spk) if is_multi_npc else None

            filename = voice_filename(
                row["func_id"], row["offset_key"],
                int(row["segment"]), npc_num)

            manifest.append({
                "filename": filename,
                "func_id": row["func_id"],
                "offset_key": row["offset_key"],
                "segment": row["segment"],
                "speaker": spk,
                "speaker_source": speaker_source,
                "npc_num": npc_num if npc_num is not None else "",
                "voice_id": voice_id,
                "voice_desc": voice_desc,
                "prev_text": "",
                "next_text": "",
                "text": text,
            })

    # Compute previous_text / next_text for segments within the same say() call
    # (same func_id + same offset_key + different segment = ~~ splitting)
    # Skip multi-NPC variants (same offset_key + same segment = same text, different NPC)
    for i, item in enumerate(manifest):
        if i > 0:
            prev = manifest[i - 1]
            if (prev["func_id"] == item["func_id"]
                    and prev["offset_key"] == item["offset_key"]
                    and prev["segment"] != item["segment"]):
                item["prev_text"] = prev["text"]
        if i + 1 < len(manifest):
            nxt = manifest[i + 1]
            if (nxt["func_id"] == item["func_id"]
                    and nxt["offset_key"] == item["offset_key"]
                    and nxt["segment"] != item["segment"]):
                item["next_text"] = nxt["text"]

    # Write manifest CSV
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(manifest)

    # Summary
    unique_files = len(set(item["filename"] for item in manifest))
    multi_npc = sum(1 for item in manifest if item["npc_num"] != "")
    total_chars = sum(len(item["text"]) for item in manifest)
    sources = {}
    for item in manifest:
        src = item["speaker_source"]
        sources[src] = sources.get(src, 0) + 1

    print(f"\nManifest: {len(manifest)} lines ready ({unique_files} unique files)")
    print(f"  Multi-NPC variants: {multi_npc}")
    print(f"  Speaker sources: {sources}")
    print(f"  Total characters: {total_chars:,}")
    print(f"Written to: {args.output}")

    # Write issues CSV
    issues_path = args.issues
    if not issues_path:
        base, ext = os.path.splitext(args.output)
        issues_path = base + "_issues" + ext

    if issues:
        ISSUES_FIELDS = [
            "issue_type", "func_id", "offset_key", "segment",
            "speaker", "speaker_source", "detail", "text",
        ]
        with open(issues_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=ISSUES_FIELDS)
            writer.writeheader()
            for row, spk, issue_type, detail in issues:
                speaker_source = "speaker" if row.get("speaker") else (
                    "caller_guess" if row.get("caller_guess") else "unknown")
                writer.writerow({
                    "issue_type": issue_type,
                    "func_id": row["func_id"],
                    "offset_key": row["offset_key"],
                    "segment": row["segment"],
                    "speaker": spk,
                    "speaker_source": speaker_source,
                    "detail": detail,
                    "text": row["text"],
                })
        print(f"Issues written to: {issues_path}")

    # Report issues to console
    if issues:
        from collections import Counter
        issue_counts = Counter(t for _, _, t, _ in issues)

        print(f"\n{'='*70}")
        print(f"Issues ({len(issues)} total):")
        for issue_type, count in issue_counts.most_common():
            print(f"  {issue_type}: {count}")
        print(f"{'='*70}")

        # Group and display by issue type
        by_type = {}
        for row, spk, issue_type, detail in issues:
            by_type.setdefault(issue_type, []).append((row, spk, detail))

        if "UNRESOLVED_VAR" in by_type:
            print(f"\n--- UNRESOLVED_VAR ({len(by_type['UNRESOLVED_VAR'])}) ---")
            print("Lines with placeholders that could not be resolved.")
            print("These need manual text in an overrides file.\n")
            for row, spk, detail in by_type["UNRESOLVED_VAR"]:
                text_preview = row["text"][:60]
                print(f"  {row['func_id']} {row['offset_key']}:{row['segment']}"
                      f"  speaker={spk or '?'}  vars={detail}")
                print(f"    \"{text_preview}...\"")

        if "NO_SPEAKER" in by_type:
            print(f"\n--- NO_SPEAKER ({len(by_type['NO_SPEAKER'])}) ---")
            print("Lines with no speaker detected (no face-switch or caller inference).")
            print("These will use the default voice.\n")
            for row, spk, detail in by_type["NO_SPEAKER"]:
                text_preview = row["text"][:60]
                print(f"  {row['func_id']} {row['offset_key']}:{row['segment']}"
                      f"  npc={row.get('npc', '?')}")
                print(f"    \"{text_preview}...\"")

        if "NO_VOICE_ASSIGNED" in by_type:
            print(f"\n--- NO_VOICE_ASSIGNED ({len(by_type['NO_VOICE_ASSIGNED'])}) ---")
            print("Speakers without a dedicated voice in VOICE_MAP.")
            print("These will use the default voice. Add entries to VOICE_MAP to fix.\n")
            # Group by speaker to avoid repetition
            speakers_missing = {}
            for row, spk, detail in by_type["NO_VOICE_ASSIGNED"]:
                speakers_missing.setdefault(spk, 0)
                speakers_missing[spk] += 1
            for spk, count in sorted(speakers_missing.items()):
                print(f"  {spk}: {count} lines")


if __name__ == "__main__":
    main()
