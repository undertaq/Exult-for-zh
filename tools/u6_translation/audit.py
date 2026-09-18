from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Iterable

from .catalog import CatalogEntry, normalize_source, source_sha256
from .consistency import repeated_source_conflicts
from .runtime_table import RuntimeRow, split_tsv_fields, unescape_field
from .terms import load_english_terms
from .traditional import load_simplified_characters


KINDS = ("dialogue", "choice", "textmsg", "item", "location", "misc", "spell")
_KEY_PATTERNS = {
    "dialogue": re.compile(r"^dialogue:0x[0-9a-f]{4}:(?:[0-9a-f]+|runtime|fallback_[0-9a-f]+|template_[a-z0-9_]+)(?:_(?:[0-9a-f]+|runtime|fallback_[0-9a-f]+|template_[a-z0-9_]+))*:\d+$"),
    "choice": re.compile(r"^choice:0x[0-9a-f]{4}:(?:0x[0-9a-f]+|unbound):\d+$"),
    "item": re.compile(r"^item:0x[0-9a-f]{4}:\d+:\d+$"),
    "textmsg": re.compile(r"^textmsg:0x[0-9a-f]+$"),
    "location": re.compile(r"^location:0x[0-9a-f]+$"),
    "misc": re.compile(r"^misc:0x[0-9a-f]+$"),
    "spell": re.compile(r"^spell:0x[0-9a-f]+$"),
}
_SOURCE_STABLE_FALLBACK_KEY = re.compile(
    r"^dialogue:0x[0-9a-f]{4}:fallback_([0-9a-f]{16}):0$"
)
_ANGLE_PLACEHOLDER = r"<[A-Za-z][A-Za-z0-9_]*>"
_PLACEHOLDER_RE = re.compile(_ANGLE_PLACEHOLDER + r"|\{[A-Za-z0-9_.-]+\}")
_ASCII_DOT_RUN_RE = re.compile(r"(?<!\.)\.{2,}(?!\.)")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_AUDIT_TOKENS = re.compile(r"@[^@\n]+@|~|\*|" + _ANGLE_PLACEHOLDER)
_PROTECTED_MARKERS = re.compile(r"~|\*|" + _ANGLE_PLACEHOLDER)
_TRADITIONAL_POLICY_RE = re.compile(
    r"^#\s*policy\s*:?\s+traditional[_-]chinese\s*=\s*(warning|error)\s*$",
    re.IGNORECASE,
)
_NAME_POLICY_HEADER = ("category", "en")
_NAME_CATEGORIES = {"npc", "place", "town", "location", "proper"}
_ENGLISH_TERM_NAME_CATEGORIES = {"person", "location", "proper"}
_OPAQUE_LANGUAGE_FUNCTIONS = {
    "0x0282",
    "0x0cb3",
    "0x0cb6",
    "0x0cf8",
    "0x0cff",
    "0x04e2",
}
_OPAQUE_LANGUAGE_PHRASES = {
    "ag-ra-lem! ges por!",
    "an-bal-sil-fer!",
    "an-bal-sil-fer!!",
    "an-bal-sil-fer...",
    "an in mani u lem, an-bal-sil-fer.",
    "sum in-korp i. vers.",
    "vas rel xen",
    "kal corp flam!",
    "gres por! gres por!",
    "ex por",
    "por ylem",
    "ombogo dono.",
    "ombogo sano!",
    "sano",
    "dono",
    "mu",
    "un.....un.....un.....",
    "un....un....un.....",
    "blank",
    "blank.",
    "...zzz...",
    "rrrrlr grrtl...",
    "..rrrrlr grrtl...",
    "mrtlx hmlsh fbbn...",
    "beh....beh....beh....",
    "cah....cah....cah....",
    "summ....summ....summ....",
    "mu...mu...mu...",
    "mu...mu...mu....",
    "om....om....om....",
    "lum....lum....lum....",
    "slurp",
}
_SIMPLIFIED_CHARACTERS = load_simplified_characters()


def _non_placeholder_markers(text: str) -> Counter[str]:
    """Return wrappers that must remain exact; angle slots are positional."""

    return Counter(
        token
        for token in _PROTECTED_MARKERS.findall(text)
        if not re.fullmatch(_ANGLE_PLACEHOLDER, token)
    )


def _usecode_speech_marker_count(text: str) -> int:
    """Count U6's ``@`` speech-boundary markers without interpreting text."""

    return text.count("@")


def _split_speech_boundary_deficit(
    source: str, translated: str
) -> tuple[str, ...]:
    """Report one-sided ``@`` boundaries omitted by a UCXT fragment.

    UCXT can expose ``@Good `` and ``.@`` as separate rows.  Those rows are
    translated as ordinary fragments, so the table value may intentionally
    omit the boundary that the runtime restores from VM provenance.  Complete
    ``@...@`` rows are audited by the canonical-template marker check instead.
    """

    if source.count("@") != 1:
        return ()
    deficits: list[str] = []
    if source.startswith("@") and not translated.startswith("@"):
        deficits.append("opening")
    if source.endswith("@") and not translated.endswith("@"):
        deficits.append("closing")
    return tuple(deficits)


def _fragment_speech_boundary_report(
    catalog: list[CatalogEntry], rows: list[RuntimeRow]
) -> dict[str, object]:
    """Summarize UCXT fragments whose one-sided speech boundary is omitted."""

    entries = {
        _identity(entry): entry
        for entry in catalog
        if set(entry.origin.split(";"))
        & {"static-ucxt", "static-fallback-item-say-ucxt"}
    }
    fragment_rows = [
        row for row in rows
        if _identity(row) in entries
    ]
    at_risk = sorted(
        row.key
        for row in fragment_rows
        if _split_speech_boundary_deficit(
            entries[_identity(row)].source, row.zh
        )
    )
    return {
        "total": len(fragment_rows),
        "at_risk": len(at_risk),
        "keys": at_risk,
    }


def _ascii_dot_runs(text: str) -> tuple[str, ...]:
    """Return contiguous ASCII dot runs that translations must preserve."""

    return tuple(_ASCII_DOT_RUN_RE.findall(text))


def _identity(value: CatalogEntry | RuntimeRow) -> tuple[str, str]:
    return value.kind, value.key


