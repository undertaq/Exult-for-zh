from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools.u6_translation.audit import correctness_report
from tools.u6_translation.catalog import CatalogEntry
from tools.u6_translation.runtime_table import RuntimeRow
from tools.u6_translation.terms import load_english_terms


class EnglishTermsTest(unittest.TestCase):
    def test_manifest_includes_legacy_people_locations_and_professional_terms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "names.tsv").write_text(
                "category\ten\n"
                "npc\tDaver\n"
                "place\tBritannia\n",
                encoding="utf-8",
            )
            manifest = root / "terms.tsv"
            manifest.write_text(
                "category\ten\tpolicy\n"
                "# include names.tsv\n"
                "professional\twisp\truntime_term+protected\n",
                encoding="utf-8",
            )

            terms = load_english_terms(manifest)

        self.assertEqual(
            {(term.category, term.en, term.policy) for term in terms},
            {
                ("person", "Daver", "protected"),
                ("location", "Britannia", "protected"),
                ("professional", "wisp", "runtime_term+protected"),
            },
        )

    def test_audit_uses_manifest_for_names_and_professional_terms(self) -> None:
        entry = CatalogEntry.from_source(
            "dialogue",
            "dialogue:0x0401:100:0",
            "Daver sees a wisp.",
            "gameplay",
            "test",
        )
        row = RuntimeRow(
            entry.kind,
            entry.key,
            entry.source_sha256,
            "戴弗看見靈光。",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = root / "names.tsv"
            names.write_text("category\ten\nnpc\tDaver\n", encoding="utf-8")
            terms = root / "terms.tsv"
            terms.write_text(
                "category\ten\tpolicy\n"
                "# include names.tsv\n"
                "professional\twisp\truntime_term+protected\n",
                encoding="utf-8",
            )
            glossary = root / "glossary.tsv"
            glossary.write_text("en\tzh\tpolicy\n", encoding="utf-8")

            report = correctness_report(
                [entry], [row], glossary, None, terms=terms
            )

        checks = {
            issue["check"] for issue in report["deterministic"]["issues"]
        }
        self.assertIn("english_name", checks)
        self.assertIn("protected_term", checks)

    def test_manifest_protects_professional_terms_across_catalog_kinds(self) -> None:
        sources = [
            ("dialogue", "dialogue:0x0401:101:0", "A wisp appears.", "一個 wisp 出現了。"),
            ("choice", "choice:0x0401:0x0089:0", "Fight wisps", "對抗 wisps"),
            ("dialogue", "dialogue:0x0282:101:0", "A book about wisps.", "一本介紹 wisps 的書。"),
            ("item", "item:0x01f4:1:0", "wisp", "wisp"),
            ("dialogue", "dialogue:0x0000:runtime:9", "wisps", "wisps"),
        ]
        entries = [
            CatalogEntry.from_source(kind, key, source, "gameplay", "test")
            for kind, key, source, _translation in sources
        ]
        rows = [
            RuntimeRow(entry.kind, entry.key, entry.source_sha256, translation)
            for entry, (_kind, _key, _source, translation) in zip(entries, sources)
        ]
        with tempfile.TemporaryDirectory() as directory:
            terms = Path(directory) / "terms.tsv"
            terms.write_text(
                "category\ten\tpolicy\n"
                "professional\twisp\truntime_term+protected\n"
                "professional\twisps\truntime_term+protected\n",
                encoding="utf-8",
            )
            glossary = Path(directory) / "glossary.tsv"
            glossary.write_text("en\tzh\tpolicy\n", encoding="utf-8")
            report = correctness_report(entries, rows, glossary, None, terms=terms)

        self.assertNotIn(
            "protected_term",
            {issue["check"] for issue in report["deterministic"]["issues"]},
        )
