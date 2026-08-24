#!/usr/bin/env python3
"""Fix speaker attribution for the FoV mirror scene (func 0x009A).

Companion to fix_arcadion_attribution.py, driven by
fov_scene_attribution_table.TABLE:
  - 6 rows tagged "Dark Core" are actually Erethian speaking (the Dark Core
    portrait is shown mid-dialogue and stole attribution)
  - 2 rows tagged "Hook" are actually Arcadion speaking from the bonded gem

Also quarantines any existing voice clips generated under the wrong NPC name
(*_npc292.ogg for Dark Core keys, *_npc291.ogg for Hook keys) so Phase C
regenerates them under the corrected speakers.

Usage:
    python fix_fov_scene_attribution.py            # apply
    python fix_fov_scene_attribution.py --dry-run  # report only
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from fov_scene_attribution_table import TABLE

MAPPING_PATH = SCRIPT_DIR / "bilingual_mapping_review.json"
BACKUP_PATH = SCRIPT_DIR / "bilingual_mapping_review.json.pre_fov_scene"
PROJECT_ROOT = SCRIPT_DIR.parent.parent
QUARANTINE = PROJECT_ROOT / "voice" / "_stale_arcadion_quarantine"
VOICE_ROOT = PROJECT_ROOT / "voice"

VOICE_DIRS = ("zh", "en")


def norm(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def quarantine_zh_side(mapping, fid, off, seg, dry_run):
    """Quarantine ZH-side clips whose zh_offset_key may differ from en."""
    moved = []
    for r in find_row(mapping, fid, off, seg):
        zoff = r.get("zh_offset_key")
        if not zoff or zoff == off:
            continue
        moved.extend(quarantine_offset(fid, zoff, dry_run))
    return moved


def find_row(mapping, fid, off, seg):
    hits = [
        r
        for r in mapping
        if r.get("en_func_id") == fid
        and r.get("en_offset_key") == off
        and (r.get("en_segment") or 0) == seg
    ]
    return hits


def quarantine_offset(fid, off, dry_run):
    _fid_glob = fid.lower().replace("0x", "")
    """Move ANY existing clip for this offset aside so Phase C regenerates it
    under the corrected speaker (old files may carry the wrong voice/name)."""
    moved = []
    for lang_dir in VOICE_DIRS:
        for src in sorted((VOICE_ROOT / lang_dir).glob(f"{_fid_glob}_{off}_*.ogg")):
            moved.append(str(src))
            if not dry_run:
                dest = QUARANTINE / lang_dir / src.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))
    return moved


def quarantine_wrong_clips(fid, off, dry_run):
    return quarantine_offset(fid, off, dry_run)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    parser.add_argument(
        "--force", action="store_true", help="Reassign even when the text-prefix sanity check fails"
    )
    args = parser.parse_args()

    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))

    applied, already, mismatched, missing, quarantined = [], [], [], [], []

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
        elif current != expected_npc and not args.force:
            mismatched.append((fid, off, seg, f"npc={current!r} expected {expected_npc!r}"))
            continue
        else:
            if args.dry_run:
                applied.append((fid, off, seg, current, target))
            else:
                row["npc"] = target
                applied.append((fid, off, seg, current, target))
        quarantined.extend(quarantine_wrong_clips(fid, off, args.dry_run))
        quarantined.extend(quarantine_zh_side(mapping, fid, off, seg, args.dry_run))

    print(f"table entries      : {len(TABLE)}")
    print(f"applied            : {len(applied)}")
    print(f"already correct    : {len(already)}")
    print(f"missing keys       : {len(missing)}")
    for m in missing[:10]:
        print("   MISSING", m)
    print(f"sanity mismatches  : {len(mismatched)}")
    for m in mismatched[:10]:
        print("   MISMATCH", m)
    print(f"wrong-voice clips  : {len(quarantined)} quarantined")
    for q in quarantined[:10]:
        print("   MOVED", q)

    if missing or mismatched:
        print("\nRefusing to write: resolve the problems above first.")
        return 1

    if args.dry_run:
        print("\nDry run complete; nothing written.")
        return 0

    if applied:
        if not BACKUP_PATH.exists():
            shutil.copy2(MAPPING_PATH, BACKUP_PATH)
            print(f"backup written     : {BACKUP_PATH.name}")
        MAPPING_PATH.write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote              : {MAPPING_PATH.name}")
    else:
        print("\nMapping already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
