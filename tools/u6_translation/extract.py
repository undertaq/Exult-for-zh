from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
import subprocess
import tempfile
from collections.abc import Iterable

from .catalog import CatalogEntry, _merge, parse_runtime_catalog, source_sha256
from .runtime_table import RuntimeRow
from .terms import load_english_terms, policy_tokens
from .usecode_templates import extract_compiled_dialogue_templates


def make_dialogue_key(function: int, callsite: str, ordinal: int) -> str:
    return f"dialogue:0x{function:04x}:{normalize_dialogue_offset_marker(callsite)}:{ordinal}"


def make_choice_key(function: int, callsite: int, ordinal: int) -> str:
    return f"choice:0x{function:04x}:0x{callsite:04x}:{ordinal}"


def make_item_key(shape: int, frame: int, quality: int) -> str:
    return f"item:0x{shape:04x}:{frame}:{quality}"


def _split_runtime_segments_with_ordinals(source: str) -> list[tuple[int, str]]:
    segments = []
    ordinal = 0
    for segment in source.split("~"):
        if not segment:
            continue
        segment = segment.lstrip("*")
        segments.append((ordinal, segment))
        ordinal += 1
    return segments


def split_runtime_segments(source: str) -> list[str]:
    segments = _split_runtime_segments_with_ordinals(source)
    return [segment for _ordinal, segment in segments if segment.strip()]


def normalize_dialogue_offset_marker(marker: str) -> str:
    """Normalize UCXT data/addsi offsets to the runtime voice-key spelling."""

    parts = marker.split("_")
    normalized = []
    for part in parts:
        value = part[2:] if part.lower().startswith("0x") else part
        normalized.append(f"{int(value, 16):x}")
    return "_".join(normalized)


@dataclass(frozen=True)
class _StaticChoice:
    entry: CatalogEntry
    function: int
    callsite: int | None
    ordinal: int


_UCXT_DATA_FILES = ("u7misc.data", "u7opcodes.data", "u7bgintrinsics.data")
_BOOK_USECODE_FUNCTIONS = frozenset({0x0282, 0x031D, 0x0638, 0x0710, 0x0CDB})
# The U6 patch delegates its unmodified book/scroll cases specifically to
# these two base BG functions (the other known handlers are not callo targets
# in this mod and their Chinese usecode has a different data layout).
_FALLBACK_BOOK_USECODE_FUNCTIONS = frozenset({0x0282, 0x031D})
_RUNTIME_TERM_GLOSSARY = Path(__file__).with_name("u6_glossary.tsv")
_ENGLISH_TERMS = Path(__file__).with_name("u6_english_terms.tsv")


def _find_usecode(root: Path) -> Path:
    candidates = (
        root / "Ultima6v1.3" / "patch" / "usecode",
        root / "patch" / "usecode",
        root / "usecode",
    )
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError(f"U6 usecode file not found under {root}")


def _bundled_ucxt_data(ucxt: Path) -> Path | None:
    data_dir = ucxt.resolve().parent.parent / "data"
    if all((data_dir / filename).is_file() for filename in _UCXT_DATA_FILES):
        return data_dir
    return None


def _decode_ucxt_output(output: bytes | str) -> str:
    if isinstance(output, bytes):
        # UCXT emits legacy game text bytes in its translation table. Latin-1
        # preserves every byte so the parser can handle non-UTF-8 output.
        return output.decode("latin-1")
    return output


def _execute_ucxt(command: list[str], cwd: Path | None) -> str:
    kwargs = {"cwd": str(cwd)} if cwd is not None else {}
    try:
        output = subprocess.check_output(command, **kwargs)
    except PermissionError:
        if command[:1] == ["/bin/sh"]:
            output = subprocess.check_output(command, **kwargs)
        else:
            output = subprocess.check_output(["/bin/sh"] + command, **kwargs)
    return _decode_ucxt_output(output)


def _run_ucxt_file(usecode: Path, ucxt: Path, output_format: str) -> str:
    usecode = usecode.resolve()
    command = [str(ucxt), "-nc", output_format, f"-i{usecode}", "-a"]
    if not (ucxt.stat().st_mode & 0o111):
        command = ["/bin/sh"] + command

    data_dir = _bundled_ucxt_data(ucxt)
    if data_dir is None:
        return _execute_ucxt(command, None)

    # The bundled UCXT binary is built with XWIN and resolves -nc data files
    # from the literal <CONFIG> directory. Stage only those read-only inputs
    # in a temporary working directory; never modify the user's game config.
    with tempfile.TemporaryDirectory(prefix="u6-ucxt-") as directory:
        config_dir = Path(directory) / "<CONFIG>"
        config_dir.mkdir()
        for filename in _UCXT_DATA_FILES:
            (config_dir / f".{filename}").symlink_to(data_dir / filename)
        return _execute_ucxt(command, Path(directory))


