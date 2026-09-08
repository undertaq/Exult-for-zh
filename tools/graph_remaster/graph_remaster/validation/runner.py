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
    checks = _checks_for(frame, master, candidate)
    passed = all(check.passed or not check.blocking for check in checks)
    errors = [check.explanation for check in checks if not check.passed and check.blocking]
    store.add_validation(ValidationResult(candidate_id, passed, {check.name: check.as_dict() for check in checks}, errors))
    store.transition_job(job.job_id or candidate.job_id, JobState.GENERATED, JobState.VALIDATED if passed else JobState.REJECTED)
    report = ValidationReport(candidate_id, passed, tuple(checks), _report_path(candidate))
    write_stage_html_report(report.html_path, "Validation report", report.as_dict())
    return report


def _checks_for(frame: FrameRecord, master: Image.Image, candidate: Candidate) -> list[CheckResult]:
    checks = [validate_rgba(master), validate_dimensions(frame, master), validate_alpha(frame, master), validate_offset(frame), validate_metadata(frame)]
    asset_type = frame.metadata.get("asset_type", "flat_tile")
    if asset_type == "flat_tile":
        atlas = AtlasBundle(master.convert("RGBA"), CanvasSpec(1, 1, frame.width, frame.height), 6)
        checks.append(validate_tile_grid(atlas, [frame]))
    elif asset_type == "npc_rle":
        tolerance = candidate.metadata.get("animation_box_tolerance", 2)
        if not isinstance(tolerance, int) or isinstance(tolerance, bool):
            tolerance = -1
        checks.append(validate_animation_boxes([frame], [master], tolerance))
    elif asset_type == "building_combo":
        threshold = candidate.metadata.get("seam_threshold", 32.0)
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            threshold = -1.0
        checks.append(validate_seams(master, float(threshold)))
    return checks


def _report_path(candidate: Candidate) -> Path:
    configured = candidate.metadata.get("validation_report_path")
    if isinstance(configured, str) and configured:
        return Path(configured)
    return Path(candidate.artifact_path).with_suffix(".validation.html")
