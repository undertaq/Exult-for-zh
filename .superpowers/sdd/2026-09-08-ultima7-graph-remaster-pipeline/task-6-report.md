# Task 6 Report: GPU discovery, two-worker scheduler, and precision fallback

## Outcome

Implemented Task 6 on baseline `e65f4c329c2336c73fc66d2306efd32696061af5`.
The implementation is confined to `tools/graph_remaster` and this report. No
renderer code or game data changed.

## CUDA discovery and device selection

`graph_remaster.workers.devices` provides a torch-lazy `probe_devices()` and
the immutable `CudaDeviceInfo` record. It captures CUDA index/name, total and
currently free VRAM bytes, compute capability, CUDA runtime version, and the
worker-process start timestamp. Missing Torch, CPU-only Torch, or unavailable
CUDA returns an empty list instead of making lightweight commands fail.

The pool uses `multiprocessing.get_context("spawn")`. Each child refreshes the
metadata for its assigned index by calling `probe_devices()` inside the child,
so the scheduler parent never initializes a CUDA context. The scheduler accepts
numeric `--device 0`/`--device 1` and normal `cuda:0`/`cuda:1` forms; numeric
smoke-command input is normalized to the CUDA spelling. Automatic assignment
chooses the idle device with the largest free VRAM, breaking ties on device
index, while a pool-level or per-job device index is deterministic.

The local two-GPU design remains the configuration default (`cuda:0`,
`cuda:1`, two workers) and does not assume that either device is present at
runtime.

## Worker and fallback behavior

`WorkerPool` starts one independent, serial process per distinct physical GPU.
The child owns its backend, loads it only when it receives work, reuses it for
same-profile work, and never shares model objects or CUDA tensors with another
process. `submit(job_id)` returns a `Future[Candidate]`; submitting when both
workers are occupied raises `WorkerBusyError` immediately.

The worker precision list is derived from Task 5's existing
`precision_fallback_ladder()` and `precision_metadata()` rather than replacing
them. Capability filtering offers FP16 and offload everywhere, FP8 only with
torchao plus compute capability 8.9 or later, and INT8/INT4 only with
bitsandbytes plus capability 7.5 or later. `PRECISION_COMPONENTS` explicitly
records which SDXL components remain FP16 and which weight-only components are
quantized for every profile.

CUDA OOM recognition is independent of importing Torch in the parent. On the
first OOM the child clears CUDA cache, unloads the backend, builds the next
profile (normally Task 5's FP16 offload profile), and reuses the original
immutable request, including seed and dimensions. A second OOM fails the
future with `ResourceFailed`; it does not mutate the seed, dimensions, or asset
identity.

## Persistence and diagnostics

The SQLite schema is now version 3. `generation_job_errors` stores a terminal
worker error, full traceback, report path, and timestamp. Version-1 databases
continue through the existing frame-FK migration and then receive the version-3
table. On a successful job, SQLite transitions `QUEUED -> GENERATED`, stores
the candidate, and merges worker/precision provenance into the original job
parameters. On an exhausted OOM (or unexpected worker exit), it follows
`QUEUED -> GENERATED -> RESOURCE_FAILED`, stores the diagnostic record, and
writes `<job-id>.resource-failure.json` beneath the report directory.

Job provenance contains both `worker.device` (the complete `CudaDeviceInfo`)
and `precision`, including Task 5-compatible attempts/applied mode plus the
explicit component mapping. This keeps error and success paths auditable from
SQLite without loading a model.

## Tests and verification

All Task 6 tests use Pillow and picklable fake backend classes. They never
import or allocate a real model. The test suite verifies:

- one serial worker per fake device, deterministic largest-free assignment, and
  rejection of a third concurrent submission;
- the `spawn` start method;
- OOM retry from FP16 to CPU offload with unchanged seed, width, and height;
- repeated OOM persistence as `RESOURCE_FAILED`, including traceback/report
  path and job-level device/precision-component metadata;
- FP8 versus INT8/INT4 capability filtering for the two local-plan capability
  classes; and
- numeric CLI device override normalization.

Fresh verification performed after the final worker-probe change:

- `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_workers.py -q`
  — `5 passed in 5.02s`.
- `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_backend.py -q`
  — `18 passed in 0.05s`.
- `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_config.py -q`
  — `10 passed in 0.02s`.
- `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_controls.py -q`
  — `12 passed in 17.30s`.
- `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_source_io.py -q`
  — `10 passed in 7.70s`.
- `uv run --project tools/graph_remaster pytest 'tools/graph_remaster/tests/test_db.py::test_migrates_v1_generation_jobs_and_preserves_valid_rows' -q`
  — `1 passed in 1.72s`.
- `uv run --project tools/graph_remaster python -m compileall -q tools/graph_remaster/graph_remaster`
  — exit 0.
- `git diff --check` — no whitespace errors.

The full legacy SQLite parameterized suite is intentionally not a model/GPU
test; focused Task 6 coverage plus the adjacent migration regression above
cover the schema change and worker behavior directly.