def _run_ucxt(root: Path, ucxt: Path) -> str:
    return _run_ucxt_file(_find_usecode(root), ucxt, "-ftt")


def _parse_numeric_id(value: str) -> int:
    return int(value, 16) if value.lower().startswith("0x") else int(value, 10)


def _join_ucxt_wrapped_strings(text: str) -> list[str]:
    """Join UCXT output lines that wrap one backtick-delimited string.

    UCXT wraps long ``-ftt`` values at the output width without inserting a
    newline into the game string. The continuation line has no indentation,
    so parsing each physical line independently silently truncates those
    values and makes their runtime hashes impossible to match.
    """

    lines: list[str] = []
    pending: str | None = None
    # The parser receives UCXT output decoded as Latin-1 so every original
    # byte is preserved.  ``str.splitlines()`` also treats U+0085 as a line
    # separator, which is a UTF-8 continuation byte in many Chinese strings.
    # Only split on the actual output newline.
    for line in text.split("\n"):
        if pending is None:
            if line.lstrip().startswith("`") and not line.rstrip().endswith("`"):
                pending = line
            else:
                lines.append(line)
            continue

        # UCXT wraps long values at the output width and starts those
        # continuation lines at column zero.  Book data can also contain real
        # newlines; those continuation lines retain the source indentation,
        # while a blank line is itself part of the value.  Keep only the
        # latter kind of newline so the catalog hash matches the runtime
        # string without reintroducing UCXT's display wrapping.
        if not line or line[0].isspace():
            pending += "\n"
        pending += line
        if line.rstrip().endswith("`"):
            lines.append(pending)
            pending = None

    if pending is not None:
        lines.append(pending)
    return lines


def _parse_ucxt_data_strings(
    text: str, functions: Iterable[int] | None = None
) -> dict[tuple[int, int], str]:
    """Return complete raw translation-table strings keyed by function/offset.

    The regular catalog parser intentionally treats backticks inside a
    string as UCXT fragments. Fallback books need the original complete
    runtime string, however, because those backticks are ordinary book text.
    The first and last backtick on an output line delimit that raw value.
    """

    wanted = set(functions) if functions is not None else None
    data: dict[tuple[int, int], str] = {}
    function: int | None = None
    offset: int | None = None
    opening_tag = re.compile(r"^<((?:0x)?[0-9a-fA-F]+)>$")

    for line in _join_ucxt_wrapped_strings(text):
        stripped = line.strip()
        if stripped == "</>":
            if offset is not None:
                offset = None
            else:
                function = None
            continue
        tag = opening_tag.fullmatch(stripped)
        if tag is not None:
            value = _parse_numeric_id(tag.group(1))
            if function is None:
                function = value
                offset = None
            else:
                offset = value
            continue
        if function is None or offset is None:
            continue
        if wanted is not None and function not in wanted:
            continue
        start = line.find("`")
        end = line.rfind("`")
        if start >= 0 and end > start:
            data[(function, offset)] = line[start + 1:end]
    return data


def _parse_ucxt_addsi_references(
    text: str, functions: Iterable[int] | None = None
) -> dict[int, list[int]]:
    """Return each function's ``addsi`` data references in execution order."""

    wanted = set(functions) if functions is not None else None
    references: dict[int, list[int]] = {}
    function: int | None = None
    function_pattern = re.compile(r"\.funcnumber\s+([0-9a-fA-F]+)H", re.IGNORECASE)
    addsi_pattern = re.compile(r"\baddsi\s+L([0-9a-fA-F]+)\b", re.IGNORECASE)
    for line in text.split("\n"):
        function_match = function_pattern.search(line)
        if function_match is not None:
            function = int(function_match.group(1), 16)
            references.setdefault(function, [])
        if function is None or (wanted is not None and function not in wanted):
            continue
        references[function].extend(
            int(match.group(1), 16) for match in addsi_pattern.finditer(line)
        )
    return references


