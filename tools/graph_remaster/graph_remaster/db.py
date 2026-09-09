"""SQLite-backed canonical state store for remaster assets and jobs."""

from __future__ import annotations

import json
import sqlite3
from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .errors import InvalidStateTransition, MigrationError
from .models import (
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

SCHEMA_VERSION = 3
ALLOWED_TRANSITIONS = {
    JobState.DISCOVERED: {JobState.EXTRACTED},
    JobState.EXTRACTED: {JobState.CONTROLS_READY},
    JobState.CONTROLS_READY: {JobState.QUEUED},
    JobState.QUEUED: {JobState.GENERATED},
    JobState.GENERATED: {JobState.VALIDATED, JobState.RESOURCE_FAILED, JobState.REJECTED},
    JobState.VALIDATED: {JobState.APPROVED},
    JobState.APPROVED: {JobState.PACKAGED},
    JobState.REJECTED: {JobState.QUEUED},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _job_state(value: JobState | str) -> JobState:
    try:
        return value if isinstance(value, JobState) else JobState(value)
    except (TypeError, ValueError) as exc:
        raise InvalidStateTransition(f"unknown job state: {value!r}") from exc


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

    def commit(self) -> None:
        """Commit pending writes, allowing bulk stages to control batching."""

        self._connection.commit()

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
                updated_at TEXT NOT NULL,
                FOREIGN KEY (archive_sha256, archive_index, shape_id, frame_id)
                    REFERENCES frames(archive_sha256, archive_index, shape_id, frame_id)
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
            CREATE TABLE IF NOT EXISTS generation_job_errors (
                error_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                error TEXT NOT NULL,
                traceback_text TEXT NOT NULL,
                report_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES generation_jobs(job_id)
            );
            """,
        )

        version = self.schema_version()
        if version > SCHEMA_VERSION:
            raise MigrationError(
                f"database schema version {version} is newer than supported version {SCHEMA_VERSION}"
            )
        if version == 1:
            self._migrate_v1_to_v2()
            version = 2
        if version == 2:
            self._migrate_v2_to_v3()
        self._connection.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
        self._connection.commit()

    def _migrate_v2_to_v3(self) -> None:
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS generation_job_errors (
            error_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            error TEXT NOT NULL,
            traceback_text TEXT NOT NULL,
            report_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES generation_jobs(job_id)
            )"""
        )

    def _migrate_v1_to_v2(self) -> None:
        if self._has_generation_job_frame_fk():
            return

        orphan = self._connection.execute(
            """SELECT job_id, archive_sha256, archive_index, shape_id, frame_id
            FROM generation_jobs AS jobs
            WHERE NOT EXISTS (
                SELECT 1 FROM frames
                WHERE frames.archive_sha256 = jobs.archive_sha256
                  AND frames.archive_index = jobs.archive_index
                  AND frames.shape_id = jobs.shape_id
                  AND frames.frame_id = jobs.frame_id
            )
            ORDER BY job_id
            LIMIT 1"""
        ).fetchone()
        if orphan is not None:
            raise MigrationError(
                "cannot migrate schema version 1: orphaned generation_jobs row "
                f"{orphan[0]!r} references frame "
                f"({orphan[1]}, {orphan[2]}, {orphan[3]}, {orphan[4]})"
            )

        self._connection.execute("PRAGMA foreign_keys = OFF")
        try:
            self._connection.execute("BEGIN")
            self._connection.execute(self._generation_jobs_table_sql("generation_jobs_v2"))
            self._connection.execute(
                """INSERT INTO generation_jobs_v2
                SELECT job_id, archive_sha256, archive_index, shape_id, frame_id,
                       state, profile, backend, parameters_json, created_at, updated_at
                FROM generation_jobs"""
            )
            self._connection.execute("DROP TABLE generation_jobs")
            self._connection.execute("ALTER TABLE generation_jobs_v2 RENAME TO generation_jobs")
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        finally:
            self._connection.execute("PRAGMA foreign_keys = ON")

    def _has_generation_job_frame_fk(self) -> bool:
        foreign_keys = self._connection.execute(
            "PRAGMA foreign_key_list(generation_jobs)"
        ).fetchall()
        return {
            (row[3], row[4])
            for row in foreign_keys
            if row[2] == "frames"
        } == {
            ("archive_sha256", "archive_sha256"),
            ("archive_index", "archive_index"),
            ("shape_id", "shape_id"),
            ("frame_id", "frame_id"),
        }

    @staticmethod
    def _generation_jobs_table_sql(name: str) -> str:
        return f"""CREATE TABLE {name} (
            job_id TEXT PRIMARY KEY,
            archive_sha256 TEXT NOT NULL,
            archive_index INTEGER NOT NULL,
            shape_id INTEGER NOT NULL,
            frame_id INTEGER NOT NULL,
            state TEXT NOT NULL,
            profile TEXT NOT NULL,
            backend TEXT NOT NULL,
            parameters_json TEXT NOT NULL DEFAULT '{{}}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (archive_sha256, archive_index, shape_id, frame_id)
                REFERENCES frames(archive_sha256, archive_index, shape_id, frame_id)
        )"""

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

    def get_source_archive(self, archive_sha256: str) -> SourceArchive | None:
        row = self._connection.execute(
            "SELECT archive_sha256, path, size_bytes, metadata_json FROM source_archives WHERE archive_sha256 = ?",
            (archive_sha256,),
        ).fetchone()
        return None if row is None else SourceArchive(row[0], row[1], row[2], json.loads(row[3]))

    def list_shapes(self, archive_sha256: str) -> list[ShapeRecord]:
        rows = self._connection.execute(
            """SELECT archive_sha256, archive_index, shape_id, width, height, frame_count, metadata_json
            FROM shapes WHERE archive_sha256 = ? ORDER BY archive_index, shape_id""",
            (archive_sha256,),
        ).fetchall()
        return [ShapeRecord(*row[:6], json.loads(row[6])) for row in rows]

    def list_frames(self, shape: ShapeRecord) -> list[FrameRecord]:
        rows = self._connection.execute(
            """SELECT frame_id, width, height, has_alpha, metadata_json FROM frames
            WHERE archive_sha256 = ? AND archive_index = ? AND shape_id = ? ORDER BY frame_id""",
            shape.key,
        ).fetchall()
        return [
            FrameRecord(
                FrameKey(shape.archive_sha256, shape.archive_index, shape.shape_id, row[0]),
                row[1], row[2], bool(row[3]), json.loads(row[4]),
            )
            for row in rows
        ]

    def list_all_frames(self, archive_sha256: str | None = None) -> list[FrameRecord]:
        query = """SELECT archive_sha256, archive_index, shape_id, frame_id, width, height,
        has_alpha, metadata_json FROM frames"""
        parameters: tuple[object, ...] = ()
        if archive_sha256 is not None:
            query += " WHERE archive_sha256 = ?"
            parameters = (archive_sha256,)
        rows = self._connection.execute(
            query + " ORDER BY archive_sha256, archive_index, shape_id, frame_id", parameters
        ).fetchall()
        return [
            FrameRecord(FrameKey(*row[:4]), row[4], row[5], bool(row[6]), json.loads(row[7]))
            for row in rows
        ]

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

    def upsert_mask(
        self, frame: FrameKey, kind: str, artifact_sha256: str, artifact_path: Path,
        metadata: dict[str, object] | None = None, *, commit: bool = True,
    ) -> None:
        self._upsert_frame_artifact(
            "masks", "mask_id", frame, kind, artifact_sha256, artifact_path, metadata, commit=commit,
        )

    def upsert_control_map(
        self, frame: FrameKey, kind: str, artifact_sha256: str, artifact_path: Path,
        metadata: dict[str, object] | None = None, *, commit: bool = True,
    ) -> None:
        self._upsert_frame_artifact(
            "control_maps", "control_map_id", frame, kind, artifact_sha256, artifact_path, metadata, commit=commit,
        )

    def _upsert_frame_artifact(
        self, table: str, id_column: str, frame: FrameKey, kind: str, artifact_sha256: str,
        artifact_path: Path, metadata: dict[str, object] | None, *, commit: bool = True,
    ) -> None:
        record_id = sha256(f"{frame!r}:{kind}:{artifact_sha256}".encode()).hexdigest()
        self._connection.execute(
            f"""INSERT INTO {table} ({id_column}, archive_sha256, archive_index, shape_id, frame_id,
            kind, artifact_path, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(archive_sha256, archive_index, shape_id, frame_id, kind) DO UPDATE SET
            {id_column}=excluded.{id_column}, artifact_path=excluded.artifact_path,
            metadata_json=excluded.metadata_json""",
            (record_id, frame.archive_sha256, frame.archive_index, frame.shape_id, frame.frame_id,
             kind, str(artifact_path), _json(metadata or {})),
        )
        if commit:
            self._connection.commit()

    def create_generation_job(self, request: GenerationJob) -> str:
        state = _job_state(request.state)
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
             state.value, request.profile, request.backend, _json(request.parameters), now, now),
        )
        self._connection.commit()
        return job_id

    def get_generation_job(self, job_id: str) -> GenerationJob:
        """Load one persisted job for scheduler dispatch."""

        row = self._connection.execute(
            """SELECT archive_sha256, archive_index, shape_id, frame_id, state, profile,
            backend, parameters_json, job_id FROM generation_jobs WHERE job_id = ?""",
            (job_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown generation job {job_id!r}")
        return GenerationJob(
            FrameKey(*row[:4]), row[4], row[5], row[6], json.loads(row[7]), row[8]
        )

    def get_frame(self, key: FrameKey) -> FrameRecord:
        """Load one persisted frame required to reconstruct a worker request."""

        row = self._connection.execute(
            """SELECT width, height, has_alpha, metadata_json FROM frames
            WHERE archive_sha256 = ? AND archive_index = ? AND shape_id = ? AND frame_id = ?""",
            (key.archive_sha256, key.archive_index, key.shape_id, key.frame_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown frame {key!r}")
        return FrameRecord(key, row[0], row[1], bool(row[2]), json.loads(row[3]))

    def list_shape_frames(self, key: FrameKey) -> list[FrameRecord]:
        """Load every frame in one shape, ordered for animation validation."""

        rows = self._connection.execute(
            """SELECT frame_id, width, height, has_alpha, metadata_json FROM frames
            WHERE archive_sha256 = ? AND archive_index = ? AND shape_id = ? ORDER BY frame_id""",
            (key.archive_sha256, key.archive_index, key.shape_id),
        ).fetchall()
        return [
            FrameRecord(
                FrameKey(key.archive_sha256, key.archive_index, key.shape_id, row[0]),
                row[1], row[2], bool(row[3]), json.loads(row[4]),
            )
            for row in rows
        ]

    def transition_job(
        self, job_id: str, expected: JobState | str, new: JobState | str
    ) -> None:
        expected_state = _job_state(expected)
        new_state = _job_state(new)
        if new_state not in ALLOWED_TRANSITIONS.get(expected_state, set()):
            raise InvalidStateTransition(f"invalid job transition {expected} -> {new}")
        cursor = self._connection.execute(
            "UPDATE generation_jobs SET state = ?, updated_at = ? WHERE job_id = ? AND state = ?",
            (new_state.value, _now(), job_id, expected_state.value),
        )
        if cursor.rowcount != 1:
            self._connection.rollback()
            raise InvalidStateTransition(
                f"job {job_id} is not in expected state {expected_state.value}"
            )
        self._connection.commit()

    def job_state(self, job_id: str) -> JobState:
        """Return the current persisted state for a generation job."""

        row = self._connection.execute(
            "SELECT state FROM generation_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown generation job {job_id!r}")
        return _job_state(row[0])

    def record_job_error(
        self, job_id: str, error: str, traceback_text: str, report_path: str
    ) -> str:
        """Persist a terminal worker error and its offline diagnostic report path."""

        error_id = str(uuid4())
        self._connection.execute(
            """INSERT INTO generation_job_errors
            (error_id, job_id, error, traceback_text, report_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (error_id, job_id, error, traceback_text, report_path, _now()),
        )
        self._connection.commit()
        return error_id

    def get_job_error(self, job_id: str) -> dict[str, str] | None:
        """Return the most recent scheduler error for a job, if it has one."""

        row = self._connection.execute(
            """SELECT error, traceback_text, report_path FROM generation_job_errors
            WHERE job_id = ? ORDER BY created_at DESC, error_id DESC LIMIT 1""",
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        return {"error": row[0], "traceback": row[1], "report_path": row[2]}

    def job_parameters(self, job_id: str) -> dict[str, object]:
        """Return the persisted generation parameters and scheduler provenance."""

        row = self._connection.execute(
            "SELECT parameters_json FROM generation_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown generation job {job_id!r}")
        return json.loads(row[0])

    def record_job_metadata(self, job_id: str, metadata: dict[str, object]) -> None:
        """Merge scheduler provenance into a job without discarding generation inputs."""

        parameters = self.job_parameters(job_id)
        parameters.update(metadata)
        cursor = self._connection.execute(
            "UPDATE generation_jobs SET parameters_json = ?, updated_at = ? WHERE job_id = ?",
            (_json(parameters), _now(), job_id),
        )
        if cursor.rowcount != 1:
            self._connection.rollback()
            raise KeyError(f"unknown generation job {job_id!r}")
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

    def get_candidate(self, candidate_id: str) -> Candidate:
        """Load one candidate and its immutable generation-job link."""

        row = self._connection.execute(
            """SELECT job_id, artifact_path, artifact_sha256, metadata_json, candidate_id
            FROM candidates WHERE candidate_id = ?""",
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown candidate {candidate_id!r}")
        return Candidate(row[0], row[1], row[2], json.loads(row[3]), row[4])

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

    def add_validation_and_transition(
        self, result: ValidationResult, expected: JobState | str, new: JobState | str
    ) -> None:
        """Persist validation and its GENERATED terminal state as one transaction."""

        expected_state = _job_state(expected)
        new_state = _job_state(new)
        if new_state not in ALLOWED_TRANSITIONS.get(expected_state, set()):
            raise InvalidStateTransition(f"invalid job transition {expected} -> {new}")
        with self._connection:
            self._connection.execute(
                """INSERT INTO validation_results
                (candidate_id, passed, checks_json, errors_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET passed=excluded.passed,
                checks_json=excluded.checks_json, errors_json=excluded.errors_json""",
                (result.candidate_id, int(result.passed), _json(result.checks), _json(result.errors), _now()),
            )
            cursor = self._connection.execute(
                """UPDATE generation_jobs SET state = ?, updated_at = ?
                WHERE job_id = (SELECT job_id FROM candidates WHERE candidate_id = ?) AND state = ?""",
                (new_state.value, _now(), result.candidate_id, expected_state.value),
            )
            if cursor.rowcount != 1:
                raise InvalidStateTransition(
                    f"candidate {result.candidate_id!r} job is not in expected state {expected_state.value}"
                )

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
