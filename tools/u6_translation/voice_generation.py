from __future__ import annotations

import csv
from pathlib import Path
import shlex
import subprocess
import sys


def _manifest_filenames(path: Path) -> set[str]:
    if not path.is_file():
        raise ValueError(f"missing voice manifest: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if "filename" not in (reader.fieldnames or ()):
            raise ValueError(f"voice manifest has no filename column: {path}")
        return {row["filename"] for row in reader if row.get("filename")}


def run_voice_generation(
    manifest_dir: Path,
    output_root: Path,
    language: str,
    dry_run: bool,
    generator_path: Path,
) -> int:
    """Run the existing generator for paired U6 manifests without a shell."""

    if language not in {"en", "zh", "both"}:
        raise ValueError(f"unsupported voice language: {language!r}")
    languages = ("en", "zh") if language == "both" else (language,)
    manifests = {
        item: manifest_dir / f"{item}_manifest.csv" for item in languages
    }
    filenames = {item: _manifest_filenames(path) for item, path in manifests.items()}
    if language == "both" and filenames["en"] != filenames["zh"]:
        raise ValueError("English and Chinese manifests must use identical filenames")

    for item in languages:
        command = [
            sys.executable,
            str(generator_path),
            "--manifest",
            str(manifests[item]),
            "--output-dir",
            str(output_root / item),
        ]
        if dry_run:
            print(" ".join(shlex.quote(part) for part in command))
            continue
        (output_root / item).mkdir(parents=True, exist_ok=True)
        subprocess.run(command, check=True)
    return 0
