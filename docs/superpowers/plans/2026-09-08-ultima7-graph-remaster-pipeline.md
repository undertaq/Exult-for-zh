# Ultima VII Graph Remaster Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a resumable Python asset-remaster pipeline for *Ultima VII: The Black Gate* that extracts Shape frames, generates 6x RGBA HD masters with SDXL ControlNet, validates them, and emits per-stage HTML review pages without changing Exult's renderer.

**Architecture:** Add a self-contained Python package under `tools/graph_remaster/`. SQLite stores the asset graph and state machine; content-addressed files store source frames, controls, candidates, masters, and reports. A two-worker scheduler targets the local RTX 5060 Ti and RTX 3060 independently, with deterministic mock inference for tests and a lazy Diffusers SDXL backend for real jobs.

**Tech Stack:** Python 3.12, `uv`, SQLite, dataclasses, argparse, Pillow, NumPy, OpenCV, PyTorch, Diffusers, Transformers, Accelerate, Safetensors, optional torchao/bitsandbytes, vanilla HTML/CSS/JavaScript.

**Spec:** `docs/superpowers/specs/2026-09-08-ultima7-graph-remaster-pipeline-design.md`

## Global Constraints

- Scope is Black Gate only; the first pilot covers flat tiles, a complete NPC animation set, and one building/combo set.
- Preserve the 320x200 logical coordinate system and 8:5 aspect ratio; the canonical HD target is 6x.
- HD masters are RGBA PNG plus metadata; indexed PNG is only a compatibility preview/fixture.
- Do not modify Exult renderer source, original FLX files, or copyrighted game data.
- Do not depend on ComfyUI or its API.
- Use SDXL image-to-image with asset-specific Canny/silhouette/synthetic-depth profiles as the first backend.
- Run one independent job per GPU; default FP16, batch size one, and one active job per GPU.
- Use precision fallback `FP16 -> offload/attention slicing/VAE tiling -> supported FP8 -> INT8 -> INT4`; record every fallback.
- Every stage emits an offline HTML report; only approved candidates may be packaged.
- Use `ipack` only as a narrow source-format adapter in the first implementation; keep the adapter interface replaceable by a pure-Python implementation.

---

## File Map

Create the following package and tests:

```text
tools/graph_remaster/
  pyproject.toml
  graph_remaster/
    __init__.py
    __main__.py
    cli.py
    config.py
    errors.py
    models.py
    db.py
    hashing.py
    source_io/
      __init__.py
      base.py
      ipack_adapter.py
      png_metadata.py
    controls/
      __init__.py
      profiles.py
      prepare.py
    backends/
      __init__.py
      base.py
      mock.py
      sdxl_controlnet.py
    workers/
      __init__.py
      devices.py
      precision.py
      scheduler.py
    postprocess/
      __init__.py
      masks.py
      hd_master.py
    validation/
      __init__.py
      checks.py
      runner.py
    reports/
      __init__.py
      writer.py
      server.py
      templates.py
    packaging/
      __init__.py
      manifest.py
      package.py
  tests/
    test_config.py
    test_db.py
    test_source_io.py
    test_controls.py
    test_backend.py
    test_postprocess.py
    test_validation.py
    test_reports.py
    test_workers.py
    test_pipeline_fixture.py
```

The implementation must not add files under `exult/`, `gamerend/`, `gamewin/`, or other renderer directories in this milestone.

## Task 1: Package bootstrap, configuration, and CLI

**Files:**
- Create: `tools/graph_remaster/pyproject.toml`
- Create: `tools/graph_remaster/graph_remaster/__init__.py`
- Create: `tools/graph_remaster/graph_remaster/__main__.py`
- Create: `tools/graph_remaster/graph_remaster/cli.py`
- Create: `tools/graph_remaster/graph_remaster/config.py`
- Create: `tools/graph_remaster/graph_remaster/errors.py`
- Create: `tools/graph_remaster/tests/test_config.py`

**Interfaces:**
- `load_config(path: Path) -> PipelineConfig`
- `PipelineConfig.from_mapping(mapping: Mapping[str, Any]) -> PipelineConfig`
- `main(argv: Sequence[str] | None = None) -> int`
- `python -m graph_remaster --help` must expose `inventory`, `extract`, `prepare-controls`, `generate`, `validate`, `review`, and `package`.

