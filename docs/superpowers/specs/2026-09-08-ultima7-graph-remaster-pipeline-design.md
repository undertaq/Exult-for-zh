# Ultima VII Graph Remaster Pipeline Design

## Status

Conversation design approved through the review-page and quantization decisions; written-spec review is pending. This document defines the first implementation scope. It does not modify Exult's renderer and does not bundle original Ultima VII data.

## Objective

Build a reproducible, Python-driven asset remaster pipeline for *Ultima VII: The Black Gate*. The pipeline will extract Shape assets from user-provided game data, generate controlled AI re-imaginings, preserve the original asset identity and spatial metadata, validate 6x HD masters, and produce reviewable packages for a later Exult renderer integration.

The first implementation is a graph pipeline, not an engine change. It must be possible to rerun one failed frame or candidate without repeating extraction or unrelated inference jobs.

## Decisions

- Scope is Black Gate only. Serpent Isle is out of scope for the first release.
- The first pilot covers three asset classes: 8x8 flat terrain tiles, a complete NPC animation set, and one building/combo set. Fonts, UI, text, and icons are excluded from AI generation.
- The logical game coordinate system remains 320x200 with the original 8:5 aspect ratio.
- The canonical HD target is 6x. A logical 8x8 tile becomes a 48x48 master; RLE frame dimensions and offsets are multiplied by six.
- A 1920x1080 display preserves the 8:5 aspect ratio with vertical letterboxing. The corresponding 6x logical canvas is 1920x1200, so the renderer may later fit it into 1920x1080 without stretching or cropping.
- The remaster master is RGBA PNG plus metadata. It is not forced back into the original indexed palette or FLX format.
- A compatibility representation remains available as indexed PNG for extraction and original-format round-trip tests.
- The first inference backend is Python Diffusers SDXL image-to-image with asset-specific ControlNet profiles. FLUX.2 Klein is a later pluggable backend, not an MVP dependency.
- ComfyUI and its API are not dependencies.
- GPU workers are independent processes. They do not shard one model across GPUs.
- On the development machine, worker 0 targets the RTX 5060 Ti 16GB and worker 1 targets the RTX 3060 12GB. The runtime still detects devices dynamically and permits overrides.
- Default inference is FP16, batch size one, and one active job per GPU.
- Quantization is an automatic fallback, not the default quality mode.
- Every pipeline stage emits an offline HTML review page. Approval is a required gate before packaging.
- Exult renderer changes are a later project that consumes approved HD masters and their manifest.

## Existing Exult integration points

The repository already provides `ipack` for extracting and creating Shape-containing Flex files and `expack` for general Flex containers. `ipack` can extract Shape frames to PNG and create/update Flex files from a script, but its documentation notes that tiled Shapes are extracted into multiple PNGs. The pipeline therefore uses an explicit frame manifest rather than assuming a single tiled file represents every Shape.

The existing Shape import path accepts indexed PNG data, converts it to the game palette, and enforces 8x8 dimensions for flat Shapes. RLE Shapes preserve variable dimensions and offsets. These paths are useful for source extraction and compatibility fixtures, but they are not the HD master format.

The source adapter must retain, at minimum:

```text
source archive path and SHA-256
archive index
shape id
frame id
flat or RLE classification
logical width and height
x/y offsets
frame count
palette identity
transparency identity
```

The original game data is an external input supplied by the user. It must never be checked into this repository.

## Architecture

The implementation lives under `tools/graph_remaster/` as a Python package with a CLI. The package is divided into small adapters:

```text
graph_remaster/
  cli.py
  config.py
  db.py
  models.py
  source_io/
    flex_adapter.py
    shape_adapter.py
  inventory/
  controls/
  backends/
    base.py
    sdxl_controlnet.py
    flux2_klein.py       # later backend, interface only in MVP
  workers/
    scheduler.py
    worker.py
    quantization.py
  postprocess/
  validation/
  reports/
  packaging/
```

The orchestration and inference code are Python-only. The first source-format adapter may invoke the repository's existing `ipack` binary as a narrow compatibility adapter; no ComfyUI process or HTTP service is involved. A pure-Python Flex/Shape adapter can replace it behind the same interface without changing the asset graph or backend code.

