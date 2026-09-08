"""SQLite-backed canonical state store for remaster assets and jobs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .errors import InvalidStateTransition
from .models import (
    Candidate,
    FrameRecord,
    GenerationJob,
    ReviewDecision,
    ShapeRecord,
    SourceArchive,
    ValidationResult,
)

SCHEMA_VERSION = 1
ALLOWED_TRANSITIONS = {
    "DISCOVERED": {"EXTRACTED"},
    "EXTRACTED": {"CONTROLS_READY"},
    "CONTROLS_READY": {"QUEUED"},
    "QUEUED": {"GENERATED"},
    "GENERATED": {"VALIDATED", "RESOURCE_FAILED", "REJECTED"},
    "VALIDATED": {"APPROVED"},
    "APPROVED": {"PACKAGED"},
    "REJECTED": {"QUEUED"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class AssetStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    def open(cls, path: Path) -> "AssetStore":
        database = Path(path)
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database)
        connection.execute("PRAGMA foreign_keys = ON")
        return cls(connection)

    def close(self) -> None:
        self._connection.close()

    def migrate(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            );
            INSERT INTO schema_version(version)
                SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM schema_version);

            CREATE TABLE IF NOT EXISTS source_archives (
                archive_sha256 TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS shapes (
                archive_sha256 TEXT NOT NULL,
                archive_index INTEGER NOT NULL,
                shape_id INTEGER NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                frame_count INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (archive_sha256, archive_index, shape_id),
                FOREIGN KEY (archive_sha256) REFERENCES source_archives(archive_sha256)
            );
            CREATE TABLE IF NOT EXISTS frames (
                archive_sha256 TEXT NOT NULL,
                archive_index INTEGER NOT NULL,
                shape_id INTEGER NOT NULL,
                frame_id INTEGER NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                has_alpha INTEGER NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (archive_sha256, archive_index, shape_id, frame_id),
                FOREIGN KEY (archive_sha256, archive_index, shape_id)
                    REFERENCES shapes(archive_sha256, archive_index, shape_id)
            );
            CREATE TABLE IF NOT EXISTS masks (
                mask_id TEXT PRIMARY KEY,
                archive_sha256 TEXT NOT NULL,
                archive_index INTEGER NOT NULL,
                shape_id INTEGER NOT NULL,
                frame_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE (archive_sha256, archive_index, shape_id, frame_id, kind),
                FOREIGN KEY (archive_sha256, archive_index, shape_id, frame_id)
                    REFERENCES frames(archive_sha256, archive_index, shape_id, frame_id)
            );
            CREATE TABLE IF NOT EXISTS control_maps (
                control_map_id TEXT PRIMARY KEY,
                archive_sha256 TEXT NOT NULL,
                archive_index INTEGER NOT NULL,
                shape_id INTEGER NOT NULL,
                frame_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE (archive_sha256, archive_index, shape_id, frame_id, kind),
                FOREIGN KEY (archive_sha256, archive_index, shape_id, frame_id)
                    REFERENCES frames(archive_sha256, archive_index, shape_id, frame_id)
            );
            CREATE TABLE IF NOT EXISTS generation_jobs (
                job_id TEXT PRIMARY KEY,
                archive_sha256 TEXT NOT NULL,
                archive_index INTEGER NOT NULL,
                shape_id INTEGER NOT NULL,
                frame_id INTEGER NOT NULL,
                state TEXT NOT NULL,
                profile TEXT NOT NULL,
                backend TEXT NOT NULL,
                parameters_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS candidates (
                candidate_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                artifact_sha256 TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES generation_jobs(job_id)
            );
            CREATE TABLE IF NOT EXISTS validation_results (
                candidate_id TEXT PRIMARY KEY,
                passed INTEGER NOT NULL,
                checks_json TEXT NOT NULL DEFAULT '{}',
                errors_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id)
            );
            CREATE TABLE IF NOT EXISTS review_decisions (
                candidate_id TEXT PRIMARY KEY,
                decision TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                notes TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id)
            );
            CREATE TABLE IF NOT EXISTS package_entries (
                entry_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                package_path TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE (candidate_id, package_path),
                FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id)
            );
            UPDATE schema_version SET version = 1;
            """,
        )
        self._connection.commit()

    def schema_version(self) -> int:
        return int(self._connection.execute("SELECT version FROM schema_version").fetchone()[0])

    def table_names(self) -> tuple[str, ...]:
        rows = self._connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        return tuple(row[0] for row in rows)

    def upsert_source_archive(self, record: SourceArchive) -> None:
        now = _now()
        self._connection.execute(
            """INSERT INTO source_archives
            (archive_sha256, path, size_bytes, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(archive_sha256) DO UPDATE SET path=excluded.path,
            size_bytes=excluded.size_bytes, metadata_json=excluded.metadata_json,
            updated_at=excluded.updated_at""",
            (record.archive_sha256, str(record.path), record.size_bytes, _json(record.metadata), now, now),
        )
        self._connection.commit()

    def upsert_shape(self, record: ShapeRecord) -> None:
        now = _now()
        self._connection.execute(
            """INSERT INTO shapes
            (archive_sha256, archive_index, shape_id, width, height, frame_count,
             metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(archive_sha256, archive_index, shape_id) DO UPDATE SET
            width=excluded.width, height=excluded.height, frame_count=excluded.frame_count,
            metadata_json=excluded.metadata_json, updated_at=excluded.updated_at""",
            (record.archive_sha256, record.archive_index, record.shape_id, record.width, record.height,
             record.frame_count, _json(record.metadata), now, now),
        )
        self._connection.commit()

    def upsert_frame(self, record: FrameRecord) -> None:
        key = record.key
        now = _now()
        self._connection.execute(
            """INSERT INTO frames
            (archive_sha256, archive_index, shape_id, frame_id, width, height,
             has_alpha, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(archive_sha256, archive_index, shape_id, frame_id) DO UPDATE SET
            width=excluded.width, height=excluded.height, has_alpha=excluded.has_alpha,
            metadata_json=excluded.metadata_json, updated_at=excluded.updated_at""",
            (key.archive_sha256, key.archive_index, key.shape_id, key.frame_id,
             record.width, record.height, int(record.has_alpha), _json(record.metadata), now, now),
        )
        self._connection.commit()

    def create_generation_job(self, request: GenerationJob) -> str:
        job_id = request.job_id or str(uuid4())
        key = request.frame
        now = _now()
        self._connection.execute(
            """INSERT INTO generation_jobs
            (job_id, archive_sha256, archive_index, shape_id, frame_id, state, profile,
             backend, parameters_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET state=excluded.state, profile=excluded.profile,
            backend=excluded.backend, parameters_json=excluded.parameters_json,
            updated_at=excluded.updated_at""",
            (job_id, key.archive_sha256, key.archive_index, key.shape_id, key.frame_id,
             request.state, request.profile, request.backend, _json(request.parameters), now, now),
        )
        self._connection.commit()
        return job_id

    def transition_job(self, job_id: str, expected: str, new: str) -> None:
        if new not in ALLOWED_TRANSITIONS.get(expected, set()):
            raise InvalidStateTransition(f"invalid job transition {expected} -> {new}")
        cursor = self._connection.execute(
            "UPDATE generation_jobs SET state = ?, updated_at = ? WHERE job_id = ? AND state = ?",
            (new, _now(), job_id, expected),
        )
        if cursor.rowcount != 1:
            self._connection.rollback()
            raise InvalidStateTransition(f"job {job_id} is not in expected state {expected}")
        self._connection.commit()

    def add_candidate(self, candidate: Candidate) -> str:
        candidate_id = candidate.candidate_id or str(uuid4())
        self._connection.execute(
            """INSERT INTO candidates
            (candidate_id, job_id, artifact_path, artifact_sha256, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(candidate_id) DO UPDATE SET artifact_path=excluded.artifact_path,
            artifact_sha256=excluded.artifact_sha256, metadata_json=excluded.metadata_json""",
            (candidate_id, candidate.job_id, candidate.artifact_path, candidate.artifact_sha256,
             _json(candidate.metadata), _now()),
        )
        self._connection.commit()
        return candidate_id

    def add_validation(self, result: ValidationResult) -> None:
        self._connection.execute(
            """INSERT INTO validation_results
            (candidate_id, passed, checks_json, errors_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(candidate_id) DO UPDATE SET passed=excluded.passed,
            checks_json=excluded.checks_json, errors_json=excluded.errors_json""",
            (result.candidate_id, int(result.passed), _json(result.checks), _json(result.errors), _now()),
        )
        self._connection.commit()

    def add_review(self, decision: ReviewDecision) -> None:
        self._connection.execute(
            """INSERT INTO review_decisions
            (candidate_id, decision, reviewer, notes, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(candidate_id) DO UPDATE SET decision=excluded.decision,
            reviewer=excluded.reviewer, notes=excluded.notes""",
            (decision.candidate_id, decision.decision, decision.reviewer, decision.notes, _now()),
        )
        self._connection.commit()