- [ ] **Step 1: Write failing configuration tests.**

```python
def test_load_config_resolves_relative_paths(tmp_path):
    config = tmp_path / "pipeline.toml"
    config.write_text(
        """[project]\nname = 'black-gate'\n[paths]\ndata = 'game-data'\nwork = 'remaster-data'\n[render]\nscale = 6\nlogical_width = 320\nlogical_height = 200\n""",
        encoding="utf-8",
    )
    loaded = load_config(config)
    assert loaded.render.scale == 6
    assert loaded.paths.data == tmp_path / "game-data"
    assert loaded.render.logical_size == (320, 200)
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_config.py -q`

Expected: FAIL because the package and configuration types do not exist.

- [ ] **Step 3: Implement the minimal package and config loader.**

Define typed dataclasses for paths, render settings, GPU settings, model settings, and asset profiles. Resolve all relative paths against the TOML file directory. Reject a render scale other than `6`, logical dimensions other than `320x200`, and missing required paths with `ConfigError`.

- [ ] **Step 4: Add the CLI parser and module entry point.**

Use `argparse`; each subcommand should parse `--config`, `--run-id`, and an optional selector. The handlers can raise a clear `NotImplementedError` until their task is implemented, but `--help` must work without importing torch or diffusers.

- [ ] **Step 5: Run focused tests and CLI help.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_config.py -q`

Expected: PASS.

Run: `PYTHONPATH=tools/graph_remaster python -m graph_remaster --help`

Expected: all seven subcommands are listed.

- [ ] **Step 6: Commit.**

```bash
git add tools/graph_remaster
git commit -m "feat: bootstrap graph remaster Python package"
```

## Task 2: Asset graph models and SQLite state store

**Files:**
- Create: `tools/graph_remaster/graph_remaster/models.py`
- Create: `tools/graph_remaster/graph_remaster/db.py`
- Create: `tools/graph_remaster/graph_remaster/hashing.py`
- Create: `tools/graph_remaster/tests/test_db.py`

**Interfaces:**
- `FrameKey(archive_sha256: str, archive_index: int, shape_id: int, frame_id: int)`
- `AssetStore.open(path: Path) -> AssetStore`
- `AssetStore.migrate() -> None`
- `AssetStore.upsert_source_archive(record: SourceArchive) -> None`
- `AssetStore.upsert_shape(record: ShapeRecord) -> None`
- `AssetStore.upsert_frame(record: FrameRecord) -> None`
- `AssetStore.create_generation_job(request: GenerationJob) -> str`
- `AssetStore.transition_job(job_id: str, expected: JobState, new: JobState) -> None`
- `AssetStore.add_candidate(candidate: Candidate) -> str`
- `AssetStore.add_validation(result: ValidationResult) -> None`
- `AssetStore.add_review(decision: ReviewDecision) -> None`
- `sha256_file(path: Path) -> str`

- [ ] **Step 1: Write failing schema and state tests.**

```python
def test_job_transition_is_compare_and_set(tmp_path):
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()
    job_id = store.create_generation_job(make_job(state="QUEUED"))
    store.transition_job(job_id, "QUEUED", "GENERATED")
    with pytest.raises(InvalidStateTransition):
        store.transition_job(job_id, "QUEUED", "VALIDATED")
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_db.py -q`

Expected: FAIL because the schema and store are absent.

- [ ] **Step 3: Implement models and migrations.**

Create tables for `source_archives`, `shapes`, `frames`, `masks`, `control_maps`, `generation_jobs`, `candidates`, `validation_results`, `review_decisions`, and `package_entries`. Use foreign keys, unique source/frame keys, ISO timestamps, JSON columns stored as text, and a schema version table.

- [ ] **Step 4: Implement state transitions.**

Allow only `DISCOVERED -> EXTRACTED -> CONTROLS_READY -> QUEUED -> GENERATED -> VALIDATED -> APPROVED -> PACKAGED`, plus `GENERATED -> RESOURCE_FAILED`, `GENERATED -> REJECTED`, and `REJECTED -> QUEUED`. Raise `InvalidStateTransition` for all other edges.

- [ ] **Step 5: Run tests and verify idempotency.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_db.py -q`

