from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.u6_translation.voice_generation import run_voice_generation


def write_manifest(path: Path, filenames: list[str], speaker: str = "Iolo") -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "filename", "func_id", "offset_key", "segment", "speaker",
            "voice_desc", "text",
        ])
        writer.writeheader()
        writer.writerows({
            "filename": filename,
            "func_id": "0401",
            "offset_key": "10",
            "segment": "0",
            "speaker": speaker,
            "voice_desc": "Warm, measured voice",
            "text": "Hello" if path.name.startswith("en_") else "你好",
        } for filename in filenames)


class VoiceGenerationTests(unittest.TestCase):
    def test_dry_run_lists_paired_jobs_without_launching_generator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = root / "manifests"
            manifests.mkdir()
            write_manifest(manifests / "en_manifest.csv", ["0401_10_0.ogg"])
            write_manifest(manifests / "zh_manifest.csv", ["0401_10_0.ogg"])

            with patch("tools.u6_translation.voice_generation.subprocess.run") as run:
                result = run_voice_generation(
                    manifests, root / "audio", "both", True, Path("generator.py")
                )

        self.assertEqual(result, 0)
        run.assert_not_called()

    def test_stages_qwen3_mapping_and_fallback_designs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = root / "manifests"
            manifests.mkdir()
            write_manifest(manifests / "en_manifest.csv", ["0401_10_0.ogg"], "U6 Stranger")
            write_manifest(manifests / "zh_manifest.csv", ["0401_10_0.ogg"], "U6 Stranger")

            run_voice_generation(manifests, root / "audio", "both", True, Path("generator.py"))

            mapping = (manifests / "qwen3" / "u6_mapping.json").read_text(encoding="utf-8")
            designs = (manifests / "qwen3" / "u6_designs.json").read_text(encoding="utf-8")

        self.assertIn('"en_output_filename":"0401_10_0.ogg"', mapping)
        self.assertIn('"zh_output_filename":"0401_10_0.ogg"', mapping)
        self.assertIn('"npcs":["U6 Stranger"]', designs)

    def test_rejects_mismatched_approved_filenames_before_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = root / "manifests"
            manifests.mkdir()
            write_manifest(manifests / "en_manifest.csv", ["0401_10_0.ogg"])
            write_manifest(manifests / "zh_manifest.csv", ["0401_11_0.ogg"])
            output = root / "audio"

            with self.assertRaisesRegex(ValueError, "identical filenames"):
                run_voice_generation(manifests, output, "both", False, Path("generator.py"))

        self.assertFalse(output.exists())

    def test_rejects_duplicate_filenames_before_staging_or_launching(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = root / "manifests"
            manifests.mkdir()
            write_manifest(manifests / "en_manifest.csv", ["0401_10_0.ogg", "0401_10_0.ogg"])
            write_manifest(manifests / "zh_manifest.csv", ["0401_10_0.ogg", "0401_10_0.ogg"])

            with self.assertRaisesRegex(ValueError, "duplicate filename"):
                run_voice_generation(manifests, root / "audio", "both", True, Path("generator.py"))

        self.assertFalse((manifests / "qwen3").exists())

    def test_rejects_missing_provider_columns_with_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = root / "manifests"
            manifests.mkdir()
            (manifests / "en_manifest.csv").write_text("filename\n0401_10_0.ogg\n", encoding="utf-8")
            (manifests / "zh_manifest.csv").write_text("filename\n0401_10_0.ogg\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "missing required columns: func_id"):
                run_voice_generation(manifests, root / "audio", "both", True, Path("generator.py"))

    def test_rejects_unsafe_provider_filename_before_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = root / "manifests"
            manifests.mkdir()
            write_manifest(manifests / "en_manifest.csv", ["../escape.ogg"])
            write_manifest(manifests / "zh_manifest.csv", ["../escape.ogg"])

            with self.assertRaisesRegex(ValueError, "unsafe output filename"):
                run_voice_generation(manifests, root / "audio", "both", True, Path("generator.py"))

    def test_fallback_design_uses_casting_description_and_stable_dialogue_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = root / "manifests"
            manifests.mkdir()
            write_manifest(manifests / "en_manifest.csv", ["0401_10_0.ogg"], "Runtime Name")
            write_manifest(manifests / "zh_manifest.csv", ["0401_10_0.ogg"], "Runtime Name")

            run_voice_generation(manifests, root / "audio", "both", True, Path("generator.py"))
            designs = (manifests / "qwen3" / "u6_designs.json").read_text(encoding="utf-8")

        self.assertIn('"voice_desc_en":"Warm, measured voice"', designs)
        self.assertIn('"ref_en_text":"Hello"', designs)
        self.assertNotIn("A clear voice for Runtime Name", designs)

    def test_reuses_exact_name_u7_reference_pair_from_voice_refs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = root / "manifests"
            manifests.mkdir()
            write_manifest(manifests / "en_manifest.csv", ["0401_10_0.ogg"], "Iolo")
            write_manifest(manifests / "zh_manifest.csv", ["0401_10_0.ogg"], "Iolo")
            u7_refs = root / "voice" / "refs"
            u7_refs.mkdir(parents=True)
            (u7_refs / "npc_iolo_en_ref.ogg").write_bytes(b"u7 english")
            (u7_refs / "npc_iolo_zh_ref.ogg").write_bytes(b"u7 chinese")
            output = root / "audio"

            with patch("tools.u6_translation.voice_generation.subprocess.run") as run:
                run_voice_generation(
                    manifests,
                    output,
                    "both",
                    False,
                    Path("generator.py"),
                    u7_reference_root=u7_refs,
                )

            self.assertEqual((output / "refs" / "npc_iolo_en_ref.ogg").read_bytes(), b"u7 english")
            self.assertEqual((output / "refs" / "npc_iolo_zh_ref.ogg").read_bytes(), b"u7 chinese")
            designs = json.loads((manifests / "qwen3" / "u6_designs.json").read_text(encoding="utf-8"))
            override = designs["designs"]["npc_iolo"]["reference_overrides"]
            self.assertEqual(override["en"]["source"], "u7")
            self.assertEqual(override["en"]["filename"], "npc_iolo_en_ref.ogg")
            self.assertEqual(override["zh"]["filename"], "npc_iolo_zh_ref.ogg")
            run.assert_called_once()

    def test_does_not_use_partial_npc_name_for_u7_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = root / "manifests"
            manifests.mkdir()
            write_manifest(manifests / "en_manifest.csv", ["0401_10_0.ogg"], "Iol")
            write_manifest(manifests / "zh_manifest.csv", ["0401_10_0.ogg"], "Iol")
            u7_refs = root / "voice" / "refs"
            u7_refs.mkdir(parents=True)
            (u7_refs / "npc_iolo_en_ref.ogg").write_bytes(b"u7 english")
            (u7_refs / "npc_iolo_zh_ref.ogg").write_bytes(b"u7 chinese")
            output = root / "audio"

            with patch("tools.u6_translation.voice_generation.subprocess.run"):
                run_voice_generation(
                    manifests,
                    output,
                    "both",
                    False,
                    Path("generator.py"),
                    u7_reference_root=u7_refs,
                )

            designs = json.loads((manifests / "qwen3" / "u6_designs.json").read_text(encoding="utf-8"))
            design = next(iter(designs["designs"].values()))
            self.assertNotIn("reference_overrides", design)
            self.assertFalse((output / "refs").exists())

    def test_launches_requested_language_once_with_qwen3_argument_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = root / "manifests"
            manifests.mkdir()
            write_manifest(manifests / "en_manifest.csv", ["0401_10_0.ogg"])
            write_manifest(manifests / "zh_manifest.csv", ["0401_10_0.ogg"])

            with patch("tools.u6_translation.voice_generation.subprocess.run") as run:
                result = run_voice_generation(
                    manifests, root / "audio", "en", False, Path("generator.py")
                )

        self.assertEqual(result, 0)
        command = run.call_args.args[0]
        self.assertIsInstance(command, list)
        self.assertEqual(command[1:], [
            "generator.py", "--phase", "all", "--reference-workflow", "legacy",
            "--mapping", str(manifests / "qwen3" / "u6_mapping.json"),
            "--en-lines", str(manifests / "en_manifest.csv"),
            "--zh-lines", str(manifests / "zh_manifest.csv"),
            "--designs", str(manifests / "qwen3" / "u6_designs.json"),
            "--output-dir", str(root / "audio"),
            "--clone-prompts", str(root / "audio" / "clone_prompts.pkl"),
            "--lang", "en",
        ])
        self.assertEqual(run.call_args.kwargs, {"check": True})
