#!/usr/bin/env python3
"""Compatibility wrapper for the canonical reviewed bilingual map generator."""

import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR / "voice_acting"))

from generate_bilingual_map import load_canonical_mappings, write_blmp  # noqa: E402


JSON_PATH = SCRIPT_DIR / "voice_acting" / "bilingual_mapping_review.json"
OUTPUT_PATH = REPO_DIR / "voice" / "bilingual_map.dat"


def main():
    mappings = load_canonical_mappings(JSON_PATH)
    write_blmp(mappings, OUTPUT_PATH)
    print(f"Wrote {len(mappings)} canonical mappings to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
