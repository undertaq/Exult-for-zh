from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
import pytest

from graph_remaster.controls.prepare import AtlasBundle, CanvasSpec
from graph_remaster.cli import main
from graph_remaster.db import AssetStore
from graph_remaster.errors import InvalidStateTransition
from graph_remaster.models import Candidate, FrameKey, FrameRecord, GenerationJob, JobState, ShapeRecord, SourceArchive, ValidationResult
from graph_remaster.validation.checks import (
    validate_alpha,
    validate_animation_boxes,
    validate_dimensions,
    validate_seams,
    validate_tile_grid,
)
from graph_remaster.validation.runner import run_validation


def make_frame(tmp_path: Path, *, frame_id: int = 0, asset_type: str = "flat_tile") -> FrameRecord:
    source = tmp_path / f"source-{frame_id}.png"
    image = Image.new("RGBA", (8, 8))
    image.paste((40, 80, 120, 255), (2, 2, 6, 6))
    image.save(source)
    return FrameRecord(
        FrameKey("a" * 64, 0, 7, frame_id), 8, 8,
        metadata={"asset_type": asset_type, "rgba_preview_path": str(source), "offset": [0, 0], "scale": 6},
    )


def master_for(frame: FrameRecord) -> Image.Image:
    with Image.open(frame.metadata["rgba_preview_path"]) as source:
        return source.convert("RGBA").resize((48, 48), Image.Resampling.NEAREST)


def seed(store: AssetStore, frame: FrameRecord, *, state: JobState = JobState.GENERATED, job_id: str = "job") -> str:
    key = frame.key
    store.upsert_source_archive(SourceArchive(key.archive_sha256, "source.vga"))
    store.upsert_shape(ShapeRecord(key.archive_sha256, key.archive_index, key.shape_id, 8, 8, 1))
    store.upsert_frame(frame)
    return store.create_generation_job(GenerationJob(key, state, frame.metadata["asset_type"], "mock", job_id=job_id))


def seed_shape(store: AssetStore, frames: list[FrameRecord]) -> None:
    key = frames[0].key
    store.upsert_source_archive(SourceArchive(key.archive_sha256, "source.vga"))
    store.upsert_shape(ShapeRecord(key.archive_sha256, key.archive_index, key.shape_id, 8, 8, len(frames)))
    for frame in frames:
        store.upsert_frame(frame)


def test_dimensions_and_alpha_use_canonical_sixfold_tile_rules(tmp_path: Path) -> None:
    frame = make_frame(tmp_path)
    master = master_for(frame)

    dimensions = validate_dimensions(frame, master)
    alpha = validate_alpha(frame, master)

    assert dimensions.name == "dimensions"
    assert dimensions.passed
    assert dimensions.metrics == {"actual_width": 48, "actual_height": 48, "expected_width": 48, "expected_height": 48, "scale": 6}
    assert alpha.name == "alpha"
    assert alpha.passed
    assert alpha.metrics["mismatched_pixels"] == 0

    wrong = Image.new("RGBA", (47, 48))
    failed = validate_dimensions(frame, wrong)
    assert not failed.passed
    assert failed.metrics["actual_width"] == 47

    hole = master.copy()
    hole.putpixel((18, 18), (40, 80, 120, 0))
    alpha_failed = validate_alpha(frame, hole)
    assert not alpha_failed.passed
    assert alpha_failed.metrics["mismatched_pixels"] == 1


