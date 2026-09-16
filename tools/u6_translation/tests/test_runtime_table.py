from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.u6_translation.catalog import parse_runtime_catalog
from tools.u6_translation.runtime_table import (
    RuntimeRow,
    escape_field,
    load_runtime_table,
    merge_runtime_rows,
    unescape_field,
    write_runtime_table,
)


FIXTURES = Path(__file__).parent / "fixtures"


class RuntimeTableCodecTest(unittest.TestCase):
    def test_runtime_capture_parses_escaped_english_fields(self) -> None:
        entries = parse_runtime_catalog(FIXTURES / "runtime_catalog.tsv")
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].source, "Line\tbreak\nnext")
        self.assertEqual(entries[0].kind, "dialogue")
        self.assertEqual(entries[0].origin, "runtime-capture")

    def test_runtime_table_round_trip_escapes_translation_text(self) -> None:
        rows = [
            RuntimeRow(
                kind="dialogue",
                key="dialogue:0x0401:10:0",
                source_sha256="a" * 64,
                zh="第一行\t第二行\n第三行\\",
            )
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "zh_translation.tsv"
            write_runtime_table(path, rows)
            self.assertEqual(load_runtime_table(path), rows)
            self.assertIn("第一行\\t第二行\\n第三行\\\\", path.read_text())

    def test_runtime_table_round_trip_preserves_latin1_control_codepoints(self) -> None:
        row = RuntimeRow("dialogue", "dialogue:0x0282:fallback_10:0", "a" * 64, "prefix\x85suffix")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "zh_translation.tsv"
            write_runtime_table(path, [row])
            self.assertEqual(load_runtime_table(path), [row])

    def test_field_codec_rejects_unknown_and_trailing_escapes(self) -> None:
        self.assertEqual(escape_field("a\\b\tc\nd\r"), "a\\\\b\\tc\\nd\\r")
        self.assertEqual(unescape_field("a\\\\b\\tc\\nd\\r"), "a\\b\tc\nd\r")
        with self.assertRaises(ValueError):
            unescape_field("bad\\x")
        with self.assertRaises(ValueError):
            unescape_field("bad\\")

    def test_codec_preserves_literal_backslash_sequences_and_trailing_field(self) -> None:
        row = "\t".join(
            escape_field(value)
            for value in ("dialogue", "key", "a" * 64, r"literal\t text\\tail")
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.tsv"
            path.write_text(row + "\n", encoding="utf-8")
            parsed = parse_runtime_catalog(path)
        self.assertEqual(parsed[0].source, r"literal\t text\\tail")

        trailing = "\t".join(escape_field(value) for value in ("dialogue", "key", "a" * 64, ""))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trailing.tsv"
            path.write_text(trailing + "\n", encoding="utf-8")
            self.assertEqual(load_runtime_table(path)[0].zh, "")

    def test_runtime_table_writer_sorts_rows_by_kind_and_key(self) -> None:
        rows = [
            RuntimeRow("dialogue", "dialogue:0x0401:10:0", "a" * 64, "one"),
            RuntimeRow("textmsg", "textmsg:0x0002", "b" * 64, "two"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sorted.tsv"
            write_runtime_table(path, reversed(rows))
            self.assertEqual([row.kind for row in load_runtime_table(path)], ["dialogue", "textmsg"])

    def test_merge_runtime_rows_keeps_existing_translation_and_adds_fallback_rows(self) -> None:
        existing = RuntimeRow("dialogue", "dialogue:0x0401:10:0", "a" * 64, "既有翻譯")
        added = RuntimeRow("dialogue", "dialogue:0x0282:fallback_10:1", "b" * 64, "書名")

        self.assertEqual(
            merge_runtime_rows([existing], [added, existing]),
            [added, existing],
        )


if __name__ == "__main__":
    unittest.main()
