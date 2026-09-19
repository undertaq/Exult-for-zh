from __future__ import annotations

import csv
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys
from typing import Any


QWEN3_DESIGNS = Path(__file__).parents[1] / "voice_acting" / "npc_voice_designs.json"
DEFAULT_U7_REFERENCE_ROOT = Path(__file__).parents[2] / "voice" / "refs"
REQUIRED_PROVIDER_COLUMNS = (
    "filename", "func_id", "offset_key", "segment", "speaker", "voice_desc", "text",
)


def _npc_reference_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _single_npc_name(design: dict[str, Any]) -> str:
    names = design.get("npcs")
    if not isinstance(names, list) or len(names) != 1:
        return ""
    name = str(names[0] or "").strip()
    return name if name and _npc_reference_slug(name) else ""


def _stage_u7_reference_overrides(
    designs_path: Path,
    output_root: Path,
    u7_reference_root: Path | None,
    dry_run: bool,
) -> None:
    """Copy exact-name U7 refs into the isolated U6 output and mark provenance."""

    if u7_reference_root is None or not u7_reference_root.is_dir():
        return

    payload = json.loads(designs_path.read_text(encoding="utf-8"))
    refs_dir = output_root / "refs"
    changed = False
    for design_id, design in sorted(payload.get("designs", {}).items()):
        npc = _single_npc_name(design)
        slug = _npc_reference_slug(npc)
        if not slug:
            continue
        overrides: dict[str, dict[str, str]] = {}
        for language in ("en", "zh"):
            source = u7_reference_root / f"npc_{slug}_{language}_ref.ogg"
            if not source.is_file():
                continue
            destination = refs_dir / f"{design_id}_{language}_ref.ogg"
            if dry_run:
                print(f"  [{npc}] {language.upper()} ref would reuse U7 {source.name}")
            else:
                refs_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            overrides[language] = {
                "source": "u7",
                "filename": source.name,
            }
        if overrides and not dry_run:
            design["reference_overrides"] = overrides
            changed = True

    if changed:
        designs_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )


def _read_manifest(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"missing voice manifest: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or ())
        missing = [field for field in REQUIRED_PROVIDER_COLUMNS if field not in fields]
        if missing:
            raise ValueError(
                f"voice manifest missing required columns: {', '.join(missing)}"
            )
        rows = [{key: value or "" for key, value in row.items()} for row in reader]
    for row in rows:
        filename = row["filename"]
        if (
            not filename
            or "/" in filename
            or "\\" in filename
            or Path(filename).name != filename
            or Path(filename).suffix != ".ogg"
        ):
            raise ValueError(f"unsafe output filename: {filename!r}")
    duplicates = sorted(filename for filename, count in Counter(
        row["filename"] for row in rows if row["filename"]
    ).items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate filename in voice manifest: {duplicates[0]}")
    return rows


def _fallback_design_id(speaker: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", speaker.lower()).strip("_") or "speaker"
    digest = hashlib.sha256(speaker.encode("utf-8")).hexdigest()[:8]
    return f"u6_{slug}_{digest}"


def _stage_qwen3_inputs(
    manifest_dir: Path,
    en_rows: list[dict[str, str]],
    zh_rows: list[dict[str, str]],
) -> tuple[Path, Path]:
    staged = manifest_dir / "qwen3"
    staged.mkdir(parents=True, exist_ok=True)
    by_filename = {row["filename"]: row for row in zh_rows}
    mapping = [
        {
            "npc": en["speaker"],
            "en_func_id": en["func_id"],
            "en_offset_key": en["offset_key"],
            "en_segment": int(en["segment"] or 0),
            "en_text": en["text"],
            "en_voice_desc": en["voice_desc"],
            "en_output_filename": en["filename"],
            "zh_func_id": by_filename[en["filename"]]["func_id"],
            "zh_offset_key": by_filename[en["filename"]]["offset_key"],
            "zh_segment": int(by_filename[en["filename"]]["segment"] or 0),
            "zh_text": by_filename[en["filename"]]["text"],
            "zh_voice_desc": by_filename[en["filename"]]["voice_desc"],
            "zh_output_filename": by_filename[en["filename"]]["filename"],
        }
        for en in sorted(en_rows, key=lambda row: row["filename"])
    ]

    existing = json.loads(QWEN3_DESIGNS.read_text(encoding="utf-8"))
    existing_by_npc = {
        npc: (design_id, design)
        for design_id, design in existing.get("designs", {}).items()
        for npc in design.get("npcs", [])
    }
    designs: dict[str, Any] = {}
    for entry in mapping:
        speaker = entry["npc"]
        if speaker in existing_by_npc:
            design_id, design = existing_by_npc[speaker]
            designs[design_id] = design
            continue
        design_id = _fallback_design_id(speaker)
        if design_id not in designs:
            reference = next(item for item in mapping if item["npc"] == speaker)
            description = reference["en_voice_desc"] or "Clear, natural speaking voice."
            designs[design_id] = {
                "npc": speaker,
                "type": "individual",
                "npcs": [speaker],
                "voice_desc_en": description,
                "voice_desc_zh": reference["zh_voice_desc"] or description,
                "ref_en_text": reference["en_text"],
                "ref_zh_text": reference["zh_text"],
            }
    design_payload = {
        "_meta": {
            "total_designs": len(designs),
            "unique_designs": len(designs),
            "group_designs": 0,
            "narrator_designs": 0,
        },
        "designs": dict(sorted(designs.items())),
    }
    mapping_path = staged / "u6_mapping.json"
    designs_path = staged / "u6_designs.json"
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    designs_path.write_text(json.dumps(design_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return mapping_path, designs_path


def run_voice_generation(
    manifest_dir: Path,
    output_root: Path,
    language: str,
    dry_run: bool,
    generator_path: Path,
    u7_reference_root: Path | None = DEFAULT_U7_REFERENCE_ROOT,
) -> int:
    """Stage paired U6 lines for the Qwen3 three-phase voice pipeline."""

    if language not in {"en", "zh", "both"}:
        raise ValueError(f"unsupported voice language: {language!r}")
    en_manifest = manifest_dir / "en_manifest.csv"
    zh_manifest = manifest_dir / "zh_manifest.csv"
    en_rows = _read_manifest(en_manifest)
    zh_rows = _read_manifest(zh_manifest)
    if Counter(row["filename"] for row in en_rows) != Counter(row["filename"] for row in zh_rows):
        raise ValueError("English and Chinese manifests must use identical filenames")
    mapping, designs = _stage_qwen3_inputs(manifest_dir, en_rows, zh_rows)
    _stage_u7_reference_overrides(
        designs,
        output_root,
        u7_reference_root,
        dry_run,
    )
    command = [
        sys.executable, str(generator_path),
        "--phase", "all", "--reference-workflow", "legacy",
        "--mapping", str(mapping),
        "--en-lines", str(en_manifest),
        "--zh-lines", str(zh_manifest),
        "--designs", str(designs),
        "--output-dir", str(output_root),
        "--clone-prompts", str(output_root / "clone_prompts.pkl"),
    ]
    if language != "both":
        command += ["--lang", language]
    if dry_run:
        print(" ".join(shlex.quote(part) for part in command))
    else:
        subprocess.run(command, check=True)
    return 0
