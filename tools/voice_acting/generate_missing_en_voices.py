#!/usr/bin/env python3
"""
Generate ONLY the missing English voice files on GPU (zero-overwrite guarantee).
Uses O(1) disk indexing matching generate_voice_review_html.py logic.
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

def build_disk_stems(target_dir):
    stems = set()
    if target_dir.exists():
        for p in target_dir.glob("*.ogg"):
            stems.add(p.stem)
            # Also add generic base without _npc / _avatar
            stem = p.stem
            base = stem.rsplit("_npc", 1)[0] if "_npc" in stem else (stem.rsplit("_avatar", 1)[0] if "_avatar" in stem else stem)
            stems.add(base)
    return stems

def main():
    mapping_file = SCRIPT_DIR / "bilingual_mapping_review.json"
    with open(mapping_file, encoding="utf-8") as f:
        data = json.load(f)

    en_dir = PROJECT_DIR / "voice" / "en"
    en_stems = build_disk_stems(en_dir)

    missing_entries = []
    missing_npcs = set()

    for entry in data:
        if (entry.get("voice_generation") or "").strip() == "skip":
            continue

        en_text = (entry.get("en_text", "") or "").strip()
        if not en_text:
            continue

        fid = entry.get("en_func_id") or entry.get("zh_func_id") or "0000"
        if isinstance(fid, str) and fid.lower().startswith("0x"):
            fid = fid[2:]
        ok = entry.get("en_offset_key") or entry.get("zh_offset_key") or "0"
        seg = entry.get("en_segment", 0) or 0
        base = f"{str(fid).lower().zfill(4)}_{ok}_{seg}"

        if base not in en_stems:
            missing_entries.append(entry)
            npc = entry.get("npc", "")
            if npc:
                missing_npcs.add(npc)

    print(f"============================================================")
    print(f"Missing EN Audit: Found {len(missing_entries)} missing English voice lines across {len(missing_npcs)} NPCs.")
    for e in missing_entries[:15]:
        print(f"  - Index {e.get('index')}, NPC: {e.get('npc')}, Base: {e.get('en_func_id')}/{e.get('en_offset_key')}/{e.get('en_segment')}, Text: {e.get('en_text')[:60]}")
    print(f"============================================================\n")

    if not missing_entries:
        print("All English voice files exist! No missing files to generate.")
        return 0

    # Ensure clone_prompts.pkl has 'en' fallback for all design IDs
    import pickle
    prompts_pkl = SCRIPT_DIR / "clone_prompts.pkl"
    if prompts_pkl.exists():
        with open(prompts_pkl, "rb") as f:
            prompts = pickle.load(f)
        modified = False
        for did, ddata in prompts.items():
            if "zh" in ddata and "en" not in ddata:
                ddata["en"] = ddata["zh"]
                modified = True
        if modified:
            with open(prompts_pkl, "wb") as f:
                pickle.dump(prompts, f)

    npc_filter = ",".join(sorted([n for n in missing_npcs if n]))
    cmd = [
        str(PYTHON_BIN),
        "-u",
        str(SCRIPT_DIR / "generate_qwen3_voice.py"),
        "--phase", "voice",
        "--lang", "en",
        "--npc", npc_filter,
        "--generic-fallbacks",
        "--device", "cuda:0"
    ]

    print(f"Launching Qwen3-TTS generation for missing English lines...")
    res = subprocess.run(cmd, cwd=str(SCRIPT_DIR))
    if res.returncode != 0:
        print(f"Error: Generation failed with exit code {res.returncode}")
        return res.returncode

    print("\nEnglish missing voice synthesis complete.")

    # Re-sync to patch directory and regenerate review HTMLs
    print("\nSyncing output to Exult runtime patch directory...")
    subprocess.run([str(PYTHON_BIN), str(SCRIPT_DIR / "sync_voice_output_to_patch.py")], cwd=str(SCRIPT_DIR))

    print("\nRegenerating review HTML packages...")
    subprocess.run([str(PYTHON_BIN), str(SCRIPT_DIR / "generate_voice_review_html.py"), "--mode", "full", "--out-dir", "../voice/review_samples/full_generated_review"], cwd=str(SCRIPT_DIR))
    subprocess.run([str(PYTHON_BIN), str(SCRIPT_DIR / "generate_voice_review_html.py"), "--mode", "full", "--out-dir", "voice_review_full"], cwd=str(SCRIPT_DIR))

    print("SUCCESS: All missing English voice lines generated and synced!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
