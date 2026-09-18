from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import struct
import tempfile

from tools.voice_acting.pack_voice import cmd_pack, read_idx


LANGUAGES = ("en", "zh")
VOICE_ARCHIVE_RELATIVE_DIR = Path("mods/Ultima6v1.3/patch/voice_acting")
OGG_MAGIC = b"OggS"


@dataclass(frozen=True)
class VoicePackageReport:
    entries_by_language: dict[str, int]
    archive_paths: dict[str, tuple[Path, Path]]
    archive_sizes: dict[str, tuple[int, int]]


def _manifest_filename(raw_name: str, *, language: str) -> str:
    name = raw_name.strip()
    if (
        not name
        or not name.endswith(".ogg")
        or "/" in name
        or "\\" in name
        or name in {".", ".."}
    ):
        raise ValueError(f"invalid {language} voice filename: {raw_name!r}")
    try:
        name[:-4].encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError(f"non-ASCII {language} voice filename: {name!r}") from error
    return name


def _load_manifest_names(manifest_dir: Path, language: str) -> tuple[str, ...]:
    path = Path(manifest_dir) / f"{language}_manifest.csv"
    if not path.is_file():
        raise ValueError(f"missing {language} voice manifest: {path}")

    names: list[str] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if "filename" not in (reader.fieldnames or ()):
            raise ValueError(f"{language} voice manifest is missing filename column: {path}")
        for row_number, row in enumerate(reader, start=2):
            raw_name = row.get("filename") or ""
            name = _manifest_filename(raw_name, language=language)
            if name in names:
                raise ValueError(
                    f"duplicate {language} approved voice filename at row {row_number}: {name}"
                )
            names.append(name)

    if not names:
        raise ValueError(f"{language} voice manifest has no approved entries: {path}")
    return tuple(sorted(names))


def _validate_audio_inputs(
    audio_root: Path,
    expected_by_language: Mapping[str, Iterable[str]],
) -> None:
    for language in LANGUAGES:
        language_root = Path(audio_root) / language
        if not language_root.is_dir():
            raise ValueError(f"missing {language} voice audio directory: {language_root}")
        expected = set(expected_by_language[language])
        actual = {
            path.name
            for path in language_root.iterdir()
            if path.is_file() and path.name.endswith(".ogg")
        }
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            details: list[str] = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if extra:
                details.append("unexpected " + ", ".join(extra))
            raise ValueError(
                f"{language} manifest coverage mismatch: " + "; ".join(details)
            )
        for name in sorted(expected):
            path = language_root / name
            if path.read_bytes()[:4] != OGG_MAGIC:
                raise ValueError(f"invalid OGG magic in {language} voice file: {path}")


def _expected_names_by_language(
    expected_names: Mapping[str, Iterable[str]] | Iterable[str],
) -> dict[str, set[str]]:
    if isinstance(expected_names, Mapping):
        result = {
            language: {_manifest_filename(name, language=language) for name in names}
            for language, names in expected_names.items()
        }
        unknown = set(result) - set(LANGUAGES)
        if unknown:
            raise ValueError(f"unsupported voice archive language(s): {sorted(unknown)}")
        return result

    names = {_manifest_filename(name, language="voice") for name in expected_names}
    return {language: set(names) for language in LANGUAGES}


def _verify_language_archive(
    archive_root: Path,
    language: str,
    expected_names: set[str],
) -> None:
    pak_path = archive_root / f"{language}_voices.pak"
    idx_path = archive_root / f"{language}_voices.idx"
    if not pak_path.is_file() or not idx_path.is_file():
        raise ValueError(f"missing {language} voice archive or index in {archive_root}")

    try:
        entries = read_idx(idx_path)
    except (IndexError, UnicodeError, OSError, struct.error, ValueError) as error:
        raise ValueError(f"invalid {language} voice index: {idx_path}") from error

    indexed_names = [f"{entry.name}.ogg" for entry in entries]
    if len(indexed_names) != len(set(indexed_names)):
        raise ValueError(f"duplicate {language} voice index entries")
    if set(indexed_names) != expected_names:
        missing = sorted(expected_names - set(indexed_names))
        extra = sorted(set(indexed_names) - expected_names)
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise ValueError(f"{language} archive manifest coverage mismatch: " + "; ".join(details))

    pak_data = pak_path.read_bytes()
    expected_offset = 0
    for entry in entries:
        end = entry.offset + entry.size
        if entry.offset != expected_offset or end > len(pak_data):
            raise ValueError(
                f"{language} archive bounds invalid for {entry.name}: "
                f"offset={entry.offset} size={entry.size} archive_size={len(pak_data)}"
            )
        data = pak_data[entry.offset:end]
        if data[:4] != OGG_MAGIC:
            raise ValueError(f"invalid OGG magic in {language} archive entry: {entry.name}")
        expected_offset = end
    if expected_offset != len(pak_data):
        raise ValueError(
            f"{language} archive size mismatch: entries={expected_offset} "
            f"archive={len(pak_data)}"
        )


