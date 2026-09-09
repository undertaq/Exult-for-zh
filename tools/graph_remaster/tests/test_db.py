from pathlib import Path
import sqlite3

import pytest

from graph_remaster.db import AssetStore
from graph_remaster.errors import InvalidStateTransition, MigrationError
from graph_remaster.hashing import sha256_file
from graph_remaster import JobState as PublicJobState
from graph_remaster.models import (
    Candidate,
    FrameKey,
    FrameRecord,
    GenerationJob,
    JobState,
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


def seed_frame(store: AssetStore, key: FrameKey) -> None:
    store.upsert_source_archive(SourceArchive(key.archive_sha256, "source.ipf"))
    store.upsert_shape(ShapeRecord(key.archive_sha256, key.archive_index, key.shape_id, 10, 20))
    store.upsert_frame(FrameRecord(key, 10, 20))


def make_legacy_v1_database(path: Path, *, orphan: bool = False) -> FrameKey:
    key = FrameKey("c" * 64, 2, 7, 4)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version VALUES (1);
        CREATE TABLE source_archives (
            archive_sha256 TEXT PRIMARY KEY, path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL DEFAULT 0, metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE shapes (
            archive_sha256 TEXT NOT NULL, archive_index INTEGER NOT NULL,
            shape_id INTEGER NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
            frame_count INTEGER NOT NULL DEFAULT 0, metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY (archive_sha256, archive_index, shape_id)
        );
        CREATE TABLE frames (
            archive_sha256 TEXT NOT NULL, archive_index INTEGER NOT NULL,
            shape_id INTEGER NOT NULL, frame_id INTEGER NOT NULL,
            width INTEGER NOT NULL, height INTEGER NOT NULL, has_alpha INTEGER NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (archive_sha256, archive_index, shape_id, frame_id)
        );
        CREATE TABLE generation_jobs (
            job_id TEXT PRIMARY KEY, archive_sha256 TEXT NOT NULL,
            archive_index INTEGER NOT NULL, shape_id INTEGER NOT NULL, frame_id INTEGER NOT NULL,
            state TEXT NOT NULL, profile TEXT NOT NULL, backend TEXT NOT NULL,
            parameters_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE candidates (
            candidate_id TEXT PRIMARY KEY, job_id TEXT NOT NULL,
            artifact_path TEXT NOT NULL, artifact_sha256 TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES generation_jobs(job_id)
        );
        """
    )
    connection.execute(
        "INSERT INTO source_archives VALUES (?, ?, 0, '{}', 't', 't')",
        (key.archive_sha256, "source.ipf"),
    )
    connection.execute(
        "INSERT INTO shapes VALUES (?, ?, ?, 10, 20, 1, '{}', 't', 't')",
        (key.archive_sha256, key.archive_index, key.shape_id),
    )
    if not orphan:
        connection.execute(
            "INSERT INTO frames VALUES (?, ?, ?, ?, 10, 20, 1, '{}', 't', 't')",
            (key.archive_sha256, key.archive_index, key.shape_id, key.frame_id),
        )
    connection.execute(
        "INSERT INTO generation_jobs VALUES (?, ?, ?, ?, ?, 'QUEUED', 'character', 'mock', '{}', 't', 't')",
        ("legacy-job", key.archive_sha256, key.archive_index, key.shape_id, key.frame_id),
    )
    connection.execute(
        "INSERT INTO candidates VALUES ('legacy-candidate', 'legacy-job', 'candidate.png', '', '{}', 't')"
    )
    connection.commit()
    connection.close()
    return key


def test_job_transition_is_compare_and_set(tmp_path: Path) -> None:
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()
    key = FrameKey("a" * 64, 0, 12, 3)
    seed_frame(store, key)
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


def test_migrates_v1_generation_jobs_and_preserves_valid_rows(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    key = make_legacy_v1_database(database)
    store = AssetStore.open(database)

    store.migrate()

    assert store.schema_version() == 3
    row = store._connection.execute(
        "SELECT job_id, state, archive_sha256, archive_index, shape_id, frame_id "
        "FROM generation_jobs"
    ).fetchone()
    assert row == ("legacy-job", "QUEUED", key.archive_sha256, 2, 7, 4)
    assert store._connection.execute("SELECT job_id FROM candidates").fetchone()[0] == "legacy-job"
    store.add_candidate(Candidate("legacy-job", "new-candidate.png", candidate_id="new-candidate"))
    foreign_keys = store._connection.execute(
        "PRAGMA foreign_key_list(generation_jobs)"
    ).fetchall()
    assert {(row[3], row[4]) for row in foreign_keys} == {
        ("archive_sha256", "archive_sha256"),
        ("archive_index", "archive_index"),
        ("shape_id", "shape_id"),
        ("frame_id", "frame_id"),
    }

    store.migrate()
    assert store.schema_version() == 3
    assert store._connection.execute("SELECT COUNT(*) FROM generation_jobs").fetchone()[0] == 1


def test_v1_migration_rejects_orphaned_legacy_jobs_without_loss(tmp_path: Path) -> None:
    database = tmp_path / "orphaned.sqlite3"
    make_legacy_v1_database(database, orphan=True)
    store = AssetStore.open(database)

    with pytest.raises(MigrationError, match="orphaned generation_jobs"):
        store.migrate()

    assert store.schema_version() == 1
    assert store._connection.execute("SELECT COUNT(*) FROM generation_jobs").fetchone()[0] == 1


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


def test_frame_artifact_upserts_can_be_batched(tmp_path: Path) -> None:
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()
    key = FrameKey("d" * 64, 1, 2, 3)
    seed_frame(store, key)

    store.upsert_mask(key, "source", "e" * 64, tmp_path / "source.png", {}, commit=False)
    observer = sqlite3.connect(tmp_path / "graph.sqlite3")
    try:
        assert observer.execute("SELECT COUNT(*) FROM masks").fetchone()[0] == 0
        store.commit()
        assert observer.execute("SELECT COUNT(*) FROM masks").fetchone()[0] == 1
    finally:
        observer.close()
        store.close()


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
    seed_frame(store, FrameKey("a" * 64, 0, 12, 3))
    job_id = store.create_generation_job(make_job(old))
    store.transition_job(job_id, old, new)
    assert store._connection.execute(
        "SELECT state FROM generation_jobs WHERE job_id = ?", (job_id,)
    ).fetchone()[0] == new


def test_generation_job_requires_existing_frame(tmp_path: Path) -> None:
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()

    with pytest.raises(sqlite3.IntegrityError):
        store.create_generation_job(make_job())


@pytest.mark.parametrize("state", ["UNKNOWN", "", "queued"])
def test_generation_job_rejects_unknown_initial_state(tmp_path: Path, state: str) -> None:
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()
    seed_frame(store, FrameKey("a" * 64, 0, 12, 3))

    with pytest.raises(InvalidStateTransition):
        store.create_generation_job(make_job(state))


def test_job_state_is_public_and_valid_transition_arguments_are_coerced(tmp_path: Path) -> None:
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()
    seed_frame(store, FrameKey("a" * 64, 0, 12, 3))
    job_id = store.create_generation_job(GenerationJob(
        FrameKey("a" * 64, 0, 12, 3), JobState.QUEUED
    ))

    store.transition_job(job_id, JobState.QUEUED, JobState.GENERATED)

    assert store._connection.execute(
        "SELECT state FROM generation_jobs WHERE job_id = ?", (job_id,)
    ).fetchone()[0] == JobState.GENERATED.value
    assert PublicJobState is JobState


@pytest.mark.parametrize("expected,new", [("not-a-state", "GENERATED"), ("QUEUED", "not-a-state")])
def test_transition_rejects_unknown_states(
    tmp_path: Path, expected: str, new: str
) -> None:
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()
    seed_frame(store, FrameKey("a" * 64, 0, 12, 3))
    job_id = store.create_generation_job(make_job())

    with pytest.raises(InvalidStateTransition):
        store.transition_job(job_id, expected, new)


def test_sha256_file_hashes_binary_content(tmp_path: Path) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"graph-remaster")

    assert sha256_file(payload) == "b6e74efc6d77b293ad1a02ab7651e026116afa2c605bbe05a1641da86d576f8b"
