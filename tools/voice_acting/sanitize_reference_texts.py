#!/usr/bin/env python3
"""Replace leak-prone reference transcripts with neutral calibration text."""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_reference_leak_risk import (
    DEFAULT_DESIGNS,
    DEFAULT_MAPPING,
    audit_reference_leak_risk,
    load_designs,
    load_mapping,
)


PROJECT_DIR = Path(__file__).resolve().parents[2]
BACKUP_DIR = PROJECT_DIR / "voice_backup"


NEUTRAL_REFS = {
    "zh": {
        "unique": "我會保持這個聲音，平穩而清楚地說話。請聽我慢慢說完這段話，語氣自然，停頓分明，心情安定。",
        "group": "我會用這個聲音清楚表達每一句話。語速自然，停頓分明，情緒穩定，讓聽者容易辨認我的語調。",
        "narrator": "畫面在眼前展開，聲音平穩地描述正在發生的事情。每個詞都清楚自然，節奏從容，語氣可靠。",
    },
    "en": {
        "unique": "I will keep this voice steady and clear. Please listen as I speak at a natural pace, with calm pauses and consistent tone.",
        "group": "I will use this voice to speak each sentence clearly. The pace is natural, the pauses are balanced, and the tone remains easy to recognize.",
        "narrator": "The scene unfolds before us, and the voice describes it with steady rhythm, clear words, and a calm, reliable tone.",
    },
}


def neutral_reference_text(lang, design):
    design_type = design.get("type", "unique")
    if design_type not in NEUTRAL_REFS[lang]:
        design_type = "unique"
    return NEUTRAL_REFS[lang][design_type]


def sanitize_designs_payload(payload, findings):
    result = json.loads(json.dumps(payload, ensure_ascii=False))
    designs = result.get("designs", result)
    changed = []
    for finding in findings:
        design = designs.get(finding["design_id"])
        if not design:
            continue
        key = f"ref_{finding['lang']}_text"
        replacement = neutral_reference_text(finding["lang"], design)
        if design.get(key) == replacement:
            continue
        changed.append({
            "design_id": finding["design_id"],
            "npc": design.get("npc", finding["design_id"]),
            "lang": finding["lang"],
            "score": finding["score"],
            "old_text": design.get(key, ""),
            "new_text": replacement,
        })
        design[key] = replacement
    return result, changed


def backup_file(path, backup_dir=BACKUP_DIR):
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{path.stem}_before_ref_sanitize_{stamp}{path.suffix}"
    shutil.copy2(path, backup_path)
    return backup_path


def main():
    parser = argparse.ArgumentParser(description="Sanitize risky voice reference transcripts.")
    parser.add_argument("--designs", default=str(DEFAULT_DESIGNS))
    parser.add_argument("--mapping", default=str(DEFAULT_MAPPING))
    parser.add_argument("--min-score", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--changes-json", default=str(PROJECT_DIR / "voice" / "review_samples" / "full_generated_review" / "reference_text_sanitize_changes.json"))
    args = parser.parse_args()

    designs_path = Path(args.designs)
    with open(designs_path, encoding="utf-8") as f:
        payload = json.load(f)

    findings = audit_reference_leak_risk(
        load_designs(designs_path),
        load_mapping(Path(args.mapping)),
        min_score=args.min_score,
    )
    sanitized, changes = sanitize_designs_payload(payload, findings)

    changes_path = Path(args.changes_json)
    changes_path.parent.mkdir(parents=True, exist_ok=True)
    changes_path.write_text(json.dumps({"changes": changes}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not args.dry_run and changes:
        backup_path = backup_file(designs_path)
        designs_path.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Backed up {designs_path} to {backup_path}")

    print(f"Findings: {len(findings)}")
    print(f"Changed refs: {len(changes)}")
    print(f"Wrote {changes_path}")


if __name__ == "__main__":
    main()
