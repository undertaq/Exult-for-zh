#!/usr/bin/env python3
"""
Backup and remove generic fallback voice files from voice/zh.
Move 5,301 base.ogg files into voice/zh_generic_backup/.
"""

import shutil
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
ZH_DIR = PROJECT_DIR / "voice" / "zh"
BACKUP_DIR = PROJECT_DIR / "voice" / "zh_generic_backup"

def main():
    if not ZH_DIR.exists():
        print(f"Error: Directory {ZH_DIR} does not exist.")
        return 1

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    generic_files = [
        f for f in ZH_DIR.glob("*.ogg")
        if "_npc" not in f.name and "_avatar" not in f.name
    ]

    print(f"Found {len(generic_files)} generic fallback files in {ZH_DIR}")
    print(f"Moving generic files to backup directory: {BACKUP_DIR}...")

    moved_count = 0
    for file_path in generic_files:
        dest_path = BACKUP_DIR / file_path.name
        shutil.move(str(file_path), str(dest_path))
        moved_count += 1

    print(f"\nSuccessfully moved {moved_count} generic voice files to {BACKUP_DIR}")

    # Verify counts
    remaining_zh = len(list(ZH_DIR.glob("*.ogg")))
    backed_up = len(list(BACKUP_DIR.glob("*.ogg")))
    print("============================================================")
    print(f"Final Count - voice/zh: {remaining_zh} files")
    print(f"Final Count - voice/zh_generic_backup: {backed_up} files")
    print("============================================================")
    return 0

if __name__ == "__main__":
    main()
