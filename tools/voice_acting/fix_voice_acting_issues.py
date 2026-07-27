#!/usr/bin/env python3
"""
Patch script for voice acting issues:
- Anmanivas (index 6146): Smooth out dialogue/narration based on en_text
- Dracothraxus (index 143): Complete untranslated English narration prefix in zh_text
- Zorn (index 2698 & 2699): Translate missing zh_text
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MAPPING_PATH = SCRIPT_DIR / "bilingual_mapping_review.json"
BACKUP_PATH = SCRIPT_DIR / f"bilingual_mapping_review.json.pre_voice_issue_fix"

FIXES = {
    6146: {
        "npc": "Anmanivas",
        "old_zh_text": "「\"聖者！」聖者 「是造成我們不快樂的原因。」",
        "new_zh_text": "「人類！」他指著你和你的同伴說，「是造成我們不快樂的原因。」",
        "reason": "Adjust Chinese text based on en_text to smooth grammar and balance delimiters"
    },
    143: {
        "npc": "Dracothraxus",
        "old_zh_text": "Dracothraxus sniffs the air distastefully, 「我聞到了毀滅的氣息。或許，我終於要獲得自由了。祝你好運，凡人。自求多福吧！」說完，巨龍便撲向了你。",
        "new_zh_text": "Dracothraxus 厭惡地嗅了嗅空氣，「我聞到了毀滅的氣息。或許，我終於要獲得自由了。祝你好運，凡人。自求多福吧！」說完，巨龍便撲向了你。",
        "reason": "Translate English narration prefix into Traditional Chinese"
    },
    2698: {
        "npc": "Zorn",
        "old_zh_text": "Zorn dips the helmet in water to cool it.",
        "new_zh_text": "Zorn 將頭盔浸入水中冷卻。",
        "reason": "Translate untranslated en_text in zh_text field"
    },
    2699: {
        "npc": "Zorn",
        "old_zh_text": "He hands you the helmet.",
        "new_zh_text": "他將頭盔遞給你。",
        "reason": "Translate untranslated en_text in zh_text field"
    }
}

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

    for item in mapping:
        idx = item.get("index")
        if idx in FIXES:
            fix_info = FIXES[idx]
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
            print(f"Patched Index {idx} ({fix_info['npc']}):")
            print(f"  Old: {old_val}")
            print(f"  New: {new_val}")

    with MAPPING_PATH.open("w", encoding="utf-8") as f:
        json.dumps(mapping)
        json.dump(mapping, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"\nSuccessfully patched {modified_count} entries in {MAPPING_PATH.name}")
    return 0

if __name__ == "__main__":
    main()
