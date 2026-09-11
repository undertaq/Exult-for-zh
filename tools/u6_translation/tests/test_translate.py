from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.u6_translation.catalog import CatalogEntry, source_sha256, write_catalog
from tools.u6_translation.ollama_backend import OllamaConfig
from tools.u6_translation.runtime_table import load_runtime_table, write_runtime_table, RuntimeRow
from tools.u6_translation.translate import review_catalog, translate_catalog


def _entry(kind: str, key: str, source: str) -> CatalogEntry:
    return CatalogEntry(
        kind=kind,
        key=key,
        source=source,
        source_sha256=source_sha256(source),
        context="gameplay",
        origin="fixture",
        protected_tokens=(),
    )


class _FakeBackend:
    def __init__(self, translations: dict[str, str]) -> None:
        self.config = OllamaConfig(model="test-model")
        self.translations = translations
        self.translation_calls: list[list[str]] = []
        self.review_calls: list[list[str]] = []

    def translate_batch(self, entries: list[CatalogEntry]) -> list[dict[str, str]]:
        self.translation_calls.append([entry.key for entry in entries])
        return [
            {
                "key": entry.key,
                "source_sha256": entry.source_sha256,
                "zh": self.translations[entry.key],
                "status": "translated",
            }
            for entry in reversed(entries)
        ]

    def review_batch(
        self,
        entries: list[CatalogEntry],
        translations: list[dict[str, str]],
    ) -> list[dict[str, object]]:
        self.review_calls.append([entry.key for entry in entries])
        return [
            {
                "key": entry.key,
                "source_sha256": entry.source_sha256,
                "status": "ok",
                "issues": [],
                "suggested_zh": next(item["zh"] for item in translations if item["key"] == entry.key),
            }
            for entry in reversed(entries)
        ]


class TranslationPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = [
            _entry("dialogue", "dialogue:0x0401:10:0", "One"),
            _entry("textmsg", "textmsg:0x0002", "Two"),
        ]

    def _write_catalog(self, directory: str) -> Path:
        path = Path(directory) / "catalog.jsonl"
        write_catalog(path, self.entries)
        return path

    def test_translate_writes_runtime_table_and_structured_cache_in_catalog_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = _FakeBackend({entry.key: f"中譯 {entry.source}" for entry in self.entries})
            translate_catalog(
                self._write_catalog(directory),
                root / "translations.tsv",
                root / "cache.json",
                backend,
                "prompt-v1",
            )

            rows = load_runtime_table(root / "translations.tsv")
            cache = json.loads((root / "cache.json").read_text(encoding="utf-8"))

        self.assertEqual(
            {row.key: row.zh for row in rows},
            {entry.key: f"中譯 {entry.source}" for entry in self.entries},
        )
        self.assertEqual(backend.translation_calls, [[entry.key for entry in self.entries]])
        self.assertEqual(len(cache["entries"]), 2)
        cache_key = next(iter(cache["entries"]))
        for part in (
            "operation", "kind", "key", "context", "source_sha256", "model",
            "prompt_version", "glossary_sha256",
        ):
            self.assertIn(part, cache_key)
        self.assertEqual(json.loads(cache_key)["prompt_version"], "prompt-v1")
        self.assertEqual(json.loads(cache_key)["operation"], "translate")

    def test_translate_uses_cache_without_backend_and_prompt_version_invalidates_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._write_catalog(directory)
            output = root / "translations.tsv"
            cache = root / "cache.json"
            first = _FakeBackend({entry.key: "第一次" for entry in self.entries})
            translate_catalog(catalog, output, cache, first, "prompt-v1")

            second = _FakeBackend({entry.key: "不應呼叫" for entry in self.entries})
            translate_catalog(catalog, output, cache, second, "prompt-v1")
            self.assertEqual(second.translation_calls, [])
            self.assertEqual({row.zh for row in load_runtime_table(output)}, {"第一次"})

            third = _FakeBackend({entry.key: "第二次" for entry in self.entries})
            translate_catalog(catalog, output, cache, third, "prompt-v2")
            self.assertEqual(third.translation_calls, [[entry.key for entry in self.entries]])
            self.assertEqual({row.zh for row in load_runtime_table(output)}, {"第二次"})

    def test_translate_canonicalizes_exact_repeated_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = [
                _entry("dialogue", "dialogue:0x0401:10:0", "The Fellowship"),
                _entry("dialogue", "dialogue:0x0401:20:0", "The Fellowship"),
            ]
            catalog = root / "catalog.jsonl"
            write_catalog(catalog, entries)
            backend = _FakeBackend({entries[0].key: "友誼會", entries[1].key: "團契"})

            translate_catalog(catalog, root / "translations.tsv", root / "cache.json", backend, "prompt-v1")

            self.assertEqual(
                {row.key: row.zh for row in load_runtime_table(root / "translations.tsv")},
                {entry.key: "友誼會" for entry in entries},
            )

    def test_translate_splits_pending_rows_into_resumable_batches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = [
                _entry("dialogue", f"dialogue:0x0401:{index + 10}:0", f"Line {index}")
                for index in range(5)
            ]
            catalog = root / "catalog.jsonl"
            write_catalog(catalog, entries)
            backend = _FakeBackend({entry.key: f"譯文 {index}" for index, entry in enumerate(entries)})

            translate_catalog(
                catalog, root / "translations.tsv", root / "cache.json", backend,
                "prompt-v1", batch_size=2,
            )

            self.assertEqual(
                backend.translation_calls,
                [
                    [entry.key for entry in entries[0:2]],
                    [entry.key for entry in entries[2:4]],
                    [entry.key for entry in entries[4:5]],
                ],
            )

    def test_review_is_advisory_jsonl_and_does_not_overwrite_candidate_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._write_catalog(directory)
            table = root / "translations.tsv"
            write_runtime_table(
                table,
                [
                    RuntimeRow(entry.kind, entry.key, entry.source_sha256, f"候選 {entry.source}")
                    for entry in self.entries
                ],
            )
            before = table.read_bytes()
            output = root / "review.jsonl"
            cache = root / "review-cache.json"
            backend = _FakeBackend({})
            review_catalog(catalog, table, output, backend, "review-v1")
            after = table.read_bytes()

            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            review_cache = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else None

        self.assertEqual(after, before)
        self.assertEqual([record["key"] for record in records], [entry.key for entry in self.entries])
        self.assertEqual(records[0]["model"], "test-model")
        self.assertEqual(records[0]["prompt_version"], "review-v1")
        self.assertEqual(records[0]["issues"], [])
        self.assertEqual(backend.review_calls, [[entry.key for entry in self.entries]])
        self.assertIsNone(review_cache)

    def test_review_cache_is_separate_from_translation_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._write_catalog(directory)
            table = root / "translations.tsv"
            write_runtime_table(
                table,
                [RuntimeRow(entry.kind, entry.key, entry.source_sha256, "候選") for entry in self.entries],
            )
            output = root / "review.jsonl"
            backend = _FakeBackend({})
            review_catalog(catalog, table, output, backend, "review-v1")
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[1]["suggested_zh"], "候選")

        self.assertEqual(backend.review_calls, [[entry.key for entry in self.entries]])


if __name__ == "__main__":
    unittest.main()
