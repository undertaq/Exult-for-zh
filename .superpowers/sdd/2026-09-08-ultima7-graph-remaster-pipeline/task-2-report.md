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