def _is_unobserved_placeholder_row(
    row: RuntimeRow, observed_identities: set[tuple[str, str]]
) -> bool:
    """Recognize a generic runtime-template row absent from static UCXT output.

    Source-stable fallback keys embed the first 16 hex digits of the
    positional template hash. Runtime capture is the only source of the
    template text for opaque ADDSV expressions, so report these rows instead
    of silently excluding them from the placeholder audit section.
    """

    if _identity(row) in observed_identities or row.kind != "dialogue":
        return False
    match = _SOURCE_STABLE_FALLBACK_KEY.fullmatch(row.key)
    return match is not None and row.source_sha256.startswith(match.group(1))


def _is_unbound(key: str) -> bool:
    return ":unbound:" in key


def _is_exact_repetition(value: str) -> bool:
    value = re.sub(r"\s+", "", value.strip())
    if len(value) < 2 or len(value) % 2:
        return False
    midpoint = len(value) // 2
    unit = value[:midpoint]
    if unit != value[midpoint:]:
        return False
    if (unit.startswith("「") and unit.endswith("」")) or (
        unit.startswith("『") and unit.endswith("』")
    ) or (unit.startswith("“") and unit.endswith("”")):
        return True
    return unit[-1] in "。！？!?…;；:："


def _empty_kind_report() -> dict[str, object]:
    return {
        "total": 0,
        "translated": 0,
        "missing": 0,
        "stale": 0,
        "duplicate": 0,
        "orphan": 0,
        "unbound": 0,
        "source_length": 0,
        "translated_source_length": 0,
        "row_coverage": 1.0,
        "entry_coverage": 1.0,
        "weighted_coverage": 1.0,
        "character_weighted_coverage": 1.0,
        "missing_keys": [],
        "stale_keys": [],
        "duplicate_keys": [],
        "orphan_keys": [],
        "unbound_keys": [],
        "stale_identities": [],
        "duplicate_identities": [],
        "orphan_identities": [],
        "unbound_identities": [],
    }


def _coverage_for_kind(
    entries: list[CatalogEntry], rows: list[RuntimeRow],
) -> dict[str, object]:
    result = _empty_kind_report()
    result["total"] = len(entries)
    result["source_length"] = sum(len(normalize_source(entry.source)) for entry in entries)

    catalog_keys = {(entry.kind, entry.key) for entry in entries}
    entry_hashes = {_identity(entry): entry.source_sha256 for entry in entries}
    row_groups: dict[tuple[str, str], list[RuntimeRow]] = defaultdict(list)
    source_rows: dict[str, list[RuntimeRow]] = defaultdict(list)
    for row in rows:
        row_groups[_identity(row)].append(row)
        source_rows[row.source_sha256].append(row)

    # Dialogue/choice/item lookups intentionally have a source-global
    # fallback in the runtime.  Runtime capture uses key 0 for overhead text
    # while static UCXT rows use the PUSHS offset; count a reviewed row under
    # either identity as translated when the source hash proves they are the
    # same sentence.  Other resource kinds remain strictly key-based.
    source_fallback_kinds = {"dialogue", "choice", "item"}

    translated_length = 0
    translated = 0
    missing_keys: list[str] = []
    stale_keys: list[str] = []
    duplicate_keys: list[str] = []
    unbound_keys: set[str] = set()
    for entry in entries:
        identity = _identity(entry)
        matching = row_groups.get(identity, [])
        blank_source = not entry.source.strip()
        translated_rows = [
            row for row in matching
            if row.source_sha256 == entry.source_sha256
            and (bool(row.zh.strip()) or blank_source)
        ]
        if (
            not translated_rows
            and entry.kind in source_fallback_kinds
        ):
            translated_rows = [
                row for row in source_rows.get(entry.source_sha256, [])
                if row.zh.strip() or blank_source
            ]
        if not translated_rows:
            result["missing"] = int(result["missing"]) + 1
            missing_keys.append(entry.key)
        if translated_rows:
            translated += 1
            translated_length += len(normalize_source(entry.source))
        stale = [row for row in matching if row.source_sha256 != entry.source_sha256]
        if stale:
            result["stale"] = int(result["stale"]) + len(stale)
            stale_keys.extend(entry.key for _ in stale)
        if len(matching) > 1:
            result["duplicate"] = int(result["duplicate"]) + len(matching) - 1
            duplicate_keys.append(entry.key)
        if _is_unbound(entry.key) or any(_is_unbound(row.key) for row in matching):
            unbound_keys.add(entry.key)

    orphan_keys: list[str] = []
    catalog_source_hashes = {
        (entry.kind, entry.source_sha256) for entry in entries
    }
    for row in rows:
        if _identity(row) in catalog_keys:
            continue
        if _is_unobserved_placeholder_row(row, catalog_keys):
            continue
        if (
            row.kind in source_fallback_kinds
            and (row.kind, row.source_sha256) in catalog_source_hashes
        ):
            continue
        if _identity(row) not in catalog_keys:
            orphan_keys.append(row.key)

    result["translated"] = translated
    result["translated_source_length"] = translated_length
    result["orphan"] = len(orphan_keys)
    result["unbound"] = len(unbound_keys)
    result["missing_keys"] = sorted(missing_keys)
    result["stale_keys"] = sorted(set(stale_keys))
    result["duplicate_keys"] = sorted(set(duplicate_keys))
    result["orphan_keys"] = sorted(orphan_keys)
    result["unbound_keys"] = sorted(unbound_keys)
    result["stale_identities"] = [list(identity) for identity, group in sorted(row_groups.items()) if identity in entry_hashes and any(row.source_sha256 != entry_hashes[identity] for row in group)]
    result["duplicate_identities"] = [list(identity) for identity, group in sorted(row_groups.items()) if len(group) > 1]
    result["orphan_identities"] = [
        list(identity)
        for identity in sorted(
            {
                _identity(row)
                for row in rows
                if _identity(row) not in catalog_keys
                and not _is_unobserved_placeholder_row(row, catalog_keys)
            }
        )
    ]
    result["unbound_identities"] = sorted({(entry.kind, entry.key) for entry in entries if _is_unbound(entry.key)})
    result["unbound_identities"] = [list(identity) for identity in result["unbound_identities"]]
    total = int(result["total"])
    source_length = int(result["source_length"])
    result["row_coverage"] = translated / total if total else 1.0
    result["entry_coverage"] = result["row_coverage"]
    result["weighted_coverage"] = (
        translated_length / source_length if source_length else (1.0 if total == 0 else result["row_coverage"])
    )
    result["character_weighted_coverage"] = result["weighted_coverage"]
    return result


