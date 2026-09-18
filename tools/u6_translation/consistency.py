from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping

from .catalog import CatalogEntry, normalize_source
from .runtime_table import RuntimeRow


def canonicalize_repeated_translations(
    entries: Iterable[CatalogEntry], records: Iterable[Mapping[str, object]]
) -> list[dict[str, object]]:
    """Use one candidate for every exact repeated English source string.

    Exact repeated strings are safe translation-memory entries: the same
    source is shown in multiple runtime identities and should not drift just
    because it was sent in a different batch or cache generation.
    """

    ordered_entries = list(entries)
    by_key = {entry.key: dict(record) for entry, record in zip(ordered_entries, records)}
    source_counts: defaultdict[str, int] = defaultdict(int)
    for entry in ordered_entries:
        source_counts[normalize_source(entry.source)] += 1

    canonical: dict[str, str] = {}
    for entry in ordered_entries:
        source = normalize_source(entry.source)
        if source_counts[source] < 2 or source in canonical:
            continue
        value = by_key.get(entry.key, {}).get("zh")
        if isinstance(value, str) and value.strip():
            canonical[source] = value.strip()

    result: list[dict[str, object]] = []
    for entry in ordered_entries:
        record = dict(by_key.get(entry.key, {}))
        source = normalize_source(entry.source)
        if source in canonical and isinstance(record.get("zh"), str):
            record["zh"] = canonical[source]
        result.append(record)
    return result


def repeated_source_conflicts(
    entries: Iterable[CatalogEntry], rows: Iterable[RuntimeRow]
) -> list[dict[str, object]]:
    """Return repeated prose sources that have multiple ZH outputs.

    One-character values are UCXT assembly fragments (for example ``a`` or
    ``.``), not independently translatable sentences.  Their translations
    legitimately depend on the surrounding fragment, so comparing them as
    translation-memory entries creates false blocking conflicts.
    """

    ordered_entries = list(entries)
    rows_by_identity = {(row.kind, row.key): row for row in rows}
    grouped: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
    for entry in ordered_entries:
        row = rows_by_identity.get((entry.kind, entry.key))
        if row is None or not row.zh.strip():
            continue
        source = normalize_source(entry.source).strip()
        if len(source) <= 1 or source.count("@") % 2:
            continue
        grouped[source].append((entry.key, row.zh.strip()))

    conflicts: list[dict[str, object]] = []
    for source, values in grouped.items():
        translations: list[str] = []
        for _key, translation in values:
            if translation not in translations:
                translations.append(translation)
        if len(translations) > 1:
            conflicts.append(
                {
                    "source": source,
                    "keys": [key for key, _translation in values],
                    "identities": [
                        [entry.kind, entry.key]
                        for entry in ordered_entries
                        if entry.key in {key for key, _translation in values}
                    ],
                    "translations": translations,
                }
            )
    return conflicts
