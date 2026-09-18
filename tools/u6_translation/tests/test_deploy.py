from __future__ import annotations

import stat
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.u6_translation.deploy import (
    DEPLOY_RELATIVE_PATHS,
    deploy_staged_files,
    validate_staging,
)


_STAGED_CONTENT = {
    "patch/autonotes.txt": "0x0:午安\r\n",
    "patch/textmsg.txt": "0x0:早安\r\n",
    "mods/Ultima6v1.3/patch/zh_translation.tsv": "# u6-translation-v1\n",
}


def _write_stage(root: Path) -> None:
    for relative, content in _STAGED_CONTENT.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
    (root / "patch/textmsg.txt").chmod(0o744)


class DeploymentTest(unittest.TestCase):
    def test_manifest_contains_only_supported_game_relative_files(self) -> None:
        self.assertEqual(
            DEPLOY_RELATIVE_PATHS,
            (
                "patch/autonotes.txt",
                "patch/textmsg.txt",
                "mods/Ultima6v1.3/patch/zh_translation.tsv",
            ),
        )

    def test_deploy_copies_mirrored_paths_and_preserves_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / "stage"
            game = root / "game"
            _write_stage(stage)

            report = deploy_staged_files(game, stage)

            self.assertEqual(len(report.copied), 3)
            self.assertEqual(
                (game / "patch/textmsg.txt").read_bytes(),
                "0x0:早安\r\n".encode("utf-8"),
            )
            self.assertEqual(
                stat.S_IMODE((game / "patch/textmsg.txt").stat().st_mode),
                0o744,
            )
            self.assertEqual(
                validate_staging(stage),
                tuple(stage / relative for relative in DEPLOY_RELATIVE_PATHS),
            )

    def test_dry_run_validates_and_does_not_modify_game_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / "stage"
            game = root / "game"
            _write_stage(stage)

            report = deploy_staged_files(game, stage, dry_run=True)

            self.assertTrue(report.dry_run)
            self.assertEqual(len(report.copied), 3)
            self.assertFalse(game.exists())

    def test_second_deploy_skips_identical_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / "stage"
            game = root / "game"
            _write_stage(stage)

            deploy_staged_files(game, stage)
            report = deploy_staged_files(game, stage)

            self.assertEqual(report.copied, ())
            self.assertEqual(len(report.skipped), 3)

    def test_missing_or_unsafe_manifest_input_fails_before_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / "stage"
            game = root / "game"
            _write_stage(stage)
            (stage / "patch/autonotes.txt").unlink()

            with self.assertRaises(ValueError):
                deploy_staged_files(game, stage)
            self.assertFalse(game.exists())

            _write_stage(stage)
            with patch(
                "tools.u6_translation.deploy.DEPLOY_RELATIVE_PATHS",
                ("../escape.txt",),
            ):
                with self.assertRaises(ValueError):
                    validate_staging(stage)

    def test_extra_staged_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory) / "stage"
            _write_stage(stage)
            (stage / "unexpected.txt").write_text("no", encoding="utf-8")

            with self.assertRaises(ValueError):
                validate_staging(stage)


if __name__ == "__main__":
    unittest.main()