def coverage_report(catalog: list[CatalogEntry], rows: list[RuntimeRow]) -> dict[str, object]:
    """Return deterministic coverage metrics for every catalog kind."""

    by_kind = {kind: _empty_kind_report() for kind in KINDS}
    catalog_by_kind: dict[str, list[CatalogEntry]] = defaultdict(list)
    rows_by_kind: dict[str, list[RuntimeRow]] = defaultdict(list)
    for entry in catalog:
        catalog_by_kind[entry.kind].append(entry)
    for row in rows:
        rows_by_kind[row.kind].append(row)
    for kind in sorted(set(catalog_by_kind) | set(rows_by_kind) - set(KINDS)):
        by_kind.setdefault(kind, _empty_kind_report())
    for kind in by_kind:
        by_kind[kind] = _coverage_for_kind(catalog_by_kind[kind], rows_by_kind[kind])

    book_entries = [entry for entry in catalog if entry.context == "book"]
    book_identities = {_identity(entry) for entry in book_entries}
    book_rows = [row for row in rows if _identity(row) in book_identities]
    book_contents = _coverage_for_kind(book_entries, book_rows)
    placeholder_template_entries = [
        entry
        for entry in catalog
        if entry.kind == "dialogue" and _PLACEHOLDER_RE.search(entry.source)
    ]
    placeholder_template_identities = {
        _identity(entry) for entry in placeholder_template_entries
    }
    placeholder_template_rows = [
        row for row in rows if _identity(row) in placeholder_template_identities
    ]
    placeholder_templates = _coverage_for_kind(
        placeholder_template_entries, placeholder_template_rows
    )
    unobserved_placeholder_keys = sorted(
        row.key
        for row in rows
        if _is_unobserved_placeholder_row(row, placeholder_template_identities)
    )
    placeholder_templates["unobserved"] = len(unobserved_placeholder_keys)
    placeholder_templates["unobserved_keys"] = unobserved_placeholder_keys

    assembled_template_entries = [
        entry
        for entry in catalog
        if entry.kind == "dialogue"
        and "static-usecode-template" in entry.origin.split(";")
    ]
    assembled_template_identities = {
        _identity(entry) for entry in assembled_template_entries
    }
    assembled_template_rows = [
        row for row in rows if _identity(row) in assembled_template_identities
    ]
    assembled_templates = _coverage_for_kind(
        assembled_template_entries, assembled_template_rows
    )
    fragment_speech_boundaries = _fragment_speech_boundary_report(catalog, rows)

    totals = _empty_kind_report()
    for kind_report in by_kind.values():
        for field in ("total", "translated", "missing", "stale", "duplicate", "orphan", "unbound", "source_length", "translated_source_length"):
            totals[field] = int(totals[field]) + int(kind_report[field])
    total = int(totals["total"])
    source_length = int(totals["source_length"])
    totals["row_coverage"] = int(totals["translated"]) / total if total else 1.0
    totals["entry_coverage"] = totals["row_coverage"]
    totals["weighted_coverage"] = int(totals["translated_source_length"]) / source_length if source_length else (1.0 if total == 0 else totals["row_coverage"])
    totals["character_weighted_coverage"] = totals["weighted_coverage"]
    for field in ("missing_keys", "stale_keys", "duplicate_keys", "orphan_keys", "unbound_keys"):
        totals[field] = sorted({key for kind_report in by_kind.values() for key in kind_report[field]})
    for field in ("stale_identities", "duplicate_identities", "orphan_identities", "unbound_identities"):
        totals[field] = sorted({tuple(identity) for kind_report in by_kind.values() for identity in kind_report[field]})
        totals[field] = [list(identity) for identity in totals[field]]

    missing = list(totals["missing_keys"])
    stale = list(totals["stale_keys"])
    duplicates = list(totals["duplicate_keys"])
    orphans = list(totals["orphan_keys"])
    unbound = list(totals["unbound_keys"])
    return {
        "by_kind": by_kind,
        "kinds": by_kind,
        "book_contents": book_contents,
        "placeholder_templates": placeholder_templates,
        "assembled_templates": assembled_templates,
        "fragment_speech_boundaries": fragment_speech_boundaries,
        "totals": totals,
        "total": total,
        "translated": int(totals["translated"]),
        "missing": len(missing),
        "stale": int(totals["stale"]),
        "duplicate": int(totals["duplicate"]),
        "orphan": int(totals["orphan"]),
        "unbound": int(totals["unbound"]),
        "row_coverage": totals["row_coverage"],
        "entry_coverage": totals["entry_coverage"],
        "weighted_coverage": totals["weighted_coverage"],
        "character_weighted_coverage": totals["character_weighted_coverage"],
        "missing_keys": missing,
        "stale_keys": stale,
        "duplicates": duplicates,
        "orphans": orphans,
        "unbound_keys": unbound,
        "stale_identities": totals["stale_identities"],
        "duplicate_identities": totals["duplicate_identities"],
        "orphan_identities": totals["orphan_identities"],
        "unbound_identities": totals["unbound_identities"],
        "dialogue_segments": by_kind.get("dialogue", {}).get("total", 0),
        "choice_ordinals": by_kind.get("choice", {}).get("total", 0),
        "structural_failures": len(stale) + int(totals["duplicate"]) + len(orphans) + len(unbound),
    }


def _source_location(entry: CatalogEntry | None) -> str:
    return entry.origin if entry is not None and entry.origin else "runtime-table"


def _issue(
    *, key: str, check: str, severity: str, message: str,
    source_location: str, blocking: bool = True,
) -> dict[str, object]:
    return {
        "key": key,
        "check": check,
        "severity": severity,
        "message": message,
        "source_location": source_location,
        "blocking": blocking,
    }


def _key_is_valid(kind: str, key: str) -> bool:
    pattern = _KEY_PATTERNS.get(kind)
    return pattern is not None and pattern.fullmatch(key) is not None


def _has_chinese(text: str) -> bool:
    return any(
        "\u3400" <= character <= "\u4dbf"
        or "\u4e00" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in text
    )