The pipeline must support these commands:

```text
python -m graph_remaster inventory
python -m graph_remaster extract
python -m graph_remaster prepare-controls
python -m graph_remaster generate --backend sdxl_controlnet
python -m graph_remaster validate
python -m graph_remaster review --run-id RUN_ID
python -m graph_remaster package
```

All commands accept a project configuration and a run identifier. Commands are resumable and operate only on pending or explicitly selected nodes.

## Asset graph and storage

SQLite is the canonical state store. Images and reports are content-addressed or run-versioned files referenced from SQLite. The logical graph is:

```text
SourceArchive
  -> Shape
      -> Frame
          -> Mask
          -> ControlMap
          -> GenerationJob
              -> Candidate
                  -> ValidationResult
          -> PackageEntry
```

Important records are:

- `SourceArchive`: game, input path, SHA-256, extraction tool/version.
- `Shape`: archive index, Shape id, type, frame count, palette id.
- `Frame`: frame id, source dimensions, offsets, source image hash, logical target dimensions.
- `Mask`: source alpha, protected regions, mask operations and hash.
- `ControlMap`: control type, parameters, source hash, output hash.
- `GenerationJob`: backend, model revision, prompt profile, seed, denoise strength, control scales, requested GPU, precision profile, retry number.
- `Candidate`: output path, dimensions, color mode, alpha hash, generation timestamp.
- `ValidationResult`: named checks, metrics, pass/fail state, validator version.
- `ReviewDecision`: reviewer, decision, reason, timestamp, candidate id.
- `PackageEntry`: asset id, HD master path, manifest path, source mapping, checksum.

Run artifacts use this layout:

```text
remaster_data/
  source/
  inventory/
  controls/
  jobs/
  candidates/
  validated/
  packages/
  reports/
```

The state machine is:

```text
DISCOVERED -> EXTRACTED -> CONTROLS_READY -> QUEUED -> GENERATED
-> VALIDATED -> APPROVED -> PACKAGED
```

Failed and rejected states retain the old candidate and can be retried with a new job record.

## Stage data flow

### Inventory and extraction

Inventory scans the Black Gate source archives and records all Shape/frame identities, but the AI pilot selects only the agreed flat tile, NPC, and building/combo subsets. Extraction produces canonical source PNGs, alpha masks, offset metadata, and compatibility indexed PNG fixtures.

Extraction must be deterministic. A second extraction of the same source checksum must produce the same frame hashes and metadata.

### Control preparation

The source transparency mask is authoritative. `rembg` is not used as the default mask generator because it can remove dark outlines, shadows, weapons, and other intentional pixels. Optional background removal is allowed only for source data that has no trustworthy alpha.

Control maps are generated in Python using Pillow/OpenCV or equivalent pinned dependencies:

- Flat tiles: nearest-neighbor 6x source enlargement, fixed atlas grid, edge/Canny map, no depth by default.
- NPC/RLE: source frame, silhouette/edge map, shared character reference, optional synthetic depth only when validated for the asset.
- Building/combo: Canny plus synthetic depth generated from masks and asset metadata. The depth map is not blindly inferred from a tiny pixel image.

The baseline does not require a Tile ControlNet. Source image, mask, edge control, and reference material carry the structural constraints.

### Generation

The SDXL backend loads the base model and compatible Canny/Depth ControlNets through Diffusers. ControlNet lists and conditioning scales are selected by asset profile. The pipeline generates on a sufficiently large model canvas, then crops or maps the result back to the exact 6x master dimensions. It never asks the diffusion model to generate a standalone 48x48 tile as the only context.

Initial profile ranges are configuration, not hard-coded truth:

```text
flat_tile:       Canny, denoise 0.25-0.35
npc_rle:         edge/silhouette, denoise 0.30-0.45
building_combo:  Canny + synthetic depth, denoise 0.20-0.35
```

Every candidate is generated with a recorded seed and immutable input/control hashes.

### Postprocessing

