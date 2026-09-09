# Task 8 — Asset-class validation and state transitions

## Delivered

Implemented deterministic validation under `tools/graph_remaster/graph_remaster/validation/` and wired the existing `validate` CLI stage.

`CheckResult` is the atomic, serializable result model. Every result carries a stable check name, pass/fail status, blocking flag, numeric or descriptive metrics, threshold, and explanation. `ValidationReport` retains every result rather than reducing validation to one boolean.

## Checks

The validation runner always executes the generic checks:

- `rgba`: artifact is stored as canonical RGBA.
- `dimensions`: image dimensions are exactly source dimensions multiplied by the canonical scale of 6.
- `alpha`: every master alpha pixel matches the nearest-neighbour, six-times source alpha silhouette.
- `offset`: the source offset is a two-integer logical-coordinate pair.
- `metadata`: required asset type, source RGBA path, and canonical scale metadata are present and usable.

Asset-specific checks are selected from the frame asset type:

- `flat_tile` adds `tile_grid`, requiring source tiles of 8×8, scale 6, and exact 48×48 aligned cells. This preserves the canonical six-times/48×48 rule.
- `npc_rle` adds `animation_boxes`, comparing foreground alpha boxes and frame count against a configurable (default 2px) drift tolerance.
- `building_combo` adds `seams`, reporting horizontal and vertical RGBA border delta metrics against a configurable threshold (default 32.0).

## State and review behavior

`run_validation(candidate_id, store)` only accepts a candidate whose job is `GENERATED`. It persists the structured `ValidationResult`, then transitions the job through the existing compare-and-set API:

- all blocking checks pass: `GENERATED → VALIDATED`
- any blocking check fails: `GENERATED → REJECTED`

It never transitions to `APPROVED`; the existing state graph continues to permit `VALIDATED → APPROVED` only, preserving the review gate.

`AssetStore.get_candidate()` was added so validation reads the persisted artifact/job relation through the store API instead of reaching into SQLite internals.

## Reporting and CLI

`graph-remaster validate [--database PATH] CANDIDATE_ID` now executes the validation stage. Each candidate receives a self-contained adjacent `*.validation.html` report, and the CLI also writes a run-level offline report at `reports/<run-id>/validate.html`. Validation errors produce matching JSON and HTML error reports. No report depends on a network, CDN, renderer, or game data.

## Test coverage

Added `tools/graph_remaster/tests/test_validation.py` with Pillow-only fixtures for:

- a correct canonical 48×48 tile and an incorrect-width tile;
- an alpha-hole mismatch;
- a fixed-grid tile atlas;
- an NPC alpha box shifted seven pixels beyond tolerance;
- an atlas seam with a deliberately mismatched border;
- successful `GENERATED → VALIDATED` and failed `GENERATED → REJECTED` transitions;
- review-gate preservation (neither validation path approves); and
- candidate-level and stage-level offline HTML reporting through the CLI.

## Verification

Commands run:

```text
uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_validation.py -q
uv run --project tools/graph_remaster pytest tools/graph_remaster/tests -q
git diff --check
```

The focused validation suite passed after implementation. The full package suite is rerun immediately before the commit recorded for this task.

---

## Review-finding fixes

### Complete NPC animation sets

NPC validation now loads every persisted source frame for the candidate job's archive/index/shape through `AssetStore.list_shape_frames()`. Candidate metadata may supply an `animation_frames` mapping from frame ID to master path; all supplied masters are loaded and matched by frame ID. The `animation_boxes` result now includes expected and actual frame counts plus explicit missing/extra-frame metrics before evaluating the maximum foreground-box drift.

A missing mapping entry or an extra candidate frame is blocking and sends the job to `REJECTED`. The regression coverage includes a valid two-frame shape as well as missing-frame and extra-frame candidates.

### Layout-aware building/combo seams

`validate_seams()` now evaluates every internal vertical and horizontal boundary declared by `AtlasBundle` layout, instead of assuming image midpoints. Results expose vertical/horizontal boundary counts, mean deltas, and the worst boundary delta. The building/combo runner reconstructs an atlas layout from candidate `atlas_layout` metadata (`columns`, `rows`, `tile_width`, `tile_height`, `scale`) before running the seam check.

Coverage includes a three-cell layout with a deliberately mismatched seam at x=48; this is not the image midpoint and proves all declared boundaries are inspected.

### Atomic validation persistence

`AssetStore.add_validation_and_transition()` writes the structured validation row and performs the candidate-linked job compare-and-set inside one SQLite transaction. `run_validation()` now calls this operation directly. If the `GENERATED` CAS fails, the context manager rolls back the validation insert; the existing review gate remains unchanged.

The rollback regression transitions a job away from `GENERATED`, attempts the atomic operation, asserts `InvalidStateTransition`, and verifies that no `validation_results` row was committed.

### Fix verification

```text
uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_validation.py -q
git diff --check
```

Focused result: `8 passed`. The full package suite is rerun immediately before the fix commit.
