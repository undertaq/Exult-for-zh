"""Approved-candidate package manifests and content-addressed copying."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any

from ..db import AssetStore
from ..models import FrameKey, JobState
from PIL import Image


@dataclass(frozen=True)
class PackageEntry:
    candidate_id: str
    source_key: dict[str, object]
    source_dimensions: tuple[int, int]
    hd_dimensions: tuple[int, int]
    scaled_offset: tuple[int, int]
    alpha_hash: str
    artifact_path: str
    artifact_sha256: str


@dataclass(frozen=True)
class PackageManifest:
    run_id: str
    created_at: str
    entries: tuple[PackageEntry, ...]

    def as_dict(self) -> dict[str, object]:
        return {"format": "ultima7-graph-remaster-package/v1", "run_id": self.run_id, "created_at": self.created_at, "entries": [asdict(entry) for entry in self.entries]}


def build_package(run_id: str, store: AssetStore, output_dir: Path) -> PackageManifest:
    """Copy only reviewed, validated, APPROVED masters into a package."""

    output_dir = Path(output_dir)
    masters_dir = output_dir / "masters"
    entries: list[PackageEntry] = []
    rows = store._connection.execute(
        """SELECT c.candidate_id, c.artifact_path, c.artifact_sha256, c.metadata_json,
        j.job_id, j.state, j.archive_sha256, j.archive_index, j.shape_id, j.frame_id,
        r.decision
        FROM candidates c JOIN generation_jobs j ON j.job_id = c.job_id
        LEFT JOIN review_decisions r ON r.candidate_id = c.candidate_id
        ORDER BY c.candidate_id"""
    ).fetchall()
    for row in rows:
        metadata = _json_object(row[3])
        if metadata.get("run_id", run_id) != run_id:
            continue
        if row[5] != JobState.APPROVED.value or row[10] != "APPROVE":
            raise ValueError(f"candidate {row[0]!r} is not approved for packaging")
        source_key = {"archive_sha256": row[6], "archive_index": row[7], "shape_id": row[8], "frame_id": row[9]}
        frame = store.get_frame(FrameKey(row[6], row[7], row[8], row[9]))
        artifact = Path(row[1])
        if not artifact.is_file():
            raise FileNotFoundError(f"approved candidate artifact is missing: {artifact}")
        destination = masters_dir / f"{row[0]}.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(artifact, destination)
        checksum = _sha256(destination)
        source_dimensions = (frame.width, frame.height)
        hd_dimensions = tuple(metadata.get("hd_dimensions", (frame.width * 6, frame.height * 6)))
        offset = metadata.get("offset", frame.metadata.get("offset", [0, 0]))
        scaled_offset = (int(offset[0]) * 6, int(offset[1]) * 6) if isinstance(offset, (list, tuple)) and len(offset) == 2 else (0, 0)
        alpha_hash = str(metadata.get("alpha_hash", ""))
        if not alpha_hash:
            source_path = frame.metadata.get("rgba_preview_path")
            if isinstance(source_path, str):
                with Image.open(source_path) as source_image:
                    alpha_hash = hashlib.sha256(source_image.convert("RGBA").getchannel("A").tobytes()).hexdigest()
        entries.append(PackageEntry(row[0], source_key, source_dimensions, hd_dimensions, scaled_offset, alpha_hash, str(destination), checksum))
        sidecar = artifact.with_suffix(".json")
        if sidecar.is_file():
            shutil.copyfile(sidecar, destination.with_suffix(".json"))
    if not entries:
        raise ValueError(f"no approved candidates found for run {run_id!r}")
    manifest = PackageManifest(run_id, datetime.now(timezone.utc).isoformat(), tuple(entries))
    write_manifest(manifest, output_dir / "manifest.json")
    return manifest


def write_manifest(manifest: PackageManifest, output: Path) -> None:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent, text=True)
    try:
        with open(fd, "w", encoding="utf-8", closefd=True) as stream:
            json.dump(manifest.as_dict(), stream, indent=2, sort_keys=True)
            stream.write("\n")
        Path(temporary).replace(output)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
