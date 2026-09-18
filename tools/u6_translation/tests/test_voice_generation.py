from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.u6_translation.voice_generation import run_voice_generation


def write_manifest(path: Path, filenames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["filename"])
        writer.writeheader()
        writer.writerows({"filename": filename} for filename in filenames)


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

    def test_launches_only_requested_language_with_argument_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = root / "manifests"
            manifests.mkdir()
            write_manifest(manifests / "en_manifest.csv", ["0401_10_0.ogg"])

            with patch("tools.u6_translation.voice_generation.subprocess.run") as run:
                result = run_voice_generation(
                    manifests, root / "audio", "en", False, Path("generator.py")
                )

        self.assertEqual(result, 0)
        command = run.call_args.args[0]
        self.assertIsInstance(command, list)
        self.assertEqual(command[1:], [
            "generator.py", "--manifest", str(manifests / "en_manifest.csv"),
            "--output-dir", str(root / "audio" / "en"),
        ])
        self.assertEqual(run.call_args.kwargs, {"check": True})
