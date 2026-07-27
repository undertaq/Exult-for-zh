#!/usr/bin/env python3
"""
Split tilde-delimited (~ / ～) dialogue lines into distinct segment rows in bilingual_mapping_review.json.
Preserves segment 0 for existing audio files, creating new rows for segment 1, 2...
"""

import json
from copy import deepcopy
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MAPPING_FILE = SCRIPT_DIR / "bilingual_mapping_review.json"
BACKUP_FILE = SCRIPT_DIR / "bilingual_mapping_review.json.pre_tilde_split"

def split_text_by_tilde(text):
    if not text:
        return []
    # Replace full-width tilde and standard tilde
    clean_text = str(text).replace("～", "~").replace("∼", "~").replace("〜", "~")
    parts = [p.strip() for p in clean_text.split("~") if p.strip()]
    return parts

def main():
    if not MAPPING_FILE.exists():
        print(f"Error: {MAPPING_FILE} not found.")
        return 1

    with open(MAPPING_FILE, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    # Backup original
    with open(BACKUP_FILE, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    print(f"Backed up original mapping to {BACKUP_FILE}")

    new_mapping = []
    split_count = 0
    new_rows_added = 0

    for entry in mapping:
        zh_text = entry.get("zh_text", "")
        en_text = entry.get("en_text", "")
        zh_raw = entry.get("zh_raw", "")
        en_raw = entry.get("en_raw", "")

        zh_check = zh_text if zh_text else zh_raw
        en_check = en_text if en_text else en_raw

        zh_parts = split_text_by_tilde(zh_check)
        en_parts = split_text_by_tilde(en_check)

        # Check if either language has multiple tilde segments
        if len(zh_parts) > 1 or len(en_parts) > 1:
            split_count += 1
            max_segs = max(len(zh_parts), len(en_parts))

            base_seg = int(entry.get("zh_segment", 0))

            for s_idx in range(max_segs):
                row = deepcopy(entry)
                row["zh_segment"] = base_seg + s_idx
                row["en_segment"] = base_seg + s_idx

                zh_seg_text = zh_parts[s_idx] if s_idx < len(zh_parts) else (zh_parts[-1] if zh_parts else "")
                en_seg_text = en_parts[s_idx] if s_idx < len(en_parts) else (en_parts[-1] if en_parts else "")

                row["zh_text"] = zh_seg_text
                row["en_text"] = en_seg_text
                if "zh_raw" in row:
                    row["zh_raw"] = zh_seg_text
                if "en_raw" in row:
                    row["en_raw"] = en_seg_text

                # If this is segment 1+, adjust NPC to narrator if action text
                if s_idx > 0:
                    new_rows_added += 1
                    # Give distinct index if needed or format string
                    row["confidence"] = "tilde_split_segment"

                new_mapping.append(row)
        else:
            new_mapping.append(entry)

    # Re-index mapping entries cleanly
    for idx, row in enumerate(new_mapping, start=1):
        row["index"] = idx

    with open(MAPPING_FILE, "w", encoding="utf-8") as f:
        json.dump(new_mapping, f, ensure_ascii=False, indent=2)

    print("============================================================")
    print(f"Total entries processed: {len(mapping)}")
    print(f"Total entries split: {split_count}")
    print(f"New segment rows added: {new_rows_added}")
    print(f"Final mapping rows: {len(new_mapping)}")
    print("============================================================")
    return 0

if __name__ == "__main__":
    main()
