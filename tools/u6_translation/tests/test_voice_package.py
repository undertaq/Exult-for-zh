from __future__ import annotations

import csv
from pathlib import Path
import os
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools.u6_translation.voice_package import (
    _install_archives,
    package_voice_archives,
    verify_voice_archives,
)
from tools.voice_acting.pack_voice import read_idx


_MANIFEST_FIELDS = (
    "filename",
    "func_id",
    "offset_key",
    "segment",
    "speaker",
    "speaker_source",
    "npc_num",
    "voice_id",
    "voice_desc",
    "prev_text",
    "next_text",
    "text",
)


def _write_ogg(path: Path, payload: bytes = b"fixture") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"OggS" + payload)


def _write_manifest(path: Path, names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_MANIFEST_FIELDS, lineterminator="\n")
        writer.writeheader()
        for name in names:
            writer.writerow(
                {
                    "filename": name,
                    "func_id": "0401",
                    "offset_key": "1a",
                    "segment": "0",
                    "speaker": "Iolo",
                    "speaker_source": "runtime-capture",
                    "npc_num": "1",
                    "voice_id": "qwen3-iolo",
                    "voice_desc": "Iolo",
                    "prev_text": "",
                    "next_text": "",
                    "text": "Hello" if path.stem.startswith("en") else "你好",
                }
            )


def _write_manifests(root: Path, en_names: list[str], zh_names: list[str]) -> None:
    _write_manifest(root / "en_manifest.csv", en_names)
    _write_manifest(root / "zh_manifest.csv", zh_names)


class VoicePackageTest(unittest.TestCase):
    def test_package_requires_matching_english_and_chinese_stems(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "audio"
            manifests = root / "manifests"
            staging = root / "staging"
            name = "0401_1a_2f_0.ogg"
            _write_ogg(audio / "en" / name)
            _write_ogg(audio / "zh" / name)
            _write_manifests(manifests, [name], [name])

            report = package_voice_archives(audio, manifests, staging)

            self.assertEqual(report.entries_by_language, {"en": 1, "zh": 1})
            output = staging / "mods/Ultima6v1.3/patch/voice_acting"
            self.assertTrue((output / "en_voices.idx").is_file())
            self.assertTrue((output / "zh_voices.idx").is_file())
            self.assertEqual([entry.name for entry in read_idx(output / "en_voices.idx")], [name[:-4]])
            verify_voice_archives(output, {"en": {name}, "zh": {name}})

    def test_package_rejects_language_set_mismatch_before_writing_archives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "audio"
            manifests = root / "manifests"
            staging = root / "staging"
            en_name = "0401_1a_2f_0.ogg"
            zh_name = "0401_1a_2f_1.ogg"
            _write_ogg(audio / "en" / en_name)
            _write_ogg(audio / "zh" / zh_name)
            _write_manifests(manifests, [en_name], [zh_name])
            output = staging / "mods/Ultima6v1.3/patch/voice_acting"
            output.mkdir(parents=True)
            old_pak = output / "en_voices.pak"
            old_idx = output / "en_voices.idx"
            old_pak.write_bytes(b"old en pak")
            old_idx.write_bytes(b"old en idx")

            with self.assertRaisesRegex(ValueError, "language pair"):
                package_voice_archives(audio, manifests, staging)

            self.assertEqual(old_pak.read_bytes(), b"old en pak")
            self.assertEqual(old_idx.read_bytes(), b"old en idx")
            self.assertFalse((output / "zh_voices.pak").exists())

    def test_package_rejects_extra_audio_and_invalid_ogg_before_packing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "audio"
            manifests = root / "manifests"
            staging = root / "staging"
            name = "0401_1a_2f_0.ogg"
            extra = "0401_1a_2f_1.ogg"
            _write_ogg(audio / "en" / name)
            _write_ogg(audio / "zh" / name)
            (audio / "en" / extra).write_bytes(b"not an ogg")
            _write_manifests(manifests, [name], [name])

            with self.assertRaisesRegex(ValueError, "manifest coverage"):
                package_voice_archives(audio, manifests, staging)

            (audio / "en" / extra).unlink()
            (audio / "en" / name).write_bytes(b"invalid")
            with self.assertRaisesRegex(ValueError, "OGG magic"):
                package_voice_archives(audio, manifests, staging)
            self.assertFalse(
                (staging / "mods/Ultima6v1.3/patch/voice_acting/en_voices.pak").exists()
            )

    def test_verify_rejects_archive_bounds_and_manifest_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive"
            archive.mkdir()
            (archive / "en_voices.pak").write_bytes(b"OggS")
            # VAIX v1, one entry named "line", claiming bytes beyond the pak.
            name = b"line"
            index = b"VAIX" + struct.pack("<II", 1, 1)
            index += struct.pack("<H", len(name)) + name + struct.pack("<QI", 0, 99)
            (archive / "en_voices.idx").write_bytes(index)

            with self.assertRaisesRegex(ValueError, "bounds"):
                verify_voice_archives(archive, {"en": {"line.ogg"}})

    def test_verify_rejects_truncated_index_without_leaking_struct_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)
            (archive / "en_voices.pak").write_bytes(b"OggS")
            (archive / "en_voices.idx").write_bytes(b"VAIX\x01")

            with self.assertRaisesRegex(ValueError, "invalid en voice index"):
                verify_voice_archives(archive, {"en": {"line.ogg"}})

    def test_verify_rejects_trailing_index_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)
            (archive / "en_voices.pak").write_bytes(b"OggS")
            name = b"line"
            index = b"VAIX" + struct.pack("<II", 1, 1)
            index += struct.pack("<H", len(name)) + name + struct.pack("<QI", 0, 4)
            (archive / "en_voices.idx").write_bytes(index + b"trailing")

            with self.assertRaisesRegex(ValueError, "trailing"):
                verify_voice_archives(archive, {"en": {"line.ogg"}})

    def test_archive_install_failure_restores_the_previous_complete_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "voice_acting"
            incoming = root / "incoming"
            output.mkdir()
            incoming.mkdir()
            names = (
                "en_voices.pak", "en_voices.idx",
                "zh_voices.pak", "zh_voices.idx",
            )
            for name in names:
                (output / name).write_bytes(f"old {name}".encode())
                (incoming / name).write_bytes(f"new {name}".encode())

            real_replace = os.replace
            failed = False

            def fail_once(source, target):
                nonlocal failed
                if Path(target) == output and not failed:
                    failed = True
                    raise OSError("simulated archive directory swap failure")
                return real_replace(source, target)

            with patch("tools.u6_translation.voice_package.os.replace", side_effect=fail_once):
                with self.assertRaisesRegex(OSError, "directory swap failure"):
                    _install_archives(incoming, output)

            self.assertTrue(output.is_dir())
            for name in names:
                self.assertEqual((output / name).read_bytes(), f"old {name}".encode())
            self.assertFalse((output.parent / ".voice_acting.install.json").exists())


if __name__ == "__main__":
    unittest.main()
