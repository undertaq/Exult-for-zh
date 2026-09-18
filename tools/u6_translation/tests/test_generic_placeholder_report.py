from __future__ import annotations

from pathlib import Path
import unittest


class GenericPlaceholderReportTest(unittest.TestCase):
    def test_offline_before_after_report_is_self_contained(self) -> None:
        report = Path(__file__).parents[3] / "reports/u6_generic_placeholder_before_after.html"
        self.assertTrue(report.is_file())
        html = report.read_text(encoding="utf-8")
        self.assertIn("Generic placeholder handling", html)
        self.assertIn("before", html.lower())
        self.assertIn("after", html.lower())
        self.assertIn("fallback_", html)
        self.assertNotIn("<script src=", html.lower())
        self.assertNotIn("<link rel=\"stylesheet\"", html.lower())


if __name__ == "__main__":
    unittest.main()
