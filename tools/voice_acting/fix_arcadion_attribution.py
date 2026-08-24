#!/usr/bin/env python3
"""Fix NPC attribution for Arcadion's dialogue in bilingual_mapping_review.json.

Root cause (see doc/bilingual_mapping_generation.md history):
Arcadion has no standard NPC conversation function (0x400+273 is unused). All
his lines live in the Forge of Virtue item function 0x06F6 (mirror / black
sword) plus two gem-whisper lines inside 0x009A. The disassembler attributes
speakers via show_npc_face(-X) -> 0x400+X, which fails three ways here:

  - n_MIRROR_FACE (-290)  -> func 0x522, absent from npc_data -> empty speaker,
                             rows fall back to UNKNOWN (narrator)
  - n_GEM_FACE    (-291)  -> 0x400+291 collides with Hook (npc 291)
  - Dark Core portrait (-292) shown mid-scene steals attribution while
                             Arcadion is the one speaking through the sword

Result: zero rows carried npc == "Arcadion", so Phase C never generated a
single line in his voice despite design + refs + clone prompt existing.

This patch applies the reviewed curation table
(arcadion_attribution_table.TABLE): 93 rows -> "Arcadion", 3 pure-cutscene
narration rows -> "UNKNOWN". Rows are matched by (en_func_id, en_offset_key,
en_segment) plus an en_text prefix sanity check -- never by list index.
Idempotent: already-correct rows are counted and left untouched.

Usage:
    python fix_arcadion_attribution.py            # apply
    python fix_arcadion_attribution.py --dry-run  # report only
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from arcadion_attribution_table import TABLE

MAPPING_PATH = SCRIPT_DIR / "bilingual_mapping_review.json"
BACKUP_PATH = SCRIPT_DIR / "bilingual_mapping_review.json.pre_arcadion"

ARCADION_VOICE_GENDER = "male"
ARCADION_VOICE_AGE = "elderly"


def norm(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def find_row(mapping, fid, off, seg):
    hits = [
        r
        for r in mapping
        if r.get("en_func_id") == fid
        and r.get("en_offset_key") == off
        and (r.get("en_segment") or 0) == seg
    ]
    return hits


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="Report without writing"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reassign even when the text-prefix sanity check fails",
    )
    args = parser.parse_args()

    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))

    applied, already, mismatched, missing = [], [], [], []

    for fid, off, seg, target, expected_npc, prefix in TABLE:
        hits = find_row(mapping, fid, off, seg)
        if len(hits) != 1:
            missing.append((fid, off, seg, len(hits)))
            continue
        row = hits[0]
        if not norm(row.get("en_text", "")).startswith(prefix):
            mismatched.append((fid, off, seg, "text-prefix"))
            continue
        current = row.get("npc")
        if current == target:
            already.append((fid, off, seg))
            continue
        if current != expected_npc:
            mismatched.append((fid, off, seg, f"npc={current!r} expected {expected_npc!r}"))
            continue
        if args.dry_run:
            applied.append((fid, off, seg, current, target))
            continue
        row["npc"] = target
        if target == "Arcadion":
            row["voice_gender"] = ARCADION_VOICE_GENDER
            row["voice_age"] = ARCADION_VOICE_AGE
        applied.append((fid, off, seg, current, target))

    print(f"table entries      : {len(TABLE)}")
    print(f"applied            : {len(applied)}")
    print(f"already correct    : {len(already)}")
    print(f"missing keys       : {len(missing)}")
    for m in missing[:10]:
        print("   MISSING", m)
    print(f"sanity mismatches  : {len(mismatched)}")
    for m in mismatched[:10]:
        print("   MISMATCH", m)

    if missing or mismatched:
        print("\nRefusing to write: resolve the problems above first.")
        return 1

    if args.dry_run:
        print("\nDry run complete; nothing written.")
        return 0

    if not applied:
        print("\nNothing to do; mapping already up to date.")
        return 0

    if not BACKUP_PATH.exists():
        shutil.copy2(MAPPING_PATH, BACKUP_PATH)
        print(f"backup written     : {BACKUP_PATH.name}")

    MAPPING_PATH.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote              : {MAPPING_PATH.name}")

    from collections import Counter

    by_target = Counter(t for *_, t in applied)
    print("reassigned         :", dict(by_target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
