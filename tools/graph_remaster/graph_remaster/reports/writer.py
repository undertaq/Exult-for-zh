"""Atomic, self-contained report generation for every pipeline stage."""

from __future__ import annotations

from enum import StrEnum
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping

from ..db import AssetStore
from .templates import document, nav_links, payload_block


class Stage(StrEnum):
    INVENTORY = "inventory"
    EXTRACTION = "extraction"
    CONTROLS = "controls"
    GENERATION = "generation"
    POSTPROCESS = "postprocess"
    VALIDATION = "validation"
    PACKAGE = "package"


STAGES: tuple[tuple[Stage, str], ...] = (
    (Stage.INVENTORY, "01-inventory.html"),
    (Stage.EXTRACTION, "02-extraction.html"),
    (Stage.CONTROLS, "03-controls.html"),
    (Stage.GENERATION, "04-generation.html"),
    (Stage.POSTPROCESS, "05-postprocess.html"),
    (Stage.VALIDATION, "06-validation.html"),
    (Stage.PACKAGE, "07-package.html"),
)


def write_stage_report(stage: Stage | str, run_id: str, store: AssetStore, output_dir: Path) -> Path:
    """Write one stage page, including provenance visible without a server."""

    stage_value = Stage(stage)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = dict(STAGES)[stage_value]
    payload = _snapshot(stage_value, run_id, store)
    links = [(item.value, filename_for(item)) for item, _ in STAGES]
    body = f"<h1>{stage_value.value.title()} report</h1>{nav_links(links)}{payload_block(payload)}"
    path = output_dir / filename
    _atomic_write(path, document(f"{stage_value.value.title()} report", body))
    return path


def write_run_index(run_id: str, output_dir: Path) -> Path:
    """Create the run index and placeholder pages for all seven stages."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    links = [(stage.value, filename) for stage, filename in STAGES]
    rows = "".join(f'<tr><td><a href="{filename}">{stage.value}</a></td><td>{filename}</td></tr>' for stage, filename in STAGES)
    body = f"<h1>Graph remaster run {run_id}</h1>{nav_links(links)}<table><tr><th>Stage</th><th>Report</th></tr>{rows}</table>"
    path = output_dir / "index.html"
    _atomic_write(path, document(f"Graph remaster run {run_id}", body))
    for stage, filename in STAGES:
        stage_path = output_dir / filename
        if not stage_path.exists():
            placeholder = f"<h1>{stage.value.title()} report</h1>{nav_links(links)}<p>Stage has not emitted a payload yet.</p>"
            _atomic_write(stage_path, document(f"{stage.value.title()} report", placeholder))
    return path


def filename_for(stage: Stage) -> str:
    return dict(STAGES)[stage]


def _snapshot(stage: Stage, run_id: str, store: AssetStore) -> dict[str, object]:
    connection = store._connection
    source_hashes = [row[0] for row in connection.execute("SELECT archive_sha256 FROM source_archives ORDER BY archive_sha256").fetchall()]
    jobs = []
    for row in connection.execute("SELECT job_id, state, profile, backend, parameters_json FROM generation_jobs ORDER BY job_id").fetchall():
        try:
            parameters = json.loads(row[4])
        except (TypeError, json.JSONDecodeError):
            parameters = {"raw": row[4]}
        jobs.append({"job_id": row[0], "state": row[1], "profile": row[2], "backend": row[3], "parameters": parameters})
    return {
        "run_id": run_id,
        "stage": stage.value,
        "source_hashes": source_hashes,
        "jobs": jobs,
        "seed_gpu_precision": [
            {"job_id": job["job_id"], "seed": job["parameters"].get("seed"), "gpu": job["parameters"].get("device"), "precision": job["parameters"].get("precision")}
            for job in jobs
        ],
    }


def _atomic_write(path: Path, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
