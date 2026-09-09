"""A deterministic, renderer-neutral Pillow fixture pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ..backends.base import InferenceRequest
from ..backends.mock import MockBackend
from ..controls.prepare import prepare_controls
from ..controls.profiles import AssetType, get_profile
from ..db import AssetStore
from ..models import Candidate, FrameKey, FrameRecord, GenerationJob, JobState, ShapeRecord, SourceArchive, ValidationResult, ReviewDecision
from ..postprocess.hd_master import write_hd_master
from ..reports.writer import STAGES, write_run_index, write_stage_report
from ..validation.runner import run_validation
from .manifest import PackageManifest, build_package


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    package_dir: Path
    manifest_path: Path
    candidate_ids: tuple[str, ...]


def run_fixture_pipeline(tmp_path: Path) -> RunSummary:
    """Exercise source-independent flat, NPC, and building candidates end to end."""

    tmp_path = Path(tmp_path)
    run_id = "fixture"
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()
    source_hash = "f" * 64
    store.upsert_source_archive(SourceArchive(source_hash, "fixture.vga", 0))
    backend = MockBackend()
    records: list[tuple[FrameRecord, str, str]] = []
    source_dir = tmp_path / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    for asset_type, shape_id, count, size in (("flat_tile", 1, 1, (8, 8)), ("npc_rle", 2, 2, (8, 8)), ("building_combo", 3, 1, (16, 8))):
        store.upsert_shape(ShapeRecord(source_hash, 0, shape_id, size[0], size[1], count))
        for frame_id in range(count):
            source_path = source_dir / f"{asset_type}-{frame_id}.png"
            Image.new("RGBA", size, (40 + frame_id, 80, 120, 255)).save(source_path)
            frame = FrameRecord(FrameKey(source_hash, 0, shape_id, frame_id), size[0], size[1], metadata={"asset_type": asset_type, "rgba_preview_path": str(source_path), "offset": [frame_id, -frame_id], "scale": 6})
            store.upsert_frame(frame)
            records.append((frame, asset_type, f"{asset_type}-{frame_id}"))
    artifacts: dict[str, Path] = {}
    npc_artifacts: dict[str, str] = {}
    for frame, asset_type, candidate_id in records:
        profile = get_profile(AssetType(asset_type))
        with Image.open(frame.metadata["rgba_preview_path"]) as source_image:
            source = source_image.convert("RGBA")
        controls = prepare_controls(frame, profile)
        job = GenerationJob(frame.key, JobState.GENERATED, profile.name, "mock", {"seed": 100 + frame.key.frame_id, "width": frame.width * 6, "height": frame.height * 6, "run_id": run_id}, f"job-{candidate_id}")
        job_id = store.create_generation_job(job)
        generated = backend.generate(InferenceRequest(job, source, controls))
        candidate_path = tmp_path / f"{candidate_id}.png"
        write_hd_master(generated.image, frame, candidate_path)
        artifacts[candidate_id] = candidate_path
        if asset_type == "npc_rle":
            npc_artifacts[str(frame.key.frame_id)] = str(candidate_path)
    for frame, asset_type, candidate_id in records:
        job_id = f"job-{candidate_id}"
        metadata = {"run_id": run_id, "hd_dimensions": [frame.width * 6, frame.height * 6], "offset": frame.metadata["offset"]}
        if asset_type == "npc_rle":
            metadata["animation_frames"] = npc_artifacts
        store.add_candidate(Candidate(job_id, str(artifacts[candidate_id]), metadata=metadata, candidate_id=candidate_id))
    candidate_ids: list[str] = []
    for _, _, candidate_id in records:
        report = run_validation(candidate_id, store)
        if not report.passed:
            raise AssertionError(f"fixture candidate failed validation: {candidate_id}: {report.as_dict()}")
        store.add_review(ReviewDecision(candidate_id, "APPROVE", "fixture", "deterministic fixture"))
        job = store.get_candidate(candidate_id).job_id
        store.transition_job(job, JobState.VALIDATED, JobState.APPROVED)
        candidate_ids.append(candidate_id)
    report_dir = tmp_path / "reports" / run_id
    write_run_index(run_id, report_dir)
    for stage, _ in STAGES:
        write_stage_report(stage, run_id, store, report_dir)
    package_dir = tmp_path / "packages" / run_id
    manifest = build_package(run_id, store, package_dir)
    store.close()
    return RunSummary(run_id, package_dir, package_dir / "manifest.json", tuple(candidate_ids))
