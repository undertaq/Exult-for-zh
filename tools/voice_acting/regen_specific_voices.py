#!/usr/bin/env python3
"""
Regenerate voice files ONLY for the specified NPCs (Jesse, Anmanivas, Dracothraxus, Zorn).
"""

import os
import sys
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent.parent
PYTHON_BIN = Path.home() / "project/qwen3-tts/.venv/bin/python"

if not PYTHON_BIN.exists():
    PYTHON_BIN = SCRIPT_DIR / ".venv/bin/python3"

TARGET_NPCS = "Jesse,Anmanivas,Dracothraxus,Zorn"

def main():
    cmd = [
        str(PYTHON_BIN),
        "-u",
        str(SCRIPT_DIR / "generate_qwen3_voice.py"),
        "--phase", "voice",
        "--npc", TARGET_NPCS,
        "--force",
        "--generic-fallbacks",
        "--device", "cuda:0"
    ]
    print(f"Executing voice regeneration for: {TARGET_NPCS}")
    print(f"Command: {' '.join(cmd)}")
    
    res = subprocess.run(cmd, cwd=str(SCRIPT_DIR))
    if res.returncode != 0:
        print(f"Voice generation failed with exit code {res.returncode}")
        return res.returncode

    print("Voice generation complete for target NPCs.")

    # Now run sync to patch directory
    sync_cmd = [
        sys.executable,
        str(SCRIPT_DIR / "sync_voice_output_to_patch.py"),
        "--lang", "all"
    ]
    print(f"\nSyncing voice files to patch directory...")
    sync_res = subprocess.run(sync_cmd, cwd=str(SCRIPT_DIR))
    if sync_res.returncode != 0:
        print(f"Sync failed with exit code {sync_res.returncode}")
        return sync_res.returncode

    print("Successfully synced regenerated voice files to patch directory!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