Expected: PASS, including reopening the same database and rerunning migrations without changing data.

- [ ] **Step 6: Commit.**

```bash
git add tools/graph_remaster
git commit -m "feat: add remaster asset graph store"
```

## Task 3: Source inventory, `ipack` adapter, and PNG metadata

**Files:**
- Create: `tools/graph_remaster/graph_remaster/source_io/base.py`
- Create: `tools/graph_remaster/graph_remaster/source_io/ipack_adapter.py`
- Create: `tools/graph_remaster/graph_remaster/source_io/png_metadata.py`
- Create: `tools/graph_remaster/tests/test_source_io.py`
- Modify: `tools/graph_remaster/graph_remaster/cli.py`

**Interfaces:**
- `SourceAdapter.inventory(source_archive: Path, work_dir: Path) -> list[ShapeRecord]`
- `SourceAdapter.extract(shape: ShapeRecord, work_dir: Path) -> list[FrameRecord]`
- `IpackAdapter(ipack_binary: Path, runner: CommandRunner).inventory(...)`
- `IpackAdapter.extract(...)`
- `read_png_offset(path: Path) -> tuple[int, int]`
- `write_ipack_script(archive: Path, palette: Path | None, prefix: Path) -> str`

- [ ] **Step 1: Write tests with a fake `ipack` executable.**

The fake command must accept `-x script`, create deterministic indexed PNG frames named by the requested prefix, and emit a non-zero exit code for missing archives. Test that the adapter records the source SHA-256, frame count, dimensions, alpha/transparency, and offsets without invoking a real game-data path.

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_source_io.py -q`

Expected: FAIL because the adapter is absent.

- [ ] **Step 3: Implement the adapter boundary and command runner.**

Generate an `ipack` script using `archive`, optional `palette`, and `all: PREFIX`. Execute with `subprocess.run(..., check=False, capture_output=True, text=True)`, include stdout/stderr in a structured `SourceToolError`, and never interpolate shell strings through `shell=True`.

- [ ] **Step 4: Implement PNG metadata extraction.**

Read PNG dimensions, indexed palette, transparency, and the `oFFs` chunk. If `oFFs` is absent, return `(0, 0)` and record that the offset was implicit. Preserve the original indexed fixture and write a normalized RGBA canonical source preview.

- [ ] **Step 5: Wire `inventory` and `extract` CLI commands.**

Each command opens the SQLite store, creates a run directory, writes stage records, and emits a structured error report on a missing binary, archive, palette, or malformed PNG. Rerunning with the same input hash must reuse existing source/frame records.

- [ ] **Step 6: Run tests and commit.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_source_io.py -q`

Expected: PASS.

```bash
git add tools/graph_remaster
git commit -m "feat: add Black Gate Shape extraction adapter"
```

## Task 4: Asset profiles, masks, atlases, and control maps

**Files:**
- Create: `tools/graph_remaster/graph_remaster/controls/profiles.py`
- Create: `tools/graph_remaster/graph_remaster/controls/prepare.py`
- Create: `tools/graph_remaster/tests/test_controls.py`
- Modify: `tools/graph_remaster/graph_remaster/cli.py`

**Interfaces:**
- `get_profile(asset_type: AssetType) -> AssetProfile`
- `prepare_mask(frame: FrameRecord) -> MaskRecord`
- `build_tile_atlas(frames: Sequence[FrameRecord], scale: int, canvas: CanvasSpec) -> AtlasBundle`
- `make_canny(image: Image.Image, threshold_low: int, threshold_high: int) -> Image.Image`
- `make_synthetic_depth(mask: Image.Image, asset_type: AssetType) -> Image.Image`
- `prepare_controls(frame: FrameRecord, profile: AssetProfile) -> ControlBundle`

- [ ] **Step 1: Write deterministic control-map tests.**

Use generated Pillow fixtures with a known opaque rectangle and transparent background. Assert that masks preserve the exact opaque region, nearest-neighbor scaling preserves hard edges, Canny/depth output hashes are stable, and the flat profile does not produce a depth map.

