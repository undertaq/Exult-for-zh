from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess

from .catalog import CatalogEntry, _merge, parse_runtime_catalog


def make_dialogue_key(function: int, callsite: str, ordinal: int) -> str:
    return f"dialogue:0x{function:04x}:{callsite}:{ordinal}"


def make_choice_key(function: int, callsite: int, ordinal: int) -> str:
    return f"choice:0x{function:04x}:0x{callsite:04x}:{ordinal}"


def make_item_key(shape: int, frame: int, quality: int) -> str:
    return f"item:0x{shape:04x}:{frame}:{quality}"


def split_runtime_segments(source: str) -> list[str]:
    return [segment.lstrip("*") for segment in source.split("~") if segment]


@dataclass(frozen=True)
class _StaticChoice:
    entry: CatalogEntry
    function: int
    callsite: int | None
    ordinal: int


def _run_ucxt(root: Path, ucxt: Path) -> str:
    command = [str(ucxt), "-ftt", str(root)]
    if not (ucxt.stat().st_mode & 0o111):
        command = ["/bin/sh"] + command
    try:
        return subprocess.check_output(command, text=True)
    except PermissionError:
        return subprocess.check_output(["/bin/sh"] + command, text=True)


def _parse_ucxt(text: str) -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    function: int | None = None
    callsite: str | None = None
    ordinal = 0
    tag_pattern = re.compile(r"</>|<(0x[0-9a-fA-F]+)>")

    for line in text.splitlines():
        for tag in tag_pattern.finditer(line):
            if tag.group(0) == "</>":
                if callsite is not None:
                    callsite = None
                    ordinal = 0
                elif function is not None:
                    function = None
                    callsite = None
                    ordinal = 0
                continue
            value = int(tag.group(1), 16)
            if function is None:
                function = value
                callsite = None
                ordinal = 0
            elif callsite is None:
                callsite = f"0x{value:04x}"
                ordinal = 0

        if function is None or callsite is None:
            continue
        for match in re.finditer(r"`([^`]*)`", line):
            for segment in split_runtime_segments(match.group(1)):
                entries.append(
                    CatalogEntry.from_source(
                        "dialogue",
                        make_dialogue_key(function, callsite, ordinal),
                        segment,
                        "gameplay",
                        "static-ucxt",
                    )
                )
                ordinal += 1
    return entries


def _parse_function_id(line: str, path: Path) -> int | None:
    patterns = (
        r"\b(?:function|function_id)\s*[:=]?\s*(0x[0-9a-fA-F]+|\d+)\b",
        r"\bFunc([0-9a-fA-F]{4})\b",
        r"\bobject#\(\s*(0x[0-9a-fA-F]+|\d+)\s*\)",
    )
    for pattern in patterns:
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            value = match.group(1)
            return int(value, 16)
    match = re.search(r"(?:^|[-_])(?:0x)?([0-9a-fA-F]{4})(?:[-_.]|$)", path.stem)
    return int(match.group(1), 16) if match else None


def _parse_callsite(line: str) -> int | None:
    match = re.search(
        r"\bcallsite\s*[:=]?\s*(0x[0-9a-fA-F]+|\d+)\b", line, re.IGNORECASE
    )
    return int(match.group(1), 16) if match else None


def _quoted_strings(text: str) -> list[str]:
    values = []
    for match in re.finditer(r'"(?:\\.|[^"\\])*"', text):
        try:
            values.append(json.loads(match.group(0)))
        except json.JSONDecodeError:
            continue
    return values


def _source_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".uc", ".usecode", ".es"}
    )


def _parse_static_choices(root: Path) -> tuple[list[CatalogEntry], list[_StaticChoice]]:
    entries: list[CatalogEntry] = []
    choices: list[_StaticChoice] = []
    for path in _source_files(root):
        function: int | None = None
        callsite: int | None = None
        ordinal = 0
        unbound_index = 0
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            parsed_function = _parse_function_id(line, path)
            if parsed_function is not None:
                if parsed_function != function:
                    function = parsed_function
                    callsite = None
                    ordinal = 0
                    unbound_index = 0

            parsed_callsite = _parse_callsite(line)
            if parsed_callsite is not None:
                callsite = parsed_callsite
                ordinal = 0

            if function is None:
                continue
            for call in re.finditer(r"\bUI_add_answer\s*\((.*)\)", line, re.IGNORECASE):
                for source in _quoted_strings(call.group(1)):
                    entry = CatalogEntry.from_source(
                        "choice",
                        f"choice:0x{function:04x}:unbound:{unbound_index}",
                        source,
                        "gameplay",
                        "static-usecode",
                    )
                    entries.append(entry)
                    choices.append(_StaticChoice(entry, function, callsite, ordinal))
                    ordinal += 1
                    unbound_index += 1
    return entries, choices


def _static(root: Path, ucxt: Path) -> tuple[list[CatalogEntry], list[_StaticChoice]]:
    entries = _parse_ucxt(_run_ucxt(root, ucxt))
    choices, choice_metadata = _parse_static_choices(root)
    return entries + choices, choice_metadata


def _resource_paths(root: Path) -> list[Path]:
    candidates = [
        root / "Ultima6v1.3" / "patch" / "textmsg.txt",
        root / "patch" / "textmsg.txt",
        root / "textmsg.txt",
    ]
    paths: list[Path] = []
    seen: set[Path] = set()
    for path in candidates + sorted(root.rglob("textmsg.txt")):
        if path.is_file() and path not in seen:
            paths.append(path)
            seen.add(path)
    return paths