def _is_only_protected_spell_text(text: str) -> bool:
    tokens = _AUDIT_TOKENS.findall(text)
    if not tokens:
        return False
    remainder = _AUDIT_TOKENS.sub("", text).strip(" \t\r\n\"'()[]{}.,!?！？。，、:：")
    return not remainder


def _is_non_linguistic_source(text: str) -> bool:
    """Return true for punctuation/number fragments with no translatable word."""

    if not any(character.isalpha() for character in text):
        return True
    return text.strip().casefold() in {"npc", "s"}


def _is_technical_source(kind: str, source: str) -> bool:
    """Recognize non-gameplay resource labels and format strings."""

    value = source.strip()
    if value in {"FRAME_BREAD", "/magic bolt//s"}:
        return True
    if kind == "dialogue":
        return value.startswith("Event ") and value.endswith(" called")
    if kind != "textmsg":
        return False
    return value in {
        "& |only |exactly | year| years| month| months| day| days| hour| hours|negative time!",
        "Roland MT-32",
        "Sound Blaster",
        "GS127",
        "Soundfont",
        "SFX",
        "ready_type: 0x",
        "3d:",
    }


def _is_runtime_greeting_value_row(entry: CatalogEntry, translated: str) -> bool:
    """Allow a structural ``Good <value>`` row to contain only a marker.

    The time word is supplied by runtime provenance and translated with the
    greeting context.  Requiring Chinese characters in the prefix/template
    would incorrectly reject the auditable ``@`` or ``<VAR0>`` scaffold.
    """

    if entry.kind != "dialogue":
        return False
    literal = entry.source.split("<", 1)[0] if "<" in entry.source else entry.source
    if re.search(r"\bGood\s*$", literal) is None:
        return False
    if _has_chinese(translated):
        return False
    remainder = _PLACEHOLDER_RE.sub("", translated).replace("@", "")
    return not any(character.isalpha() for character in remainder)


def _is_protected_term_only_source(
    source: str, term_rules: Iterable[tuple[str, str, str]]
) -> bool:
    """Allow standalone English protected terms to remain untranslated.

    A runtime value such as ``wisp`` is intentionally English-only.  It is
    still audited for the protected spelling, but should not be reported as a
    duplicated sentence or as missing Chinese output.  Longer sentences that
    merely contain the term continue through the normal language checks.
    """

    candidate = source.strip().strip("@~*").strip(
        " \t\r\n\"'()[]{}.,!?！？。，、:："
    )
    return any(
        policy == "protected" and candidate.casefold() == english.casefold()
        for english, _chinese, policy in term_rules
    )


def _required_greeting_translation(source: str) -> str | None:
    match = re.search(r"\bGood\s+(morning|afternoon|evening)\b", source, re.IGNORECASE)
    if match is None:
        return None
    return {
        "morning": "早安",
        "afternoon": "午安",
        "evening": "晚安",
    }[match.group(1).lower()]


def _has_literal_good_greeting(source: str) -> bool:
    literal = source.split("<", 1)[0] if "<" in source else source
    return re.search(r"\bGood\s*$", literal) is not None


def _is_opaque_language_entry(kind: str, key: str, source: str) -> bool:
    """Recognize U6 Gargish/incantation strings that must remain English."""

    if kind != "dialogue":
        return False
    parts = key.split(":")
    function_id = parts[1] if len(parts) > 1 else ""
    if function_id in _OPAQUE_LANGUAGE_FUNCTIONS:
        return True
    text = source.replace("@", "").replace("*", "").strip().casefold()
    return text in _OPAQUE_LANGUAGE_PHRASES


def _is_punctuation_only(text: str) -> bool:
    """Return true when a translated value contains no letters or digits."""

    return not any(character.isalpha() or character.isdigit() for character in text)


def _name_signature(text: str) -> str:
    return " ".join(re.findall(r"[A-Za-z0-9]+", text)).casefold()


@lru_cache(maxsize=8)
def _known_name_tokens(
    name_rules: tuple[tuple[str, str], ...],
) -> frozenset[str]:
    return frozenset(
        token.casefold()
        for _category, name in name_rules
        for token in re.findall(r"[A-Za-z0-9]+", name)
    )


def _is_name_only_source(source: str, name_rules: Iterable[tuple[str, str]]) -> bool:
    """Recognize a name or name/location label surrounded by formatting."""

    candidate = source.strip().strip("@~*").strip()
    tokens = re.findall(r"[A-Za-z0-9]+", candidate)
    if not tokens:
        return False
    known_tokens = _known_name_tokens(tuple(name_rules))
    recognized = False
    for token in tokens:
        normalized = token.casefold()
        if normalized == "x":
            continue
        if normalized not in known_tokens:
            return False
        recognized = True
    # ``(x)`` and an empty parenthesized marker are emitted by the scroll
    # roster display; they are formatting, not translatable prose.
    return recognized


def _name_protects_term(
    source: str, english: str, name_rules: Iterable[tuple[str, str]]
) -> bool:
    """Do not rewrite a glossary term when it is part of an English name."""

    return any(
        _contains_english_name(source, name)
        and _contains_english_name(name, english)
        for _category, name in name_rules
    )


def _load_glossary(
    path: Path,
) -> tuple[tuple[tuple[str, str, str], ...], str | None]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].split("\t") != ["en", "zh", "policy"]:
        raise ValueError("invalid U6 glossary header")
    result = []
    traditional_policy: str | None = None
    for line in lines[1:]:
        policy_match = _TRADITIONAL_POLICY_RE.fullmatch(line.strip())
        if policy_match:
            if traditional_policy is not None:
                raise ValueError("duplicate Traditional-Chinese policy declaration")
            traditional_policy = policy_match.group(1).lower()
            continue
        if line.lstrip().startswith("#"):
            continue
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != 3 or not all(fields):
            raise ValueError("invalid U6 glossary row")
        result.append((fields[0], fields[1], fields[2]))
    return tuple(result), traditional_policy


def _policy_tokens(policy: str) -> set[str]:
    return {token for token in re.split(r"[+,|/;:\s]+", policy.lower()) if token}