- [ ] **Step 2: Run tests and verify failure.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_controls.py -q`

Expected: FAIL because profiles and control generation are absent.

- [ ] **Step 3: Implement the three approved profiles.**

Use `flat_tile`, `npc_rle`, and `building_combo` profiles with the agreed control types and denoise ranges. Keep all thresholds and canvas sizes in config records so the generation job can serialize them.

- [ ] **Step 4: Implement authoritative mask handling.**

Use the source alpha/transparency as the primary mask. Do not call `rembg` in the default path. Store source, protected, and generation masks separately so postprocessing can restore the original silhouette.

- [ ] **Step 5: Implement atlas and control-map generation.**

Upscale source pixels with nearest-neighbor, lay flat tiles on a fixed grid, produce Canny only for flat tiles, produce edge/silhouette maps for NPCs, and produce Canny plus mask-derived synthetic depth for buildings. Save each image by content hash and link it from SQLite.

- [ ] **Step 6: Run tests and commit.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_controls.py -q`

Expected: PASS.

```bash
git add tools/graph_remaster
git commit -m "feat: prepare asset-specific remaster controls"
```

## Task 5: Backend interface, mock backend, and SDXL ControlNet backend

**Files:**
- Create: `tools/graph_remaster/graph_remaster/backends/base.py`
- Create: `tools/graph_remaster/graph_remaster/backends/mock.py`
- Create: `tools/graph_remaster/graph_remaster/backends/sdxl_controlnet.py`
- Create: `tools/graph_remaster/tests/test_backend.py`
- Modify: `tools/graph_remaster/graph_remaster/config.py`

**Interfaces:**
- `InferenceRequest(job: GenerationJob, source: Image.Image, controls: ControlBundle, reference: Image.Image | None)`
- `InferenceBackend.load(device: str, precision: PrecisionProfile) -> None`
- `InferenceBackend.generate(request: InferenceRequest) -> GeneratedImage`
- `InferenceBackend.unload() -> None`
- `MockBackend.generate(...)` returns a deterministic marked candidate without torch.
- `SdxlControlNetBackend.load(...)` lazily imports Diffusers and loads the configured SDXL/ControlNet revisions.

- [ ] **Step 1: Write backend contract tests.**

Test that the mock backend preserves job id, seed, requested dimensions, and metadata; repeated requests with the same input and seed produce the same image hash; and an unavailable backend raises `BackendUnavailable` with an actionable message.

- [ ] **Step 2: Run tests and verify failure.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_backend.py -q`

Expected: FAIL because the backend modules are absent.

- [ ] **Step 3: Implement the backend protocol and mock backend.**

Keep the protocol independent of torch so inventory, controls, validation, and HTML tests run in a lightweight environment. The mock backend must write a visibly different but deterministic RGBA image and never claim it is a real AI candidate.

- [ ] **Step 4: Implement lazy SDXL loading.**

Load `stabilityai/stable-diffusion-xl-base-1.0` and compatible Canny/Depth ControlNet revisions through Diffusers only when `generate` uses the backend. Pass control images as a list only for profiles that request them. Use the job's generator seed and conditioning scales. Keep model IDs and revisions in config, not source constants.

- [ ] **Step 5: Add an opt-in real-model smoke command.**

Add `--real-model-smoke` to `generate` so the default test suite never downloads weights. The smoke command must run one fixed-seed image on a selected device, save peak VRAM and model revisions, and return a non-zero exit code for missing CUDA, missing weights, or invalid ControlNet/model combinations.

- [ ] **Step 6: Run mock tests and commit.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_backend.py -q`

Expected: PASS without importing torch.

```bash
git add tools/graph_remaster
git commit -m "feat: add remaster backend abstraction and SDXL backend"
```

## Task 6: GPU discovery, two-worker scheduler, and precision fallback

**Files:**
- Create: `tools/graph_remaster/graph_remaster/workers/devices.py`
- Create: `tools/graph_remaster/graph_remaster/workers/precision.py`
- Create: `tools/graph_remaster/graph_remaster/workers/scheduler.py`
- Create: `tools/graph_remaster/tests/test_workers.py`
- Modify: `tools/graph_remaster/graph_remaster/cli.py`