def verify_voice_archives(
    audio_root: Path,
    expected_names: Mapping[str, Iterable[str]] | Iterable[str],
) -> None:
    """Verify VAIX archives in ``audio_root`` against approved OGG names.

    Manifest filenames retain their ``.ogg`` suffix; VAIX index entries are
    checked using the corresponding suffix-less stem written by the packer.
    """

    archive_root = Path(audio_root)
    expected_by_language = _expected_names_by_language(expected_names)
    for language, names in expected_by_language.items():
        _verify_language_archive(archive_root, language, names)


def _backup_existing(path: Path, backup_path: Path) -> None:
    try:
        os.link(path, backup_path)
    except OSError:
        shutil.copy2(path, backup_path)


def _install_archives(temp_root: Path, output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    targets = tuple(
        output_root / f"{language}_voices.{suffix}"
        for language in LANGUAGES
        for suffix in ("pak", "idx")
    )
    sources = tuple(temp_root / target.name for target in targets)
    backups: dict[Path, Path] = {}
    installed: list[Path] = []
    try:
        for index, target in enumerate(targets):
            if target.is_symlink():
                raise ValueError(f"voice archive target is a symlink: {target}")
            if target.exists():
                backup = temp_root / f".backup-{index}-{target.name}"
                _backup_existing(target, backup)
                backups[target] = backup
        for source, target in zip(sources, targets):
            os.replace(source, target)
            installed.append(target)
    except Exception:
        for target in reversed(installed):
            backup = backups.get(target)
            if backup is not None and backup.exists():
                os.replace(backup, target)
            elif target.exists():
                target.unlink()
        raise


def package_voice_archives(
    audio_root: Path,
    manifest_dir: Path,
    staging_root: Path,
) -> VoicePackageReport:
    """Pack paired, approved U6 OGG outputs into verified VAIX archives."""

    audio_root = Path(audio_root)
    manifest_dir = Path(manifest_dir)
    staging_root = Path(staging_root)
    names_by_language = {
        language: _load_manifest_names(manifest_dir, language)
        for language in LANGUAGES
    }
    if set(names_by_language["en"]) != set(names_by_language["zh"]):
        en_names = set(names_by_language["en"])
        zh_names = set(names_by_language["zh"])
        missing_zh = sorted(en_names - zh_names)
        missing_en = sorted(zh_names - en_names)
        details: list[str] = []
        if missing_zh:
            details.append("missing zh: " + ", ".join(missing_zh))
        if missing_en:
            details.append("missing en: " + ", ".join(missing_en))
        raise ValueError("language pair manifest mismatch: " + "; ".join(details))

    # Complete both-language validation happens before the packer can touch
    # the release staging tree.
    _validate_audio_inputs(audio_root, names_by_language)

    output_root = staging_root / VOICE_ARCHIVE_RELATIVE_DIR
    output_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".u6-voice-package-", dir=str(output_root.parent)
    ) as temporary:
        temporary_root = Path(temporary)
        for language in LANGUAGES:
            cmd_pack(language, audio_root / language, temporary_root)
        verify_voice_archives(temporary_root, names_by_language)
        _install_archives(temporary_root, output_root)

    archive_paths = {
        language: (
            output_root / f"{language}_voices.pak",
            output_root / f"{language}_voices.idx",
        )
        for language in LANGUAGES
    }
    archive_sizes = {
        language: (paths[0].stat().st_size, paths[1].stat().st_size)
        for language, paths in archive_paths.items()
    }
    return VoicePackageReport(
        entries_by_language={
            language: len(names_by_language[language]) for language in LANGUAGES
        },
        archive_paths=archive_paths,
        archive_sizes=archive_sizes,
    )
