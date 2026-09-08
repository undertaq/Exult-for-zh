from pathlib import Path

import pytest

from graph_remaster.db import AssetStore
from graph_remaster.errors import InvalidStateTransition
from graph_remaster.hashing import sha256_file
from graph_remaster.models import (
    Candidate,
    FrameKey,
    FrameRecord,
    GenerationJob,
    ReviewDecision,
    ShapeRecord,
    SourceArchive,
    ValidationResult,
)


def make_job(state: str = "QUEUED") -> GenerationJob:
    return GenerationJob(
        frame=FrameKey("a" * 64, 0, 12, 3),
        state=state,
        profile="character",
        backend="mock",
        parameters={"seed": 7},
    )


def test_job_transition_is_compare_and_set(tmp_path: Path) -> None:
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()
    job_id = store.create_generation_job(make_job())

    store.transition_job(job_id, "QUEUED", "GENERATED")

    with pytest.raises(InvalidStateTransition):
        store.transition_job(job_id, "QUEUED", "VALIDATED")


def test_schema_and_migrations_are_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "graph.sqlite3"
    store = AssetStore.open(database)
    store.migrate()
    first_tables = store.table_names()
    first_version = store.schema_version()
    store.close()

    reopened = AssetStore.open(database)
    reopened.migrate()

    assert reopened.table_names() == first_tables
    assert reopened.schema_version() == first_version
    reopened.close()


def test_asset_records_upsert_and_related_records_are_idempotent(tmp_path: Path) -> None:
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()
    key = FrameKey("b" * 64, 1, 2, 3)
    store.upsert_source_archive(SourceArchive(key.archive_sha256, "source.ipf", 10, {"game": "bg"}))
    store.upsert_shape(ShapeRecord(key.archive_sha256, key.archive_index, key.shape_id, 10, 20))
    store.upsert_frame(FrameRecord(key, 10, 20))
    job_id = store.create_generation_job(GenerationJob(key, "QUEUED", "prop", "mock", {"seed": 1}, "job"))
    candidate_id = store.add_candidate(Candidate(job_id, "candidate.png", candidate_id="candidate"))
    store.add_validation(ValidationResult(candidate_id, True, {"size": True}))
    store.add_review(ReviewDecision(candidate_id, "APPROVE", "tester", "ok"))

    store.upsert_source_archive(SourceArchive(key.archive_sha256, "source.ipf", 11))
    store.upsert_shape(ShapeRecord(key.archive_sha256, key.archive_index, key.shape_id, 12, 20))
    store.upsert_frame(FrameRecord(key, 12, 20, False))
    store.add_candidate(Candidate(job_id, "candidate-2.png", candidate_id=candidate_id))

    assert store._connection.execute("SELECT COUNT(*) FROM source_archives").fetchone()[0] == 1
    assert store._connection.execute("SELECT COUNT(*) FROM shapes").fetchone()[0] == 1
    assert store._connection.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == 1
    assert store._connection.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 1
    assert store._connection.execute("SELECT passed FROM validation_results").fetchone()[0] == 1
    assert store._connection.execute("SELECT decision FROM review_decisions").fetchone()[0] == "APPROVE"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("DISCOVERED", "EXTRACTED"),
        ("EXTRACTED", "CONTROLS_READY"),
        ("CONTROLS_READY", "QUEUED"),
        ("QUEUED", "GENERATED"),
        ("GENERATED", "VALIDATED"),
        ("GENERATED", "RESOURCE_FAILED"),
        ("GENERATED", "REJECTED"),
        ("VALIDATED", "APPROVED"),
        ("APPROVED", "PACKAGED"),
        ("REJECTED", "QUEUED"),
    ],
)
def test_allowed_job_transitions(tmp_path: Path, old: str, new: str) -> None:
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()
    job_id = store.create_generation_job(make_job(old))
    store.transition_job(job_id, old, new)
    assert store._connection.execute(
        "SELECT state FROM generation_jobs WHERE job_id = ?", (job_id,)
    ).fetchone()[0] == new


def test_sha256_file_hashes_binary_content(tmp_path: Path) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"graph-remaster")

    assert sha256_file(payload) == "b6e74efc6d77b293ad1a02ab7651e026116afa2c605bbe05a1641da86d576f8b"
