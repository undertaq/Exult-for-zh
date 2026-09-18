from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools.u6_translation.runtime_table import RuntimeRow, load_runtime_table, write_runtime_table
from tools.u6_translation.traditional import (
    convert_runtime_table,
    convert_text,
    load_simplified_characters,
    load_simplified_to_traditional,
)


class TraditionalConversionTest(unittest.TestCase):
    def test_checked_in_map_covers_exactly_the_audit_inventory(self) -> None:
        self.assertEqual(
            set(load_simplified_to_traditional()),
            set(load_simplified_characters()),
        )

    def test_convert_text_uses_checked_in_traditional_conversion(self) -> None:
        converted = convert_text("發達的秘密，<PLAYER_NAME>。")

        self.assertEqual(converted.text, "發達的祕密，<PLAYER_NAME>。")
        self.assertEqual(converted.changed_characters, (("秘", "祕"),))
        self.assertEqual(convert_text(converted.text).text, converted.text)

    def test_convert_runtime_table_preserves_metadata_and_reports_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tsv"
            output = root / "converted.tsv"
            row = RuntimeRow(
                "dialogue",
                "dialogue:0x0430:50:0",
                "a" * 64,
                "一個發達的秘密<VAR>",
            )
            write_runtime_table(source, [row])

            report = convert_runtime_table(source, output)
            converted_rows = load_runtime_table(output)

        self.assertEqual(report.rows, 1)
        self.assertEqual(report.changed_rows, 1)
        self.assertEqual(report.changed_characters, 1)
        self.assertEqual(converted_rows[0].kind, row.kind)
        self.assertEqual(converted_rows[0].key, row.key)
        self.assertEqual(converted_rows[0].source_sha256, row.source_sha256)
        self.assertEqual(converted_rows[0].zh, "一個發達的祕密<VAR>")

    def test_check_mode_does_not_write_and_reports_needed_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tsv"
            output = root / "converted.tsv"
            write_runtime_table(
                source,
                [RuntimeRow("dialogue", "dialogue:0x0430:50:0", "a" * 64, "秘密")],
            )

            report = convert_runtime_table(source, output, check=True)

        self.assertEqual(report.changed_rows, 1)
        self.assertFalse(output.exists())

    def test_escaped_runtime_fields_round_trip_through_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tsv"
            output = root / "converted.tsv"
            row = RuntimeRow(
                "dialogue",
                "dialogue:0x0430:50:0",
                "a" * 64,
                "秘密\t<VAR>\n\\",
            )
            write_runtime_table(source, [row])

            convert_runtime_table(source, output)
            converted = load_runtime_table(output)[0]

        self.assertEqual(converted.zh, "祕密\t<VAR>\n\\")


if __name__ == "__main__":
    unittest.main()
