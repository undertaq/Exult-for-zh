#!/usr/bin/env python3
"""Ingest missing voice-line sources into the pipeline (surgical patch).

Two gaps fixed:

1. Rune-sign reader EN lines (func 0x095F, offsets 0x0/0x146, segment 0):
   zh_voice_lines.csv carries them but en_voice_lines.csv never did, so the
   runtime-key audit rejected every EN variant -> 18 silent sign-reader clips.

2. Companion gem-bark (func 0x02F8, offset 0xAD): "I believe the gem must be
   held in the weapon hand to break the mirror." Bark-class lines go through
   pushs+call[extern 0x08FF], which extract_say_lines ignores entirely. This
   adds the row to both CSVs and bilingual_mapping_review.json; generation
   expands it per-companion via COMPANION_BARK_FUNCS ('02f8' added there).

Idempotent: rows are keyed by (func_id, offset_key, segment) and skipped if
already present. Mapping JSON rows are matched the same way.
"""
import argparse
import csv
import io
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent

EN_CSV = SCRIPT_DIR / "en_voice_lines.csv"
ZH_CSV = SCRIPT_DIR / "zh_voice_lines.csv"
MAPPING = SCRIPT_DIR / "bilingual_mapping_review.json"

SIGN_EN_TEXT_0 = (
    'nowadays only these \'retro-style\' signs remain in use!"'
)
CSV_HEADER = "func_id,npc,speaker,caller_guess,offset_key,segment,total_segments,has_var,text"

BARK = {
    "func": "0x02F8",
    "offset_csv": "0xAD",
    "offset_json": "ad",
    "segment": 0,
    "en_text": "I believe the gem must be held in the weapon hand to break the mirror.",
    # Authored translation (usecode.zh does not override func 0x02F8).
    "zh_text": "我相信寶石必須握在持武器的手中，才能打破鏡子。",
}


def csv_row(func, offset, segment, text):
    buf = io.StringIO()
    csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="").writerow(
        [func, "", "", "", offset, segment, 1, "False", text]
    )
    return buf.getvalue()


def existing_keys(csv_path):
    keys = set()
    if not csv_path.exists():
        return keys
    for line in csv_path.read_text(encoding="utf-8").splitlines():
        parts = line.split(",")
        if len(parts) >= 6 and parts[0].upper().startswith("0X"):
            keys.add((parts[0].upper(), parts[5].strip().lower(), parts[6].strip()))
    return keys


def append_unique(csv_path, rows):
    have = existing_keys(csv_path)
    added = []
    with csv_path.open("a", encoding="utf-8") as f:
        for key, line in rows:
            if key in have:
                continue
            f.write(line + "\n")
            added.append(key)
    return added


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))

    # --- 1. rune-sign reader EN rows ------------------------------------
    sign_rows = []
    for r in mapping:
        if (r.get("en_func_id") or "").upper() == "0X095F":
            off = r.get("en_offset_key")
            seg = r.get("en_segment") or 0
            text = r.get("en_text") or ""
            if not text:
                continue
            r["en_segment"] = 0  # align EN with ZH segment numbering
            sign_rows.append((( "0X095F", off.lower(), "0"),
                              csv_row("0x095F", f"0x{int(off,16):X}", 0, text)))
    # dedupe
    seen = set()
    sign_rows = [x for x in sign_rows if not (x[0] in seen or seen.add(x[0]))]

    # --- 2. companion bark row ------------------------------------------
    bark_rows = [
        (("0X02F8", BARK["offset_json"], "0"),
         csv_row("0x02F8", BARK["offset_csv"], 0, BARK["en_text"])),
    ]
    bark_rows_zh = [
        (("0X02F8", BARK["offset_json"], "0"),
         csv_row("0x02F8", BARK["offset_csv"], 0, BARK["zh_text"])),
    ]

    if args.dry_run:
        print("EN csv additions:", [k for k, _ in sign_rows + bark_rows])
        print("ZH csv additions:", [k for k, _ in bark_rows_zh])
        print("json 02F8 row:", "missing" if not any(
            (r.get("en_func_id") or "").upper() == "0X02F8" for r in mapping) else "present")
        return 0

    added_en = append_unique(EN_CSV, sign_rows + bark_rows)
    added_zh = append_unique(ZH_CSV, bark_rows_zh)
    print("en_voice_lines.csv added:", added_en)
    print("zh_voice_lines.csv added:", added_zh)

    if not any((r.get("en_func_id") or "").upper() == "0X02F8" for r in mapping):
        mapping.append({
            "npc": "UNKNOWN",
            "en_func_id": "0x02F8",
            "en_offset_key": BARK["offset_json"],
            "en_segment": BARK["segment"],
            "zh_func_id": "0x02F8",
            "zh_offset_key": BARK["offset_json"],
            "zh_segment": BARK["segment"],
            "en_text": BARK["en_text"],
            "zh_text": BARK["zh_text"],
        })
        MAPPING.write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print("mapping json: appended 0x02F8 bark row")
    else:
        print("mapping json: 0x02F8 already present")

    return 0


if __name__ == "__main__":
    sys.exit(main())
