from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .catalog import CatalogEntry, load_catalog
from .ollama_backend import OllamaBackend
from .prompts import glossary_sha256
from .runtime_table import RuntimeRow, load_runtime_table, write_runtime_table


_CACHE_VERSION = 1


def make_cache_key(
    *,
    operation: str,
    source_sha256: str,
    model: str,
    prompt_version: str,
    glossary_hash: str,
) -> str:
    return json.dumps(
        {
            "operation": operation,
            "source_sha256": source_sha256,
            "model": model,
            "prompt_version": prompt_version,
            "glossary_sha256": glossary_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _backend_model(backend: OllamaBackend) -> str:
    config = getattr(backend, "config", None)
    model = getattr(config, "model", None)
    return model if isinstance(model, str) and model else "unknown"


def _load_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != _CACHE_VERSION:
        raise ValueError("invalid translation cache")
    entries = data.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("invalid translation cache entries")
    return {key: value for key, value in entries.items() if isinstance(key, str) and isinstance(value, dict)}


def _write_cache(path: Path, entries: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": _CACHE_VERSION, "entries": entries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _valid_translation(record: object, entry: CatalogEntry) -> bool:
    if not isinstance(record, dict):
        return False
    return (
        record.get("key") == entry.key
        and record.get("source_sha256") == entry.source_sha256
        and isinstance(record.get("zh"), str)
        and isinstance(record.get("status"), str)
    )


def _ordered_translation_response(
    entries: list[CatalogEntry], records: list[dict[str, str]]
) -> dict[str, dict[str, str]]:
    by_key: dict[str, dict[str, str]] = {}
    for record in records:
        key = record.get("key")
        if not isinstance(key, str) or key in by_key:
            raise ValueError("translation backend returned duplicate or invalid key")
        by_key[key] = record
    if set(by_key) != {entry.key for entry in entries}:
        raise ValueError("translation backend response keys do not match request batch")
    ordered: dict[str, dict[str, str]] = {}
    for entry in entries:
        record = by_key[entry.key]
        if not _valid_translation(record, entry):
            raise ValueError("translation backend returned invalid record: " + entry.key)
        ordered[entry.key] = {
            "key": record["key"],
            "source_sha256": record["source_sha256"],
            "zh": record["zh"],
            "status": record["status"],
        }
    return ordered


def translate_catalog(
    catalog_path: Path,
    output_path: Path,
    cache_path: Path,
    backend: OllamaBackend,
    prompt_version: str,
) -> None:
    catalog = load_catalog(catalog_path)
    model = _backend_model(backend)
    glossary_hash = glossary_sha256()
    cache = _load_cache(cache_path)
    translations: dict[str, dict[str, str]] = {}
    pending: list[CatalogEntry] = []

    for entry in catalog:
        cache_key = make_cache_key(
            operation="translate",
            source_sha256=entry.source_sha256,
            model=model,
            prompt_version=prompt_version,
            glossary_hash=glossary_hash,
        )
        cached = cache.get(cache_key)
        if _valid_translation(cached, entry):
            translations[entry.key] = {
                "key": cached["key"],
                "source_sha256": cached["source_sha256"],
                "zh": cached["zh"],
                "status": cached["status"],
            }
        else:
            pending.append(entry)

    if pending:
        generated = _ordered_translation_response(pending, backend.translate_batch(pending))
        for entry in pending:
            cache_key = make_cache_key(
                operation="translate",
                source_sha256=entry.source_sha256,
                model=model,
                prompt_version=prompt_version,
                glossary_hash=glossary_hash,
            )
            translations[entry.key] = generated[entry.key]
            cache[cache_key] = generated[entry.key]
        _write_cache(cache_path, cache)

    rows = [
        RuntimeRow(entry.kind, entry.key, entry.source_sha256, translations[entry.key]["zh"])
        for entry in catalog
    ]
    write_runtime_table(output_path, rows)


def _valid_review(record: object, entry: CatalogEntry) -> bool:
    if not isinstance(record, dict):
        return False
    return (
        record.get("key") == entry.key
        and record.get("source_sha256") == entry.source_sha256
        and isinstance(record.get("status"), str)
        and isinstance(record.get("issues"), list)
        and all(isinstance(issue, str) for issue in record["issues"])
        and isinstance(record.get("suggested_zh"), str)
    )


def _ordered_review_response(
    entries: list[CatalogEntry], records: list[dict[str, object]]
) -> list[dict[str, object]]:
    by_key: dict[str, dict[str, object]] = {}
    for record in records:
        key = record.get("key")
        if not isinstance(key, str) or key in by_key:
            raise ValueError("review backend returned duplicate or invalid key")
        by_key[key] = record
    if set(by_key) != {entry.key for entry in entries}:
        raise ValueError("review backend response keys do not match request batch")
    ordered: list[dict[str, object]] = []
    for entry in entries:
        record = by_key[entry.key]
        if not _valid_review(record, entry):
            raise ValueError("review backend returned invalid record: " + entry.key)
        ordered.append(
            {
                "key": record["key"],
                "source_sha256": record["source_sha256"],
                "status": record["status"],
                "issues": list(record["issues"]),
                "suggested_zh": record["suggested_zh"],
            }
        )
    return ordered


def review_catalog(
    catalog_path: Path,
    table_path: Path,
    output_path: Path,
    backend: OllamaBackend,
    prompt_version: str,
) -> None:
    catalog = load_catalog(catalog_path)
    table_rows = load_runtime_table(table_path)
    catalog_by_identity = {(entry.kind, entry.key): entry for entry in catalog}
    selected: list[tuple[CatalogEntry, RuntimeRow]] = []
    for row in table_rows:
        entry = catalog_by_identity.get((row.kind, row.key))
        if entry is None:
            raise ValueError("translation table row is not present in catalog: " + row.key)
        if row.source_sha256 != entry.source_sha256:
            raise ValueError("translation table source hash mismatch: " + row.key)
        selected.append((entry, row))
    selected.sort(key=lambda pair: catalog.index(pair[0]))
    entries = [entry for entry, _ in selected]
    translations = [
        {
            "key": entry.key,
            "source_sha256": entry.source_sha256,
            "zh": row.zh,
            "status": "candidate",
        }
        for entry, row in selected
    ]
    records = _ordered_review_response(entries, backend.review_batch(entries, translations))
    model = _backend_model(backend)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(
            json.dumps(
                {
                    **record,
                    "model": model,
                    "prompt_version": prompt_version,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