def test_tile_grid_animation_boxes_and_seams_publish_stable_metrics(tmp_path: Path) -> None:
    first = make_frame(tmp_path, frame_id=0)
    second = make_frame(tmp_path, frame_id=1)
    atlas_image = Image.new("RGBA", (96, 48))
    atlas_image.alpha_composite(master_for(first), (0, 0))
    atlas_image.alpha_composite(master_for(second), (48, 0))
    atlas = AtlasBundle(atlas_image, CanvasSpec(2, 1, 8, 8), 6)

    grid = validate_tile_grid(atlas, [first, second])
    assert grid.name == "tile_grid"
    assert grid.passed
    assert grid.metrics["cell_width"] == 48
    assert grid.metrics["frame_count"] == 2

    shifted = master_for(second)
    shifted.putalpha(Image.new("L", (48, 48)))
    shifted_alpha = master_for(second).getchannel("A")
    shifted.putalpha(shifted_alpha.transform((48, 48), Image.Transform.AFFINE, (1, 0, -7, 0, 1, 0)))
    boxes = validate_animation_boxes([first, second], [master_for(first), shifted], tolerance=2)
    assert boxes.name == "animation_boxes"
    assert not boxes.passed
    assert boxes.metrics["max_drift"] == 7
    assert boxes.threshold == 2

    mismatched = Image.new("RGBA", (96, 48), (0, 0, 0, 255))
    for y in range(48):
        mismatched.putpixel((47, y), (255, 255, 255, 255))
    seams = validate_seams(AtlasBundle(mismatched, CanvasSpec(2, 1, 8, 8), 6), threshold=0.1)
    assert seams.name == "seams"
    assert not seams.passed
    assert seams.metrics["max_mean_delta"] == 191.25


def test_seams_inspect_every_layout_boundary_not_only_the_midpoint() -> None:
    atlas_image = Image.new("RGBA", (144, 48), (0, 0, 0, 255))
    for y in range(48):
        atlas_image.putpixel((47, y), (255, 255, 255, 255))

    seams = validate_seams(AtlasBundle(atlas_image, CanvasSpec(3, 1, 8, 8), 6), threshold=0.1)

    assert not seams.passed
    assert seams.metrics["vertical_boundary_count"] == 2
    assert seams.metrics["max_mean_delta"] == 191.25


def test_runner_persists_structured_results_transitions_and_offline_html(tmp_path: Path) -> None:
    frame = make_frame(tmp_path)
    artifact = tmp_path / "candidate.png"
    master_for(frame).save(artifact)
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()
    job_id = seed(store, frame)
    store.add_candidate(Candidate(job_id, str(artifact), candidate_id="candidate"))

    report = run_validation("candidate", store)

    assert report.passed
    assert store.job_state(job_id) is JobState.VALIDATED
    checks = store._connection.execute("SELECT checks_json FROM validation_results").fetchone()[0]
    assert set(json.loads(checks)) >= {"dimensions", "alpha", "rgba", "offset", "metadata", "tile_grid"}
    assert report.html_path.is_file()
    assert "Validation report" in report.html_path.read_text(encoding="utf-8")

    rejected_frame = make_frame(tmp_path, frame_id=1)
    rejected_artifact = tmp_path / "rejected.png"
    Image.new("RGBA", (47, 48)).save(rejected_artifact)
    rejected_job = seed(store, rejected_frame, job_id="rejected-job")
    store.add_candidate(Candidate(rejected_job, str(rejected_artifact), candidate_id="rejected"))

    rejected = run_validation("rejected", store)

    assert not rejected.passed
    assert store.job_state(rejected_job) is JobState.REJECTED
    assert JobState.APPROVED not in {store.job_state(job_id), store.job_state(rejected_job)}


def test_validate_cli_runs_candidate_stage_and_writes_offline_html(tmp_path: Path) -> None:
    frame = make_frame(tmp_path)
    artifact = tmp_path / "candidate.png"
    master_for(frame).save(artifact)
    database = tmp_path / "graph.sqlite3"
    store = AssetStore.open(database)
    store.migrate()
    job_id = seed(store, frame)
    store.add_candidate(Candidate(job_id, str(artifact), candidate_id="candidate"))
    store.close()
    config = tmp_path / "pipeline.toml"
    config.write_text(
        "[project]\nname = 'black-gate'\n[paths]\ndata = 'data'\nwork = 'work'\n"
        "[render]\nscale = 6\nlogical_width = 320\nlogical_height = 200\n",
        encoding="utf-8",
    )

    assert main(["validate", "--config", str(config), "--database", str(database), "candidate"]) == 0
    assert "Validation report" in artifact.with_suffix(".validation.html").read_text(encoding="utf-8")
    assert "Validation report" in (tmp_path / "work" / "reports" / "default" / "validate.html").read_text(encoding="utf-8")


