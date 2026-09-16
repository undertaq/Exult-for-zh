from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable


TABLE_HEADER = "# u6-translation-v1\n# kind\tkey\tsource_sha256\tzh\n"


@dataclass(frozen=True)
class RuntimeRow:
    kind: str
    key: str
    source_sha256: str
    zh: str


def escape_field(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def unescape_field(value: str) -> str:
    result: list[str] = []
    index = 0
    escapes = {"t": "\t", "n": "\n", "r": "\r", "\\": "\\"}
    while index < len(value):
        character = value[index]
        if character != "\\":
            result.append(character)
            index += 1
            continue
        index += 1
        if index == len(value):
            raise ValueError("trailing escape")
        escaped = value[index]
        index += 1
        if escaped not in escapes:
            raise ValueError("unknown escape: " + escaped)
        result.append(escapes[escaped])
    return "".join(result)


def split_tsv_fields(line: str, expected_fields: int = 4) -> tuple[str, ...]:
    """Split a physical TSV row before decoding escaped field contents.

    Delimiters are actual tabs. A literal backslash-t is field data and is
    decoded only by ``unescape_field``. ``str.split`` intentionally preserves
    an empty final field.
    """

    fields = tuple(line.split("\t"))
    if len(fields) != expected_fields:
        raise ValueError("invalid TSV row: expected " + str(expected_fields) + " fields")
    return fields


def decode_tsv_row(line: str, expected_fields: int = 4) -> tuple[str, ...]:
    return tuple(unescape_field(field) for field in split_tsv_fields(line, expected_fields))


def load_runtime_table(path: Path) -> list[RuntimeRow]:
    rows = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if not line or line.startswith("#"):
            continue
        rows.append(RuntimeRow(*decode_tsv_row(line)))
    return rows


def merge_runtime_rows(
    existing: Iterable[RuntimeRow], additions: Iterable[RuntimeRow]
) -> list[RuntimeRow]:
    """Add generated rows without replacing reviewed translations."""

    merged: dict[tuple[str, str], RuntimeRow] = {
        (row.kind, row.key): row for row in existing
    }
    for row in additions:
        identity = (row.kind, row.key)
        previous = merged.get(identity)
        if previous is None:
            merged[identity] = row
            continue
        if previous.source_sha256 != row.source_sha256:
            raise ValueError("duplicate runtime key with different source hash: " + row.key)
        if not previous.zh.strip() and row.zh.strip():
            merged[identity] = row
    return sorted(
        merged.values(),
        key=lambda row: (row.kind, row.key, row.source_sha256, row.zh),
    )


def write_runtime_table(path: Path, rows: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(
        rows,  # type: ignore[arg-type]
        key=lambda row: (row.kind, row.key, row.source_sha256, row.zh),
    )
    content = TABLE_HEADER + "".join(
        "\t".join(
            escape_field(value)
            for value in (row.kind, row.key, row.source_sha256, row.zh)
        )
        + "\n"
        for row in ordered
    )
    path.write_text(content, encoding="utf-8")
