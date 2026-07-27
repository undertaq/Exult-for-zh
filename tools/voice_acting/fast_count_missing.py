#!/usr/bin/env python3
import json
from pathlib import Path

VOICE_DIR = Path(__file__).resolve().parents[2] / "voice"
MAPPING_FILE = Path(__file__).resolve().parent / "bilingual_mapping_review.json"

with open(MAPPING_FILE, encoding="utf-8") as f:
    data = json.load(f)

# Load NPC numbers
try:
    from npc_data import NPC_NUMBERS
except ImportError:
    NPC_NUMBERS = {}

missing_zh = 0
missing_en = 0
total_zh = 0
total_en = 0

for entry in data:
    npc = entry.get("npc", "")
    npc_num = NPC_NUMBERS.get(npc)
    npc_suffix = f"_npc{npc_num}" if npc_num is not None else ""

    for lang in ["zh", "en"]:
        text = str(entry.get(f"{lang}_text", "") or "").strip()
        if not text:
            continue

        if lang == "zh":
            total_zh += 1
        else:
            total_en += 1

        fid = entry.get(f"{lang}_func_id", "") or entry.get("zh_func_id", "") or entry.get("en_func_id", "") or "0000"
        if isinstance(fid, str) and fid.lower().startswith("0x"):
            fid = fid[2:]
        ok = entry.get(f"{lang}_offset_key", "") or "0"
        seg = entry.get(f"{lang}_segment", 0) or 0
        base = f"{str(fid).lower().zfill(4)}_{ok}_{seg}"

        fname = f"{base}{npc_suffix}.ogg"
        generic_fname = f"{base}.ogg"

        p1 = VOICE_DIR / lang / fname
        p2 = VOICE_DIR / lang / generic_fname

        if not p1.exists() and not p2.exists():
            if lang == "zh":
                missing_zh += 1
            else:
                missing_en += 1

print(f"Total ZH entries: {total_zh}, Missing on disk: {missing_zh}")
print(f"Total EN entries: {total_en}, Missing on disk: {missing_en}")
print(f"Total Missing: {missing_zh + missing_en}")