def _glossary_rules(
    entries: tuple[tuple[str, str, str], ...],
    traditional_policy: str | None,
) -> tuple[tuple[tuple[str, str, str], ...], set[str], str]:
    """Decode glossary policies into term checks and Traditional-Chinese rules."""

    term_rules: list[tuple[str, str, str]] = []
    # The character inventory is always active so every audit invocation
    # checks translated text.  The glossary policy only controls severity.
    traditional_characters: set[str] = set(_SIMPLIFIED_CHARACTERS)
    traditional_severity = traditional_policy or "warning"
    for english, chinese, policy in entries:
        tokens = _policy_tokens(policy)
        if tokens & {"translated", "translate", "required", "replacement"}:
            term_rules.append((english, chinese, "translated"))
        elif tokens & {"protected", "preserve", "keep"}:
            term_rules.append((english, chinese, "protected"))
        elif tokens & {"forbidden", "ban", "banned"}:
            term_rules.append((english, chinese, "forbidden"))
    return tuple(term_rules), traditional_characters, traditional_severity


def _load_name_policy(path: Path) -> tuple[tuple[str, str], ...]:
    """Load the English-only named-entity inventory."""

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or tuple(lines[0].split("\t")) != _NAME_POLICY_HEADER:
        raise ValueError("invalid U6 English-name policy header")
    names: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in lines[1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 2 or not all(fields):
            raise ValueError("invalid U6 English-name policy row")
        category, name = fields
        if category not in _NAME_CATEGORIES:
            raise ValueError(f"invalid U6 English-name policy category: {category!r}")
        identity = (category, name)
        if identity in seen:
            raise ValueError(f"duplicate U6 English-name policy row: {category}/{name}")
        seen.add(identity)
        names.append(identity)
    return tuple(names)


def _contains_english_name(text: str, name: str) -> bool:
    """Match a name without accepting it as part of a larger English word."""

    pattern = rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])"
    return re.search(pattern, text) is not None


def _contains_glossary_term(text: str, term: str) -> bool:
    """Match a glossary term as a complete token, including case variants.

    Single-word professional terms such as ``wisp`` and ``wisps`` must not
    cross-match each other (or a longer English word), while multi-word and
    non-ASCII glossary values retain their literal matching behavior.
    """

    if re.fullmatch(r"[A-Za-z0-9]+", term):
        pattern = rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
        return re.search(pattern, text, re.IGNORECASE) is not None
    return term in text


def _name_is_preserved_in_source_segment(
    source: str, translated: str, name: str
) -> bool:
    """Keep an inline name in the same marker-delimited text segment.

    U6 uses ``@`` as a display segment marker.  Requiring a named span to be
    present in the corresponding translated segment prevents a second English
    copy from being appended outside the translated sentence to mask a missing
    or transliterated name.
    """

    source_segments = source.split("@")
    translated_segments = translated.split("@")
    if len(source_segments) != len(translated_segments):
        # A translated value with an unmatched marker is usually an appended
        # English annotation (for example ``中文。@ Name``).  Do not let that
        # copy satisfy the name rule; only a complete marker pair can carry a
        # protected name when the segment counts differ.
        source_indices = [
            index
            for index, segment in enumerate(source_segments)
            if _contains_english_name(segment, name)
        ]
        if any(index % 2 for index in source_indices):
            if translated.count("@") == 0:
                return _contains_english_name(translated, name)
            if translated.count("@") % 2:
                return False
            return any(
                index % 2 and _contains_english_name(segment, name)
                for index, segment in enumerate(translated_segments)
            )
        return _contains_english_name(translated, name)
    source_indices = [
        index
        for index, segment in enumerate(source_segments)
        if _contains_english_name(segment, name)
    ]
    return bool(source_indices) and all(
        _contains_english_name(translated_segments[index], name)
        for index in source_indices
    )


def _append_coverage_issues(
    issues: list[dict[str, object]], coverage: dict[str, object], catalog_by_identity: dict[tuple[str, str], CatalogEntry],
) -> None:
    for field, check, message in (
        ("stale_identities", "source_hash", "source hash is stale"),
        ("duplicate_identities", "duplicate_row", "translation table contains duplicate rows"),
        ("orphan_identities", "orphan_row", "translation row is absent from catalog"),
        ("unbound_identities", "unbound_choice", "choice row has no runtime callsite binding"),
    ):
        for kind, key in coverage.get(field, []):
            entry = catalog_by_identity.get((kind, key))
            issues.append(_issue(
                key=key,
                check=check,
                severity="error",
                message=message,
                source_location=_source_location(entry),
            ))