def _decode_ucxt_translation_value(value: str) -> str | None:
    """Decode a Chinese UCXT value while accepting already-decoded fixtures."""

    try:
        return value.encode("latin-1").decode("utf-8")
    except UnicodeEncodeError:
        return value
    except UnicodeDecodeError:
        return None


def _book_segments(source: str) -> list[tuple[int, str]]:
    return [
        (ordinal, segment)
        for ordinal, segment in _split_runtime_segments_with_ordinals(source)
        if segment.strip()
    ]


def _fallback_book_key(function: int, offset: int, ordinal: int) -> str:
    return f"dialogue:0x{function:04x}:fallback_{offset:x}:{ordinal}"


def _fallback_book_catalog_entries(
    data: dict[tuple[int, int], str],
    references: dict[int, list[int]],
    functions: Iterable[int],
) -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    for function in sorted(set(functions)):
        for offset in references.get(function, []):
            for ordinal, source in _book_segments(data.get((function, offset), "")):
                entries.append(
                    CatalogEntry.from_source(
                        "dialogue",
                        _fallback_book_key(function, offset, ordinal),
                        source,
                        "book",
                        "static-fallback-ucxt",
                    )
                )
    return entries


def _pair_usecode_translation_rows(
    english_data: dict[tuple[int, int], str],
    chinese_data: dict[tuple[int, int], str],
    english_references: dict[int, list[int]],
    chinese_references: dict[int, list[int]],
    functions: Iterable[int],
) -> list[RuntimeRow]:
    """Pair fallback book translations by ``addsi`` order, not data offsets."""

    rows: dict[tuple[str, str], RuntimeRow] = {}
    for function in sorted(set(functions)):
        english_refs = english_references.get(function, [])
        chinese_refs = chinese_references.get(function, [])
        for english_offset, chinese_offset in zip(english_refs, chinese_refs):
            english_segments = _book_segments(
                english_data.get((function, english_offset), "")
            )
            chinese_value = _decode_ucxt_translation_value(
                chinese_data.get((function, chinese_offset), "")
            )
            if chinese_value is None:
                continue
            chinese_segments = _book_segments(chinese_value)
            normalized_chinese_value = chinese_value.replace("～", "~")
            normalized_chinese_segments = _book_segments(normalized_chinese_value)
            if len(english_segments) == len(normalized_chinese_segments):
                chinese_segments = normalized_chinese_segments
            if len(english_segments) != len(chinese_segments):
                continue
            for (ordinal, source), (chinese_ordinal, translation) in zip(
                english_segments, chinese_segments
            ):
                if ordinal != chinese_ordinal or not translation.strip():
                    continue
                key = _fallback_book_key(function, english_offset, ordinal)
                rows[("dialogue", key)] = RuntimeRow(
                    "dialogue", key, source_sha256(source), translation
                )
    return [rows[identity] for identity in sorted(rows)]


def extract_fallback_book_catalog(
    english_usecode: Path, ucxt_path: Path
) -> list[CatalogEntry]:
    english_usecode = english_usecode.resolve()
    english_data = _parse_ucxt_data_strings(
        _run_ucxt_file(english_usecode, ucxt_path, "-ftt"),
        _FALLBACK_BOOK_USECODE_FUNCTIONS,
    )
    english_references = _parse_ucxt_addsi_references(
        _run_ucxt_file(english_usecode, ucxt_path, "-fa"),
        _FALLBACK_BOOK_USECODE_FUNCTIONS,
    )
    return _fallback_book_catalog_entries(
        english_data, english_references, _FALLBACK_BOOK_USECODE_FUNCTIONS
    )


def extract_usecode_translation_rows(
    english_usecode: Path, chinese_usecode: Path, ucxt_path: Path
) -> list[RuntimeRow]:
    english_usecode = english_usecode.resolve()
    chinese_usecode = chinese_usecode.resolve()
    english_data = _parse_ucxt_data_strings(
        _run_ucxt_file(english_usecode, ucxt_path, "-ftt"),
        _FALLBACK_BOOK_USECODE_FUNCTIONS,
    )
    chinese_data = _parse_ucxt_data_strings(
        _run_ucxt_file(chinese_usecode, ucxt_path, "-ftt"),
        _FALLBACK_BOOK_USECODE_FUNCTIONS,
    )
    english_references = _parse_ucxt_addsi_references(
        _run_ucxt_file(english_usecode, ucxt_path, "-fa"),
        _FALLBACK_BOOK_USECODE_FUNCTIONS,
    )
    chinese_references = _parse_ucxt_addsi_references(
        _run_ucxt_file(chinese_usecode, ucxt_path, "-fa"),
        _FALLBACK_BOOK_USECODE_FUNCTIONS,
    )
    return _pair_usecode_translation_rows(
        english_data,
        chinese_data,
        english_references,
        chinese_references,
        _FALLBACK_BOOK_USECODE_FUNCTIONS,
    )


