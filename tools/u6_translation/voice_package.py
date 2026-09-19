from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile

from tools.voice_acting.pack_voice import cmd_pack, read_idx


LANGUAGES = ("en", "zh")
VOICE_ARCHIVE_RELATIVE_DIR = Path("mods/Ultima6v1.3/patch/voice_acting")
OGG_MAGIC = b"OggS"
_INSTALL_JOURNAL_NAME = ".voice_acting.install.json"


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

    expected_index_size = 12
    for entry in entries:
        try:
            name_size = len(entry.name.encode("ascii"))
        except UnicodeEncodeError as error:
            raise ValueError(f"invalid {language} voice index: {idx_path}") from error
        expected_index_size += 2 + name_size + 12
    actual_index_size = idx_path.stat().st_size
    if actual_index_size != expected_index_size:
        raise ValueError(
            f"trailing or missing bytes in {language} voice index: "
            f"expected={expected_index_size} actual={actual_index_size}"
        )

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


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove_path(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_install_journal(path: Path, payload: Mapping[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _clear_install_journal(path: Path) -> None:
    if path.exists():
        path.unlink()
        _fsync_directory(path.parent)


def _journal_path(output_root: Path) -> Path:
    return output_root.parent / _INSTALL_JOURNAL_NAME


def _journal_entry_path(payload: Mapping[str, object], key: str, output_root: Path) -> Path:
    raw_path = payload.get(key)
    if not isinstance(raw_path, str):
        raise ValueError(f"voice archive install journal is missing {key}")
    path = Path(raw_path)
    if path.parent != output_root.parent:
        raise ValueError(f"voice archive install journal has unsafe {key}")
    return path


def _recover_archive_install(output_root: Path) -> None:
    journal = _journal_path(output_root)
    if not journal.is_file():
        for temporary in output_root.parent.glob(f".{journal.name}.tmp-*"):
            if temporary.is_file() or temporary.is_symlink():
                temporary.unlink()
        return
    try:
        payload = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid voice archive install journal: {journal}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"invalid voice archive install journal: {journal}")

    stored_output = _journal_entry_path(payload, "output_root", output_root)
    if stored_output != output_root:
        raise ValueError(f"voice archive install journal targets another directory: {journal}")
    backup_root = _journal_entry_path(payload, "backup_root", output_root)
    staged_root = _journal_entry_path(payload, "staged_root", output_root)
    had_output = payload.get("had_output") is True

    if output_root.is_symlink():
        raise ValueError(f"voice archive target is a symlink: {output_root}")
    if _path_exists(backup_root) and backup_root.is_symlink():
        raise ValueError(f"voice archive backup is a symlink: {backup_root}")
    if _path_exists(staged_root) and staged_root.is_symlink():
        raise ValueError(f"voice archive staging path is a symlink: {staged_root}")

    if _path_exists(output_root) and _path_exists(backup_root):
        # The new directory was installed; discard the old complete pair.
        _remove_path(backup_root)
    elif not _path_exists(output_root) and _path_exists(backup_root):
        if had_output:
            os.replace(backup_root, output_root)
            _fsync_directory(output_root.parent)
        else:
            _remove_path(backup_root)

    if _path_exists(staged_root):
        _remove_path(staged_root)
    _clear_install_journal(journal)


def _install_archives(temp_root: Path, output_root: Path) -> None:
    temp_root = Path(temp_root).absolute()
    output_root = Path(output_root).absolute()
    if temp_root.is_symlink() or not temp_root.is_dir():
        raise ValueError(f"voice archive staging path is not a directory: {temp_root}")
    if output_root.is_symlink():
        raise ValueError(f"voice archive target is a symlink: {output_root}")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    _recover_archive_install(output_root)

    expected_names = {
        f"{language}_voices.{suffix}"
        for language in LANGUAGES
        for suffix in ("pak", "idx")
    }
    if output_root.exists():
        if not output_root.is_dir():
            raise ValueError(f"voice archive target is not a directory: {output_root}")
        actual_names = {path.name for path in output_root.iterdir()}
        extra = sorted(actual_names - expected_names)
        if extra:
            raise ValueError(
                "existing voice archive directory mismatch: unexpected "
                + ", ".join(extra)
            )
        if any(path.is_symlink() or not path.is_file() for path in output_root.iterdir()):
            raise ValueError("existing voice archive directory contains non-file entries")

    staged_names = {path.name for path in temp_root.iterdir()}
    if staged_names != expected_names:
        raise ValueError("voice archive staging directory mismatch")
    if any(not (temp_root / name).is_file() for name in expected_names):
        raise ValueError("voice archive staging directory contains non-file entries")

    backup_root = Path(tempfile.mkdtemp(
        prefix=f".{output_root.name}.backup-", dir=str(output_root.parent)
    ))
    backup_root.rmdir()
    journal = _journal_path(output_root)
    payload: dict[str, object] = {
        "output_root": str(output_root),
        "backup_root": str(backup_root),
        "staged_root": str(temp_root),
        "had_output": output_root.exists(),
        "phase": "prepared",
    }
    _write_install_journal(journal, payload)
    try:
        if output_root.exists():
            os.replace(output_root, backup_root)
            payload["phase"] = "old_moved"
            _write_install_journal(journal, payload)
        os.replace(temp_root, output_root)
        payload["phase"] = "new_installed"
        _write_install_journal(journal, payload)
        if _path_exists(backup_root):
            _remove_path(backup_root)
        _clear_install_journal(journal)
        _fsync_directory(output_root.parent)
    except Exception:
        try:
            _recover_archive_install(output_root)
        except Exception as recovery_error:
            raise RuntimeError(
                f"voice archive installation failed and recovery failed: {recovery_error}"
            ) from recovery_error
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
