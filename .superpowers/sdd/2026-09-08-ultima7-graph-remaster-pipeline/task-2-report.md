# Task 2 Report: Asset graph models and SQLite state store

## Outcome

Implemented the Task 2 asset graph persistence layer under
`tools/graph_remaster/`. SQLite is the canonical state store; no renderer or
game data files were changed, and Task 1 configuration behavior remains
unchanged.

## Public interfaces

- `models.py` provides `FrameKey`, `SourceArchive`, `ShapeRecord`,
  `FrameRecord`, `GenerationJob`, `Candidate`, `ValidationResult`, and
  `ReviewDecision` immutable records.
- `db.py` provides `AssetStore.open`, `migrate`, all requested upsert/add
  methods, and compare-and-set `transition_job`.
- `hashing.py` provides `sha256_file(path: Path) -> str` using streaming
  1 MiB reads.
- `errors.py` now also exposes `InvalidStateTransition` for rejected job
  transitions.

## Schema

`AssetStore.migrate()` creates an idempotent schema version table and the
required `source_archives`, `shapes`, `frames`, `masks`, `control_maps`,
`generation_jobs`, `candidates`, `validation_results`, `review_decisions`, and
`package_entries` tables. Composite primary/unique keys preserve source,
shape, and frame identity. Foreign keys are enabled on every connection.
Metadata and validation details are serialized as deterministic JSON text;
timestamps are UTC ISO-8601 strings.

Upserts are conflict-safe for source archives, shapes, frames, jobs,
candidates, validations, and reviews. Reopening a database and rerunning
migrations preserves the schema version and table set.

## State transitions

The store permits exactly the requested edges:

`DISCOVERED -> EXTRACTED -> CONTROLS_READY -> QUEUED -> GENERATED ->
VALIDATED -> APPROVED -> PACKAGED`, plus `GENERATED -> RESOURCE_FAILED`,
`GENERATED -> REJECTED`, and `REJECTED -> QUEUED`.

Each transition validates the requested edge and updates only when the stored
job still has the expected state. A stale expected state, missing job, or
illegal edge raises `InvalidStateTransition`.

## Verification evidence

- Focused and existing package tests: `24 passed in 29.14s`.
- Bytecode compilation: `tools/graph_remaster/.venv/bin/python -m compileall -q
  tools/graph_remaster/graph_remaster` exited `0`.
- `git diff --check` completed without whitespace errors.

The test suite covers migration idempotency, compare-and-set behavior, every
legal transition, upsert idempotency, related-record persistence, JSON-backed
fields, and deterministic SHA-256 hashing.

## Reviewer-fix report

Addressed the two Task 2 review findings without changing the migration or
upsert idempotency contract:

- Restored the composite foreign key from
  `generation_jobs(archive_sha256, archive_index, shape_id, frame_id)` to the
  corresponding `frames` key. CAS fixtures now create source archive, shape,
  and frame rows first; a generation job referring to a missing frame raises
  SQLite `IntegrityError`.
- Added the public `JobState` string enum with all lifecycle states and
  exported it from both `graph_remaster.models` and the package root. Job
  creation and CAS transitions coerce valid strings to the enum and reject
  arbitrary initial, expected, or target values with `InvalidStateTransition`.

Added regressions for missing-frame rejection, public enum exposure, valid
enum/string CAS values, and unknown state rejection. The package suite at
that point passed with `31 passed in 42.23s`; bytecode compilation exited `0`, and
`git diff --check` reports no whitespace errors.

## Migration re-review fix

Implemented a real versioned migration from schema version 1 to version 2.
`SCHEMA_VERSION` is now `2`; fresh databases create the composite
`generation_jobs` foreign key directly, while version-1 databases are upgraded
by rebuilding that table inside a transaction and preserving all columns and
rows.

Before rebuilding, migration checks every legacy job against `frames`. If any
orphan exists, migration raises `MigrationError` with the job ID and referenced
frame key, leaves schema version 1, and leaves the legacy table/data intact.
No orphan rows are silently deleted or rewritten. Valid version-1 databases
upgrade to version 2 and a second migration is a no-op.

Added regression fixtures for a base-format version-1 database, valid-row
preservation, composite-FK inspection, rerun idempotency, and deterministic
orphan rejection, and preservation of an existing candidate row that references
the rebuilt jobs table. Focused Task 2 verification: `23 passed in 43.76s`.
Final package verification after these changes: `33 passed in 40.69s`;
compilation exited `0` and `git diff --check` passed.
