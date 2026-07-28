#!/usr/bin/env python3
"""
Patch missing egg-triggered dialog from function 0x06FA into
bilingual_mapping_review.json and the supporting CSV files.

Function 0x06FA uses pushs+call (not addsi+say), so the extraction tool
cannot see these lines. They must be injected manually.

Also patches en_voice_lines.csv, zh_voice_lines.csv, and offset_mapping.csv
so the voice generator's runtime key check accepts the new entries.

Run before sync_mapping_voice_prompts in the pipeline:
    python tools/voice_acting/patch_missing_egg_dialog.py
"""

import argparse
import csv
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_JSON = SCRIPT_DIR / "bilingual_mapping_review.json"
DEFAULT_EN_VOICE = SCRIPT_DIR / "en_voice_lines.csv"
DEFAULT_ZH_VOICE = SCRIPT_DIR / "zh_voice_lines.csv"
DEFAULT_OFFSET_MAP = SCRIPT_DIR / "offset_mapping.csv"

ENTRY_A = {
    "index": None,
    "npc": "Iolo|Spark|Shamino|Dupre|Jaana|Trellek|Sentri|Julia|Katrina|Tseramed|Petre|Finnigan",
    "zh_offset_key": "0",
    "zh_segment": 0,
    "zh_text": "「看來附近的島嶼一點也不穩定。」",
    "en_offset_key": "0",
    "en_segment": 0,
    "en_text": '"It would seem the nearby island is not at all stable."',
    "confidence": "manual",
    "zh_func_id": "0x06FA",
    "en_func_id": "0x06FA",
    "voice_gender": "",
    "voice_age": "",
    "voice_prompt": "",
    "voice_lang": "en",
    "tone": "neutral",
    "tone_instruct": "",
    "voice_prompt_zh": "",
    "en_raw": '"It would seem the nearby island is not at all stable."',
    "zh_raw": "「看來附近的島嶼一點也不穩定。」",
}

ENTRY_B = {
    "index": None,
    "npc": "Iolo",
    "zh_offset_key": "38",
    "zh_segment": 0,
    "zh_text": "「不列顛尼亞似乎有些不對勁。也許不列顛王會知道這場地震背後的原因。」",
    "en_offset_key": "38",
    "en_segment": 0,
    "en_text": '"All is not right in Britannia. Perhaps Lord British will know the reason behind this tremor."',
    "confidence": "manual",
    "zh_func_id": "0x06FA",
    "en_func_id": "0x06FA",
    "voice_gender": "",
    "voice_age": "",
    "voice_prompt": "",
    "voice_lang": "en",
    "tone": "neutral",
    "tone_instruct": "",
    "voice_prompt_zh": "",
    "en_raw": '"All is not right in Britannia. Perhaps Lord British will know the reason behind this tremor."',
    "zh_raw": "「不列顛尼亞似乎有些不對勁。也許不列顛王會知道這場地震背後的原因。」",
}

ENTRIES = [ENTRY_A, ENTRY_B]


def csv_lines_exist(func_id, offset_key, path):
    """Return True if a row with func_id + offset_key already exists in the CSV."""
    if not path.exists():
        return False
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("func_id", "").strip() == func_id and row.get("offset_key", "").strip() == offset_key:
                return True
    return False


def add_to_voice_csv(path, func_id, npc, offset_key, text):
    """Append a row to an EN/ZH voice lines CSV if not already present."""
    already = csv_lines_exist(func_id, offset_key, path)
    if already:
        print(f"  CSV EXISTS: {path.name} {func_id} offset={offset_key}")
        return False
    row = [func_id, npc, "", "", offset_key, "0", "1", "False", text]
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(row)
    print(f"  CSV ADDED:  {path.name} {func_id} offset={offset_key}")
    return True


def offset_map_exists(func_id, offset_key, path):
    """Return True if a row with this func_id + EN offset_key exists."""
    if not path.exists():
        return False
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ef = row.get("en_func_id", "").strip()
            ek = row.get("en_offset_key", "").strip()
            if ef == func_id and ek == offset_key:
                return True
    return False


def add_to_offset_map(path, en_func_id, en_ok, en_text, zh_func_id, zh_ok, zh_text):
    """Append a row to offset_mapping.csv if not already present."""
    already = offset_map_exists(en_func_id, en_ok, path)
    if already:
        print(f"  CSV EXISTS: {path.name} {en_func_id}/{en_ok}")
        return False
    row = [en_func_id, en_ok, "0", en_text, zh_func_id, zh_ok, "0"]
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(row)
    print(f"  CSV ADDED:  {path.name} {en_func_id}/{en_ok}")
    return True


def json_entry_exists(entry, data):
    for e in data:
        if (e.get("en_func_id") == entry["en_func_id"]
                and e.get("en_offset_key") == entry["en_offset_key"]
                and e.get("en_segment") == entry["en_segment"]
                and e.get("zh_func_id") == entry["zh_func_id"]
                and e.get("zh_offset_key") == entry["zh_offset_key"]
                and e.get("zh_segment") == entry["zh_segment"]):
            return True
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Patch missing egg-triggered dialog files"
    )
    parser.add_argument("--json", default=str(DEFAULT_JSON))
    parser.add_argument("--en-voice", default=str(DEFAULT_EN_VOICE))
    parser.add_argument("--zh-voice", default=str(DEFAULT_ZH_VOICE))
    parser.add_argument("--offset-map", default=str(DEFAULT_OFFSET_MAP))
    args = parser.parse_args()

    # ── bilingual_mapping_review.json ──────────────────────────────────
    json_path = Path(args.json)
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    max_index = max((e.get("index", 0) or 0) for e in data)
    added_json = 0
    for entry in ENTRIES:
        if json_entry_exists(entry, data):
            print(f"  JSON EXISTS:  {entry['en_func_id']} offset={entry['en_offset_key']}")
        else:
            max_index += 1
            new_entry = dict(entry)
            new_entry["index"] = max_index
            data.append(new_entry)
            print(f"  JSON ADDED [{max_index}]: {entry['en_text'][:55]}...")
            added_json += 1

    if added_json > 0:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"  JSON saved ({len(data)} entries)")

    # ── en_voice_lines.csv ─────────────────────────────────────────────
    en_path = Path(args.en_voice)
    for entry in ENTRIES:
        add_to_voice_csv(
            en_path, "0x06FA", "",
            f"0x{entry['en_offset_key']}", entry["en_text"],
        )

    # ── zh_voice_lines.csv ─────────────────────────────────────────────
    zh_path = Path(args.zh_voice)
    for entry in ENTRIES:
        add_to_voice_csv(
            zh_path, "0x06FA", "",
            f"0x{entry['zh_offset_key']}", entry["zh_text"],
        )

    # ── offset_mapping.csv ─────────────────────────────────────────────
    map_path = Path(args.offset_map)
    for entry in ENTRIES:
        add_to_offset_map(
            map_path,
            "0x06FA", entry["en_offset_key"], entry["en_text"],
            "0x06FA", entry["zh_offset_key"], entry["zh_text"],
        )

    total = added_json
    print(f"Done. Patched {total} dialog line(s) into all 4 files (idempotent).")


if __name__ == "__main__":
    main()