**Interfaces:**
- `probe_devices() -> list[CudaDeviceInfo]`
- `resolve_precision(device: CudaDeviceInfo, installed: CapabilitySet) -> list[PrecisionProfile]`
- `WorkerPool.submit(job_id: str) -> Future[Candidate]`
- `WorkerPool.close() -> None`
- `is_cuda_oom(error: BaseException) -> bool`

- [ ] **Step 1: Write scheduler tests with fake devices and backend.**

Test one job per device, rejection of a third concurrent job when both workers are occupied, deterministic device assignment, and an OOM retry that advances from FP16 to offload without changing the job's seed or dimensions.

- [ ] **Step 2: Run tests and verify failure.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_workers.py -q`

Expected: FAIL because worker modules are absent.

- [ ] **Step 3: Implement device discovery and explicit overrides.**

Use PyTorch only inside the worker process. Record index, name, total/free VRAM, compute capability, CUDA version, and process start time. Support `--device 0`, `--device 1`, and an automatic mode that prefers the largest free device.

- [ ] **Step 4: Implement spawned independent workers.**

Use `multiprocessing.get_context("spawn")`; each worker loads one backend pipeline once and processes jobs serially. Do not share model objects or CUDA tensors between workers. The scheduler must preserve SQLite state transitions when a worker exits unexpectedly.

- [ ] **Step 5: Implement precision profiles and optional quantizers.**

Define FP16, offload, FP8 weight-only, INT8 weight-only, and INT4 weight-only profiles. Probe torchao/bitsandbytes availability and GPU capability before offering a profile. Keep the quantized component mapping explicit and record it in each job.

- [ ] **Step 6: Implement OOM recovery.**

Catch CUDA OOM, call `torch.cuda.empty_cache()`, unload the current backend, build the next precision profile, and retry once. On repeated failure, store `RESOURCE_FAILED` plus the traceback and report path.

- [ ] **Step 7: Run tests and commit.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_workers.py -q`

Expected: PASS without allocating a real model.

```bash
git add tools/graph_remaster
git commit -m "feat: add dual GPU workers and precision fallback"
```

## Task 7: Postprocessing and HD master generation

**Files:**
- Create: `tools/graph_remaster/graph_remaster/postprocess/masks.py`
- Create: `tools/graph_remaster/graph_remaster/postprocess/hd_master.py`
- Create: `tools/graph_remaster/tests/test_postprocess.py`

**Interfaces:**
- `restore_source_alpha(candidate: Image.Image, source_mask: Image.Image) -> Image.Image`
- `scale_offset(xoff: int, yoff: int, scale: int = 6) -> tuple[int, int]`
- `write_hd_master(candidate: Image.Image, frame: FrameRecord, output: Path) -> HDMaster`
- `write_indexed_preview(master: HDMaster, palette: Palette, output: Path) -> Path`

- [ ] **Step 1: Write tests for alpha and six-times metadata.**

Assert that the source alpha replaces candidate alpha exactly, a 32x48 frame becomes a 192x288 master, offsets become six times their logical values, and the canonical output remains RGBA even when a compatibility preview is indexed.

- [ ] **Step 2: Run tests and verify failure.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_postprocess.py -q`

Expected: FAIL because postprocessing modules are absent.

- [ ] **Step 3: Implement mask restoration and crop mapping.**

Use the recorded source-to-canvas transform to crop the AI output back to the exact HD target. Apply the authoritative alpha mask after crop, preserve RGB under transparent pixels for review, and write a sidecar metadata JSON containing source key, dimensions, offsets, and hashes.

- [ ] **Step 4: Implement compatibility preview generation.**

Quantize only a derived preview to the original palette and transparency convention. Never overwrite the RGBA master. Record quantization errors and preview paths separately.

- [ ] **Step 5: Run tests and commit.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_postprocess.py -q`

Expected: PASS.

```bash
git add tools/graph_remaster
git commit -m "feat: write six-times RGBA HD masters"
```

## Task 8: Asset-class validation and state transitions

