from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.u6_translation.catalog import CatalogEntry
from tools.u6_translation.emit import emit_approved_table
from tools.u6_translation.runtime_table import load_runtime_table


FIXTURES = Path(__file__).parent / "fixtures"


def _catalog_from_reviews() -> list[CatalogEntry]:
    entries = []
    for line in (FIXTURES / "approved_review.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        entries.append(
            CatalogEntry.from_source(
                record["kind"],
                record["key"],
                {
                    "dialogue:0x0401:10:0": "Hello",
                    "choice:0x0401:0x0088:0": "yes",
                    "textmsg:0x0123": "Hello there",
                    "item:0x01f4:0:0": "a torch",
                    "location:0x002a": "Britain",
                    "misc:0x0042": "the Avatar",
                    "spell:0x0012": "@Corp Por@",
                }[record["key"]],
                "gameplay",
                "emit-fixture",
            )
        )
    return entries


class EmitApprovedTableTest(unittest.TestCase):
    def test_emission_defaults_to_the_staged_release_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "deploy" / "zh_translation.tsv"
            with patch("tools.u6_translation.emit.DEFAULT_TABLE_PATH", output):
                emit_approved_table(
                    _catalog_from_reviews(),
                    FIXTURES / "approved_review.jsonl",
                )

            self.assertTrue(output.exists())
            self.assertEqual(len(load_runtime_table(output)), 7)

    def test_emission_requires_approved_review_and_writes_sorted_versioned_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "zh_translation.tsv"
            emit_approved_table(
                _catalog_from_reviews(),
                FIXTURES / "approved_review.jsonl",
                output,
            )
            raw = output.read_text(encoding="utf-8")
            rows = load_runtime_table(output)

        self.assertEqual(raw.splitlines()[:2], [
            "# u6-translation-v1",
            "# kind\tkey\tsource_sha256\tzh",
        ])
        self.assertNotIn(b"\\t", raw.encode("utf-8").splitlines()[1])
        self.assertEqual(
            [(row.kind, row.key) for row in rows],
            sorted((entry.kind, entry.key) for entry in _catalog_from_reviews()),
        )
        self.assertEqual(len(rows), 7)

    def test_emission_rejects_non_approved_review_without_writing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            review = Path(directory) / "review.jsonl"
            records = [
                json.loads(line)
                for line in (FIXTURES / "approved_review.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            records[0]["status"] = "needs-review"
            review.write_text(
                "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
                encoding="utf-8",
            )
            output = Path(directory) / "zh_translation.tsv"
            with self.assertRaises(ValueError):
                emit_approved_table(_catalog_from_reviews(), review, output)
            self.assertFalse(output.exists())

    def test_emission_rejects_deterministic_marker_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            review = Path(directory) / "review.jsonl"
            records = [
                json.loads(line)
                for line in (FIXTURES / "approved_review.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            records[-1]["zh"] = "焚燒"
            review.write_text(
                "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
                encoding="utf-8",
            )
            output = Path(directory) / "zh_translation.tsv"
            with self.assertRaises(ValueError):
                emit_approved_table(_catalog_from_reviews(), review, output)
            self.assertFalse(output.exists())

    def test_emission_allows_non_blocking_traditional_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            review = Path(directory) / "review.jsonl"
            records = [
                json.loads(line)
                for line in (FIXTURES / "approved_review.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            records[3]["zh"] = "简体中文"
            records[3]["suggested_zh"] = "简体中文"
            review.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
            output = Path(directory) / "zh_translation.tsv"
            emit_approved_table(_catalog_from_reviews(), review, output)
            self.assertTrue(output.exists())
            converted = {
                row.key: row.zh for row in load_runtime_table(output)
            }
            self.assertEqual(converted[records[3]["key"]], "簡體中文")


if __name__ == "__main__":
    unittest.main()
