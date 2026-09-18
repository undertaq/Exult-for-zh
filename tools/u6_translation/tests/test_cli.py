from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.u6_translation.catalog import CatalogEntry, write_catalog
from tools.u6_translation.runtime_table import RuntimeRow, load_runtime_table, write_runtime_table
from tools.u6_translation.__main__ import main
from tools.u6_translation.ollama_backend import OllamaBackend


ROOT = Path(__file__).parents[3]
GLOSSARY = ROOT / "tools/u6_translation/u6_glossary.tsv"


class TranslationCliTest(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "tools.u6_translation", *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
        )

    def test_legacy_catalog_extraction_invocation_still_prints_entries(self) -> None:
        result = self._run("tools/u6_translation/tests/fixtures/catalog.jsonl")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dialogue:0x0401:10:0 First", result.stdout)

    def test_audit_subcommand_writes_json_terminal_report_and_strict_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "catalog.jsonl"
            report_path = root / "audit.json"
            write_catalog(
                catalog_path,
                [CatalogEntry.from_source("choice", "choice:0x0401:0x0088:0", "yes", "gameplay", "cli")],
            )
            table = root / "table.tsv"
            table.write_text("# u6-translation-v1\n# kind\\tkey\\tsource_sha256\\tzh\n", encoding="utf-8")
            result = self._run(
                "audit", "coverage", "--catalog", str(catalog_path), "--table", str(table),
                "--report", str(report_path), "--strict",
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("U6 translation audit", result.stdout)
        self.assertEqual(report["totals"]["missing"], 1)

    def test_audit_accepts_shared_english_terms_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = CatalogEntry.from_source(
                "dialogue", "dialogue:0x0401:100:0", "wisp", "gameplay", "cli"
            )
            catalog_path = root / "catalog.jsonl"
            write_catalog(catalog_path, [entry])
            table = root / "table.tsv"
            write_runtime_table(
                table,
                [RuntimeRow(entry.kind, entry.key, entry.source_sha256, "靈光")],
            )
            glossary = root / "glossary.tsv"
            glossary.write_text("en\tzh\tpolicy\n", encoding="utf-8")
            terms = root / "terms.tsv"
            terms.write_text(
                "category\ten\tpolicy\n"
                "professional\twisp\truntime_term+protected\n",
                encoding="utf-8",
            )
            report_path = root / "report.json"
            result = self._run(
                "audit", "correctness", "--catalog", str(catalog_path),
                "--table", str(table), "--report", str(report_path),
                "--glossary", str(glossary), "--terms", str(terms),
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["english_term_count"], 1)
        self.assertIn(
            "protected_term",
            {issue["check"] for issue in report["deterministic"]["issues"]},
        )

    def test_extract_translate_and_emit_commands_are_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mod_root = root / "mod"
            (mod_root / "Ultima6v1.3" / "patch").mkdir(parents=True)
            (mod_root / "Ultima6v1.3" / "patch" / "usecode").write_bytes(b"fixture")
            (mod_root / "Ultima6v1.3" / "patch" / "textmsg.txt").write_text(
                "%%section msgs\n0x0123:Hello there\n%%endsection\n", encoding="utf-8"
            )
            ucxt = root / "ucxt"
            ucxt.write_text(
                "#!/bin/sh\nprintf '%b' '<0x0401>\\n<0x0010>\\n`Hello`\\n</>\\n</>'\n",
                encoding="utf-8",
            )
            ucxt.chmod(0o755)
            catalog = root / "catalog.jsonl"
            extract = self._run(
                "extract", "--mod-root", str(mod_root), "--ucxt", str(ucxt),
                "--output", str(catalog),
            )
            self.assertEqual(extract.returncode, 0, extract.stderr)
            self.assertTrue(catalog.exists())

            source = CatalogEntry.from_source("dialogue", "dialogue:0x0401:10:0", "Hello", "gameplay", "cli")
            table = root / "candidate.tsv"
            write_runtime_table(table, [RuntimeRow(source.kind, source.key, source.source_sha256, "你好")])
            correctness = root / "correctness.json"
            audit = self._run(
                "audit", "correctness", "--catalog", str(catalog), "--table", str(table),
                "--report", str(correctness), "--glossary", str(GLOSSARY),
            )
            self.assertEqual(audit.returncode, 0, audit.stderr)

            review = root / "review.jsonl"
            review.write_text(
                json.dumps({
                    "kind": source.kind, "key": source.key, "source_sha256": source.source_sha256,
                    "zh": "你好", "status": "approved", "issues": [], "suggested_zh": "你好",
                    "model": "test", "prompt_version": "test",
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            emitted = root / "emitted.tsv"
            emit = self._run(
                "emit", "--catalog", str(catalog), "--review", str(review), "--output", str(emitted),
            )
            self.assertEqual(emit.returncode, 0, emit.stderr)
            self.assertTrue(emitted.read_text(encoding="utf-8").startswith("# u6-translation-v1\n"))

    def test_convert_traditional_command_checks_and_writes_a_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tsv"
            output = root / "converted.tsv"
            write_runtime_table(
                source,
                [RuntimeRow("dialogue", "dialogue:0x0430:50:0", "a" * 64, "秘密")],
            )

            check = self._run(
                "convert-traditional", "--input", str(source), "--check"
            )
            converted = self._run(
                "convert-traditional", "--input", str(source), "--output", str(output)
            )
            clean_check = self._run(
                "convert-traditional", "--input", str(output), "--check"
            )

            converted_rows = load_runtime_table(output)

        self.assertNotEqual(check.returncode, 0)
        self.assertIn("changed_rows=1", check.stdout)
        self.assertEqual(converted.returncode, 0, converted.stderr)
        self.assertEqual(converted_rows[0].zh, "祕密")
        self.assertEqual(clean_check.returncode, 0, clean_check.stderr)

    def test_extract_can_include_static_gameplay_resources_without_runtime_capture(self) -> None:
        fixture = ROOT / "tools/u6_translation/tests/fixtures/indexed_mod"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "catalog.jsonl"
            result = self._run(
                "extract", "--mod-root", str(fixture),
                "--ucxt", str(fixture / "ucxt_fixture.sh"),
                "--include-static", "--output", str(output),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            kinds = {json.loads(line)["kind"] for line in output.read_text(encoding="utf-8").splitlines()}
            self.assertIn("dialogue", kinds)
            self.assertIn("item", kinds)
            self.assertIn("textmsg", kinds)

    @patch("tools.u6_translation.__main__.extract_usecode_translation_rows")
    def test_import_fallback_books_merges_generated_rows_into_existing_table(self, extract_rows) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            table = root / "zh_translation.tsv"
            existing = RuntimeRow("dialogue", "dialogue:0x0401:10:0", "a" * 64, "既有翻譯")
            added = RuntimeRow("dialogue", "dialogue:0x0282:fallback_10:1", "b" * 64, "書名")
            write_runtime_table(table, [existing])
            extract_rows.return_value = [added]

            result = main([
                "import-fallback-books",
                "--english-usecode", str(root / "USECODE"),
                "--chinese-usecode", str(root / "usecode.zh"),
                "--ucxt", str(root / "ucxt"),
                "--table", str(table),
            ])

            self.assertEqual(result, 0)
            self.assertEqual(load_runtime_table(table), [added, existing])

    @patch("tools.u6_translation.__main__.translate_catalog")
    def test_translate_command_builds_ollama_backend_and_calls_pipeline(self, translate_catalog):
        result = main([
            "translate", "--catalog", "catalog.jsonl", "--output", "candidates.tsv",
            "--cache", "cache.json", "--model", "qwen3:8b",
            "--url", "http://127.0.0.1:11434/api/chat", "--batch-size", "12",
            "--timeout", "181", "--retries", "0",
        ])
        self.assertEqual(result, 0)
        translate_catalog.assert_called_once()
        args = translate_catalog.call_args.args
        self.assertEqual(args[:3], (Path("catalog.jsonl"), Path("candidates.tsv"), Path("cache.json")))
        self.assertIsInstance(args[3], OllamaBackend)
        self.assertEqual(args[3].config.model, "qwen3:8b")
        self.assertEqual(args[3].config.url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(translate_catalog.call_args.kwargs["batch_size"], 12)
        self.assertEqual(args[3].config.timeout_seconds, 181.0)
        self.assertEqual(args[3].config.retries, 0)

    def test_audit_all_combines_coverage_and_correctness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = CatalogEntry.from_source("choice", "choice:0x0401:0x0088:0", "yes", "gameplay", "cli")
            catalog = root / "catalog.jsonl"; write_catalog(catalog, [entry])
            table = root / "table.tsv"; table.write_text("# u6-translation-v1\n# kind\\tkey\\tsource_sha256\\tzh\n", encoding="utf-8")
            report_path = root / "all.json"
            result = self._run("audit", "all", "--catalog", str(catalog), "--table", str(table), "--report", str(report_path), "--strict")
            report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("coverage", report)
        self.assertIn("correctness", report)
        self.assertIn("issues", report)

    def test_review_html_command_writes_editable_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = CatalogEntry.from_source(
                "dialogue", "dialogue:0x0401:10:0", "Hello", "gameplay", "cli"
            )
            catalog = root / "catalog.jsonl"
            write_catalog(catalog, [entry])
            table = root / "table.tsv"
            write_runtime_table(
                table,
                [RuntimeRow(entry.kind, entry.key, entry.source_sha256, "你好")],
            )
            output = root / "review.html"

            result = self._run(
                "review-html", "--catalog", str(catalog), "--table", str(table),
                "--output", str(output), "--model", "test-model",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.exists())
            self.assertIn("Needs modification", output.read_text(encoding="utf-8"))

    def test_review_html_prefers_runtime_speaker_capture_over_static_map(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = CatalogEntry.from_source(
                "dialogue", "dialogue:0x0401:10:0", "Hello", "gameplay", "cli"
            )
            catalog = root / "catalog.jsonl"
            write_catalog(catalog, [entry])
            table = root / "table.tsv"
            write_runtime_table(
                table,
                [RuntimeRow(entry.kind, entry.key, entry.source_sha256, "你好")],
            )
            static_map = root / "static-speakers.json"
            static_map.write_text(
                json.dumps({entry.key: "Static speaker"}), encoding="utf-8"
            )
            capture = root / "speakers.tsv"
            capture.write_text(
                "# u6-runtime-speakers-v1\n"
                "dialogue\tdialogue:0x0401:10:0\t1\tRuntime speaker\n",
                encoding="utf-8",
            )
            output = root / "review.html"

            result = self._run(
                "review-html", "--catalog", str(catalog), "--table", str(table),
                "--output", str(output), "--speaker-map", str(static_map),
                "--speaker-capture", str(capture),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            html = output.read_text(encoding="utf-8")
            self.assertIn("Runtime speaker", html)
            self.assertNotIn("Static speaker", html)


if __name__ == "__main__":
    unittest.main()