def correctness_report(
    catalog: list[CatalogEntry],
    rows: list[RuntimeRow],
    glossary: Path,
    semantic_reviews: list[dict[str, object]] | None,
    semantic_strict: bool = False,
    names: Path | None = None,
    terms: Path | None = None,
) -> dict[str, object]:
    """Run deterministic checks and keep optional semantic results advisory."""

    coverage = coverage_report(catalog, rows)
    catalog_by_identity = {_identity(entry): entry for entry in catalog}
    issues: list[dict[str, object]] = []
    _append_coverage_issues(issues, coverage, catalog_by_identity)

    for entry in catalog:
        if entry.source_sha256 != source_sha256(entry.source):
            issues.append(_issue(key=entry.key, check="catalog_source_hash", severity="error", message="catalog source hash does not match source", source_location=_source_location(entry)))
        if not _key_is_valid(entry.kind, entry.key):
            issues.append(_issue(key=entry.key, check="key_syntax", severity="error", message="catalog key has invalid syntax", source_location=_source_location(entry)))

    try:
        glossary_entries, traditional_policy = _load_glossary(glossary)
        glossary_error = None
    except (OSError, UnicodeError, ValueError) as error:
        glossary_entries = ()
        traditional_policy = None
        glossary_error = str(error)
        issues.append(_issue(key="<glossary>", check="glossary", severity="error", message=glossary_error, source_location=str(glossary)))

    term_rules, traditional_characters, traditional_severity = _glossary_rules(
        glossary_entries, traditional_policy
    )

    english_term_error: str | None = None
    english_term_count = 0
    english_terms = ()
    if terms is not None:
        try:
            english_terms = load_english_terms(terms)
            english_term_count = len(english_terms)
            known_term_rules = set(term_rules)
            term_rules_list = list(term_rules)
            for term in english_terms:
                # Named people, locations, and proper entities are checked by
                # the name policy below. Professional terms use the same
                # protected-term path as glossary-backed wisp/wisps rows.
                if term.category != "professional":
                    continue
                if "protected" not in _policy_tokens(term.policy):
                    continue
                rule = (term.en, term.en, "protected")
                if rule not in known_term_rules:
                    term_rules_list.append(rule)
                    known_term_rules.add(rule)
            term_rules = tuple(term_rules_list)
        except (OSError, UnicodeError, ValueError) as error:
            english_term_error = str(error)
            issues.append(_issue(
                key="<english-terms>", check="english_terms", severity="error",
                message=english_term_error, source_location=str(terms),
            ))

    name_rules: tuple[tuple[str, str], ...] = ()
    name_error: str | None = None
    if names is not None:
        try:
            name_rules = _load_name_policy(names)
        except (OSError, UnicodeError, ValueError) as error:
            name_error = str(error)
            issues.append(_issue(
                key="<names>", check="english_name_policy", severity="error",
                message=name_error, source_location=str(names),
            ))

    if terms is not None and english_term_error is None:
        existing_names = {name.casefold() for _category, name in name_rules}
        name_rules_list = list(name_rules)
        for term in english_terms:
            if (
                term.category in _ENGLISH_TERM_NAME_CATEGORIES
                and "protected" in _policy_tokens(term.policy)
            ):
                rule = (term.category, term.en)
                if term.en.casefold() not in existing_names:
                    name_rules_list.append(rule)
                    existing_names.add(term.en.casefold())
        name_rules = tuple(name_rules_list)

    for row in rows:
        entry = catalog_by_identity.get(_identity(row))
        location = _source_location(entry)
        if row.kind not in KINDS or not _key_is_valid(row.kind, row.key):
            issues.append(_issue(key=row.key, check="key_syntax", severity="error", message="runtime key has invalid syntax", source_location="runtime-table"))
        if not _HASH_RE.fullmatch(row.source_sha256):
            issues.append(_issue(key=row.key, check="hash_format", severity="error", message="source_sha256 must be 64 lowercase hex characters", source_location="runtime-table"))
        if entry is None:
            continue
        if row.source_sha256 != entry.source_sha256:
            issues.append(_issue(key=row.key, check="source_hash", severity="error", message="runtime source hash does not match catalog", source_location=location))
        if not row.zh.strip() and entry.source.strip():
            issues.append(_issue(key=row.key, check="nonempty_zh", severity="error", message="Chinese translation is empty", source_location=location))
            continue

        if row.kind == "item":
            source_parts = entry.source.split("/")
            translated_parts = row.zh.split("/")
            invalid_quantity_format = len(source_parts) != len(translated_parts)
            if (
                not invalid_quantity_format
                and len(source_parts) == 4
                and source_parts[-1]
                and translated_parts[-1] == source_parts[-1]
                and _has_chinese(row.zh)
            ):
                invalid_quantity_format = True
            if invalid_quantity_format:
                issues.append(_issue(
                    key=row.key,
                    check="item_name_format",
                    severity="error",
                    message="item quantity name slash/plural structure differs from source",
                    source_location=location,
                ))

        english_name_only = _is_name_only_source(entry.source, name_rules)
        opaque_language = _is_opaque_language_entry(entry.kind, entry.key, entry.source)
        non_translatable = _is_non_linguistic_source(entry.source) or _is_technical_source(entry.kind, entry.source)
        english_only_glossary_term = _is_protected_term_only_source(
            entry.source, term_rules
        )

        expected_markers = _non_placeholder_markers(entry.source)
        actual_markers = _non_placeholder_markers(row.zh)
        if expected_markers != actual_markers:
            issues.append(_issue(key=row.key, check="protected_markers", severity="error", message="protected marker multiset differs from source", source_location=location))

        # Legacy UCXT segments may intentionally carry only one side of an
        # ``@`` pair; the compiled static-template rows represent the whole
        # expression and must retain its speech boundaries for display-time
        # quote formatting.
        if (
            row.kind == "dialogue"
            and "static-usecode-template" in entry.origin.split(";")
            and _usecode_speech_marker_count(entry.source)
            != _usecode_speech_marker_count(row.zh)
        ):
            issues.append(_issue(
                key=row.key,
                check="dialogue_speech_markers",
                severity="error",
                message="usecode @ speech-marker count differs from source",
                source_location=location,
            ))

        if row.kind == "dialogue" and set(entry.origin.split(";")) & {
            "static-ucxt", "static-fallback-item-say-ucxt"
        }:
            boundary_deficits = _split_speech_boundary_deficit(
                entry.source, row.zh
            )
            if boundary_deficits:
                labels = " and ".join(boundary_deficits)
                issues.append(_issue(
                    key=row.key,
                    check="fragment_speech_boundary",
                    severity="warning",
                    message=(
                        f"UCXT fragment omits its {labels} @ speech boundary; "
                        "runtime restores it from VM provenance"
                    ),
                    source_location=location,
                    blocking=False,
                ))

        expected_placeholders = len(_PLACEHOLDER_RE.findall(entry.source))
        actual_placeholders = len(_PLACEHOLDER_RE.findall(row.zh))
        if expected_placeholders != actual_placeholders:
            issues.append(_issue(key=row.key, check="placeholders", severity="error", message="placeholder count differs from source", source_location=location))

        source = normalize_source(entry.source)
        translated = normalize_source(row.zh)
        runtime_greeting_row = _is_runtime_greeting_value_row(entry, translated)
        required_greeting = _required_greeting_translation(source)
        if (
            (
                required_greeting is not None
                and required_greeting not in translated
            )
            or (_has_literal_good_greeting(source) and "美好的" in translated)
        ) and not runtime_greeting_row:
            expected = required_greeting or "the Taiwan greeting form"
            issues.append(_issue(
                key=row.key,
                check="greeting_terms",
                severity="error",
                message=f"Good time-of-day greeting must use {expected}",
                source_location=location,
            ))
        if _ascii_dot_runs(source) != _ascii_dot_runs(translated):
            issues.append(_issue(
                key=row.key,
                check="ascii_dot_runs",
                severity="error",
                message="ASCII dot runs (.., ..., and longer runs) must remain unchanged",
                source_location=location,
            ))
        if translated.count("\n") < source.count("\n"):
            issues.append(_issue(key=row.key, check="newlines", severity="error", message="newline structure differs from source", source_location=location))
        if source.strip() == translated.strip() and not (
            non_translatable
            or english_name_only
            or opaque_language
            or english_only_glossary_term
            or (row.kind == "spell" and _is_only_protected_spell_text(row.zh))
        ):
            issues.append(_issue(key=row.key, check="source_duplication", severity="error", message="translation duplicates the English source", source_location=location))
        if (
            _is_exact_repetition(row.zh)
            and not _is_exact_repetition(source.replace("@", ""))
            and not _is_punctuation_only(row.zh)
        ):
            issues.append(_issue(key=row.key, check="duplicate_translation", severity="error", message="translation repeats the same complete text twice", source_location=location))

        if (
            row.kind != "spell"
            and not non_translatable
            and not english_name_only
            and not opaque_language
            and not english_only_glossary_term
            and not runtime_greeting_row
            and not _has_chinese(row.zh)
            and not _is_only_protected_spell_text(row.zh)
        ):
            issues.append(_issue(key=row.key, check="traditional_chinese", severity="warning", message="translation contains no Traditional Chinese text", source_location=location, blocking=False))
            issues.append(_issue(key=row.key, check="chinese_output", severity="error", message="translation contains no Chinese text", source_location=location))
        simplified = sorted(set(character for character in row.zh if character in traditional_characters))
        if simplified:
            issues.append(_issue(
                key=row.key,
                check="traditional_chinese",
                severity=traditional_severity,
                message="translation contains simplified character(s): " + "".join(simplified),
                source_location=location,
                blocking=traditional_severity == "error",
            ))

        source_spell_terms = [token for token in _AUDIT_TOKENS.findall(entry.source) if token.startswith("@")] if row.kind == "spell" else []
        actual_spell_terms = [token for token in _AUDIT_TOKENS.findall(row.zh) if token.startswith("@")] if row.kind == "spell" else []
        if source_spell_terms != actual_spell_terms:
            issues.append(_issue(key=row.key, check="protected_spell_terms", severity="error", message="protected spell terms changed", source_location=location))

        for english, chinese, policy in term_rules:
            if non_translatable or opaque_language:
                continue
            if not _contains_glossary_term(entry.source, english):
                continue
            if _name_protects_term(entry.source, english, name_rules):
                continue
            if policy == "translated" and not _contains_glossary_term(row.zh, chinese):
                issues.append(_issue(key=row.key, check="glossary", severity="error", message=f"glossary term {english!r} must use {chinese!r}", source_location=location))
            elif policy == "protected" and not _contains_glossary_term(row.zh, english):
                issues.append(_issue(key=row.key, check="protected_term", severity="error", message=f"glossary term {english!r} must remain protected", source_location=location))
            elif policy == "forbidden" and _contains_glossary_term(row.zh, english):
                issues.append(_issue(key=row.key, check="protected_term", severity="error", message=f"glossary term {english!r} must not appear in the translation", source_location=location))

        for category, name in name_rules:
            if not _contains_english_name(entry.source, name):
                continue
            source_is_name = entry.source.strip() == name
            translated_name_is_valid = (
                row.zh.strip() == name
                if source_is_name
                else _name_is_preserved_in_source_segment(
                    entry.source, row.zh, name
                )
            )
            if not translated_name_is_valid:
                requirement = "remain exactly English" if source_is_name else "remain in English"
                issues.append(_issue(
                    key=row.key,
                    check="english_name",
                    severity="error",
                    message=f"{category} name {name!r} must {requirement}",
                    source_location=location,
                ))

    for conflict in repeated_source_conflicts(catalog, rows):
        source = str(conflict["source"])
        translations = ", ".join(str(value) for value in conflict["translations"])
        for kind, key in conflict["identities"]:
            entry = catalog_by_identity.get((str(kind), str(key)))
            issues.append(_issue(
                key=str(key),
                check="term_consistency",
                severity="error",
                message=f"repeated English source {source!r} has conflicting translations: {translations}",
                source_location=_source_location(entry),
            ))

    deterministic = {
        "issues": issues,
        "failure_count": sum(1 for issue in issues if issue["blocking"]),
        "warning_count": sum(1 for issue in issues if issue["severity"] == "warning"),
        "has_failures": any(issue["blocking"] for issue in issues),
    }
    reviews = list(semantic_reviews or [])
    semantic_failures = [
        review for review in reviews
        if review.get("status") not in {"ok", "approved"}
        or bool(review.get("issues"))
    ]
    return {
        "coverage": coverage,
        "deterministic": deterministic,
        "issues": issues,
        "semantic_reviews": reviews,
        "semantic": {
            "count": len(reviews),
            "reviews": reviews,
            "policy": "strict" if semantic_strict else "advisory",
            "has_failures": semantic_strict and bool(semantic_failures),
            "blocking_failures": semantic_failures if semantic_strict else [],
        },
        "glossary": str(glossary),
        "glossary_error": glossary_error,
        "traditional_chinese_policy": traditional_policy,
        "names": str(names) if names is not None else None,
        "name_policy_error": name_error,
        "english_name_count": len(name_rules),
        "terms": str(terms) if terms is not None else None,
        "english_term_error": english_term_error,
        "english_term_count": english_term_count,
    }


