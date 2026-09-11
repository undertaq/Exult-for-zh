from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.u6_translation.catalog import CatalogEntry, source_sha256
from tools.u6_translation.review_html import build_review_html, write_review_html
from tools.u6_translation.runtime_table import RuntimeRow


class ReviewHtmlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = [
            CatalogEntry(
                kind="dialogue",
                key="dialogue:0x0401:10:0",
                source='Say "hello"',
                source_sha256=source_sha256('Say "hello"'),
                context="gameplay",
                origin="fixture",
                protected_tokens=(),
            )
        ]
        self.rows = [
            RuntimeRow(
                self.entries[0].kind,
                self.entries[0].key,
                self.entries[0].source_sha256,
                "說「你好」",
            )
        ]

    def test_html_has_editable_translation_and_accepted_default(self) -> None:
        html = build_review_html(
            self.entries,
            self.rows,
            model="qwen3.8:27b",
            prompt_version="u6-zh-traditional-v2",
        )

        self.assertIn("<textarea", html)
        self.assertIn("accepted by default", html)
        self.assertIn("Needs modification", html)
        self.assertIn("Download review JSONL", html)
        self.assertIn("localStorage", html)
        self.assertIn("Say &quot;hello&quot;", html)
        self.assertIn('"status": "approved"', html)

    def test_html_embedded_rows_include_identity_hash_and_candidate(self) -> None:
        html = build_review_html(
            self.entries,
            self.rows,
            model="test-model",
            prompt_version="test-prompt",
        )

        self.assertIn(self.entries[0].key, html)
        self.assertIn(self.entries[0].source_sha256, html)
        self.assertIn("說「你好」", html)

    def test_write_review_html_creates_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "review.html"

            write_review_html(
                output,
                self.entries,
                self.rows,
                model="test-model",
                prompt_version="test-prompt",
            )

            self.assertTrue(output.exists())
            self.assertIn("U6 Translation Review", output.read_text(encoding="utf-8"))

    def test_blank_source_row_is_accepted_by_default(self) -> None:
        entry = CatalogEntry.from_source(
            "dialogue", "dialogue:0x0401:11:0", "", "gameplay", "fixture"
        )

        html = build_review_html(
            [entry],
            [RuntimeRow(entry.kind, entry.key, entry.source_sha256, "")],
            model="test-model",
            prompt_version="test-prompt",
        )

        self.assertIn('"status": "approved"', html)


if __name__ == "__main__":
    unittest.main()