Postprocessing restores the original alpha mask, scales and records offsets, crops the approved region, and writes an RGBA 6x master. It must not quantize the canonical master to the original palette. A separate compatibility preview may be quantized for comparison and round-trip tests.

### Validation and package

Validation runs before review and again before packaging. Packaging only includes approved candidates and emits a manifest mapping each HD asset to its original archive/Shape/frame identity. The MVP package is a renderer-neutral HD asset directory plus manifest, not a modified `exult_bg.flx`.

## GPU execution and precision fallback

The runtime probes CUDA devices through PyTorch and exposes explicit device selection. The observed development machine has:

```text
CUDA 0: NVIDIA GeForce RTX 5060 Ti, 16GB, compute capability 12.0
CUDA 1: NVIDIA GeForce RTX 3060, 12GB, compute capability 8.6
```

The scheduler assigns one job to one worker and never runs two jobs simultaneously on the same GPU. The 5060 Ti receives larger or more complex canvases; the 3060 receives batch-one tile/NPC jobs with CPU offload when needed.

Precision fallback is:

```text
FP16
  -> CPU offload + attention slicing + VAE tiling
  -> FP8 weight-only where the device/backend supports it
  -> INT8 weight-only
  -> INT4 weight-only
```

FP8 is attempted only on devices whose capability and installed torchao backend pass a startup capability check. On the RTX 3060, FP8 is not a default path. Quantization is applied only to supported large components; VAE, normalization, and ControlNet convolution paths remain at safe precision unless a dedicated smoke test proves otherwise.

An OOM retry records the failure, clears the worker cache, reconstructs the pipeline with the next profile, and retries once. Repeated failure marks the job `RESOURCE_FAILED` with a report rather than silently changing dimensions or asset identity.

## HTML review reports

Every run emits local, offline HTML pages with relative links and no CDN dependency:

```text
reports/RUN_ID/
  index.html
  01-inventory.html
  02-extraction.html
  03-controls.html
  04-generation.html
  05-postprocess.html
  06-validation.html
  07-package.html
  assets/
```

Each stage page includes the relevant images, metadata, hashes, parameters, logs, and status. Generation pages show source/control/candidate comparisons and GPU/precision information. Validation pages show named PASS/FAIL checks and metric values. Package pages show source-to-HD mappings and checksums.

The pages are readable with `file://`. A local Python review server enables persistent `Approve`, `Reject`, and `Needs retry` actions; direct file viewing is read-only. Review decisions are written to SQLite and are required for packaging.

## Validation and testing

Unit tests cover:

- manifest serialization and migrations
- logical-to-6x dimension and offset calculations
- alpha mask preservation
- control-map determinism
- asset-class profile selection
- retry and state transitions
- report generation

Fixture tests cover known Shape extraction and compatibility round-trips. Backend smoke tests use a fixed seed on each local GPU and verify model loading, output dimensions, and metadata capture. The pilot integration test must process one flat atlas, one complete NPC animation group, and one building/combo group through extraction, controls, generation, postprocessing, validation, review, and package creation.

The implementation is not complete until:

1. All three pilot classes produce review pages at every stage.
2. At least one candidate per class passes automated validation and is manually approved.
3. The package manifest maps every approved HD master back to its source Shape/frame.
4. Re-running inventory and extraction with the same input hash is deterministic.
5. The pipeline can recover from one forced OOM by using the configured precision fallback.
6. No Exult renderer source is changed by this pipeline milestone.

## Explicit non-goals

- No renderer or in-game 1080p integration in this milestone.
- No automatic full Black Gate remaster.
- No AI generation of fonts, UI, text, or icons.
- No overwrite of original FLX files.
- No bundling of copyrighted game data.
- No dependence on a running ComfyUI instance.

## External implementation references

- [Diffusers ControlNet documentation](https://huggingface.co/docs/diffusers/en/using-diffusers/controlnet)
- [Diffusers bitsandbytes quantization](https://huggingface.co/docs/diffusers/quantization/bitsandbytes)
- [Diffusers torchao quantization](https://huggingface.co/docs/diffusers/v0.36.0/quantization/torchao)
- [Black Forest Labs FLUX.2 Python repository](https://github.com/black-forest-labs/flux2)
