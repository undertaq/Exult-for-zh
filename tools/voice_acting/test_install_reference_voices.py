"""Tests for transactional selected-reference installation."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.voice_acting import install_reference_voices as module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class InstallReferenceVoicesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "artifacts"
        self.refs = self.root / "voice" / "refs"
        self.backups = self.root / "voice_backup"
        self.prompts = self.root / "clone_prompts.pkl"
        self.manifest_path = self.root / "reference_import_manifest.json"
        self.refs.mkdir(parents=True)
        self.backups.mkdir()
        self.prompts.write_bytes(b"old clone prompts")
        (self.refs / "npc_iolo_en_ref.ogg").write_bytes(b"old english reference")
        (self.refs / "npc_iolo_zh_ref.ogg").write_bytes(b"old chinese reference")

        self.en_source = self._write_candidate(
            "iolo", "English", 8, b"selected english reference", "Iolo English sample."
        )
        self.zh_source = self._write_candidate(
            "iolo", "Chinese", 9, b"selected chinese reference", "Iolo Chinese sample."
        )
        self.en_hash = sha256(self.en_source)
        self.zh_hash = sha256(self.zh_source)
        self.selection = {
            "selected": {
                "iolo": {
                    "npc": "Iolo",
                    "slug": "iolo",
                    "english_wav": "references/iolo/candidate_English_8.ogg",
                    "english_index": 8,
                    "chinese_wav": "references/iolo/candidate_Chinese_9.ogg",
                    "chinese_index": 9,
                }
            }
        }
        self.designs = {
            "designs": {
                "npc_iolo": {
                    "npc": "Iolo",
                    "npcs": ["Iolo"],
                    "ref_en_text": "Iolo English sample.",
                    "ref_zh_text": "Iolo Chinese sample.",
                }
            }
        }
        self.items = module.preflight(self.selection, self.source, self.designs)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_candidate(
        self, slug: str, language: str, index: int, audio_bytes: bytes, sample_text: str
    ) -> Path:
        directory = self.source / "references" / slug
        directory.mkdir(parents=True, exist_ok=True)
        audio = directory / f"candidate_{language}_{index}.ogg"
        audio.write_bytes(audio_bytes)
        audio.with_suffix(".json").write_text(
            json.dumps(
                {
                    "npc": slug.title(),
                    "slug": slug,
                    "language": language,
                    "index": index,
                    "sample_text": sample_text,
                    "seed": 1000 + index,
                    "model_revision": "fixture-model",
                    "sha256": sha256(audio),
                }
            ),
            encoding="utf-8",
        )
        return audio

    def _cli_args(self, mode: str) -> list[str]:
        selection_path = self.root / "selection.json"
        designs_path = self.root / "designs.json"
        selection_path.write_text(json.dumps(self.selection), encoding="utf-8")
        designs_path.write_text(json.dumps(self.designs), encoding="utf-8")
        return [
            "--selection", str(selection_path),
            "--source-root", str(self.source),
            "--designs", str(designs_path),
            "--refs-dir", str(self.refs),
            "--backup-root", str(self.backups),
            "--clone-prompts", str(self.prompts),
            mode,
        ]

    def test_preflight_fails_before_backup_when_one_candidate_is_missing(self) -> None:
        missing = self.source / "references/iolo/candidate_English_8.ogg"
        missing.unlink()

        with self.assertRaises(module.InstallError):
            module.preflight(self.selection, self.source, self.designs)

        self.assertFalse(any(self.backups.iterdir()))

    def test_preflight_rejects_candidate_hash_mismatch(self) -> None:
        self.en_source.write_bytes(b"tampered candidate")

        with self.assertRaisesRegex(module.InstallError, "sha256"):
            module.preflight(self.selection, self.source, self.designs)

    def test_preflight_rejects_design_text_that_is_not_the_exact_sample_text(self) -> None:
        self.designs["designs"]["npc_iolo"]["ref_en_text"] = "Changed reference text."

        with self.assertRaisesRegex(module.InstallError, "reference text"):
            module.preflight(self.selection, self.source, self.designs)

    def test_preflight_rejects_design_assigned_to_multiple_npcs(self) -> None:
        self.designs["designs"]["npc_iolo"]["npcs"] = ["Iolo", "Dupre"]

        with self.assertRaisesRegex(module.InstallError, "exactly one NPC"):
            module.preflight(self.selection, self.source, self.designs)

    def test_preflight_rejects_duplicate_design_destinations(self) -> None:
        duplicate = dict(self.selection["selected"]["iolo"])
        self.selection["selected"]["iolo_duplicate"] = duplicate

        with self.assertRaisesRegex(module.InstallError, "duplicate"):
            module.preflight(self.selection, self.source, self.designs)

    def test_install_backs_up_then_copies_exact_selected_files(self) -> None:
        manifest = module.install(
            self.items, self.refs, self.backups, self.prompts, self.manifest_path
        )

        backup = self.backups / manifest["backup_id"]
        self.assertTrue((backup / "refs").is_dir())
        self.assertEqual(sha256(self.refs / "npc_iolo_en_ref.ogg"), self.en_hash)
        self.assertEqual(sha256(self.refs / "npc_iolo_zh_ref.ogg"), self.zh_hash)
        self.assertEqual(
            (backup / "refs" / "npc_iolo_en_ref.ogg").read_bytes(),
            b"old english reference",
        )
        self.assertEqual((backup / "clone_prompts.pkl").read_bytes(), b"old clone prompts")
        self.assertEqual(
            json.loads(self.manifest_path.read_text(encoding="utf-8"))["items"][0]["sha256"],
            self.en_hash,
        )

    def test_install_checks_staged_hashes_before_creating_a_backup(self) -> None:
        old_en_hash = sha256(self.refs / "npc_iolo_en_ref.ogg")
        self.en_source.write_bytes(b"changed after preflight")

        with self.assertRaisesRegex(module.InstallError, "staged sha256"):
            module.install(self.items, self.refs, self.backups, self.prompts, self.manifest_path)

        self.assertEqual(sha256(self.refs / "npc_iolo_en_ref.ogg"), old_en_hash)
        self.assertFalse(any(self.backups.iterdir()))
        self.assertFalse(self.manifest_path.exists())

    def test_install_reserves_backup_directory_without_replacing_collision(self) -> None:
        collision = self.backups / "refs_fixed"
        original_copy2 = module.shutil.copy2

        def create_collision_after_staging(source: Path, destination: Path, *args: object, **kwargs: object) -> Path:
            result = original_copy2(source, destination, *args, **kwargs)
            if not collision.exists():
                collision.mkdir()
            return result

        with patch.object(module, "_backup_id", return_value="refs_fixed"), patch.object(
            module.shutil, "copy2", side_effect=create_collision_after_staging
        ):
            manifest = module.install(
                self.items, self.refs, self.backups, self.prompts, self.manifest_path
            )

        self.assertEqual(manifest["backup_id"], "refs_fixed_01")
        self.assertTrue(collision.is_dir())
        self.assertFalse(any(collision.iterdir()))

    def test_install_rolls_back_after_injected_partial_publication_failure(self) -> None:
        original_replace = Path.replace
        old_en = (self.refs / "npc_iolo_en_ref.ogg").read_bytes()
        old_zh = (self.refs / "npc_iolo_zh_ref.ogg").read_bytes()

        def fail_second_publication(source: Path, destination: Path) -> Path:
            if (
                source.parent.name.startswith(".reference-install-")
                and source.name == "npc_iolo_zh_ref.ogg"
                and destination == self.refs / "npc_iolo_zh_ref.ogg"
            ):
                raise OSError("injected publication failure")
            return original_replace(source, destination)

        with patch.object(Path, "replace", new=fail_second_publication):
            with self.assertRaisesRegex(module.InstallError, "injected publication failure"):
                module.install(self.items, self.refs, self.backups, self.prompts, self.manifest_path)

        self.assertEqual((self.refs / "npc_iolo_en_ref.ogg").read_bytes(), old_en)
        self.assertEqual((self.refs / "npc_iolo_zh_ref.ogg").read_bytes(), old_zh)
        self.assertEqual(len(list(self.backups.iterdir())), 1)
        self.assertFalse(self.manifest_path.exists())

    def test_verify_installed_rejects_tampered_destination(self) -> None:
        module.install(self.items, self.refs, self.backups, self.prompts, self.manifest_path)
        self.assertEqual(module.verify_installed(self.items, self.refs), 2)
        (self.refs / "npc_iolo_en_ref.ogg").write_bytes(b"tampered installed reference")

        with self.assertRaisesRegex(module.InstallError, "installed sha256"):
            module.verify_installed(self.items, self.refs)

    def test_dry_run_is_validation_only(self) -> None:
        selection_path = self.root / "selection.json"
        designs_path = self.root / "designs.json"
        selection_path.write_text(json.dumps(self.selection), encoding="utf-8")
        designs_path.write_text(json.dumps(self.designs), encoding="utf-8")
        old_en_hash = sha256(self.refs / "npc_iolo_en_ref.ogg")

        result = module.main(
            [
                "--selection", str(selection_path),
                "--source-root", str(self.source),
                "--designs", str(designs_path),
                "--refs-dir", str(self.refs),
                "--backup-root", str(self.backups),
                "--clone-prompts", str(self.prompts),
                "--dry-run",
            ]
        )

        self.assertEqual(result, 0)
        self.assertEqual(sha256(self.refs / "npc_iolo_en_ref.ogg"), old_en_hash)
        self.assertFalse(any(self.backups.iterdir()))

    def test_verify_only_does_not_mutate_filesystem(self) -> None:
        before_refs = {
            path.name: path.read_bytes() for path in sorted(self.refs.iterdir())
        }
        before_prompts = self.prompts.read_bytes()

        result = module.main(self._cli_args("--verify-only"))

        self.assertEqual(result, 0)
        self.assertEqual(
            {path.name: path.read_bytes() for path in sorted(self.refs.iterdir())}, before_refs
        )
        self.assertEqual(self.prompts.read_bytes(), before_prompts)
        self.assertFalse(any(self.backups.iterdir()))
        self.assertFalse(self.manifest_path.exists())

    def test_verify_installed_succeeds_then_rejects_tampering(self) -> None:
        module.install(self.items, self.refs, self.backups, self.prompts, self.manifest_path)
        verify_args = self._cli_args("--verify-installed")

        self.assertEqual(module.main(verify_args), 0)
        (self.refs / "npc_iolo_en_ref.ogg").write_bytes(b"tampered installed reference")

        with self.assertRaises(SystemExit) as raised:
            module.main(verify_args)

        self.assertNotEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