def _indexed_shape(line: str) -> tuple[int, int, int, str] | None:
    variant = re.match(
        r"^\s*(0x[0-9a-fA-F]+|\d+)\s*[/,]\s*"
        r"(0x[0-9a-fA-F]+|\d+)\s*[/,]\s*"
        r"(0x[0-9a-fA-F]+|\d+)\s*:\s*(.*)$",
        line,
    )
    if variant:
        return (
            int(variant.group(1), 0),
            int(variant.group(2), 0),
            int(variant.group(3), 0),
            variant.group(4),
        )
    variant = re.match(
        r"^\s*(0x[0-9a-fA-F]+|\d+)\s*:\s*"
        r"(0x[0-9a-fA-F]+|\d+)\s*:\s*"
        r"(0x[0-9a-fA-F]+|\d+)\s*:\s*(.*)$",
        line,
    )
    if variant:
        return (
            int(variant.group(1), 0),
            int(variant.group(2), 0),
            int(variant.group(3), 0),
            variant.group(4),
        )
    plain = re.match(r"^\s*(0x[0-9a-fA-F]+|\d+)\s*:\s*(.*)$", line)
    if plain:
        return int(plain.group(1), 0), 0, 0, plain.group(2)
    return None


def _parse_indexed_resources(root: Path) -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    item_sections = {"shapes", "items", "item_names", "indexed_items"}
    misc_sections = {"miscnames", "misc_names", "misc"}
    location_sections = {"locations", "location_names"}
    for path in _resource_paths(root):
        section = ""
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            section_match = re.match(r"^\s*%%section\s+([^\s]+)", line, re.IGNORECASE)
            if section_match:
                section = section_match.group(1).lower()
                continue
            if re.match(r"^\s*%%endsection\b", line, re.IGNORECASE):
                section = ""
                continue
            if not section or not line.strip() or line.lstrip().startswith("#"):
                continue

            if section in item_sections:
                indexed = _indexed_shape(line)
                if indexed is not None:
                    shape, frame, quality, source = indexed
                    entries.append(
                        CatalogEntry.from_source(
                            "item",
                            make_item_key(shape, frame, quality),
                            source,
                            "gameplay",
                            "static-textmsg",
                        )
                    )
                continue

            indexed = _indexed_shape(line)
            if indexed is None:
                continue
            index, _frame, _quality, source = indexed
            if section in location_sections:
                kind = "textmsg"
                key = f"textmsg:0x{index:04x}"
                context = "location"
            elif section == "msgs":
                kind = "textmsg"
                key = f"textmsg:0x{index:04x}"
                context = "gameplay"
            elif section in misc_sections:
                kind = "misc"
                key = f"misc:0x{index:04x}"
                context = "gameplay"
            else:
                continue
            entries.append(
                CatalogEntry.from_source(
                    kind, key, source, context, "static-textmsg"
                )
            )
    return entries


_CHOICE_KEY = re.compile(
    r"^choice:0x([0-9a-fA-F]+):0x([0-9a-fA-F]+):(\d+)$"
)


def _choice_identity(key: str) -> tuple[int, int, int] | None:
    match = _CHOICE_KEY.match(key)
    return (
        (int(match.group(1), 16), int(match.group(2), 16), int(match.group(3)))
        if match
        else None
    )


def _bind_runtime_choices(
    entries: list[CatalogEntry],
    static_choices: list[_StaticChoice],
    runtime: list[CatalogEntry],
) -> list[CatalogEntry]:
    remaining = list(static_choices)
    bound: list[CatalogEntry] = []
    runtime_identities = {
        identity
        for row in runtime
        if row.kind == "choice"
        for identity in [_choice_identity(row.key)]
        if identity is not None
    }

    for row in runtime:
        if row.kind != "choice":
            continue
        identity = _choice_identity(row.key)
        if identity is None:
            continue
        function, callsite, ordinal = identity
        exact = [
            candidate
            for candidate in remaining
            if candidate.function == function
            and candidate.callsite == callsite
            and candidate.ordinal == ordinal
        ]
        if not exact:
            unbound = [
                candidate
                for candidate in remaining
                if candidate.function == function
                and candidate.callsite is None
                and candidate.ordinal == ordinal
            ]
            same_ordinal = [
                runtime_identity
                for runtime_identity in runtime_identities
                if runtime_identity[0] == function and runtime_identity[2] == ordinal
            ]
            if len(unbound) == 1 and len(same_ordinal) == 1:
                exact = unbound
        if len(exact) != 1:
            continue
        candidate = exact[0]
        remaining.remove(candidate)
        bound.append(
            CatalogEntry(
                kind=candidate.entry.kind,
                key=row.key,
                source=candidate.entry.source,
                source_sha256=candidate.entry.source_sha256,
                context=candidate.entry.context,
                origin=candidate.entry.origin,
                protected_tokens=candidate.entry.protected_tokens,
            )
        )

    remaining_keys = {candidate.entry.key for candidate in remaining}
    return [entry for entry in entries if entry.key in remaining_keys or ":unbound:" not in entry.key] + bound + runtime


def extract_catalog(
    mod_root: Path, ucxt_path: Path, runtime_catalog: Path | None
) -> list[CatalogEntry]:
    entries, static_choices = _static(mod_root, ucxt_path)
    entries.extend(_parse_indexed_resources(mod_root))
    if runtime_catalog is not None:
        runtime = parse_runtime_catalog(runtime_catalog)
        entries = _bind_runtime_choices(entries, static_choices, runtime)
    return _merge(entries)
