from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from typing import Iterable

from .catalog import CatalogEntry, normalize_source, source_sha256, _TOKENS
from .runtime_table import RuntimeRow, escape_field, split_tsv_fields, unescape_field


KINDS = ("dialogue", "choice", "textmsg", "item", "location", "misc", "spell")
_KEY_PATTERNS = {
    "dialogue": re.compile(r"^dialogue:0x[0-9a-f]{4}:[A-Za-z0-9_]+:\d+$"),
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
    }


def _coverage_for_kind(
    entries: list[CatalogEntry], rows: list[RuntimeRow],
) -> dict[str, object]:
    result = _empty_kind_report()
    result["total"] = len(entries)
    result["source_length"] = sum(len(entry.source) for entry in entries)

    catalog_keys = {(entry.kind, entry.key) for entry in entries}
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
        if not matching:
            result["missing"] = int(result["missing"]) + 1
            missing_keys.append(entry.key)
        valid = [row for row in matching if row.source_sha256 == entry.source_sha256 and bool(row.zh.strip())]
        if valid:
            translated += 1
            translated_length += len(valid[0].zh)
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
    total = int(result["total"])
    source_length = int(result["source_length"])
    result["row_coverage"] = translated / total if total else 1.0
    result["entry_coverage"] = result["row_coverage"]
    result["weighted_coverage"] = (
        translated_length / source_length if source_length else 1.0
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
    totals["weighted_coverage"] = int(totals["translated_source_length"]) / source_length if source_length else 1.0
    totals["character_weighted_coverage"] = totals["weighted_coverage"]
    for field in ("missing_keys", "stale_keys", "duplicate_keys", "orphan_keys", "unbound_keys"):
        totals[field] = sorted({key for kind_report in by_kind.values() for key in kind_report[field]})

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


def _load_glossary(path: Path) -> tuple[tuple[str, str, str], ...]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].split("\t") != ["en", "zh", "policy"]:
        raise ValueError("invalid U6 glossary header")
    result = []
    for line in lines[1:]:
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != 3 or not all(fields):
            raise ValueError("invalid U6 glossary row")
        result.append((fields[0], fields[1], fields[2]))
    return tuple(result)


def _append_coverage_issues(
    issues: list[dict[str, object]], coverage: dict[str, object], catalog_by_identity: dict[tuple[str, str], CatalogEntry],
) -> None:
    for key in coverage["stale_keys"]:
        entry = next((entry for identity, entry in catalog_by_identity.items() if identity[1] == key), None)
        issues.append(_issue(key=key, check="source_hash", severity="error", message="source hash is stale", source_location=_source_location(entry)))
    for key in coverage["duplicates"]:
        entry = next((entry for identity, entry in catalog_by_identity.items() if identity[1] == key), None)
        issues.append(_issue(key=key, check="duplicate_row", severity="error", message="translation table contains duplicate rows", source_location=_source_location(entry)))
    for key in coverage["orphans"]:
        issues.append(_issue(key=key, check="orphan_row", severity="error", message="translation row is absent from catalog", source_location="runtime-table"))
    for key in coverage["unbound_keys"]:
        entry = next((entry for identity, entry in catalog_by_identity.items() if identity[1] == key), None)
        issues.append(_issue(key=key, check="unbound_choice", severity="error", message="choice row has no runtime callsite binding", source_location=_source_location(entry)))


def correctness_report(
    catalog: list[CatalogEntry],
    rows: list[RuntimeRow],
    glossary: Path,
    semantic_reviews: list[dict[str, object]] | None,
) -> dict[str, object]:
    """Run deterministic checks and keep optional semantic results advisory."""

    coverage = coverage_report(catalog, rows)
    catalog_by_identity = {_identity(entry): entry for entry in catalog}
    issues: list[dict[str, object]] = []
    _append_coverage_issues(issues, coverage, catalog_by_identity)

    for entry in catalog:
        if not _key_is_valid(entry.kind, entry.key):
            issues.append(_issue(key=entry.key, check="key_syntax", severity="error", message="catalog key has invalid syntax", source_location=_source_location(entry)))
        if _is_unbound(entry.key):
            continue

    rows_by_identity: dict[tuple[str, str], list[RuntimeRow]] = defaultdict(list)
    for row in rows:
        rows_by_identity[_identity(row)].append(row)

    try:
        glossary_entries = _load_glossary(glossary)
        glossary_error = None
    except (OSError, UnicodeError, ValueError) as error:
        glossary_entries = ()
        glossary_error = str(error)
        issues.append(_issue(key="<glossary>", check="glossary", severity="error", message=glossary_error, source_location=str(glossary)))

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
        if not row.zh.strip():
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

        if row.kind != "spell" and not _has_chinese(row.zh) and not _is_only_protected_spell_text(row.zh):
            issues.append(_issue(key=row.key, check="traditional_chinese", severity="warning", message="translation contains no Traditional Chinese text", source_location=location))
            issues.append(_issue(key=row.key, check="chinese_output", severity="error", message="translation contains no Chinese text", source_location=location))
        simplified = sorted(set(character for character in row.zh if character in _SIMPLIFIED_TO_TRADITIONAL))
        if simplified:
            issues.append(_issue(key=row.key, check="traditional_chinese", severity="warning", message="translation contains simplified character(s): " + "".join(simplified), source_location=location))

        source_spell_terms = [token for token in _AUDIT_TOKENS.findall(entry.source) if token.startswith("@")] if row.kind == "spell" else []
        actual_spell_terms = [token for token in _AUDIT_TOKENS.findall(row.zh) if token.startswith("@")] if row.kind == "spell" else []
        if source_spell_terms != actual_spell_terms:
            issues.append(_issue(key=row.key, check="protected_spell_terms", severity="error", message="protected spell terms changed", source_location=location))

        for english, chinese, policy in glossary_entries:
            if english in entry.source and policy == "translated" and chinese not in row.zh:
                issues.append(_issue(key=row.key, check="glossary", severity="error", message=f"glossary term {english!r} must use {chinese!r}", source_location=location))

    deterministic = {
        "issues": issues,
        "failure_count": sum(1 for issue in issues if issue["blocking"]),
        "warning_count": sum(1 for issue in issues if issue["severity"] == "warning"),
        "has_failures": bool(issues),
    }
    reviews = list(semantic_reviews or [])
    return {
        "coverage": coverage,
        "deterministic": deterministic,
        "issues": issues,
        "semantic_reviews": reviews,
        "semantic": {"count": len(reviews), "reviews": reviews},
        "glossary": str(glossary),
        "glossary_error": glossary_error,
    }


def load_audit_table(path: Path) -> tuple[list[RuntimeRow], list[dict[str, object]]]:
    """Load a table while retaining malformed UTF-8/TSV issues for reporting."""

    issues: list[dict[str, object]] = []
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        issues.append(_issue(key="<table>", check="utf8", severity="error", message=str(error), source_location=str(path)))
        return [], issues

    rows: list[RuntimeRow] = []
    for line_number, line in enumerate(text.splitlines(), 1):
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
    report.setdefault("issues", issues)
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
