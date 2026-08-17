#!/usr/bin/env python3
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("sync_voice_output_to_patch.py")


def load_script_module():
    spec = importlib.util.spec_from_file_location("sync_voice_output_to_patch_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SyncVoiceOutputToPatchTest(unittest.TestCase):
    def test_resolves_blackgate_patch_path_from_local_config(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = root / "exult.cfg"
            cfg.write_text(
                """
                <config>
                  <disk>
                    <game>
                      <blackgate>
                        <path>../Ultima_7</path>
                        <patch>../Ultima_7/patch</patch>
                      </blackgate>
                    </game>
                  </disk>
                </config>
                """,
                encoding="utf-8",
            )

            patch_dir = module.resolve_patch_dir(cfg, "blackgate")

            self.assertEqual(patch_dir, (root / "../Ultima_7/patch").resolve())

    def test_sync_language_copies_missing_files_to_patch_voice_acting_tree(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "voice" / "en"
            patch = root / "Ultima_7" / "patch"
            source.mkdir(parents=True)
            (source / "0401_48d_1_npc1.ogg").write_bytes(b"iolo stable")

            copied, skipped = module.sync_language(source, patch, "en")

            target = patch / "voice_acting" / "en" / "0401_48d_1_npc1.ogg"
            self.assertEqual((copied, skipped), (1, 0))
            self.assertEqual(target.read_bytes(), b"iolo stable")

    def test_sync_language_skips_identical_existing_files(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "voice" / "en"
            target_dir = root / "Ultima_7" / "patch" / "voice_acting" / "en"
            source.mkdir(parents=True)
            target_dir.mkdir(parents=True)
            (source / "0401_48d_1_npc1.ogg").write_bytes(b"iolo stable")
            (target_dir / "0401_48d_1_npc1.ogg").write_bytes(b"iolo stable")

            copied, skipped = module.sync_language(source, root / "Ultima_7" / "patch", "en")

            self.assertEqual((copied, skipped), (0, 1))


if __name__ == "__main__":
    unittest.main()
