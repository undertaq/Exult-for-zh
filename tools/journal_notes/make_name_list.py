#!/usr/bin/env python3
"""
Generate tools/journal_notes/name_place_list.txt - the canonical English
proper-noun list (NPC names + place names) used when repairing the zh
auto-notes: any occurrence of these names in a zh entry must stay in
English, never translated or transliterated.

Sources:
  - NPC names: tools/voice_acting/npc_data.py NPC_NUMBERS keys, plus every
    name seen in [npc=...] tags of the autonotes files.
  - Place names: curated list of Britannia locations + every proper-noun
    phrase extracted from the English autonotes (frequency filter).
"""

import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "voice_acting"))

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "name_place_list.txt")

# ---- NPC names -----------------------------------------------------------
try:
    from npc_data import NPC_NUMBERS  # noqa: E402
    npc_names = set(NPC_NUMBERS.keys())
except ImportError:
    npc_names = set()

# every [npc=...] tag in the outputs
for f in ("data/bg/autonotes.txt", "data/bg/autonotes_zh.txt"):
    p = os.path.join(ROOT, f)
    if os.path.exists(p):
        for ln in open(p, encoding="utf-8", newline="").read().split("\r\n"):
            for m in re.finditer(r"\[npc=([^\]]+)\]", ln):
                npc_names.add(m.group(1).strip())

# ---- Place names (curated Ultima VII: Black Gate) -----------------------
places = set("""
Trinsic
Britain
Minoc
Cove
Paws
Yew
Skara Brae
Moonglow
New Magincia
Jhelom
Vesper
Buccaneer's Den
Serpent's Spine
Black Gate
Britannia
Terfin
Isle of Fire
Empath Abbey
Fellowship Hall
Castle Britannia
Lord British's Castle
Hook Den
Moongates
Serpent Spine
Passage of
Wrong
Deceit
Despise
Destard
Covetous
Shame
Hythloth
Doom
Blackrock
Golem Book
Star of Unity
Ophidian
Pothole
Shrine of Truth
Shrine of Courage
Shrine of Principles
Temple of Love
Temple of Spirituality
Temple of Sacrifice
Temple of Honesty
Isle of the Avatar
Monastery
Island of the Avatar
Time Lord
Ferryman
Golem
Shadowblade
Crown Jewels
Magic Storm
Armageddon
Great Earth Serpent
Great Water Serpent
Scroll of Infinity
Talisman of Infinity
Orb of the Moons
""".splitlines())

# ---- proper-noun phrases from the English entries -----------------------
proper = Counter()
phrase_re = re.compile(r"\b([A-Z][A-Za-z']+(?:\s+[A-Z][A-Za-z']+){0,2})\b")
for p in ("data/bg/autonotes.txt",):
    path = os.path.join(ROOT, p)
    if not os.path.exists(path):
        continue
    for ln in open(path, encoding="utf-8", newline="").read().split("\r\n"):
        m = re.match(r"^(?:#\s*)?(?:0x[0-9A-Fa-f]+)\s*:\s*(.*)$", ln)
        if not m:
            continue
        text = re.sub(r"\[npc=[^\]]*\]", "", m.group(1))
        for ph in phrase_re.findall(text):
            proper[ph] += 1

# phrases seen 2+ times that look like names/places (multi-word only)
for ph, n in proper.most_common():
    if n >= 2 and " " in ph:
        places.add(ph)

# ---- write ---------------------------------------------------------------
lines = []
lines.append("# Canonical English proper-noun list (NPC names + place names).")
lines.append("# Used by the autonote zh repair pass: these names must stay in English")
lines.append("# in the Chinese auto-notes - never translated.")
lines.append("# [NPC]")
for n in sorted(npc_names):
    if n and n != "npc":
        lines.append(n)
lines.append("# [PLACE]")
for p in sorted(places):
    if p and p not in npc_names:
        lines.append(p)

with open(OUT, "w", encoding="utf-8", newline="\r\n") as f:
    f.write("\r\n".join(lines) + "\r\n")
print(f"wrote {OUT}: {len(npc_names)} NPC names, {len(places)} places/phrases")
