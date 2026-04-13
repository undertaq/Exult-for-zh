#!/usr/bin/env python3
"""
Audit voice acting data by comparing the runtime log against
the statically extracted voice lines.

Checks that for each line encountered at runtime:
  1. The filename (key) matches the expected static extraction
  2. The text matches (accounting for dynamic <VAR> substitution)
  3. The speaker matches

Outputs a CSV report with three sections:
  1. Exact matches between runtime and extracted
  2. Runtime lines not found in extracted
  3. Extracted lines not seen at runtime

Usage:
    python audit_voice_lines.py \
        --log "path/to/voice_acting_log.csv" \
        --extracted "path/to/voice_lines.csv" \
        --output audit_report.csv
"""

import argparse
import csv
import io
import re
import sys


def load_runtime_log(path):
    """Load the runtime log CSV."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def normalize_offset_key(key):
    """Normalize offset key by stripping 0x prefixes for consistent matching.
    e.g., '0xaf_0x151_0x254' -> 'af_151_254'"""
    return "_".join(part.replace("0x", "") for part in key.split("_"))


def normalize_func_id(fid):
    """Normalize func_id to consistent format: '0x0401'"""
    fid = fid.strip().lower()
    if not fid.startswith("0x"):
        fid = "0x" + fid
    hex_part = fid[2:]
    return "0x" + hex_part.zfill(4)


def load_extracted(path):
    """Load the extracted voice lines CSV. Returns a dict keyed by
    (func_id, offset_key, segment)."""
    extracted = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            func_id = normalize_func_id(row["func_id"])
            offset_key = normalize_offset_key(row["offset_key"])
            key = (func_id, offset_key, int(row["segment"]))
            row["_norm_func_id"] = func_id
            row["_norm_offset_key"] = offset_key
            extracted[key] = row
    return extracted


# NPC number -> name mapping
# Negative NPC numbers as used in usecode / runtime log
NPC_NAMES = {
    0: "Avatar",
    -1: "Iolo", -2: "Spark", -3: "Shamino", -4: "Dupre",
    -5: "Jaana", -6: "Trellek", -7: "Sentri", -8: "Julia",
    -9: "Katrina", -10: "Tseramed", -11: "Petre", -12: "Finnigan",
    -13: "Gilberto", -14: "Johnson", -15: "Eiko", -16: "Klog",
    -17: "Chantu", -18: "Dell", -19: "Apollonia", -20: "Markus",
    -21: "Gargan", -22: "Caroline", -23: "Lord British",
    -24: "Nystul", -25: "Chuckles", -26: "Batlin",
}


def npc_name(num):
    """Convert NPC number to name."""
    num = int(num)
    return NPC_NAMES.get(num, f"NPC({num})")


def text_matches_template(actual_text, template_text):
    """
    Check if the actual runtime text matches the extracted template.
    The template may contain <PLAYER_NAME>, <PRONOUN>, <HONORIFIC>
    placeholders that match any text in the actual string.
    Returns (bool, detail_string).
    """
    if not template_text:
        return False, "no template"

    # Reject templates that contain no static text (only placeholders).
    # These match anything and produce false positives.
    static_text = template_text
    for placeholder in ("<PLAYER_NAME>", "<PRONOUN>", "<HONORIFIC>", "<VAR>"):
        static_text = static_text.replace(placeholder, "")
    if not static_text.strip():
        return False, "template_is_only_vars"

    pattern = re.escape(template_text)
    pattern = pattern.replace(re.escape("<PLAYER_NAME>"), ".*?")
    pattern = pattern.replace(re.escape("<PRONOUN>"), ".*?")
    pattern = pattern.replace(re.escape("<HONORIFIC>"), ".*?")
    pattern = pattern.replace(re.escape("<VAR>"), ".*?")
    pattern = "^" + pattern + "$"

    try:
        if re.match(pattern, actual_text, re.DOTALL):
            return True, "match"
        else:
            return False, "text_mismatch"
    except re.error:
        return False, "regex_error"


def csv_escape(s):
    """Escape for CSV output."""
    if '"' in s or ',' in s or '\n' in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def main():
    parser = argparse.ArgumentParser(
        description="Audit voice acting: compare runtime log vs static extraction"
    )
    parser.add_argument("--log", required=True,
                        help="Path to voice_acting_log.csv (runtime)")
    parser.add_argument("--extracted", required=True,
                        help="Path to extracted voice_lines.csv (static)")
    parser.add_argument("--output", "-o", default="audit_report.csv",
                        help="Output CSV report path (default: audit_report.csv)")
    parser.add_argument("--session", default=None,
                        help="Filter to a specific session ID (default: latest)")
    args = parser.parse_args()

    log_entries = load_runtime_log(args.log)
    extracted = load_extracted(args.extracted)

    # Filter to session
    if args.session:
        log_entries = [e for e in log_entries if e["session"] == args.session]
    else:
        sessions = sorted(set(e["session"] for e in log_entries))
        if sessions:
            latest = sessions[-1]
            log_entries = [e for e in log_entries if e["session"] == latest]
            print(f"Using latest session: {latest}")
        else:
            print("No log entries found.")
            sys.exit(1)

    print(f"Runtime log: {len(log_entries)} entries")
    print(f"Extracted:   {len(extracted)} lines")

    # Classify each runtime entry
    matched_rows = []
    unmatched_runtime_rows = []
    seen_keys = set()

    REPORT_HEADER = [
        "section", "filename", "func_id", "offset_key", "segment",
        "runtime_speaker", "extracted_speaker", "speaker_match",
        "text_match", "runtime_text", "extracted_text",
        "issues",
    ]

    for entry in log_entries:
        func_id = normalize_func_id(entry["func_id"])
        offset_key = normalize_offset_key(entry["offset_key"])
        segment = int(entry["segment"])
        runtime_text = entry["text"]
        speaker_npc = int(entry["speaker_npc"])
        caller_npc = int(entry["caller_npc"])
        filename = entry["filename"]

        key = (func_id, offset_key, segment)
        seen_keys.add(key)
        ext = extracted.get(key)

        runtime_speaker_name = npc_name(speaker_npc)

        if not ext:
            unmatched_runtime_rows.append({
                "section": "RUNTIME_NOT_IN_EXTRACTED",
                "filename": filename,
                "func_id": func_id,
                "offset_key": offset_key,
                "segment": segment,
                "runtime_speaker": runtime_speaker_name,
                "extracted_speaker": "",
                "speaker_match": "",
                "text_match": "",
                "runtime_text": runtime_text,
                "extracted_text": "",
                "issues": "KEY_NOT_IN_EXTRACTED",
            })
            continue

        # Check text
        clean_runtime = runtime_text.rstrip('*').strip('"')
        ext_text = ext["text"].rstrip('*').strip('"')
        text_ok, _ = text_matches_template(clean_runtime, ext_text)

        # Check speaker
        ext_speaker = ext.get("speaker", "")
        if ext_speaker:
            speaker_ok = (runtime_speaker_name == ext_speaker)
        else:
            speaker_ok = False  # No extracted speaker - needs review

        issues = []
        if not text_ok:
            issues.append("TEXT_MISMATCH")
        if not speaker_ok:
            if ext_speaker:
                issues.append("SPEAKER_MISMATCH")
            else:
                issues.append("SPEAKER_UNKNOWN_IN_EXTRACTED")

        row = {
            "section": "MATCH" if not issues else "MISMATCH",
            "filename": filename,
            "func_id": func_id,
            "offset_key": offset_key,
            "segment": segment,
            "runtime_speaker": runtime_speaker_name,
            "extracted_speaker": ext_speaker,
            "speaker_match": "yes" if speaker_ok else "NO",
            "text_match": "yes" if text_ok else "NO",
            "runtime_text": runtime_text,
            "extracted_text": ext["text"],
            "issues": "; ".join(issues) if issues else "",
        }
        matched_rows.append(row)

    # Extracted lines not seen at runtime
    unseen_rows = []
    for key in sorted(extracted.keys()):
        if key not in seen_keys:
            ext = extracted[key]
            func_id, offset_key, segment = key
            unseen_rows.append({
                "section": "EXTRACTED_NOT_IN_RUNTIME",
                "filename": "",
                "func_id": func_id,
                "offset_key": offset_key,
                "segment": segment,
                "runtime_speaker": "",
                "extracted_speaker": ext.get("speaker", ""),
                "speaker_match": "",
                "text_match": "",
                "runtime_text": "",
                "extracted_text": ext["text"],
                "issues": "",
            })

    # Write CSV report
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_HEADER)

        # Section 1: Matches (and mismatches)
        writer.writerow({k: k for k in REPORT_HEADER})  # Header
        for row in matched_rows:
            writer.writerow(row)

        # Blank separator
        writer.writerow({k: "" for k in REPORT_HEADER})

        # Section 2: Runtime lines not in extracted
        for row in unmatched_runtime_rows:
            writer.writerow(row)

        # Blank separator
        writer.writerow({k: "" for k in REPORT_HEADER})

        # Section 3: Extracted lines not seen at runtime
        for row in unseen_rows:
            writer.writerow(row)

    # Print summary
    n_match = sum(1 for r in matched_rows if r["section"] == "MATCH")
    n_mismatch = sum(1 for r in matched_rows if r["section"] == "MISMATCH")

    print()
    print(f"Section 1 - Matched:                    {n_match}")
    print(f"           Mismatched:                  {n_mismatch}")
    print(f"Section 2 - Runtime not in extracted:    {len(unmatched_runtime_rows)}")
    print(f"Section 3 - Extracted not in runtime:    {len(unseen_rows)}")
    print()
    print(f"Report written to: {args.output}")


if __name__ == "__main__":
    main()
