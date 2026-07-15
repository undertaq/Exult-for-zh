#!/usr/bin/env python3
"""Sync per-NPC reference-voice prompts into bilingual_mapping_review.json.

The new reference-voice integration stores each NPC's voice description in
``npc_voice_designs.json`` as ``voice_desc_en`` / ``voice_desc_zh``. This tool
copies those into every mapping row:

  * ``voice_prompt``     <- design.voice_desc_en
  * ``voice_prompt_zh``  <- design.voice_desc_zh   (new field)

Only those two keys are touched; every other field (including ``zh_text`` and
all runtime-identity keys) is preserved. Rows whose NPC cannot be resolved are
left untouched and reported.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MAPPING = SCRIPT_DIR / "bilingual_mapping_review.json"
DEFAULT_DESIGNS = SCRIPT_DIR / "npc_voice_designs.json"

SPECIAL_ROUTES = {
    "": "npc_unknown",
    "UNKNOWN": "npc_unknown",
    "Avatar": "npc_avatar_male",
}


def build_npc_to_prompt_map(designs: dict) -> dict[str, tuple[str, str]]:
    """Map NPC name -> (voice_desc_en, voice_desc_zh) from voice designs.

    Each design's ``npcs`` list is expanded into the map. Special names
    (generic ``Avatar``, empty, ``UNKNOWN``) route to their canonical design.
    """
    prompt_map: dict[str, tuple[str, str]] = {}
    design_lookup = designs.get("designs", {})

    for did, design in design_lookup.items():
        en = (design.get("voice_desc_en") or "").strip()
        zh = (design.get("voice_desc_zh") or "").strip()
        if not en and not zh:
            continue
        for npc in design.get("npcs", []) or []:
            name = (npc or "").strip()
            if name:
                prompt_map[name] = (en, zh)

    for alias, target_did in SPECIAL_ROUTES.items():
        target = design_lookup.get(target_did)
        if not target:
            continue
        en = (target.get("voice_desc_en") or "").strip()
        zh = (target.get("voice_desc_zh") or "").strip()
        if en or zh:
            prompt_map[alias] = (en, zh)

    return prompt_map


def sync_row(row: dict, prompt_map: dict[str, tuple[str, str]]) -> tuple[bool, bool]:
    """Update ``voice_prompt`` / ``voice_prompt_zh`` in place.

    Returns (changed_en, changed_zh). Rows whose NPC is not in the map are
    left untouched.
    """
    npc = (row.get("npc") or "").strip()
    if npc not in prompt_map:
        return False, False
    en, zh = prompt_map[npc]
    changed_en = row.get("voice_prompt") != en
    changed_zh = row.get("voice_prompt_zh") != zh
    if changed_en:
        row["voice_prompt"] = en
    if changed_zh:
        row["voice_prompt_zh"] = zh
    return changed_en, changed_zh


def sync_mapping(mapping: list[dict], prompt_map: dict[str, tuple[str, str]]) -> dict:
    """Return counts: changed_en, changed_zh, unchanged, unresolved."""
    counts = {"changed_en": 0, "changed_zh": 0, "unchanged": 0, "unresolved": 0}
    for row in mapping:
        npc = (row.get("npc") or "").strip()
        if npc not in prompt_map:
            counts["unresolved"] += 1
            continue
        changed_en, changed_zh = sync_row(row, prompt_map)
        if changed_en:
            counts["changed_en"] += 1
        if changed_zh:
            counts["changed_zh"] += 1
        if not changed_en and not changed_zh:
            counts["unchanged"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--designs", type=Path, default=DEFAULT_DESIGNS)
    parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing")
    args = parser.parse_args(argv)

    designs = json.loads(args.designs.read_text(encoding="utf-8"))
    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))

    prompt_map = build_npc_to_prompt_map(designs)
    counts = sync_mapping(mapping, prompt_map)

    print(
        f"Resolved NPCs: {len(prompt_map)} | "
        f"changed_en={counts['changed_en']} changed_zh={counts['changed_zh']} "
        f"unchanged={counts['unchanged']} unresolved={counts['unresolved']}"
    )

    if args.dry_run:
        return 0

    args.mapping.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.mapping}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
