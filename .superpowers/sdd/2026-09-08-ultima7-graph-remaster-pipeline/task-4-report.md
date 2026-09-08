# Task 4 Report: Asset profiles, masks, atlases, and control maps

## Outcome

Implemented Task 4 in `tools/graph_remaster` from baseline
`9784434ae6b3df15e469d8ef1f6707d4ebafe4e9`. The implementation is scoped to
the graph-remaster pipeline. It does not modify Exult renderer sources or game
data.

## Profiles and configuration

- Added the approved `AssetType` values and immutable profile lookup:
  `flat_tile`, `npc_rle`, and `building_combo`.
- `AssetProfile` now serializes the selected controls, denoise interval, Canny
  thresholds, and fixed atlas dimensions. TOML `asset_profiles` accepts these
  fields, so a queued generation job can retain all control-relevant inputs.
- Defaults are explicit and backend-independent: flat tiles use Canny only;
  NPCs use alpha-edge plus silhouette controls; buildings use Canny plus
  mask-derived synthetic depth.

## Deterministic image controls

- `prepare_mask` opens only extracted-frame `rgba_preview_path` metadata and
  treats its alpha channel as authoritative. Source, protected, and generation
  masks are distinct Pillow images with identical source-alpha pixels. There is
  no `rembg` dependency or default segmentation path.
- `build_tile_atlas` uses `Image.Resampling.NEAREST`, retains hard pixel edges,
  and places fixed-size tiles in a stable left-to-right/top-to-bottom grid. The
  configured renderer scale remains the required sixfold scale.
- `make_canny` is a deterministic Pillow-only implementation: Gaussian
  smoothing, Sobel magnitude/direction, non-maximum suppression, and
  low/high-threshold hysteresis. It does not require OpenCV.
- Synthetic depth is generated only for `building_combo` from the protected
  alpha silhouette. Flat tiles never receive a depth control.

## Artifacts and SQLite links

- `persist_controls` encodes controls as deterministic PNG bytes, names each
  stored object `<sha256>.png` under a hash prefix directory, and reuses an
  existing identical object.
- It links source/protected/generation masks through the existing `masks`
  table and control images through `control_maps`. The links are idempotent per
  frame and kind; metadata contains the artifact SHA-256 and complete serialized
  profile settings.
- `AssetStore` now exposes idempotent mask/control-map upserts and deterministic
  frame listing for the preparation stage.

## CLI

`graph-remaster prepare-controls` now accepts `--database` and optional archive
SHA selector. It reads extracted frames from SQLite, chooses a metadata-specified
asset type (defaulting to `flat_tile`), creates the controls, writes content
addressed artifacts below `paths.controls/<run-id>/`, and emits `stage.json`.
It imports no generation backend.

## Tests and verification

Test-first sequence:

1. Added `tests/test_controls.py`; the first focused run failed because Pillow
   and the controls module were absent.
2. Declared Pillow as the explicit package dependency and generated `uv.lock`.
   The focused test then failed on the absent `graph_remaster.controls` API.
3. Added the minimal controls/persistence implementation and completed the
   red-green cycle for the CLI stage.

Automated coverage verifies:

- Exact opaque rectangle preservation in all three masks.
- Fixed-grid nearest-neighbor 6x atlas pixels and transparent boundaries.
- Stable byte hashes for flat/building Canny and building depth controls.
- No flat-tile depth output.
- Content-addressed PNG reuse and idempotent SQLite links.
- End-to-end `prepare-controls` CLI persistence and stage manifest creation.

Fresh verification:

- `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_controls.py -q`
  — `5 passed in 4.79s`.
- `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests -q`
  — `48 passed in 93.09s`.
- `uv run --project tools/graph_remaster python -m compileall -q tools/graph_remaster/graph_remaster`
  — exit 0.
- `PYTHONPATH=tools/graph_remaster uv run --project tools/graph_remaster python -m graph_remaster prepare-controls --help`
  — exit 0, including `--database` and optional selector.
- `git diff --check` — no whitespace errors.

The package lock contains Pillow 12.3.0 for the current resolved environment.
