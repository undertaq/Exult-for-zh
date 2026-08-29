# Isometric View Support Design

## Status

Approved direction: projection-aware world rendering with per-tile/per-shape transforms when the selected projection cannot use the existing bitmap geometry.

This document is based on the current checkout, including the tracked renderer and the user's existing untracked `gamerend/iso_projection.{h,cc}` work. It does not treat the untracked design notes as implementation truth where they differ from the source.

## Context and current constraints

The current software renderer is organized around an orthogonal screen grid:

- `Game_window::Get_shape_location` converts tile coordinates to `x = tx * c_tilesize` and `y = ty * c_tilesize`, then applies the existing `4 * tz` lift offset.
- `Game_render::paint_map` copies cached flat chunks as square `c_chunksize` images at orthogonal offsets.
- `Game_object::paint` obtains the same shape location and delegates raw/RLE drawing to `Shape_manager` and `Shape_frame`.
- Effects, selection, grid, terrain-editor rendering, and several drag/cheat paths perform their own scroll-plus-tile arithmetic.
- `Game_window::paint` composites the world, effects, gumps, dragging, and text in one frame. A post-process warp would therefore also warp UI or require a second, fragile composition path.

The existing partial selector describes diamond, true-isometric, and dimetric projections, but the tracked renderer does not currently have a diamond screen-space path. The compatibility mode must therefore represent the current square/orthogonal behavior and remain the default. Diamond, true-isometric, and dimetric are opt-in projections until their world rendering is complete.

## Goals

1. Add a runtime-selectable world projection for the current software renderer.
2. Keep the current view visually and behaviorally compatible when the default mode is selected.
3. Project tile anchors, object anchors, effects, selection, and world-space hit testing through one shared service.
4. Transform indexed-color tile/shape pixels only for projection modes whose source bitmap geometry is incompatible with the destination basis.
5. Preserve palette indexes, transparency, remapping, and translucency semantics.
6. Make projection changes invalidate affected caches and repaint the world safely.

## Non-goals

- Do not warp the complete framebuffer; gumps, text, cursor UI, and other screen-space controls remain unprojected.
- Do not change pathfinding, game-world tile coordinates, savegame map formats, or object ownership semantics.
- Do not introduce a new asset file format or require pre-generated variants for every shape.
- Do not alter the default view until the compatibility path has the same placement and draw behavior as the current renderer.

## Projection model

Introduce a single projection value used by world rendering and inverse hit testing. The initial values are:

| Mode | Purpose | Default |
| --- | --- | --- |
| `legacy` | Current square/orthogonal renderer and bitmap placement | Yes |
| `diamond` | 2:1 diamond tile basis | No |
| `true_iso` | Equal-angle isometric basis | No |
| `dimetric` | Configurable dimetric basis matching the selected view | No |

The public projection API should operate on logical tile coordinates plus lift, rather than exposing renderer-specific scroll arithmetic. A projected point is represented as integer screen coordinates plus an ordering/depth value. The ground-plane transform is a pair of basis vectors:

```
screen = origin + tx * basis_x + ty * basis_y - lift * lift_basis
```

The diamond basis is symmetric around the vertical axis. The true-isometric and dimetric bases use the same logical tile axes with their own horizontal and vertical scale. The implementation must use deterministic rounding at the API boundary so a point projects and unprojects consistently on all supported platforms.

The legacy implementation is kept as an explicit branch and continues to use the current wrap and scroll rules. It is not expressed as a visual approximation of diamond mode.

`unproject` solves the inverse of the two ground-plane basis vectors. Since a screen click does not carry an object height, it returns a ground tile candidate; existing object hit tests then apply shape bounds and lift/depth checks. Wrapped tile coordinates are normalized using the same map dimensions as forward placement.

`tile_bounds` must project all four ground corners, not just the diagonal corner, and return a non-empty integer rectangle. This rectangle is used for clip expansion, dirty-region calculation, selection, and cache placement.

## Rendering architecture

### Shared world-space placement

Add a projection-aware placement service (implemented alongside the existing projection selector) with operations equivalent to:

- project a tile/lift anchor relative to the current camera;
- unproject a screen point to a candidate tile;
- return projected tile bounds and lift pixels;
- report depth ordering for painter traversal;
- identify whether the selected mode can use legacy square bitmap placement.

`Game_window::Get_shape_location` becomes the central adapter for object placement. It retains the current output for `legacy` and calls the projection service for other modes. World effects and any remaining direct tile-to-screen call sites must use the same adapter rather than duplicating formulas. Screen-space gumps and text do not use it.

### Terrain and map flats

