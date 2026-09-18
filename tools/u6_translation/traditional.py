from __future__ import annotations

from pathlib import Path


SIMPLIFIED_CHARACTERS_PATH = Path(__file__).with_name(
    "u6_simplified_characters.txt"
)


def load_simplified_characters(
    path: Path = SIMPLIFIED_CHARACTERS_PATH,
) -> frozenset[str]:
    """Load the unambiguous Simplified-Chinese character inventory."""

    characters: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        characters.update(line.strip())
    return frozenset(characters)
