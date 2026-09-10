from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.u6_translation.catalog import CatalogEntry, write_catalog
from tools.u6_translation.runtime_table import RuntimeRow, write_runtime_table


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
        self.assertIn("dialogue:0x0401:0x0010:0 First", result.stdout)

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

    def test_extract_translate_and_emit_commands_are_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mod_root = root / "mod"
            (mod_root / "Ultima6v1.3" / "patch").mkdir(parents=True)
            (mod_root / "Ultima6v1.3" / "patch" / "textmsg.txt").write_text(
                "%%section msgs\n0x0123:Hello there\n%%endsection\n", encoding="utf-8"
            )
            ucxt = root / "ucxt"
            ucxt.write_text(
                "#!/bin/sh\nprintf '%s' '<0x0401>\\n<0x0010>\\n`Hello`\\n</>\\n</>'\n",
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

            source = CatalogEntry.from_source("dialogue", "dialogue:0x0401:0x0010:0", "Hello", "gameplay", "cli")
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


if __name__ == "__main__":
    unittest.main()