**Files:**
- Create: `tools/graph_remaster/graph_remaster/validation/checks.py`
- Create: `tools/graph_remaster/graph_remaster/validation/runner.py`
- Create: `tools/graph_remaster/tests/test_validation.py`
- Modify: `tools/graph_remaster/graph_remaster/cli.py`

**Interfaces:**
- `validate_dimensions(frame, master) -> CheckResult`
- `validate_alpha(frame, master) -> CheckResult`
- `validate_tile_grid(atlas, frame_set) -> CheckResult`
- `validate_animation_boxes(frames, masters, tolerance: int) -> CheckResult`
- `validate_seams(atlas, threshold: float) -> CheckResult`
- `run_validation(candidate_id: str, store: AssetStore) -> ValidationReport`

- [ ] **Step 1: Write failing check tests.**

Create fixtures for a correct 48x48 tile, an incorrect-size tile, a masked alpha hole, an NPC with one frame shifted beyond tolerance, and an atlas with a deliberately mismatched border. Assert named checks and metric values are stable.

- [ ] **Step 2: Run tests and verify failure.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_validation.py -q`

Expected: FAIL because checks are absent.

- [ ] **Step 3: Implement generic metadata and image checks.**

Return structured results with check name, status, numeric metrics, threshold, and explanation. Do not use a single aggregate boolean without retaining individual failures.

- [ ] **Step 4: Implement asset-specific checks.**

Flat tiles must have exact 48x48 crops and grid alignment. NPC groups must preserve frame count and bounded foreground-box drift. Building/combo groups must report border seam metrics. All assets must pass RGBA, alpha, offset, and metadata checks.

- [ ] **Step 5: Wire validation state transitions.**

Transition `GENERATED -> VALIDATED`; transition to `REJECTED` when a blocking check fails, otherwise leave the candidate pending review. Only a review decision can transition to `APPROVED`.

- [ ] **Step 6: Run tests and commit.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_validation.py -q`

Expected: PASS.

```bash
git add tools/graph_remaster
git commit -m "feat: validate remaster candidates by asset class"
```

## Task 9: Per-stage HTML reports and local review server

**Files:**
- Create: `tools/graph_remaster/graph_remaster/reports/templates.py`
- Create: `tools/graph_remaster/graph_remaster/reports/writer.py`
- Create: `tools/graph_remaster/graph_remaster/reports/server.py`
- Create: `tools/graph_remaster/tests/test_reports.py`
- Modify: `tools/graph_remaster/graph_remaster/cli.py`

**Interfaces:**
- `write_stage_report(stage: Stage, run_id: str, store: AssetStore, output_dir: Path) -> Path`
- `write_run_index(run_id: str, output_dir: Path) -> Path`
- `ReviewServer(store_path: Path, report_root: Path)`
- `record_review(candidate_id: str, decision: ReviewDecision) -> None`

- [ ] **Step 1: Write report tests.**

Assert that a fixture run creates `index.html` plus all seven stage pages, that every page references only relative local assets, that metadata includes source hash/seed/GPU/precision, and that a review POST writes a `ReviewDecision` and does not approve a failed candidate.

- [ ] **Step 2: Run tests and verify failure.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_reports.py -q`

Expected: FAIL because report modules are absent.

- [ ] **Step 3: Implement static report generation.**

Use standard-library HTML escaping and vanilla JS/CSS. Generate `01-inventory.html`, `02-extraction.html`, `03-controls.html`, `04-generation.html`, `05-postprocess.html`, `06-validation.html`, and `07-package.html`, plus a run index. Use thumbnails for grids and relative links for full images; do not use external CDN assets.

- [ ] **Step 4: Implement review actions.**

Use a small standard-library HTTP server or a lightweight optional dependency. Expose `Approve`, `Reject`, and `Needs retry` actions with a required reason for rejection/retry. Direct `file://` pages remain read-only. Validate candidate state and validation results before accepting approval.

- [ ] **Step 5: Wire reports to every CLI stage.**

Write a report even when a stage fails, showing the error, command, config hash, and log path. Make report writing atomic by writing a temporary file and renaming it.

