from __future__ import annotations

import unittest

from tools.u6_translation.catalog import CatalogEntry, source_sha256
from tools.u6_translation.consistency import (
    canonicalize_repeated_translations,
    repeated_source_conflicts,
)
from tools.u6_translation.runtime_table import RuntimeRow


def _entry(key: str, source: str) -> CatalogEntry:
    return CatalogEntry(
        kind="dialogue",
        key=key,
        source=source,
        source_sha256=source_sha256(source),
        context="gameplay",
        origin="fixture",
        protected_tokens=(),
    )


class TranslationConsistencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = [
            _entry("dialogue:0x0401:10:0", "The Fellowship"),
            _entry("dialogue:0x0401:20:0", "The Fellowship"),
        ]

    def test_repeated_source_uses_first_nonempty_translation_as_canonical(self) -> None:
        records = [
            {"key": self.entries[0].key, "zh": "友誼會"},
            {"key": self.entries[1].key, "zh": " fellowship "},
        ]

        canonical = canonicalize_repeated_translations(self.entries, records)

        self.assertEqual([record["zh"] for record in canonical], ["友誼會", "友誼會"])

    def test_consistency_audit_reports_conflicting_repeated_source_translations(self) -> None:
        rows = [
            RuntimeRow(entry.kind, entry.key, entry.source_sha256, zh)
            for entry, zh in zip(self.entries, ("友誼會", "團契"))
        ]

        conflicts = repeated_source_conflicts(self.entries, rows)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["source"], "The Fellowship")
        self.assertEqual(conflicts[0]["translations"], ["友誼會", "團契"])


if __name__ == "__main__":
    unittest.main()