def _parse_ucxt(text: str) -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    function: int | None = None
    offset_markers: list[str] = []
    ordinal = 0
    tag_pattern = re.compile(
        r"</>|<((?:0x)?[0-9a-fA-F]+(?:_(?:0x)?[0-9a-fA-F]+)*)>"
    )

    for line in _join_ucxt_wrapped_strings(text):
        for tag in tag_pattern.finditer(line):
            if tag.group(0) == "</>":
                if offset_markers:
                    offset_markers = []
                    ordinal = 0
                elif function is not None:
                    function = None
                    ordinal = 0
                continue
            marker = tag.group(1)
            if function is None:
                function = _parse_numeric_id(marker)
                offset_markers = []
                ordinal = 0
            else:
                offset_markers.extend(marker.split("_"))
                ordinal = 0

        if function is None or not offset_markers:
            continue
        callsite = "_".join(normalize_dialogue_offset_marker(marker) for marker in offset_markers)
        for match in re.finditer(r"`([^`]*)`", line):
            segments = _split_runtime_segments_with_ordinals(match.group(1))
            for segment_ordinal, segment in segments:
                if not segment.strip():
                    continue
                entries.append(
                    CatalogEntry.from_source(
                        "dialogue",
                        make_dialogue_key(function, callsite, ordinal + segment_ordinal),
                        segment,
                        "book" if function in _BOOK_USECODE_FUNCTIONS else "gameplay",
                        "static-ucxt",
                    )
                )
            ordinal += len(segments)
    return entries


# ``STATIC/USECODE`` is loaded underneath a mod patch at runtime.  The patch
# may therefore call an inherited helper which is absent from the mod's own
# compiled usecode.  Keep the intrinsic IDs here (rather than any NPC or
# sentence names) so all inherited overhead helpers are discovered by the
# same path.  The first value is Black Gate's ordinary item_say; the others
# are the corresponding Serpent Isle/gump slots used by shared usecode.
_ITEM_SAY_INTRINSICS = frozenset({0x40, 0x4C, 0x4D, 0x7F, 0x99})


def _item_say_function_ids(usecode: Path) -> set[int]:
    """Return compiled functions that invoke an item_say intrinsic.

    This deliberately follows the bytecode call graph instead of matching
    literal text.  It consequently covers every inherited overhead helper
    (and future helpers with the same intrinsic) without maintaining an NPC
    or sentence registry.
    """

    from tools.voice_acting import disassemble_usecode as disassembler

    data = usecode.resolve().read_bytes()
    try:
        offset = disassembler.skip_symbol_table(data, 0)
    except (IndexError, ValueError, TypeError, struct.error):
        return set()

    functions: set[int] = set()
    while offset < len(data):
        try:
            function_id, function_data, extended, next_offset = (
                disassembler.parse_function(data, offset)
            )
            if next_offset <= offset or next_offset > len(data):
                break
            function = disassembler.disassemble_function(
                function_id, function_data, extended
            )
        except (IndexError, ValueError, TypeError, struct.error):
            break
        if any(
            name == "calli"
            and params
            and int(params[0]) in _ITEM_SAY_INTRINSICS
            for _address, _raw, name, params, _comment in function["instructions"]
        ):
            functions.add(function_id)
        offset = next_offset
    return functions


def _fallback_item_say_catalog(
    usecode: Path, ucxt: Path, shadowed_functions: set[int]
) -> list[CatalogEntry]:
    """Extract only inherited static strings that can reach item_say.

    A mod function completely replaces its base function, so shadowed
    function IDs must not contribute duplicate/different UCXT rows.  Keeping
    the filter at function/intrinsic level avoids hard-coded sentence lists
    while keeping the audit catalog focused on display text rather than all
    inherited books and conversation data.
    """

    functions = _item_say_function_ids(usecode) - shadowed_functions
    if not functions:
        return []
    entries = _parse_ucxt(_run_ucxt_file(usecode, ucxt, "-ftt"))
    result: list[CatalogEntry] = []
    for entry in entries:
        if _dialogue_function(entry.key) not in functions:
            continue
        result.append(replace(entry, origin="static-fallback-item-say-ucxt"))
    return result