- [ ] **Step 6: Run tests and commit.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_reports.py -q`

Expected: PASS.

```bash
git add tools/graph_remaster
git commit -m "feat: add per-stage HTML review reports"
```

## Task 10: Approved package manifest and fixture end-to-end pipeline

**Files:**
- Create: `tools/graph_remaster/graph_remaster/packaging/manifest.py`
- Create: `tools/graph_remaster/graph_remaster/packaging/package.py`
- Create: `tools/graph_remaster/tests/test_pipeline_fixture.py`
- Create: `tools/graph_remaster/README.md`
- Modify: `tools/graph_remaster/graph_remaster/cli.py`

**Interfaces:**
- `build_package(run_id: str, store: AssetStore, output_dir: Path) -> PackageManifest`
- `write_manifest(manifest: PackageManifest, output: Path) -> None`
- `run_fixture_pipeline(tmp_path: Path) -> RunSummary`

- [ ] **Step 1: Write the fixture integration test.**

Generate one flat atlas, one multi-frame NPC set, and one building atlas entirely with Pillow. Run inventory, extraction, control preparation, `MockBackend` generation, postprocessing, validation, report generation, approve all candidates through the store API, and package the approved masters. Assert that all stage pages exist and each manifest entry maps to a source frame.

- [ ] **Step 2: Run the integration test and verify failure.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_pipeline_fixture.py -q`

Expected: FAIL because packaging and full orchestration are absent.

- [ ] **Step 3: Implement the renderer-neutral package writer.**

Copy only approved RGBA masters and metadata sidecars into `packages/RUN_ID/masters/`; write `manifest.json` with source key, logical dimensions, HD dimensions, scaled offsets, alpha hash, candidate id, and checksum. Refuse to package a candidate without an `APPROVED` review decision.

- [ ] **Step 4: Wire the full CLI orchestration.**

Make each command select pending records from SQLite, execute only its stage, update state, and emit the corresponding report. `generate` must support `--backend mock` for tests and `--backend sdxl_controlnet --real-model-smoke` for local GPUs.

- [ ] **Step 5: Document local execution.**

In `README.md`, document `uv` setup, the config file, how to point at user-owned Black Gate data, how to select `--device 0` or `--device 1`, how to start the review server, how quantization fallback is selected, and that no original data is committed.

- [ ] **Step 6: Run the full lightweight suite and commit.**

Run: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests -q`

Expected: PASS without downloading diffusion weights or requiring CUDA.

```bash
git add tools/graph_remaster
git commit -m "feat: package approved HD masters and fixture pipeline"
```

## Task 11: Local GPU smoke test and final verification

**Files:**
- Modify: `tools/graph_remaster/README.md` only if observed commands differ from the documented runbook.
- Generated outside Git: local `remaster_data/` run directory and reports.

- [ ] **Step 1: Verify the local CUDA environment.**

Run:

```bash
nvidia-smi --query-gpu=index,name,memory.total,memory.free,compute_cap --format=csv
uv run --project tools/graph_remaster python -c "import torch; print(torch.cuda.is_available(), torch.cuda.device_count())"
```

Expected: both local GPUs are visible and no pre-existing process is terminated by the pipeline.

- [ ] **Step 2: Run one fixed-seed SDXL smoke job on each GPU.**

Run the `generate --real-model-smoke` command once with `--device 0` and once with `--device 1`, using a generated fixture image, batch size one, and the smallest configured pilot canvas. Record model download paths, runtime, peak VRAM, precision profile, and report paths.

- [ ] **Step 3: Exercise the fallback path with a test double.**

Use a backend test double that raises a CUDA-OOM-shaped exception on its first call. Assert that the scheduler retries with the next precision profile, records the fallback, and either succeeds or emits `RESOURCE_FAILED` without corrupting the candidate graph.

- [ ] **Step 4: Run final verification.**

Run:

```bash
uv run --project tools/graph_remaster pytest tools/graph_remaster/tests -q
git diff --check
git status --short --branch
```

Expected: all lightweight tests pass, no renderer files changed, and only intended pipeline files are tracked. Do not claim the pipeline is complete until the local smoke reports and fixture reports exist.

- [ ] **Step 5: Commit any runbook correction.**

```bash
git add tools/graph_remaster/README.md
git commit -m "docs: verify local graph remaster execution"
```
