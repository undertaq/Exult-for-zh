#!/usr/bin/env python3
"""
Generate ONLY the missing voice files on disk without touching existing voice files.
Ultra-fast zero-dependency file-existence audit.
"""

import os
import sys
import json
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent.parent
PYTHON_BIN = Path.home() / "project/qwen3-tts/.venv/bin/python"

if "qwen3-tts" not in sys.executable:
    if PYTHON_BIN.exists():
        os.execv(str(PYTHON_BIN), [str(PYTHON_BIN)] + sys.argv)

def make_filename(entry, lang="zh", npc_numbers=None):
    if npc_numbers is None:
        sys.path.insert(0, str(SCRIPT_DIR))
        from npc_data import NPC_NUMBERS
        npc_numbers = NPC_NUMBERS

    npc = entry.get("npc", "")
    npc_num = npc_numbers.get(npc)
    npc_suffix = f"_npc{npc_num}" if npc_num is not None else ""

    avatar_gender = entry.get("_avatar_voice_gender")

    if lang == "zh" and not (entry.get("zh_text", "") or "").strip() and (entry.get("en_func_id", "") and entry.get("en_offset_key", "")):
        fid = entry.get("en_func_id", "") or "0000"
        ok = entry.get("en_offset_key", "") or "0"
        seg = entry.get("en_segment", 0) or 0
    elif lang == "en" and not (entry.get("en_text", "") or "").strip() and (entry.get("zh_func_id", "") and entry.get("zh_offset_key", "")):
        fid = entry.get("zh_func_id", "") or "0000"
        ok = entry.get("zh_offset_key", "") or "0"
        seg = entry.get("zh_segment", 0) or 0
    else:
        fid = entry.get(f"{lang}_func_id", "") or entry.get("zh_func_id", "") or entry.get("en_func_id", "") or "0000"
        ok = entry.get(f"{lang}_offset_key", "") or "0"
        seg = entry.get(f"{lang}_segment", 0) or 0

    if isinstance(fid, str) and fid.lower().startswith("0x"):
        fid = fid[2:]
    base = f"{str(fid).lower().zfill(4)}_{ok}_{seg}"

    if avatar_gender in ("male", "female"):
        return f"{base}_avatar_{avatar_gender}.ogg"
    return f"{base}{npc_suffix}.ogg"

def get_missing_entries():
    sys.path.insert(0, str(SCRIPT_DIR))
    from npc_data import NPC_NUMBERS

    mapping_file = SCRIPT_DIR / "bilingual_mapping_review.json"
    with open(mapping_file, encoding="utf-8") as f:
        data = json.load(f)

    zh_dir = PROJECT_DIR / "voice" / "zh"
    en_dir = PROJECT_DIR / "voice" / "en"

    missing_npcs = set()
    missing_count = 0

    for entry in data:
        if (entry.get("voice_generation") or "").strip() == "skip":
            continue
        npc_name = entry.get("npc", "")
        for lang in ["zh", "en"]:
            text = (entry.get(f"{lang}_text", "") or "").strip()
            if not text:
                continue
            fname = make_filename(entry, lang=lang, npc_numbers=NPC_NUMBERS)
            generic_fname = make_filename(entry, lang=lang, npc_numbers={})
            target_dir = zh_dir if lang == "zh" else en_dir
            p1 = target_dir / fname
            p2 = target_dir / generic_fname
            if not (p1.exists() or p2.exists()):
                missing_npcs.add(npc_name)
                missing_count += 1

    return sorted(list(missing_npcs)), missing_count

def main():
    missing_npcs, missing_count = get_missing_entries()
    if not missing_npcs:
        print("All voice files exist! No missing files to generate.")
        return 0

    npc_filter = ",".join(missing_npcs)
    print(f"============================================================")
    print(f"Fast Audit Complete: Found {missing_count} missing voice files across {len(missing_npcs)} NPCs.")
    print(f"Target NPCs: {npc_filter}")
    print("============================================================\n")

    cmd = [
        str(PYTHON_BIN),
        "-u",
        str(SCRIPT_DIR / "generate_qwen3_voice.py"),
        "--phase", "voice",
        "--npc", npc_filter,
        "--generic-fallbacks",
        "--device", "cuda:0"
    ]

    res = subprocess.run(cmd, cwd=str(SCRIPT_DIR))
    if res.returncode != 0:
        print(f"\nError: Voice generation failed with exit code {res.returncode}")
        return res.returncode

    print("\nGeneration of missing voice files complete.")

    # Sync generated voice files to Exult runtime patch directory
    sync_cmd = [
        str(PYTHON_BIN),
        str(SCRIPT_DIR / "sync_voice_output_to_patch.py"),
        "--lang", "all"
    ]
    print("\nSyncing voice files to Exult runtime patch directory...")
    sync_res = subprocess.run(sync_cmd, cwd=str(SCRIPT_DIR))
    if sync_res.returncode != 0:
        print(f"Error: Sync failed with exit code {sync_res.returncode}")
        return sync_res.returncode

    print("Successfully synced all voice files to patch directory!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
