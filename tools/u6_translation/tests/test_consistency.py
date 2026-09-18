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

    def test_consistency_ignores_single_character_assembly_fragments(self) -> None:
        entries = [
            _entry("dialogue:0x0282:10:0", "a"),
            _entry("dialogue:0x02cb:8:0", "a"),
            _entry("dialogue:0x0401:10:0", "."),
            _entry("dialogue:0x0401:11:0", "."),
            _entry("dialogue:0x043a:7a:0", "crowns, okay?@"),
            _entry("dialogue:0x047d:220:0", "crowns, okay?@"),
        ]
        rows = [
            RuntimeRow(entries[0].kind, entries[0].key, entries[0].source_sha256, "a"),
            RuntimeRow(entries[1].kind, entries[1].key, entries[1].source_sha256, "一個"),
            RuntimeRow(entries[2].kind, entries[2].key, entries[2].source_sha256, "完成探索之前，他不會把地圖交給你。"),
            RuntimeRow(entries[3].kind, entries[3].key, entries[3].source_sha256, "位。"),
            RuntimeRow(entries[4].kind, entries[4].key, entries[4].source_sha256, "克朗，好嗎？"),
            RuntimeRow(entries[5].kind, entries[5].key, entries[5].source_sha256, "克朗，好嗎？@"),
        ]

        self.assertEqual(repeated_source_conflicts(entries, rows), [])


if __name__ == "__main__":
    unittest.main()