def _dialogue_function(key: str) -> int | None:
    parts = key.split(":")
    if len(parts) < 2 or not parts[1].startswith("0x"):
        return None
    try:
        return int(parts[1], 16)
    except ValueError:
        return None


def _runtime_term_catalog(
    glossary: Path = _RUNTIME_TERM_GLOSSARY,
    terms: Path = _ENGLISH_TERMS,
) -> list[CatalogEntry]:
    """Expose source-global usecode helper values to extraction and audit.

    Shared helpers such as the inherited gendered-title function return a
    string without an NPC-specific UCXT callsite.  Marking those glossary
    entries as ``runtime_term`` gives the catalog a stable, auditable source
    identity while the runtime still resolves the translation globally.
    """

    runtime_terms: set[str] = set()
    for line in glossary.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 3 or not all(fields):
            continue
        english, _chinese, policy = fields
        if "runtime_term" not in policy_tokens(policy):
            continue
        runtime_terms.add(english)

    for term in load_english_terms(terms):
        if "runtime_term" in policy_tokens(term.policy):
            runtime_terms.add(term.en)

    entries: list[CatalogEntry] = []
    for ordinal, english in enumerate(sorted(runtime_terms)):
        entries.append(
            CatalogEntry.from_source(
                "dialogue",
                f"dialogue:0x0000:runtime:{ordinal}",
                english,
                "gameplay",
                "static-runtime-term",
            )
        )
    return entries


def _parse_function_id(line: str, path: Path) -> int | None:
    match = re.search(
        r"\b(?:function|function_id)\s*[:=]?\s*(0x[0-9a-fA-F]+|\d+)\b",
        line,
        re.IGNORECASE,
    )
    if match:
        return _parse_numeric_id(match.group(1))
    match = re.search(r"\bFunc([0-9a-fA-F]{4})\b", line, re.IGNORECASE)
    if match:
        return int(match.group(1), 16)
    match = re.search(
        r"\bobject#\(\s*(0x[0-9a-fA-F]+|\d+)\s*\)", line, re.IGNORECASE
    )
    if match:
        return int(match.group(1), 16)
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


def _static(
    root: Path,
    ucxt: Path,
    fallback_usecode: Path | None = None,
) -> tuple[list[CatalogEntry], list[_StaticChoice]]:
    entries = _parse_ucxt(_run_ucxt(root, ucxt))
    if fallback_usecode is not None:
        shadowed_functions = {
            function
            for entry in entries
            for function in [_dialogue_function(entry.key)]
            if function is not None
        }
        entries.extend(
            _fallback_item_say_catalog(
                fallback_usecode, ucxt, shadowed_functions
            )
        )
        entries.extend(extract_fallback_book_catalog(fallback_usecode, ucxt))
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


def _spell_name_paths(root: Path) -> list[Path]:
    candidates = [
        root / "Ultima6v1.3" / "patch" / "spellnames.txt",
        root / "patch" / "spellnames.txt",
        root / "spellnames.txt",
    ]
    return [path for path in candidates if path.is_file()]


def _parse_spell_names(root: Path) -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    for path in _spell_name_paths(root):
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.match(r"^\s*(0x[0-9a-fA-F]+|\d+)\s*:\s*(.*?)\s*$", line)
            if match is None:
                continue
            spell = int(match.group(1), 0)
            if 0 <= spell < 72 and match.group(2):
                entries.append(
                    CatalogEntry.from_source(
                        "spell", f"spell:0x{spell:04x}", match.group(2),
                        "gameplay", "static-spellnames",
                    )
                )
    return entries


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
                    if not source.strip():
                        continue
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
            if not source.strip():
                continue
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
_DIALOGUE_KEY = re.compile(
    r"^dialogue:0x([0-9a-fA-F]+):[^:]+:\d+$"
)


def _dialogue_function(key: str) -> int | None:
    match = _DIALOGUE_KEY.match(key)
    return int(match.group(1), 16) if match else None


def _choice_identity(key: str) -> tuple[int, int, int] | None:
    match = _CHOICE_KEY.match(key)
    return (
        (int(match.group(1), 16), int(match.group(2), 16), int(match.group(3)))
        if match
        else None
    )


