from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from typing import Iterable

from .catalog import CatalogEntry, normalize_source, source_sha256
from .consistency import repeated_source_conflicts
from .runtime_table import RuntimeRow, split_tsv_fields, unescape_field


KINDS = ("dialogue", "choice", "textmsg", "item", "location", "misc", "spell")
_KEY_PATTERNS = {
    "dialogue": re.compile(r"^dialogue:0x[0-9a-f]{4}:[0-9a-f]+(?:_[0-9a-f]+)*:\d+$"),
    "choice": re.compile(r"^choice:0x[0-9a-f]{4}:(?:0x[0-9a-f]{4}|unbound):\d+$"),
    "item": re.compile(r"^item:0x[0-9a-f]{4}:\d+:\d+$"),
    "textmsg": re.compile(r"^textmsg:0x[0-9a-f]+$"),
    "location": re.compile(r"^location:0x[0-9a-f]+$"),
    "misc": re.compile(r"^misc:0x[0-9a-f]+$"),
    "spell": re.compile(r"^spell:0x[0-9a-f]+$"),
}
_PLACEHOLDER_RE = re.compile(r"<[A-Z][A-Z0-9_]*>|\{[A-Za-z0-9_.-]+\}")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_AUDIT_TOKENS = re.compile(r"@[^@\n]+@|~|\*|<(?:PLAYER_NAME|HONORIFIC|PRONOUN|GENDER_FLAG|VAR)>")
_TRADITIONAL_POLICY_RE = re.compile(
    r"^#\s*policy\s*:?\s+traditional[_-]chinese\s*=\s*(warning|error)\s*$",
    re.IGNORECASE,
)
_SIMPLIFIED_TO_TRADITIONAL = str.maketrans({
    "简": "簡", "体": "體", "汉": "漢", "语": "語", "国": "國",
    "门": "門", "后": "後", "发": "發", "们": "們", "这": "這",
    "个": "個", "为": "為", "复": "復", "药": "藥", "术": "術",
    "剑": "劍", "爱": "愛", "学": "學", "头": "頭", "见": "見",
    "开": "開", "关": "關", "时": "時", "间": "間", "东": "東",
    "电": "電", "风": "風", "马": "馬", "鱼": "魚", "龙": "龍",
    "宝": "寶", "岛": "島", "炉": "爐", "灭": "滅", "气": "氣",
    "灵": "靈", "华": "華", "画": "畫", "书": "書", "万": "萬",
    "与": "與", "传": "傳", "让": "讓", "听": "聽", "说": "說",
    "读": "讀", "写": "寫", "习": "習", "阵": "陣", "伤": "傷",
    "敌": "敵", "数": "數", "认": "認", "识": "識", "对": "對",
    "错": "錯", "实": "實", "现": "現", "处": "處", "战": "戰",
    "杂": "雜", "圣": "聖", "术": "術", "炼": "煉", "炼": "煉",
})


def _identity(value: CatalogEntry | RuntimeRow) -> tuple[str, str]:
    return value.kind, value.key


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
    for row in rows:
        row_groups[_identity(row)].append(row)

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
        if not matching or not any(row.zh.strip() or blank_source for row in matching):
            result["missing"] = int(result["missing"]) + 1
            missing_keys.append(entry.key)
        valid = [
            row for row in matching
            if row.source_sha256 == entry.source_sha256
            and (bool(row.zh.strip()) or blank_source)
        ]
        if valid:
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
    for row in rows:
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
            {_identity(row) for row in rows if _identity(row) not in catalog_keys}
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
    traditional_characters: set[str] = set()
    traditional_severity = traditional_policy or "warning"
    for english, chinese, policy in entries:
        tokens = _policy_tokens(policy)
        if tokens & {"translated", "translate", "required", "replacement"}:
            term_rules.append((english, chinese, "translated"))
        elif tokens & {"protected", "preserve", "keep"}:
            term_rules.append((english, chinese, "protected"))
        elif tokens & {"forbidden", "ban", "banned"}:
            term_rules.append((english, chinese, "forbidden"))
    if traditional_policy is not None:
        traditional_characters = {chr(code) for code in _SIMPLIFIED_TO_TRADITIONAL}
    return tuple(term_rules), traditional_characters, traditional_severity


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

        expected_markers = Counter(_AUDIT_TOKENS.findall(entry.source))
        actual_markers = Counter(_AUDIT_TOKENS.findall(row.zh))
        if expected_markers != actual_markers:
            issues.append(_issue(key=row.key, check="protected_markers", severity="error", message="protected marker multiset differs from source", source_location=location))

        expected_placeholders = Counter(_PLACEHOLDER_RE.findall(entry.source))
        actual_placeholders = Counter(_PLACEHOLDER_RE.findall(row.zh))
        if expected_placeholders != actual_placeholders:
            issues.append(_issue(key=row.key, check="placeholders", severity="error", message="placeholder set differs from source", source_location=location))

        source = normalize_source(entry.source)
        translated = normalize_source(row.zh)
        if source.count("\n") != translated.count("\n"):
            issues.append(_issue(key=row.key, check="newlines", severity="error", message="newline structure differs from source", source_location=location))
        if source.strip() == translated.strip() and not (row.kind == "spell" and _is_only_protected_spell_text(row.zh)):
            issues.append(_issue(key=row.key, check="source_duplication", severity="error", message="translation duplicates the English source", source_location=location))
        if _is_exact_repetition(row.zh):
            issues.append(_issue(key=row.key, check="duplicate_translation", severity="error", message="translation repeats the same complete text twice", source_location=location))

        if row.kind != "spell" and not _has_chinese(row.zh) and not _is_only_protected_spell_text(row.zh):
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
            if english not in entry.source:
                continue
            if policy == "translated" and chinese not in row.zh:
                issues.append(_issue(key=row.key, check="glossary", severity="error", message=f"glossary term {english!r} must use {chinese!r}", source_location=location))
            elif policy == "protected" and english not in row.zh:
                issues.append(_issue(key=row.key, check="protected_term", severity="error", message=f"glossary term {english!r} must remain protected", source_location=location))
            elif policy == "forbidden" and english in row.zh:
                issues.append(_issue(key=row.key, check="protected_term", severity="error", message=f"glossary term {english!r} must not appear in the translation", source_location=location))

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

    lines = text.splitlines()
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
    if correctness is not None:
        deterministic = correctness.get("deterministic", {})
        lines.append(f"deterministic issues: {len(deterministic.get('issues', []))}")
        lines.append(f"semantic reviews: {len(correctness.get('semantic_reviews', []))}")
    return "\n".join(lines) + "\n"


def write_json_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