def test_npc_runner_validates_the_complete_shape_set_and_rejects_missing_or_extra_frames(tmp_path: Path) -> None:
    frames = [make_frame(tmp_path, frame_id=index, asset_type="npc_rle") for index in range(2)]
    artifacts = []
    for frame in frames:
        artifact = tmp_path / f"npc-{frame.key.frame_id}.png"
        master_for(frame).save(artifact)
        artifacts.append(artifact)
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()
    seed_shape(store, frames)

    complete_job = store.create_generation_job(GenerationJob(frames[0].key, JobState.GENERATED, "npc_rle", "mock", job_id="complete"))
    store.add_candidate(Candidate(complete_job, str(artifacts[0]), metadata={"animation_frames": {"0": str(artifacts[0]), "1": str(artifacts[1])}}, candidate_id="complete"))
    complete = run_validation("complete", store)

    complete_boxes = next(check for check in complete.checks if check.name == "animation_boxes")
    assert complete.passed
    assert complete_boxes.metrics["expected_frame_count"] == 2
    assert complete_boxes.metrics["actual_frame_count"] == 2

    missing_job = store.create_generation_job(GenerationJob(frames[0].key, JobState.GENERATED, "npc_rle", "mock", job_id="missing"))
    store.add_candidate(Candidate(missing_job, str(artifacts[0]), metadata={"animation_frames": {"0": str(artifacts[0])}}, candidate_id="missing"))
    missing = run_validation("missing", store)
    extra_job = store.create_generation_job(GenerationJob(frames[0].key, JobState.GENERATED, "npc_rle", "mock", job_id="extra"))
    store.add_candidate(Candidate(extra_job, str(artifacts[0]), metadata={"animation_frames": {"0": str(artifacts[0]), "1": str(artifacts[1]), "2": str(artifacts[1])}}, candidate_id="extra"))
    extra = run_validation("extra", store)

    assert not missing.passed
    assert not extra.passed
    assert store.job_state(missing_job) is JobState.REJECTED
    assert store.job_state(extra_job) is JobState.REJECTED


def test_building_runner_uses_candidate_atlas_layout_for_non_midpoint_seams(tmp_path: Path) -> None:
    source = tmp_path / "building-source.png"
    Image.new("RGBA", (24, 8), (0, 0, 0, 255)).save(source)
    frame = FrameRecord(
        FrameKey("b" * 64, 0, 8, 0), 24, 8,
        metadata={"asset_type": "building_combo", "rgba_preview_path": str(source), "offset": [0, 0], "scale": 6},
    )
    artifact = tmp_path / "building.png"
    with Image.open(source) as image:
        atlas = image.resize((144, 48), Image.Resampling.NEAREST)
    for y in range(48):
        atlas.putpixel((47, y), (255, 255, 255, 255))
    atlas.save(artifact)
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()
    job_id = seed(store, frame)
    store.add_candidate(Candidate(job_id, str(artifact), metadata={"atlas_layout": {"columns": 3, "rows": 1, "tile_width": 8, "tile_height": 8, "scale": 6}, "seam_threshold": 0.1}, candidate_id="building"))

    report = run_validation("building", store)

    seams = next(check for check in report.checks if check.name == "seams")
    assert not report.passed
    assert seams.metrics["vertical_boundary_count"] == 2
    assert seams.metrics["max_mean_delta"] == 191.25


def test_validation_persistence_rolls_back_when_generated_compare_and_set_fails(tmp_path: Path) -> None:
    frame = make_frame(tmp_path)
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()
    job_id = seed(store, frame)
    store.add_candidate(Candidate(job_id, "candidate.png", candidate_id="candidate"))
    store.transition_job(job_id, JobState.GENERATED, JobState.REJECTED)

    with pytest.raises(InvalidStateTransition):
        store.add_validation_and_transition(
            ValidationResult("candidate", True, {"dimensions": {"status": "passed"}}),
            JobState.GENERATED,
            JobState.VALIDATED,
        )

    assert store._connection.execute("SELECT COUNT(*) FROM validation_results").fetchone()[0] == 0
    assert store.job_state(job_id) is JobState.REJECTED
