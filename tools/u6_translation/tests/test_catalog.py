from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.u6_translation.catalog import (
    CatalogEntry,
    load_catalog,
    normalize_source,
    source_sha256,
    write_catalog,
)


FIXTURES = Path(__file__).parent / "fixtures"


class CatalogCodecTest(unittest.TestCase):
    def test_fixture_round_trip_preserves_entries(self) -> None:
        entries = load_catalog(FIXTURES / "catalog.jsonl")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "catalog.jsonl"
            write_catalog(output, entries)
            self.assertEqual(load_catalog(output), entries)

    def test_catalog_round_trip_preserves_latin1_control_codepoints(self) -> None:
        entry = CatalogEntry.from_source(
            "dialogue", "dialogue:0x0282:fallback_10:0", "prefix\x85suffix",
            "book", "fixture",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "catalog.jsonl"
            write_catalog(output, [entry])
            self.assertEqual(load_catalog(output), [entry])

    def test_write_catalog_has_deterministic_kind_key_order(self) -> None:
        entries = [
            CatalogEntry(
                kind="textmsg",
                key="textmsg:0x0002",
                source="two",
                source_sha256=source_sha256("two"),
                context="gameplay",
                origin="fixture",
                protected_tokens=(),
            ),
            CatalogEntry(
                kind="dialogue",
                key="dialogue:0x0401:10:0",
                source="one",
                source_sha256=source_sha256("one"),
                context="gameplay",
                origin="fixture",
                protected_tokens=(),
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.jsonl"
            second = Path(directory) / "second.jsonl"
            write_catalog(first, reversed(entries))
            write_catalog(second, entries)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(load_catalog(first)[0].kind, "dialogue")

    def test_source_hash_matches_cpp_normalization_and_known_vector(self) -> None:
        self.assertEqual(normalize_source("a\r\nb\rc"), "a\nb\nc")
        self.assertEqual(source_sha256("abc"),
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertEqual(source_sha256("a\r\nb\rc"), source_sha256("a\nb\nc"))

    def test_protected_tokens_are_extracted_in_source_order(self) -> None:
        entry = CatalogEntry.from_source(
            kind="dialogue",
                key="dialogue:0x0401:10:0",
            source="@name@~*<PLAYER_NAME><HONORIFIC><PRONOUN><GENDER_FLAG><VAR>",
            context="gameplay",
            origin="fixture",
        )
        self.assertEqual(
            entry.protected_tokens,
            ("@name@", "~", "*", "<PLAYER_NAME>", "<HONORIFIC>",
             "<PRONOUN>", "<GENDER_FLAG>", "<VAR>"),
        )

    def test_duplicate_key_with_different_hash_is_rejected(self) -> None:
        entries = [
            CatalogEntry.from_source(
                "textmsg", "textmsg:0x0001", "one", "gameplay", "a"
            ),
            CatalogEntry.from_source(
                "textmsg", "textmsg:0x0001", "two", "gameplay", "b"
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                write_catalog(Path(directory) / "catalog.jsonl", entries)

    def test_identical_static_and_runtime_rows_retain_both_origins(self) -> None:
        entry = CatalogEntry.from_source(
            "textmsg", "textmsg:0x0001", "one", "gameplay", "static"
        )
        runtime = CatalogEntry.from_source(
            "textmsg", "textmsg:0x0001", "one", "gameplay", "runtime-capture"
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "catalog.jsonl"
            write_catalog(output, [runtime, entry])
            merged = load_catalog(output)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].origin, "runtime-capture;static")


if __name__ == "__main__":
    unittest.main()