def _canonicalize_runtime_key_collisions(
    runtime: list[CatalogEntry],
) -> list[CatalogEntry]:
    """Give repeated dynamic callsites a stable identity.

    The U6 gypsy helper reuses one usecode callsite for every generated
    question and answer.  The runtime key is therefore not unique, although
    the source hash is.  Keep ordinary keys unchanged and use the source hash
    only for colliding rows so the capture can be merged into a catalog and
    emitted into ``zh_translation.tsv`` without dropping a question.
    """

    grouped: dict[tuple[str, str], set[str]] = {}
    for row in runtime:
        grouped.setdefault((row.kind, row.key), set()).add(row.source_sha256)

    collision_groups = {
        identity for identity, sources in grouped.items() if len(sources) > 1
    }
    canonical: list[CatalogEntry] = []
    for row in runtime:
        if (row.kind, row.key) not in collision_groups:
            canonical.append(row)
            continue

        if row.kind == "dialogue":
            function = _dialogue_function(row.key)
            if function is None:
                canonical.append(row)
                continue
            key = f"dialogue:0x{function:04x}:{row.source_sha256}:0"
        elif row.kind == "choice":
            identity = _choice_identity(row.key)
            if identity is None:
                canonical.append(row)
                continue
            function, _callsite, ordinal = identity
            key = f"choice:0x{function:04x}:0x{row.source_sha256[:16]}:{ordinal}"
        else:
            canonical.append(row)
            continue

        canonical.append(replace(row, key=key))
    return canonical


def _reconcile_runtime_dialogues(
    entries: list[CatalogEntry], runtime: list[CatalogEntry]
) -> list[CatalogEntry]:
    """Bind a runtime-assembled line to its static source entry.

    U6 can construct one sentence at runtime from values at a different
    usecode offset than the source sentence reported by UCXT. If the runtime
    key collides with another static line, retain the canonical static key and
    merge the runtime capture into it. The C++ side then matches the complete
    source text, independent of either offset.
    """

    static_dialogues = [entry for entry in entries if entry.kind == "dialogue"]
    reconciled: list[CatalogEntry] = []
    for row in runtime:
        if row.kind != "dialogue":
            reconciled.append(row)
            continue

        source_matches = [
            entry
            for entry in static_dialogues
            if entry.source_sha256 == row.source_sha256
        ]
        if len(source_matches) == 1:
            reconciled.append(replace(row, key=source_matches[0].key))
            continue

        same_key = next(
            (entry for entry in static_dialogues if entry.key == row.key), None
        )
        if same_key is None or same_key.source_sha256 == row.source_sha256:
            reconciled.append(row)
            continue

        function = _dialogue_function(row.key)
        matches = [
            entry
            for entry in static_dialogues
            if _dialogue_function(entry.key) == function
            and entry.source_sha256 == row.source_sha256
        ]
        if len(matches) == 1:
            reconciled.append(replace(row, key=matches[0].key))
        else:
            # Preserve the existing fail-closed duplicate-key behavior when
            # the source cannot identify one canonical static entry.
            reconciled.append(row)
    return reconciled


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
    mod_root: Path,
    ucxt_path: Path,
    runtime_catalog: Path | None,
    fallback_usecode: Path | None = None,
    include_runtime_terms: bool = False,
    terms: Path | None = None,
) -> list[CatalogEntry]:
    entries, static_choices = _static(mod_root, ucxt_path, fallback_usecode)
    try:
        usecode = _find_usecode(mod_root)
    except FileNotFoundError:
        usecode = None
    if usecode is not None:
        entries.extend(extract_compiled_dialogue_templates(usecode))
    if fallback_usecode is not None:
        shadowed_functions = {
            function
            for entry in entries
            for function in [_dialogue_function(entry.key)]
            if function is not None
        }
        entries.extend(
            replace(entry, origin="static-fallback-usecode-template")
            for entry in extract_compiled_dialogue_templates(fallback_usecode)
            if _dialogue_function(entry.key) not in shadowed_functions
        )
    entries.extend(_parse_indexed_resources(mod_root))
    entries.extend(_parse_spell_names(mod_root))
    if include_runtime_terms:
        entries.extend(_runtime_term_catalog(terms=terms or _ENGLISH_TERMS))
    if runtime_catalog is not None:
        runtime = parse_runtime_catalog(runtime_catalog)
        runtime = _reconcile_runtime_dialogues(entries, runtime)
        runtime = _canonicalize_runtime_key_collisions(runtime)
        entries = _bind_runtime_choices(entries, static_choices, runtime)
    return _merge(entries)
