from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from graph_remaster.db import AssetStore
from graph_remaster.models import Candidate, FrameKey, FrameRecord, GenerationJob, JobState, ReviewDecision, ShapeRecord, SourceArchive, ValidationResult
from graph_remaster.reports.server import ReviewServer
from graph_remaster.reports.writer import STAGES, write_run_index, write_stage_report


def seed_candidate(tmp_path: Path, *, passed: bool = True) -> tuple[AssetStore, str, str]:
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()
    key = FrameKey("a" * 64, 0, 1, 0)
    store.upsert_source_archive(SourceArchive(key.archive_sha256, "source.vga", 1))
    store.upsert_shape(ShapeRecord(key.archive_sha256, 0, 1, 8, 8, 1))
    store.upsert_frame(FrameRecord(key, 8, 8, metadata={"asset_type": "flat_tile"}))
    job_id = store.create_generation_job(GenerationJob(key, JobState.GENERATED, "flat_tile", "mock", job_id="job"))
    store.add_candidate(Candidate(job_id, str(tmp_path / "candidate.png"), candidate_id="candidate"))
    store.add_validation(ValidationResult("candidate", passed, {"dimensions": {"passed": passed}}))
    store.transition_job(job_id, JobState.GENERATED, JobState.VALIDATED)
    return store, job_id, "candidate"


def test_run_reports_create_index_and_all_relative_stage_pages(tmp_path: Path) -> None:
    store, _, _ = seed_candidate(tmp_path)
    output = tmp_path / "reports" / "run-1"
    index = write_run_index("run-1", output)
    for stage, filename in STAGES:
        path = write_stage_report(stage, "run-1", store, output)
        assert path.name == filename
        assert path.is_file()
    assert index.is_file()
    assert all("https://" not in path.read_text(encoding="utf-8") for path in output.glob("*.html"))
    assert "source_hashes" in (output / "04-generation.html").read_text(encoding="utf-8")
    store.close()


def test_review_server_approves_only_passed_validated_candidate(tmp_path: Path) -> None:
    store, job_id, candidate_id = seed_candidate(tmp_path, passed=True)
    store.close()
    server = ReviewServer(tmp_path / "graph.sqlite3", tmp_path / "reports")
    server.record_review(candidate_id, ReviewDecision(candidate_id, "APPROVE", "tester", "looks good"))
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    assert store.job_state(job_id) is JobState.APPROVED
    assert store._connection.execute("SELECT decision FROM review_decisions").fetchone()[0] == "APPROVE"
    store.close()

    failed_store, failed_job, failed_id = seed_candidate(tmp_path / "failed", passed=False)
    failed_store.close()
    with pytest.raises(ValueError, match="failed candidates"):
        server = ReviewServer(tmp_path / "failed" / "graph.sqlite3", tmp_path / "failed-reports")
        server.record_review(failed_id, ReviewDecision(failed_id, "APPROVE", "tester", "bad"))
    failed_store = AssetStore.open(tmp_path / "failed" / "graph.sqlite3")
    assert failed_store.job_state(failed_job) is JobState.VALIDATED
    failed_store.close()


def test_review_requires_reason_for_retry(tmp_path: Path) -> None:
    store, _, candidate_id = seed_candidate(tmp_path)
    store.close()
    with pytest.raises(ValueError, match="requires a reason"):
        ReviewServer(tmp_path / "graph.sqlite3", tmp_path / "reports").record_review(
            candidate_id, ReviewDecision(candidate_id, "RETRY", "tester", "")
        )
