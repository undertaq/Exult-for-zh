from __future__ import annotations

import unittest
from pathlib import Path

from tools.u6_translation.audit import (
    correctness_report,
    coverage_report,
    format_terminal_report,
    report_exit_code,
)
from tools.u6_translation.catalog import CatalogEntry, source_sha256
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
        self.assertLess(report["by_kind"]["dialogue"]["weighted_coverage"], 1.0)
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

    def test_terminal_report_is_deterministic_and_mentions_kind_coverage(self) -> None:
        report = coverage_report(self.catalog, self.rows)
        terminal = format_terminal_report(report)
        self.assertIn("U6 translation audit", terminal)
        self.assertIn("choice", terminal)
        self.assertIn("weighted", terminal)


if __name__ == "__main__":
    unittest.main()
