#!/usr/bin/env python3
"""
Patch script for voice acting issues:
- Anmanivas: Smooth out dialogue/narration based on en_text
- Dracothraxus: Complete untranslated English narration prefix in zh_text
- Zorn: Translate missing zh_text

Targets are matched by content (npc + en_offset_key + zh_text), NOT by
hardcoded index — the index layout shifts whenever alignment changes.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MAPPING_PATH = SCRIPT_DIR / "bilingual_mapping_review.json"
BACKUP_PATH = SCRIPT_DIR / f"bilingual_mapping_review.json.pre_voice_issue_fix"

# Keyed by (npc, en_offset_key). Match old_zh_text to verify we have the
# right row before patching (guards against index drift).
FIXES = [
    {
        "npc": "Anmanivas",
        "en_offset_key": "197_19a_19d",
        "old_zh_text": "「\"聖者！」聖者 「是造成我們不快樂的原因。」",
        "new_zh_text": "「人類！」他指著你和你的同伴說，「是造成我們不快樂的原因。」",
        "reason": "Adjust Chinese text based on en_text to smooth grammar and balance delimiters"
    },
    {
        "npc": "Dracothraxus",
        "en_offset_key": "1fe",
        "old_zh_text": "Dracothraxus sniffs the air distastefully, 「我聞到了毀滅的氣息。或許，我終於要獲得自由了。祝你好運，凡人。自求多福吧！」說完，巨龍便撲向了你。",
        "new_zh_text": "Dracothraxus 厭惡地嗅了嗅空氣，「我聞到了毀滅的氣息。或許，我終於要獲得自由了。祝你好運，凡人。自求多福吧！」說完，巨龍便撲向了你。",
        "reason": "Translate English narration prefix into Traditional Chinese"
    },
    {
        "npc": "Zorn",
        "en_offset_key": "b7d",
        "old_zh_text": "Zorn dips the helmet in water to cool it.",
        "new_zh_text": "Zorn 將頭盔浸入水中冷卻。",
        "reason": "Translate untranslated en_text in zh_text field"
    },
    {
        "npc": "Zorn",
        "en_offset_key": "c12",
        "old_zh_text": "He hands you the helmet.",
        "new_zh_text": "他將頭盔遞給你。",
        "reason": "Translate untranslated en_text in zh_text field"
    }
]


def main():
    if not MAPPING_PATH.exists():
        print(f"Error: {MAPPING_PATH} does not exist.")
        return 1

    print(f"Creating backup: {BACKUP_PATH.name}")
    shutil.copy2(MAPPING_PATH, BACKUP_PATH)

    with MAPPING_PATH.open("r", encoding="utf-8") as f:
        mapping = json.load(f)

    timestamp = datetime.now().isoformat()
    modified_count = 0

    for fix_info in FIXES:
        # Locate the target row by content
        matches = [
            item for item in mapping
            if item.get("npc") == fix_info["npc"]
            and str(item.get("en_offset_key", "")) == fix_info["en_offset_key"]
            and (item.get("zh_text") or "") == fix_info["old_zh_text"]
        ]
        if not matches:
            # Fallback: match by npc + offset even if zh_text drifted
            matches = [
                item for item in mapping
                if item.get("npc") == fix_info["npc"]
                and str(item.get("en_offset_key", "")) == fix_info["en_offset_key"]
            ]
        if not matches:
            print(f"WARNING: no match for {fix_info['npc']} {fix_info['en_offset_key']} — skipping")
            continue
        item = matches[0]
        old_val = item.get("zh_text")
        new_val = fix_info["new_zh_text"]
        item["zh_text"] = new_val
        item["_voice_fix_marked"] = {
            "timestamp": timestamp,
            "reason": fix_info["reason"],
            "old_zh_text": old_val,
            "new_zh_text": new_val
        }
        modified_count += 1
        print(f"Patched {fix_info['npc']} ({fix_info['en_offset_key']}):")
        print(f"  Old: {old_val}")
        print(f"  New: {new_val}")

    with MAPPING_PATH.open("w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"\nSuccessfully patched {modified_count} entries in {MAPPING_PATH.name}")
    return 0


if __name__ == "__main__":
    main()
