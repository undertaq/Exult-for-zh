from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import tempfile
from collections.abc import Iterable

from .runtime_table import RuntimeRow, load_runtime_table, write_runtime_table

SIMPLIFIED_CHARACTERS_PATH = Path(__file__).with_name(
    "u6_simplified_characters.txt"
)
SIMPLIFIED_TO_TRADITIONAL_PATH = Path(__file__).with_name(
    "u6_simplified_to_traditional.tsv"
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


def load_simplified_to_traditional(
    path: Path = SIMPLIFIED_TO_TRADITIONAL_PATH,
) -> dict[str, str]:
    """Load the checked-in character map used by the release converter.

    The map is deliberately character-level.  It is generated from OpenCC's
    ``s2t`` character dictionary and contains only the unambiguous characters
    used by the audit inventory.  Keeping the mapping in the repository means
    conversion is deterministic and does not require a Python OpenCC package.
    """

    mapping: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 2 or len(fields[0]) != 1 or not fields[1]:
            raise ValueError(f"invalid Simplified-to-Traditional mapping at {path}:{line_number}")
        source, target = fields
        if source in mapping and mapping[source] != target:
            raise ValueError(f"duplicate Simplified mapping at {path}:{line_number}: {source}")
        mapping[source] = target
    return mapping


@dataclass(frozen=True)
class TextConversion:
    text: str
    changed_characters: tuple[tuple[str, str], ...]
    changed_count: int


@dataclass(frozen=True)
class TableConversionChange:
    kind: str
    key: str
    before: str
    after: str
    changed_characters: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class TableConversionReport:
    rows: int
    changed_rows: int
    changed_characters: int
    changes: tuple[TableConversionChange, ...]
    unresolved: tuple[tuple[str, str], ...]


@lru_cache(maxsize=1)
def _default_mapping() -> dict[str, str]:
    mapping = load_simplified_to_traditional()
    inventory = load_simplified_characters()
    missing = sorted(inventory - mapping.keys())
    if missing:
        raise ValueError(
            "Simplified-to-Traditional map is missing audit characters: "
            + "".join(missing)
        )
    extra = sorted(mapping.keys() - inventory)
    if extra:
        raise ValueError(
            "Simplified-to-Traditional map contains non-audit characters: "
            + "".join(extra)
        )
    return mapping


def convert_text(
    text: str,
    mapping: dict[str, str] | None = None,
) -> TextConversion:
    """Convert known Simplified glyphs while preserving all other text.

    This operates on the same explicit inventory used by the Traditional
    Chinese audit.  ASCII names, placeholders such as ``<VAR>``, hashes, and
    punctuation therefore pass through unchanged.
    """

    active_mapping = mapping if mapping is not None else _default_mapping()
    converted_parts: list[str] = []
    changed_pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    changed_count = 0
    for character in text:
        replacement = active_mapping.get(character, character)
        converted_parts.append(replacement)
        if replacement == character:
            continue
        changed_count += 1
        pair = (character, replacement)
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            changed_pairs.append(pair)
    return TextConversion("".join(converted_parts), tuple(changed_pairs), changed_count)


def _write_runtime_table_atomically(path: Path, rows: Iterable[RuntimeRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing_mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        existing_mode = None
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        write_runtime_table(temporary, list(rows))
        if existing_mode is not None:
            os.chmod(temporary, existing_mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def convert_runtime_table(
    input_path: Path,
    output_path: Path | None = None,
    *,
    check: bool = False,
    dry_run: bool = False,
) -> TableConversionReport:
    """Convert a runtime TSV and optionally write it with an atomic replace.

    ``check`` and ``dry_run`` never write an output file.  The CLI uses the
    report to return a non-zero status when conversion is still needed.
    """

    rows = load_runtime_table(input_path)
    converted_rows: list[RuntimeRow] = []
    changes: list[TableConversionChange] = []
    unresolved: list[tuple[str, str]] = []
    changed_characters = 0
    inventory = load_simplified_characters()
    for row in rows:
        conversion = convert_text(row.zh)
        converted = RuntimeRow(row.kind, row.key, row.source_sha256, conversion.text)
        converted_rows.append(converted)
        changed_characters += conversion.changed_count
        if conversion.text != row.zh:
            changes.append(
                TableConversionChange(
                    row.kind,
                    row.key,
                    row.zh,
                    conversion.text,
                    conversion.changed_characters,
                )
            )
        remaining = sorted(set(character for character in conversion.text if character in inventory))
        unresolved.extend((row.key, character) for character in remaining)

    report = TableConversionReport(
        rows=len(rows),
        changed_rows=len(changes),
        changed_characters=changed_characters,
        changes=tuple(changes),
        unresolved=tuple(unresolved),
    )
    if not check and not dry_run:
        if output_path is None:
            raise ValueError("output_path is required unless check or dry_run is enabled")
        _write_runtime_table_atomically(output_path, converted_rows)
    return report
