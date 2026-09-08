# Task 7: Postprocessing and HD Master Generation Report

## Scope

Implemented only `tools/graph_remaster` postprocessing code and its focused
tests. Renderer and game-data files were not changed.

## Delivered behavior

- `restore_source_alpha()` substitutes the source alpha channel exactly while
  retaining the candidate's RGB bytes, including pixels made transparent.
- `write_hd_master()` accepts either an exact HD candidate or crops a generated
  canvas using `frame.metadata["source_to_canvas"]["crop"]`, expressed as
  `[left, top, width, height]` in candidate pixel coordinates.
- Masters are canonical RGBA PNGs with dimensions `logical_size * scale`
  (default scale: 6). Source alpha is nearest-neighbour scaled before exact
  restoration, and logical PNG offsets are scaled by the same factor.
- Each master gets a JSON sidecar recording the frame source key, logical and
  HD dimensions, logical and HD offsets, transform, and SHA-256 hashes for the
  cropped candidate pixels, source alpha, RGBA master pixels, and emitted PNG.
- `Palette` and `write_indexed_preview()` produce palette-quantized indexed
  PNG derivatives. Transparent pixels are assigned the specified source
  transparent index. Preview PNG/JSON paths must differ from the master; an
  attempted master overwrite raises `ValueError`.
- Preview JSON records its own path and hash, the master path/hash, palette
  hash, transparency convention, and opaque-pixel quantization MSE. It does
  not mutate the canonical master or its sidecar.

## Tests

The new focused suite covers exact alpha replacement with hidden RGB retention,
pixel-space canvas crop mapping, 32x48 to 192x288 generation, sixfold negative
and positive offsets, RGBA master persistence, sidecar hashes, indexed preview
transparency, preview quantization metadata, and master non-overwrite.

1. RED: `uv run --project tools/graph_remaster pytest tools/graph_remaster/tests/test_postprocess.py -q`
   failed during collection with `ModuleNotFoundError: graph_remaster.postprocess` before implementation.
2. GREEN: the same command passed with `4 passed in 0.09s` after implementation.
3. `git diff --check` completed without whitespace errors.

## Deliberate contract decisions

- The recorded transform is strict: only `{"crop": [left, top, width, height]}`
  is accepted, and its extent must exactly equal the expected HD size and fit
  inside the candidate. This prevents silent geometry drift.
- A candidate already matching the target HD dimensions is accepted unchanged,
  even when the frame retains its original canvas transform. This supports
  backends that crop before returning a candidate without applying the crop a
  second time.
