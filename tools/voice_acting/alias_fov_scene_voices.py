#!/usr/bin/env python3
"""Make engine-requested voice filenames serve the correct FoV scene voices.

The game engine keys voice lookup by the *face NPC* (from show_npc_face), not
by the true speaker. During the Forge-of-Virtue mirror/gem scenes the face
shown is the gem face (npc 291) or the Dark Core portrait (npc 292), so the
engine requests ``_npc291``/``_npc292`` names even though the true speaker is
Arcadion (npc 273) or Erethian (npc 286). Historically those names were voiced
by Dark Core/Hook -- the stale shadows the player still hears.

This script hard-links the correct clip under every name the engine may request
for each scene row, and removes orphaned stale shadows whose key no longer maps
to an Arcadion/Erethian row. Idempotent.

Engine alias policy (safe because npc291/npc292 files exist ONLY in 0x06F6 and
0x009A -- no legit Hook/Dark Core dialogue elsewhere):
  - Arcadion (npc 290) 0x06F6 + 0x009A rows -> also provide _npc291, _npc292
  - Erethian 0x009A rows           -> also provide _npc292
  - orphan _npc291/_npc292 files   -> remove
"""
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import generate_qwen3_voice as G

VOICE_ROOT = SCRIPT_DIR.parent.parent / "voice"


def main():
    data, _ = G.load_mapping()
    expanded = []
    for e in data:
        expanded.extend(G.expand_entry_for_voice_speakers(e))

    made = 0
    removed = 0
    for e in expanded:
        fid = (e.get("en_func_id") or "").lower()
        if fid not in ("0x06f6", "0x009a"):
            continue
        npc = e.get("npc") or ""
        target = None
        aliases = []
        if npc == "Arcadion":
            target = "npc290"
            aliases = ["npc290", "npc291", "npc292"]
        elif npc == "Erethian":
            target = "npc286"
            aliases = ["npc286", "npc292"]
        else:
            continue
        for lang in ("zh", "en"):
            t = (e.get(f"{lang}_text") or "").strip()
            if not t or lang in (e.get("_invalid_runtime_keys") or []):
                continue
            out = VOICE_ROOT / lang
            src = out / G.make_filename(e, lang)
            if not src.exists():
                continue
            # find a valid alias source if the canonical target name is absent
            if not src.name.endswith(f"_{target}.ogg"):
                cand = out / (G.make_filename(e, lang).rsplit("_", 1)[0] + f"_{target}.ogg")
                if cand.exists():
                    src = cand
                else:
                    continue
            for alias in aliases:
                dest_name = G.make_filename(e, lang).rsplit("_", 1)[0] + f"_{alias}.ogg"
                dest = out / dest_name
                if dest.exists():
                    if os.path.samefile(dest, src):
                        continue
                    os.remove(dest)
                os.link(src, dest)
                made += 1

    # Remove orphaned stale npc291/npc292 shadows in the scene funcs.
    for lang in ("zh", "en"):
        out = VOICE_ROOT / lang
        valid = set()
        for e in expanded:
            fid = (e.get("en_func_id") or "").lower()
            if fid not in ("0x06f6", "0x009a"):
                continue
            if (e.get("npc") or "") not in ("Arcadion", "Erethian"):
                continue
            t = (e.get("zh_text") if lang == "zh" else e.get("en_text")) or ""
            if not t.strip():
                continue
            base = G.make_filename(e, lang).rsplit("_", 1)[0]
            for a in ("npc291", "npc292"):
                valid.add(f"{base}_{a}.ogg")
        for f in list(out.glob("06f6_*_npc29[12].ogg")) + list(out.glob("009a_*_npc29[12].ogg")):
            if f.name not in valid:
                os.remove(f)
                removed += 1

    print(f"created aliases: {made}")
    print(f"removed orphans: {removed}")


if __name__ == "__main__":
    main()