def combine_audit_reports(
    coverage: dict[str, object],
    correctness: dict[str, object],
) -> dict[str, object]:
    """Combine coverage and correctness without dropping either report."""

    deterministic = correctness["deterministic"]
    return {
        "coverage": coverage,
        "correctness": correctness,
        "issues": list(deterministic["issues"]),
        "deterministic": deterministic,
        "semantic_reviews": list(correctness["semantic_reviews"]),
        "semantic": correctness.get("semantic", {}),
    }


def load_audit_table(path: Path) -> tuple[list[RuntimeRow], list[dict[str, object]]]:
    """Load a table while retaining malformed UTF-8/TSV issues for reporting."""

    issues: list[dict[str, object]] = []
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        issues.append(_issue(key="<table>", check="utf8", severity="error", message=str(error), source_location=str(path)))
        return [], issues

    lines = text.split("\n")
    expected_headers = (
        "# u6-translation-v1",
        "# kind\tkey\tsource_sha256\tzh",
    )
    for index, expected in enumerate(expected_headers):
        if index >= len(lines) or lines[index] != expected:
            issues.append(_issue(
                key="<table>", check=("table_version", "table_columns")[index],
                severity="error", message="table header is not the exact U6 release header",
                source_location=f"{path}:{index + 1}",
            ))

    if issues:
        return [], issues

    rows: list[RuntimeRow] = []
    for line_number, line in enumerate(lines[2:], 3):
        if not line.strip() or line.startswith("#"):
            continue
        location = f"{path}:{line_number}"
        fields = line.split("\t")
        if len(fields) != 4:
            issues.append(_issue(key=fields[1] if len(fields) > 1 else "<unknown>", check="field_count", severity="error", message="TSV row must contain exactly four fields", source_location=location))
            continue
        try:
            decoded = tuple(unescape_field(field) for field in split_tsv_fields(line, 4))
        except ValueError as error:
            issues.append(_issue(key=fields[1], check="tsv_escaping", severity="error", message=str(error), source_location=location))
            continue
        rows.append(RuntimeRow(*decoded))
    return rows, issues


