from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from tools.u6_translation.audit import (
    correctness_report,
    coverage_report,
    format_terminal_report,
    report_exit_code,
)
from tools.u6_translation.catalog import CatalogEntry
from tools.u6_translation.runtime_table import RuntimeRow, load_runtime_table


FIXTURES = Path(__file__).parent / "fixtures"
GLOSSARY = Path(__file__).parents[1] / "u6_glossary.tsv"


def _entry(kind: str, key: str, source: str) -> CatalogEntry:
    return CatalogEntry.from_source(kind, key, source, "gameplay", "audit-fixture")


class AuditReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = [
            _entry("dialogue", "dialogue:0x0401:0x0010:0", "Hello"),
            _entry("choice", "choice:0x0401:0x0088:0", "yes"),
            _entry("choice", "choice:0x0401:0x0088:1", "no"),
            _entry("choice", "choice:0x0401:unbound:2", "maybe"),
            _entry("textmsg", "textmsg:0x0123", "The bed is occupied."),
            _entry("item", "item:0x01f4:0:0", "a torch"),
            _entry("dialogue", "dialogue:0x0401:0x0020:0", "Wait ~ here"),
            _entry("dialogue", "dialogue:0x0401:0x0021:0", "Hello <PLAYER_NAME>"),
            _entry("misc", "misc:0x0042", "Welcome"),
            _entry("spell", "spell:0x0012", "@Corp Por@"),
            _entry("misc", "misc:0x0043", "The Avatar"),
            _entry("misc", "misc:0x0044", "Same"),
        ]
        self.rows = load_runtime_table(FIXTURES / "bad_translation.tsv")

    def test_coverage_reports_all_kinds_and_weighted_dialogue_choice_counts(self) -> None:
        report = coverage_report(self.catalog, self.rows)

        self.assertEqual(
            set(report["by_kind"]),
            {"dialogue", "choice", "textmsg", "item", "location", "misc", "spell"},
        )
        self.assertEqual(report["by_kind"]["choice"]["total"], 3)
        self.assertEqual(report["by_kind"]["choice"]["translated"], 2)
        self.assertEqual(report["by_kind"]["choice"]["missing"], 1)
        self.assertEqual(report["by_kind"]["choice"]["unbound"], 1)
        self.assertEqual(report["by_kind"]["item"]["duplicate"], 1)
        self.assertEqual(report["by_kind"]["textmsg"]["stale"], 1)
        self.assertEqual(len(report["orphans"]), 1)
        self.assertEqual(report["by_kind"]["dialogue"]["total"], 3)
        self.assertEqual(report["by_kind"]["dialogue"]["translated"], 3)
        self.assertEqual(report["by_kind"]["dialogue"]["weighted_coverage"], 1.0)
        self.assertEqual(report["totals"]["total"], len(self.catalog))

    def test_correctness_reports_structural_and_translation_issues_separately(self) -> None:
        report = correctness_report(self.catalog, self.rows, GLOSSARY, [])
        issues = report["deterministic"]["issues"]
        checks = {issue["check"] for issue in issues}

        self.assertIn("protected_markers", checks)
        self.assertIn("placeholders", checks)
        self.assertIn("traditional_chinese", checks)
        self.assertIn("glossary", checks)
        self.assertIn("protected_spell_terms", checks)
        self.assertIn("source_duplication", checks)
        self.assertEqual(report["semantic_reviews"], [])
        self.assertTrue(all({"key", "check", "severity", "source_location"} <= set(issue) for issue in issues))
        simplified = next(issue for issue in issues if issue["check"] == "traditional_chinese")
        self.assertEqual(simplified["severity"], "warning")

    def test_exit_code_allows_only_reviewable_missing_rows_in_non_strict_mode(self) -> None:
        missing_only = coverage_report(
            [_entry("choice", "choice:0x0401:0x0088:0", "yes")], []
        )
        self.assertEqual(report_exit_code(missing_only, strict=False), 0)
        self.assertNotEqual(report_exit_code(missing_only, strict=True), 0)

        report = coverage_report(self.catalog, self.rows)
        self.assertNotEqual(report_exit_code(report, strict=False), 0)

    def test_weighted_coverage_uses_normalized_source_lengths(self) -> None:
        entry = _entry("dialogue", "dialogue:0x0401:0x0030:0", "Long English source")
        report = coverage_report([entry], [
            RuntimeRow(entry.kind, entry.key, entry.source_sha256, "短")
        ])
        self.assertEqual(report["totals"]["translated_source_length"], len(entry.source))
        self.assertEqual(report["weighted_coverage"], 1.0)

    def test_empty_translation_counts_as_missing(self) -> None:
        entry = _entry("choice", "choice:0x0401:0x0090:0", "yes")
        report = coverage_report([entry], [
            RuntimeRow(entry.kind, entry.key, entry.source_sha256, "   ")
        ])
        self.assertEqual(report["by_kind"]["choice"]["missing"], 1)
        self.assertEqual(report["by_kind"]["choice"]["translated"], 0)
        self.assertEqual(report_exit_code(report, strict=False), 0)

    def test_glossary_configures_protected_terms_and_traditional_policy(self) -> None:
        catalog = [_entry("misc", "misc:0x0050", "Avatar Rune")]
        row = RuntimeRow("misc", "misc:0x0050", catalog[0].source_sha256, "聖者 Rune 简")
        with tempfile.TemporaryDirectory() as directory:
            glossary = Path(directory) / "glossary.tsv"
            glossary.write_text(
                "en\tzh\tpolicy\n"
                "Avatar\t聖者\ttranslated\n"
                "Rune\tRune\tprotected\n"
                "# policy traditional_chinese=warning\n",
                encoding="utf-8",
            )
            report = correctness_report(catalog, [row], glossary, None)
        self.assertFalse(report["deterministic"]["has_failures"])
        self.assertEqual({issue["check"] for issue in report["deterministic"]["issues"]}, {"traditional_chinese"})
        self.assertFalse(report["deterministic"]["issues"][0]["blocking"])
        bad_row = RuntimeRow("misc", "misc:0x0050", catalog[0].source_sha256, "聖者 符文")
        with tempfile.TemporaryDirectory() as directory:
            glossary = Path(directory) / "glossary.tsv"
            glossary.write_text("en\tzh\tpolicy\nAvatar\t聖者\ttranslated\nRune\tRune\tprotected\n", encoding="utf-8")
            bad_report = correctness_report(catalog, [bad_row], glossary, None)
        self.assertIn("protected_term", {issue["check"] for issue in bad_report["deterministic"]["issues"]})

    def test_traditional_policy_requires_glossary_declaration(self) -> None:
        entry = _entry("misc", "misc:0x0052", "Welcome")
        row = RuntimeRow(entry.kind, entry.key, entry.source_sha256, "简体中文")
        with tempfile.TemporaryDirectory() as directory:
            undeclared = Path(directory) / "undeclared.tsv"
            undeclared.write_text("en\tzh\tpolicy\n", encoding="utf-8")
            undeclared_report = correctness_report([entry], [row], undeclared, None)

            declared = Path(directory) / "declared.tsv"
            declared.write_text(
                "en\tzh\tpolicy\n"
                "# policy traditional_chinese=error\n",
                encoding="utf-8",
            )
            declared_report = correctness_report([entry], [row], declared, None)

        self.assertNotIn(
            "traditional_chinese",
            {issue["check"] for issue in undeclared_report["deterministic"]["issues"]},
        )
        traditional = [
            issue for issue in declared_report["deterministic"]["issues"]
            if issue["check"] == "traditional_chinese"
        ]
        self.assertEqual(len(traditional), 1)
        self.assertEqual(traditional[0]["severity"], "error")
        self.assertTrue(traditional[0]["blocking"])

    def test_orphan_identity_reporting_is_sorted_and_deduplicated(self) -> None:
        rows = [
            RuntimeRow("misc", "misc:0x0099", "a" * 64, "甲"),
            RuntimeRow("misc", "misc:0x0099", "b" * 64, "乙"),
            RuntimeRow("item", "item:0x0abc:0:0", "c" * 64, "物"),
        ]
        report = coverage_report([], rows)

        self.assertEqual(
            report["by_kind"]["misc"]["orphan_identities"],
            [["misc", "misc:0x0099"]],
        )
        self.assertEqual(
            report["orphan_identities"],
            [["item", "item:0x0abc:0:0"], ["misc", "misc:0x0099"]],
        )

    def test_traditional_warning_is_non_blocking(self) -> None:
        entry = _entry("misc", "misc:0x0051", "Welcome")
        row = RuntimeRow(entry.kind, entry.key, entry.source_sha256, "简体中文")
        report = correctness_report([entry], [row], GLOSSARY, None)
        warnings = [issue for issue in report["deterministic"]["issues"] if issue["severity"] == "warning"]
        self.assertTrue(warnings)
        self.assertFalse(report["deterministic"]["has_failures"])
        self.assertEqual(report_exit_code(report, strict=False), 0)

    def test_coverage_issues_use_kind_and_key_identity(self) -> None:
        dialogue = CatalogEntry.from_source("dialogue", "dialogue:0x0401:0x0070:0", "Hello", "gameplay", "dialogue-origin")
        choice = CatalogEntry.from_source("choice", "dialogue:0x0401:0x0070:0", "yes", "gameplay", "choice-origin")
        rows = [
            RuntimeRow(dialogue.kind, dialogue.key, "0" * 64, "你好"),
            RuntimeRow(choice.kind, choice.key, "0" * 64, "是"),
        ]
        report = correctness_report([dialogue, choice], rows, GLOSSARY, None)
        stale = [issue for issue in report["deterministic"]["issues"] if issue["check"] == "source_hash"]
        self.assertEqual({issue["source_location"] for issue in stale}, {"dialogue-origin", "choice-origin"})

    def test_terminal_report_is_deterministic_and_mentions_kind_coverage(self) -> None:
        report = coverage_report(self.catalog, self.rows)
        terminal = format_terminal_report(report)
        self.assertIn("U6 translation audit", terminal)
        self.assertIn("choice", terminal)
        self.assertIn("weighted", terminal)


if __name__ == "__main__":
    unittest.main()
