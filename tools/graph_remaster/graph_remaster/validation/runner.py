"""Persist validation results and state transitions without approving assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ..controls.prepare import AtlasBundle, CanvasSpec
from ..db import AssetStore
from ..models import Candidate, FrameRecord, JobState, ValidationResult
from ..reporting import write_stage_html_report
from .checks import CheckResult, validate_alpha, validate_animation_boxes, validate_dimensions, validate_metadata, validate_offset, validate_rgba, validate_seams, validate_tile_grid


@dataclass(frozen=True)
class ValidationReport:
    candidate_id: str
    passed: bool
    checks: tuple[CheckResult, ...]
    html_path: Path

    def as_dict(self) -> dict[str, object]:
        return {"stage": "validate", "candidate_id": self.candidate_id, "passed": self.passed, "checks": {check.name: check.as_dict() for check in self.checks}}


def run_validation(candidate_id: str, store: AssetStore) -> ValidationReport:
    """Validate one GENERATED candidate, persist details, then validate or reject it.

    This function never transitions a job to APPROVED.  Approval remains the
    exclusive responsibility of the review stage.
    """

    candidate = store.get_candidate(candidate_id)
    job = store.get_generation_job(candidate.job_id)
    state = JobState(job.state)
    if state is not JobState.GENERATED:
        raise ValueError(f"candidate {candidate_id!r} belongs to {state.value}, not GENERATED")
    frame = store.get_frame(job.frame)
    with Image.open(candidate.artifact_path) as loaded:
        master = loaded.copy()
    checks = _checks_for(store, frame, master, candidate)
    passed = all(check.passed or not check.blocking for check in checks)
    errors = [check.explanation for check in checks if not check.passed and check.blocking]
    store.add_validation_and_transition(
        ValidationResult(candidate_id, passed, {check.name: check.as_dict() for check in checks}, errors),
        JobState.GENERATED,
        JobState.VALIDATED if passed else JobState.REJECTED,
    )
    report = ValidationReport(candidate_id, passed, tuple(checks), _report_path(candidate))
    write_stage_html_report(report.html_path, "Validation report", report.as_dict())
    return report


def _checks_for(store: AssetStore, frame: FrameRecord, master: Image.Image, candidate: Candidate) -> list[CheckResult]:
    checks = [validate_rgba(master), validate_dimensions(frame, master), validate_alpha(frame, master), validate_offset(frame), validate_metadata(frame)]
    asset_type = frame.metadata.get("asset_type", "flat_tile")
    if asset_type == "flat_tile":
        atlas = AtlasBundle(master.convert("RGBA"), CanvasSpec(1, 1, frame.width, frame.height), 6)
        checks.append(validate_tile_grid(atlas, [frame]))
    elif asset_type == "npc_rle":
        tolerance = candidate.metadata.get("animation_box_tolerance", 2)
        if not isinstance(tolerance, int) or isinstance(tolerance, bool):
            tolerance = -1
        frames = store.list_shape_frames(frame.key)
        candidate_frame_ids, masters = _animation_masters(frame, master, candidate)
        checks.append(validate_animation_boxes(frames, masters, tolerance, candidate_frame_ids))
    elif asset_type == "building_combo":
        threshold = candidate.metadata.get("seam_threshold", 32.0)
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            threshold = -1.0
        checks.append(validate_seams(_atlas_with_layout(master, candidate), float(threshold)))
    return checks


def _report_path(candidate: Candidate) -> Path:
    configured = candidate.metadata.get("validation_report_path")
    if isinstance(configured, str) and configured:
        return Path(configured)
    return Path(candidate.artifact_path).with_suffix(".validation.html")


def _animation_masters(frame: FrameRecord, master: Image.Image, candidate: Candidate) -> tuple[list[int], list[Image.Image]]:
    raw_paths = candidate.metadata.get("animation_frames")
    if raw_paths is None:
        return [frame.key.frame_id], [master]
    if not isinstance(raw_paths, dict):
        return [], []
    loaded: list[tuple[int, Image.Image]] = []
    for frame_id, path in raw_paths.items():
        try:
            parsed_id = int(frame_id)
            if isinstance(frame_id, bool) or not isinstance(path, str) or not path:
                continue
            with Image.open(path) as image:
                loaded.append((parsed_id, image.copy()))
        except (OSError, ValueError):
            continue
    loaded.sort(key=lambda item: item[0])
    return [frame_id for frame_id, _ in loaded], [image for _, image in loaded]


def _atlas_with_layout(master: Image.Image, candidate: Candidate) -> AtlasBundle:
    layout = candidate.metadata.get("atlas_layout")
    if not isinstance(layout, dict):
        return AtlasBundle(master.convert("RGBA"), CanvasSpec(1, 1, master.width // 6, master.height // 6), 6)
    columns = layout.get("columns")
    rows = layout.get("rows")
    tile_width = layout.get("tile_width")
    tile_height = layout.get("tile_height")
    scale = layout.get("scale", 6)
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in (columns, rows, tile_width, tile_height, scale)):
        return AtlasBundle(master.convert("RGBA"), CanvasSpec(1, 1, master.width // 6, master.height // 6), 6)
    return AtlasBundle(master.convert("RGBA"), CanvasSpec(columns, rows, tile_width, tile_height), scale)
