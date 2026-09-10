from __future__ import annotations

import json
from pathlib import Path

from .audit import correctness_report
from .catalog import CatalogEntry
from .prompts import GLOSSARY_PATH
from .runtime_table import RuntimeRow, escape_field


TABLE_HEADER = "# u6-translation-v1\n# kind\tkey\tsource_sha256\tzh\n"
_REVIEW_STATUSES = {"approved", "needs-review", "rejected"}
_REQUIRED_REVIEW_FIELDS = {
    "key", "source_sha256", "status", "issues", "suggested_zh", "model", "prompt_version",
}


def _load_reviews(path: Path) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ValueError(f"cannot read review file {path}: {error}") from error
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid review JSON at {path}:{line_number}") from error
        if not isinstance(record, dict):
            raise ValueError(f"review row at {path}:{line_number} must be an object")
        records.append(record)
    return records


def _review_kind(record: dict[str, object], by_key: dict[str, CatalogEntry]) -> str:
    kind = record.get("kind")
    key = record.get("key")
    if isinstance(kind, str):
        return kind
    if isinstance(key, str) and key in by_key:
        # Task 7 review records did not include kind; infer it to preserve that
        # accepted JSONL contract while accepting the richer Task 8 format.
        return by_key[key].kind
    raise ValueError("review row must contain kind")


def _review_translation(record: dict[str, object]) -> str:
    value = record.get("zh")
    if value is None:
        # Task 7 stored the candidate in suggested_zh. Task 8 records normally
        # carry zh explicitly, but accepting the former keeps the pipeline
        # resumable without rewriting old review files.
        value = record.get("suggested_zh")
    if not isinstance(value, str):
        raise ValueError("review row must contain a Chinese translation")
    return value


def _validate_review_records(
    catalog: list[CatalogEntry], records: list[dict[str, object]]
) -> list[RuntimeRow]:
    by_identity = {(entry.kind, entry.key): entry for entry in catalog}
    by_key = {entry.key: entry for entry in catalog}
    seen: set[tuple[str, str]] = set()
    rows: list[RuntimeRow] = []
    for record in records:
        missing = sorted(_REQUIRED_REVIEW_FIELDS - set(record))
        if missing:
            raise ValueError("review row missing " + ", ".join(missing))
        key = record.get("key")
        source_hash = record.get("source_sha256")
        status = record.get("status")
        if not all(isinstance(value, str) for value in (key, source_hash, status)):
            raise ValueError("review key, source_sha256, and status must be strings")
        kind = _review_kind(record, by_key)
        identity = (kind, key)
        if identity in seen:
            raise ValueError("duplicate review row: " + key)
        seen.add(identity)
        entry = by_identity.get(identity)
        if entry is None:
            raise ValueError("review row is absent from catalog: " + key)
        if source_hash != entry.source_sha256:
            raise ValueError("review source hash mismatch: " + key)
        if status not in _REVIEW_STATUSES:
            raise ValueError("invalid review status: " + status)
        if status != "approved":
            raise ValueError("review row is not approved: " + key)
        issues = record.get("issues")
        if not isinstance(issues, list) or not all(isinstance(issue, str) for issue in issues):
            raise ValueError("review issues must be a JSON array of strings: " + key)
        for field in ("model", "prompt_version", "suggested_zh"):
            if not isinstance(record.get(field), str):
                raise ValueError(f"review {field} must be a string: {key}")
        rows.append(RuntimeRow(kind, key, source_hash, _review_translation(record)))

    expected = set(by_identity)
    if seen != expected:
        missing = sorted(expected - seen)
        extra = sorted(seen - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(key for _kind, key in missing))
        if extra:
            details.append("orphan " + ", ".join(key for _kind, key in extra))
        raise ValueError("review rows do not exactly cover catalog: " + "; ".join(details))
    return rows


def _write_versioned_table(path: Path, rows: list[RuntimeRow]) -> None:
    ordered = sorted(rows, key=lambda row: (row.kind, row.key, row.source_sha256, row.zh))
    body = "".join(
        "\t".join(escape_field(value) for value in (row.kind, row.key, row.source_sha256, row.zh)) + "\n"
        for row in ordered
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TABLE_HEADER + body, encoding="utf-8")


def emit_approved_table(
    catalog: list[CatalogEntry], review_path: Path, output_path: Path
) -> None:
    """Emit a release table only after review and deterministic checks pass."""

    identities = [(entry.kind, entry.key) for entry in catalog]
    if len(set(identities)) != len(identities):
        raise ValueError("catalog contains duplicate kind/key identities")
    records = _load_reviews(review_path)
    rows = _validate_review_records(catalog, records)
    audit = correctness_report(catalog, rows, GLOSSARY_PATH, None)
    deterministic = audit["deterministic"]
    if deterministic["has_failures"]:
        checks = sorted({str(issue["check"]) for issue in deterministic["issues"]})
        raise ValueError("deterministic audit failed: " + ", ".join(checks))
    _write_versioned_table(output_path, rows)