The legacy path keeps the current cached flat-chunk copy for performance and compatibility. For a projected mode, the renderer must not copy a square orthogonal chunk directly into the destination. It instead enumerates visible logical tiles, projects each tile's anchor/bounds, and draws the source flat tile through the transformed-tile path. A projected chunk cache may be added after correctness is established, keyed by chunk identity, projection mode, and relevant palette/cache version.

Visible tile enumeration is derived by unprojecting the clip rectangle corners and expanding by a guard margin large enough for projected tile bounds and lifted objects. This avoids assuming that screen `x / c_tilesize` and `y / c_tilesize` identify a tile in an isometric mode.

Terrain-editor rendering, selection outlines, grid lines, dungeon blackness, and other world overlays must either use the projection service or remain on the legacy path explicitly. They must not silently draw orthogonal overlays over a projected world.

### Objects and shapes

The existing shape decoder and draw routines remain the source of palette/remap/translucency behavior. Add a reusable transformed-frame/cache layer that:

1. Decodes raw or RLE source pixels into an indexed-color temporary representation while preserving transparent pixels.
2. Applies the affine scale/skew implied by the selected projection around the shape's logical anchor/pivot using nearest-neighbor sampling initially.
3. Stores the transformed indexed pixels and destination offset/bounds.
4. Draws the result through the existing transparent/remapped/translucent image-buffer operations so palette selection remains a draw-time concern.

The cache key includes source shape/frame identity, projection mode, transform parameters/version, and any source dimensions needed to prevent stale reuse. Legacy mode bypasses this cache and calls the existing shape path unchanged. A transformed frame must retain enough source metadata for cache invalidation when shape data or palette-related render state changes.

The first implementation may use a per-frame temporary buffer if the image-buffer API cannot safely draw an affine result directly. It must not mutate the original shape cache or source VGA data.

### Ordering and effects

Logical tile coordinates remain authoritative. Painter ordering continues to use logical depth (with lift/object dependencies preserved), while projected screen rectangles determine clipping. Effects such as sprites, projectiles, weather, and animated overlays must project their world anchors through the shared service before drawing. Their screen-space labels and UI effects remain unprojected where they are currently screen-space.

## Configuration and user selection

Use `config/video/projection` as the runtime setting. Accepted names are `legacy`, `diamond`, `true_iso`, and `dimetric`; invalid or missing values fall back to `legacy` without failing startup. This is a session/video preference and does not require a savegame format field.

Expose the setting in the existing video/display options UI if that UI can select a string or enum without changing unrelated controls. Changing the setting must:

- update the shared projection service;
- invalidate transformed shape and projected terrain caches;
- reset or rebase camera interpolation state if the old and new bases have different dimensions;
- mark the world and effects dirty;
- repaint before the options dialog returns to gameplay.

## Testing strategy

Tests are written before the implementation changes and must provide a failing test for each new behavior.

### Projection math tests

- Legacy projection reproduces current `Get_shape_location` coordinates, including lift and wrapping.
- Each non-legacy mode has the expected basis and lift direction.
- `unproject(project(tile, 0))` round-trips representative positive, negative, and wrapped tile coordinates.
- `tile_bounds` is non-empty and contains all four projected ground corners.
- Invalid configuration values select `legacy`.
- Projection changes produce different coordinates for at least one representative tile in each non-legacy mode.

### Pixel transform tests

- Raw and RLE source frames produce equivalent transformed output.
- Transparent source pixels remain transparent.
- A small asymmetric test image lands at the expected transformed coordinates for each mode.
- Legacy mode is byte-identical to the existing untransformed draw path.
- Source frame data is not modified by transformation or cache reuse.

### Renderer integration checks

- A headless/software render can initialize each mode and paint a clipped map region without an assertion or out-of-bounds write.
- Projected selection/hit testing returns the tile under representative screen points.
- Effects and object anchors agree with terrain tile anchors.
- Gumps and screen-space text retain their existing screen positions after a projection change.

If the repository's native build does not already provide a C++ unit-test runner, add the smallest project-local test target that can exercise the projection and transform helpers without requiring a game data installation. The normal build must include all new production sources for supported build systems.

## Build and documentation changes

Add the new projection and transform sources to the autotools/common object lists and the maintained Visual Studio project. Keep headers in the corresponding source/header lists so a clean build sees them. Update the isometric documentation after behavior is implemented, clearly distinguishing compatibility mode from the three projected modes.

## Acceptance criteria

The feature is complete when:

1. The default `legacy` setting produces the existing renderer's placement and appearance.
2. Selecting each non-legacy mode projects terrain, objects, effects, overlays, and hit testing consistently.
3. Source tile/shape bitmaps are transformed only where needed and remain palette-indexed, transparent, and immutable.
4. Switching modes during a running session invalidates stale render data and repaints correctly.
5. Unit tests cover projection math and pixel transforms, integration checks cover a clipped render, and all available build/test commands pass.