def merge_input_issues(report: dict[str, object], input_issues: Iterable[dict[str, object]]) -> dict[str, object]:
    """Attach raw-table issues to a correctness or combined report."""

    additions = list(input_issues)
    if not additions:
        return report
    if "deterministic" in report:
        deterministic = report["deterministic"]
    elif "correctness" in report:
        deterministic = report["correctness"]["deterministic"]
    else:
        report["deterministic"] = {"issues": [], "failure_count": 0, "warning_count": 0, "has_failures": False}
        deterministic = report["deterministic"]
    issues = deterministic["issues"]
    issues.extend(additions)
    deterministic["failure_count"] += len(additions)
    deterministic["has_failures"] = True
    report["issues"] = issues
    return report


def _report_parts(report: dict[str, object]) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else None
    correctness = report.get("correctness") if isinstance(report.get("correctness"), dict) else None
    if coverage is None and "by_kind" in report:
        coverage = report
    if correctness is None and "deterministic" in report:
        correctness = report
    return coverage, correctness


def report_exit_code(report: dict[str, object], strict: bool) -> int:
    coverage, correctness = _report_parts(report)
    if coverage is not None:
        totals = coverage.get("totals", {})
        if any(int(totals.get(field, 0)) for field in ("stale", "duplicate", "orphan", "unbound")):
            return 1
        if strict and int(totals.get("missing", 0)):
            return 1
    if correctness is not None:
        deterministic = correctness.get("deterministic", {})
        if deterministic.get("has_failures"):
            return 1
        semantic = correctness.get("semantic", {})
        if semantic.get("has_failures"):
            return 1
    return 0


def format_terminal_report(report: dict[str, object]) -> str:
    coverage, correctness = _report_parts(report)
    if coverage is None:
        coverage = {}
    by_kind = coverage.get("by_kind", {})
    lines = ["U6 translation audit"]
    lines.append("kind                 total translated missing stale duplicate orphan unbound weighted")
    for kind in sorted(by_kind):
        values = by_kind[kind]
        lines.append(
            f"{kind:<20} {int(values['total']):>5} {int(values['translated']):>10} "
            f"{int(values['missing']):>7} {int(values['stale']):>5} {int(values['duplicate']):>9} "
            f"{int(values['orphan']):>6} {int(values['unbound']):>7} {float(values['weighted_coverage']):>8.3f}"
        )
    totals = coverage.get("totals")
    if isinstance(totals, dict):
        lines.append(
            f"total                {int(totals['total']):>5} {int(totals['translated']):>10} "
            f"{int(totals['missing']):>7} {int(totals['stale']):>5} {int(totals['duplicate']):>9} "
            f"{int(totals['orphan']):>6} {int(totals['unbound']):>7} {float(totals['weighted_coverage']):>8.3f}"
        )
    book_contents = coverage.get("book_contents")
    if isinstance(book_contents, dict):
        lines.append(
            f"book contents: {int(book_contents['total'])} total, "
            f"{int(book_contents['translated'])} translated, "
            f"{int(book_contents['missing'])} missing"
        )
    placeholder_templates = coverage.get("placeholder_templates")
    if isinstance(placeholder_templates, dict):
        lines.append(
            f"placeholder templates: {int(placeholder_templates['total'])} total, "
            f"{int(placeholder_templates['translated'])} translated, "
            f"{int(placeholder_templates['missing'])} missing, "
            f"{int(placeholder_templates.get('unobserved', 0))} unobserved"
        )
    assembled_templates = coverage.get("assembled_templates")
    if isinstance(assembled_templates, dict):
        lines.append(
            f"assembled templates: {int(assembled_templates['total'])} total, "
            f"{int(assembled_templates['translated'])} translated, "
            f"{int(assembled_templates['missing'])} missing"
        )
    fragment_boundaries = coverage.get("fragment_speech_boundaries")
    if isinstance(fragment_boundaries, dict):
        lines.append(
            f"fragment speech boundaries: {int(fragment_boundaries['total'])} total, "
            f"{int(fragment_boundaries['at_risk'])} restored from provenance"
        )
    if correctness is not None:
        deterministic = correctness.get("deterministic", {})
        lines.append(f"deterministic issues: {len(deterministic.get('issues', []))}")
        traditional_policy = correctness.get("traditional_chinese_policy") or "warning"
        traditional_issues = sum(
            1
            for issue in deterministic.get("issues", [])
            if issue.get("check") == "traditional_chinese"
        )
        lines.append(
            f"Traditional-Chinese policy: {traditional_policy}; "
            f"issues: {traditional_issues}"
        )
        english_name_count = correctness.get("english_name_count")
        if english_name_count is not None:
            english_name_issues = sum(
                1 for issue in deterministic.get("issues", [])
                if issue.get("check") == "english_name"
            )
            lines.append(
                f"English-name policy: {int(english_name_count)} names; "
                f"issues: {english_name_issues}"
            )
        english_term_count = correctness.get("english_term_count")
        if english_term_count is not None:
            english_term_issues = sum(
                1
                for issue in deterministic.get("issues", [])
                if issue.get("check") in {"protected_term", "english_terms"}
            )
            lines.append(
                f"English-term manifest: {int(english_term_count)} entries; "
                f"issues: {english_term_issues}"
            )
        lines.append(f"semantic reviews: {len(correctness.get('semantic_reviews', []))}")
    return "\n".join(lines) + "\n"


def write_json_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
