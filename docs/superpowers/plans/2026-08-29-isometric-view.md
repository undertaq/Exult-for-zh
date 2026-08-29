# Isometric View Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add runtime-selectable legacy, diamond, true-isometric, and dimetric world views to the software renderer, transforming indexed tile/shape pixels when the selected projection requires it while leaving screen-space UI unchanged.

**Architecture:** Keep the current square/orthogonal renderer as an explicit `legacy` compatibility path. Route world tile placement, inverse hit testing, depth, terrain enumeration, effects, and overlays through a shared `IsoProjection` service. For non-legacy modes, decode raw/RLE indexed pixels into immutable cached rasters, apply a deterministic nearest-neighbor affine projection, and draw through `Image_buffer8` so transparency, palette remapping, and translucency remain intact.

**Tech Stack:** C++17, existing Exult `Image_buffer8`/`Shape_frame` software renderer, autotools, MinGW makefiles, Visual Studio 2019 project, native C++ test executable under `make check`.

**Spec:** `docs/superpowers/specs/2026-08-29-isometric-view-design.md`

## Global Constraints

- `legacy` is the default and must retain the current `Game_window::Get_shape_location` and cached square-flat behavior.
- Accepted configuration values are `legacy`, `diamond`, `true_iso`, and `dimetric`; missing or invalid values select `legacy`.
- Logical `Tile_coord` values remain authoritative; projection affects world rendering and inverse screen hit testing only.
- Gumps, text, cursor UI, drag previews, menus, and other screen-space drawing remain unprojected.
- Source VGA data and existing shape caches are immutable; transformed rasters are separate cache entries keyed by source frame and projection.
- Pixel index `0` remains transparent in transformed output, and palette remapping/translucency is applied when the transformed raster is drawn.
- Do not add a savegame field for the projection; persist the value through the normal video configuration only.
- Every behavior change starts with a failing native C++ test and ends with a focused test run plus a commit.

## File map

| File | Responsibility in this feature |
| --- | --- |
| `gamerend/iso_projection.h`, `gamerend/iso_projection.cc` | Projection modes, basis math, deterministic rounding, config-name conversion, forward/inverse mapping, tile bounds. |
| `gamerend/iso_raster.h`, `gamerend/iso_raster.cc` | Indexed raster representation and nearest-neighbor projection transform. |
| `shapes/vgafile.h`, `shapes/vgafile.cc` | Decode raw/RLE frames into rasters, cache transformed frames, draw transformed frames. |
| `imagewin/ibuf8.h`, `imagewin/ibuf8.cc` | Draw a transparent indexed raster with optional remap/translucency semantics. |
| `shapeid.h` | Separate world-shape drawing from UI-shape drawing. |
| `gamerend.h`, `gamerend.cc` | Projection-aware terrain enumeration, flat drawing, depth/overlay routing, and legacy fast path. |
| `gamewin.h`, `gamewin.cc` | Projection state, shape locations/rectangles, screen-to-tile conversion, object hit testing, config load, repaint invalidation. |
| `objs/objs.cc`, `objs/iregobjs.cc`, `actors.cc` | Route world object, actor, and weapon drawing through the world-shape API. |
| `effects.cc` | Route world effect anchors through shared projection placement. |
| `gumps/GameDisplayOptions_gump.h`, `gumps/GameDisplayOptions_gump.cc` | Read, display, save, and apply the projection setting without projecting gump graphics. |
| `tiles.h` | Keep logical tile distance helpers independent of screen basis; add only projection-specific screen helper declarations if required by tests. |
| `tests/iso_projection_test.cc`, `tests/iso_raster_test.cc`, `tests/iso_shape_test.cc`, `tests/Makefile.am` | Native unit tests for projection math, raster transforms, shape decoding/drawing semantics, and configuration parsing. |
| `Makefile.am`, `Makefile.common`, `Makefile.mingw`, `configure.ac` | Autotools/common/MinGW source and test integration. |
| `msvcstuff/vs2019/Exult.vcxproj`, `msvcstuff/vs2019/Exult.vcxproj.filters` | Visual Studio source integration. |
| `docs/iso_projection.md` | User/developer documentation for the implemented modes and compatibility behavior. |

---

### Task 1: Replace the partial selector with tested projection math

**Files:**
- Modify: `gamerend/iso_projection.h`
- Modify: `gamerend/iso_projection.cc`
- Create: `tests/iso_projection_test.cc`
- Create: `tests/Makefile.am`
- Modify: `Makefile.am`
- Modify: `configure.ac`

**Interfaces:**
- Produces `enum class IsoKind { Legacy, Diamond, TrueIso, Dimetric }`.
- Produces `IsoProjection::project(int tx, int ty, int tz, int& sx, int& sy, int& depth) const`.
- Produces `IsoProjection::unproject(int sx, int sy, int& tx, int& ty) const`.
- Produces `IsoProjection::tile_bounds(int tx, int ty, int tz, int& x, int& y, int& w, int& h) const`.
- Produces `IsoProjection::from_name(const std::string&)`, `IsoProjection::name()`, and `IsoProjection::is_legacy()`.
- Keeps `IsoProjection::current()` and `set_current()` as the process-local selector used by the main thread.

- [ ] **Step 1: Write the failing projection test**

Create a small assertion-based executable. Its first cases must describe the compatibility contract and the four-corner bounds contract:

```cpp
#include "iso_projection.h"

#include <cassert>
#include <string>

static void expect(bool condition) {
    assert(condition);
}

int main() {
    const IsoProjection legacy(IsoKind::Legacy);
    int sx = 0, sy = 0, depth = 0;
    legacy.project(3, 5, 2, sx, sy, depth);
    expect(sx == 16);
    expect(sy == 32);
    expect(depth == 8);

    for (const IsoKind kind : {IsoKind::Diamond, IsoKind::TrueIso, IsoKind::Dimetric}) {
        const IsoProjection projection(kind);
        projection.project(7, 4, 0, sx, sy, depth);
        int tx = 0, ty = 0;
        expect(projection.unproject(sx, sy, tx, ty));
        expect(tx == 7 && ty == 4);
        int x = 0, y = 0, w = 0, h = 0;
        projection.tile_bounds(7, 4, 0, x, y, w, h);
        expect(w > 0 && h > 0);
    }

    expect(IsoProjection::from_name("invalid").kind == IsoKind::Legacy);
    expect(std::string(IsoProjection(IsoKind::Diamond).name()) == "diamond");
}
```

- [ ] **Step 2: Add the minimal native test target and run it red**

Add `tests/Makefile.am` with `check_PROGRAMS = iso_projection_test`, `TESTS = iso_projection_test`, and sources `iso_projection_test.cc`, `$(top_srcdir)/gamerend/iso_projection.cc`. Add `tests` to the root `SUBDIRS` and `tests/Makefile` to `AC_CONFIG_FILES`.

Run from a configured autotools build directory:

```text
make -C tests check
```

Expected: compilation or assertions fail because `Legacy`, config parsing, and the corrected bounds implementation do not yet exist.

- [ ] **Step 3: Implement the four projection modes**

Replace the partial three-value enum and stale savegame methods with the tested API. Use these basis values at `c_tilesize == 8`, preserving floating-point constants internally and `std::lround` at the integer boundary:

```cpp
// screen x = (tx - ty) * horizontal_basis
// screen y = (tx + ty) * vertical_basis - tz * 4
Legacy   : (8, 8)      // current square view; adapter applies legacy lift to both axes
Diamond  : (4, 2)
TrueIso  : (6.928203, 4)
Dimetric : (6.928203, 3.2)
```

Keep legacy’s current square placement explicit. For projected modes, invert the 2x2 ground basis, round the resulting logical coordinates, and return `false` only for a singular basis. Compute `tile_bounds` by projecting `(tx,ty)`, `(tx+1,ty)`, `(tx,ty+1)`, and `(tx+1,ty+1)` and taking the min/max rectangle.

- [ ] **Step 4: Run the projection test green**

Run:

```text
make -C tests check
```

Expected: `iso_projection_test` passes, including legacy lift behavior, all three round trips, non-empty bounds, and invalid-name fallback.

- [ ] **Step 5: Commit the projection unit**

```text
git add gamerend/iso_projection.h gamerend/iso_projection.cc tests/iso_projection_test.cc tests/Makefile.am Makefile.am configure.ac
git commit -m "feat: add tested world projection math"
```

### Task 2: Add an indexed raster transform and drawing primitive

**Files:**
- Create: `gamerend/iso_raster.h`
- Create: `gamerend/iso_raster.cc`
- Create: `tests/iso_raster_test.cc`
- Modify: `tests/Makefile.am`
- Modify: `imagewin/ibuf8.h`
- Modify: `imagewin/ibuf8.cc`

**Interfaces:**
- Produces `struct IsoRaster { int width; int height; int xleft; int yabove; std::vector<unsigned char> pixels; }`.
- Produces `IsoRaster decode_raw_raster(const unsigned char*, int width, int height, int xleft, int yabove)`.
- Produces `IsoRaster decode_rle_raster(const unsigned char*, int width, int height, int xleft, int yabove)` for Exult's zero-terminated scanline encoding.
- Produces `IsoRaster transform_iso_raster(const IsoRaster&, IsoKind)`.
- Produces `Image_buffer8::copy_transparent8(const unsigned char*, int, int, int, int, const Xform_palette*, int, const unsigned char*)` as a non-virtual overload that preserves existing five-argument callers.

- [ ] **Step 1: Write failing raster tests**

Use a 3x2 asymmetric indexed image with one transparent pixel and assert output dimensions, transformed positions, transparent preservation, and source immutability:

```cpp
#include <algorithm>
#include <vector>

static IsoRaster sample() {
    return IsoRaster{3, 2, 1, 1, {1, 2, 0, 3, 4, 5}};
}

int main() {
    const IsoRaster source = sample();
    const IsoRaster before = source;
    const IsoRaster diamond = transform_iso_raster(source, IsoKind::Diamond);
    assert(diamond.width > 0 && diamond.height > 0);
    assert(diamond.pixels != std::vector<unsigned char>(diamond.width * diamond.height, 0));
    assert(source.width == before.width && source.pixels == before.pixels);
    assert(std::count(diamond.pixels.begin(), diamond.pixels.end(), 0) > 0);
    assert(transform_iso_raster(source, IsoKind::Legacy).pixels == source.pixels);
}
```

Add a second case that transforms the same source through `TrueIso` and `Dimetric` and asserts distinct bounds.

- [ ] **Step 2: Run the raster test red**

Run:

```text
make -C tests check
```

Expected: compile failure because `IsoRaster` and `transform_iso_raster` are not defined.

- [ ] **Step 3: Implement immutable nearest-neighbor projection**

For every nonzero source pixel at coordinates relative to the source origin, project its pixel center using the selected basis. First compute destination min/max from all source corners, allocate a zero-filled destination, then place each nonzero source pixel at the rounded projected coordinate. Store the transformed origin as `xleft = -min_x` and `yabove = -min_y`. Legacy returns a value copy with the original pixels and offsets.

Implement `decode_raw_raster` as a checked row-major copy and `decode_rle_raster` with the same raw/encoded scanline rules used by `Image_buffer8::paint_rle`: read the 16-bit length, signed 16-bit x/y offsets, then either copy literal bytes or expand count/value pairs until the scanline is filled. Ignore pixels outside the declared raster and leave them transparent.

- [ ] **Step 4: Implement transparent indexed drawing with draw-time palette operations**

Add the overload below in `Image_buffer8` and implement clipping exactly like `copy_transparent8`:

```cpp
void copy_transparent8(
    const unsigned char* src_pixels, int srcw, int srch, int destx, int desty,
    const Xform_palette* xforms, int xfcnt, const unsigned char* trans);
```

For each nonzero source pixel, apply `trans[pix]` first when present; skip a result of `255`. For pixels in the translucency range `0xff - xfcnt` through `0xfe`, apply the selected xform to the destination pixel; otherwise write the final source pixel. Keep all writes inside the current clip rectangle.

- [ ] **Step 5: Run raster tests green and commit**

Run:

```text
make -C tests check
```

Expected: both projection and raster tests pass.

```text
git add gamerend/iso_raster.h gamerend/iso_raster.cc tests/iso_raster_test.cc tests/Makefile.am imagewin/ibuf8.h imagewin/ibuf8.cc
git commit -m "feat: add indexed isometric raster transforms"
```

### Task 3: Decode and render projected world shapes without affecting UI shapes

**Files:**
- Modify: `shapes/vgafile.h`
- Modify: `shapes/vgafile.cc`
- Modify: `shapeid.h`
- Modify: `objs/objs.cc`
- Modify: `objs/iregobjs.cc`
- Modify: `actors.cc`
- Create: `tests/iso_shape_test.cc`
- Modify: `tests/Makefile.am`

**Interfaces:**
- Produces `Shape_frame::paint_projected(Image_buffer8*, int xoff, int yoff, IsoKind, const Xform_palette*, int, const unsigned char*)`.
- Produces `Shape_frame::has_projected_point(int x, int y, IsoKind) const`.
- Produces `Shape_manager::paint_world_shape(...)` and `ShapeID::paint_world_shape(...)` with the same palette/remap arguments as normal shape painting.
- Adds the test-local helper `std::vector<unsigned char> render_shape(Shape_frame&, IsoKind)` to render a frame into a clipped `Image_buffer8` and return its pixels.
- Existing `paint_shape`, gump painting, menu painting, and screen effects remain unchanged.

- [ ] **Step 1: Add a failing world-shape test case**

Create `tests/iso_shape_test.cc` with a raw 8x8 `Shape_frame` whose pixels contain an asymmetric nonzero pattern. The test-local helper below renders a frame into a clipped `Image_buffer8` and returns its bytes:

```cpp
static std::vector<unsigned char> render_shape(Shape_frame& frame, IsoKind kind) {
    Image_buffer8 target(64, 64);
    target.fill8(0);
    target.set_clip(0, 0, 64, 64);
    frame.paint_projected(&target, 32, 32, kind, nullptr, 0, nullptr);
    return std::vector<unsigned char>(target.get_bits(), target.get_bits() + 64 * 64);
}

assert(render_shape(raw, IsoKind::Legacy) == render_shape(raw, IsoKind::Legacy));
assert(render_shape(raw, IsoKind::Diamond) == render_shape(rle, IsoKind::Diamond));
assert(render_shape(raw, IsoKind::Diamond) != render_shape(raw, IsoKind::Legacy));
```

Construct `rle` from the same source pixels with `Shape_frame::encode_rle`, then add the test executable to `tests/Makefile.am` and link it with the already-built `shapes/libshapes.la`, `imagewin/libimagewin.la`, `files/libu7file.la`, and `$(SYSLIBS)` libraries.

- [ ] **Step 2: Run the shape test red**

Run:

```text
make -C tests check
```

Expected: compile failure because the world-shape methods and transformed frame path do not exist.

- [ ] **Step 3: Decode raw and RLE frames into `IsoRaster`**

In `Shape_frame`, use `xleft`, `yabove`, `get_width()`, and `get_height()` to create the source raster. Raw frames call `decode_raw_raster`; RLE frames call `decode_rle_raster` with the stored data and extents. The decoder initializes the raster to zero and writes decoded nonzero pixels at `scanx + xleft`, `scany + yabove`.

- [ ] **Step 4: Cache transformed frames by mode without mutating source data**

Add four mutable `std::unique_ptr<IsoRaster>` cache slots to `Shape_frame`, indexed by `IsoKind`. Build a slot from the immutable source frame only on first use; legacy returns the source path without allocating a transformed slot. This cache is safe because frame pixels and dimensions do not change after load; `Shape_frame::set_offset` must clear all transformed slots.

- [ ] **Step 5: Route only world shapes through transformed drawing**

Add `Shape_manager::paint_world_shape` beside `paint_shape`. It selects the current projection and calls `Shape_frame::paint_projected` for non-legacy modes while preserving the existing remap/translucency branch ordering. Add `ShapeID::paint_world_shape` beside `paint_shape`, then update `Game_object::paint`, `Ireg_game_object::paint`, actor body drawing, and actor weapon drawing to use it. Leave gump, browser, conversation, menu, and drag-preview callers on `paint_shape`.

- [ ] **Step 6: Add projected point containment and run tests green**

Implement `has_projected_point` by transforming the queried point into the cached raster’s coordinate space and checking the nonzero pixel. Run:

```text
make -C tests check
```

Expected: legacy raw rendering remains unchanged, raw/RLE projected footprints agree, transparent pixels remain empty, and source frame data remains unchanged.

- [ ] **Step 7: Commit world-shape rendering**

```text
git add shapes/vgafile.h shapes/vgafile.cc shapeid.h objs/objs.cc objs/iregobjs.cc actors.cc tests
git commit -m "feat: render world shapes through projection transforms"
```

### Task 4: Render terrain through projected tile anchors while retaining the legacy fast path

**Files:**
- Modify: `gamerend.h`
- Modify: `gamerend.cc`
- Modify: `objs/chunkter.cc`
- Modify: `objs/chunkter.h`

**Interfaces:**
- Produces `Game_render::paint_projected_map(int x, int y, int w, int h)`.
- Produces `Game_render::paint_projected_tile(int tx, int ty, int tz)` as the single projected flat-tile draw helper.
- Keeps `paint_chunk_flats` and `paint_chunk_flat_rles` as the legacy-only cached chunk path.

- [ ] **Step 1: Add a failing clipped terrain smoke test**

Add a test helper that projects a 3x3 logical tile neighborhood into a clipped `Image_buffer8` and asserts every tile’s projected bounds intersects the expected clip region exactly once. Assert the selector’s dispatch predicate directly so the legacy and projected branches cannot be swapped:

```cpp
assert(IsoProjection(IsoKind::Legacy).is_legacy());
assert(!IsoProjection(IsoKind::Diamond).is_legacy());
```

- [ ] **Step 2: Run the terrain test red**

Run:

```text
make -C tests check
```

Expected: compile failure because the projected map path and mode dispatch do not exist.

- [ ] **Step 3: Add projected tile enumeration**

In `paint_map`, branch immediately after clip setup: legacy continues through the current chunk calculations; non-legacy calls `paint_projected_map`. Unproject all four clip corners, expand the logical range by two tiles, normalize with `c_num_tiles`, and iterate the resulting tile rectangle. For each logical tile, obtain `Map_chunk::get_chunk(cx, cy)->get_terrain()->get_flat(localx, localy)`, compute its projected anchor relative to `scrolltx/scrollty`, and draw it with `paint_world_shape`.

- [ ] **Step 4: Project the terrain tile anchor and flat bitmap**

Use `IsoProjection::project` for the tile anchor and pass the resulting anchor to `ShapeID::paint_world_shape`. The tile shape path transforms its indexed pixels to the selected footprint. Keep the existing `skip_lift` and map-editor branches explicit; projected terrain-editor drawing uses the same tile loop and does not call `copy8` at orthogonal offsets.

- [ ] **Step 5: Preserve painter depth and projected clipping**

Sort or iterate projected tile candidates by the projection depth returned from `project`, using stable logical `tx + ty` order for ties. Clip through the existing `Image_window8` clip rectangle. Do not enlarge the world bounds by assuming `x / c_tilesize` identifies a tile in non-legacy modes.

- [ ] **Step 6: Update projected chunk/editor overlays and run tests green**

Route selected-chunk fills, chunk outlines, dungeon blackness bounds, and tile-grid lines through projected tile bounds in non-legacy mode. Keep the current rectangular routines for legacy. Run:

```text
make -C tests check
```

Expected: projection math, raster, shape, and terrain smoke tests pass.

- [ ] **Step 7: Commit projected terrain**

```text
git add gamerend.h gamerend.cc objs/chunkter.h objs/chunkter.cc tests
git commit -m "feat: render terrain with projected tile anchors"
```

### Task 5: Route camera placement, effects, hit testing, and world overlays through the projection

**Files:**
- Modify: `gamewin.h`
- Modify: `gamewin.cc`
- Modify: `effects.cc`
- Modify: `cheat.cc`
- Modify: `drag.cc`
- Modify: `exult.cc`

**Interfaces:**
- Produces `Game_window::screen_to_tile(int x, int y, Tile_coord& tile) const`.
- Produces `Game_window::get_projection() const` and `Game_window::set_projection(IsoKind)`.
- Makes `get_shape_location`, `get_shape_rect`, `get_flat`, `find_object`, and `show_game_location` projection-aware.
- Keeps drag previews and gump hit testing in screen space.

- [ ] **Step 1: Add failing inverse-placement and hit-test tests**

For each non-legacy mode, project representative ground tiles relative to a fixed camera and assert `IsoProjection::unproject` returns the same relative tile. Add a projected shape test where the point is inside a transformed nonzero pixel and a neighboring transparent point is rejected.

```cpp
for (const IsoKind kind : {IsoKind::Diamond, IsoKind::TrueIso, IsoKind::Dimetric}) {
    const IsoProjection projection(kind);
    const int relative_tx = 7 - 100;
    const int relative_ty = 4 - 200;
    int screen_x = 0, screen_y = 0, depth = 0;
    projection.project(relative_tx, relative_ty, 0, screen_x, screen_y, depth);
    Tile_coord actual;
    int actual_tx = 0, actual_ty = 0;
    assert(projection.unproject(screen_x, screen_y, actual_tx, actual_ty));
    assert(actual_tx == relative_tx && actual_ty == relative_ty);
}
```

- [ ] **Step 2: Run inverse-placement tests red**

Run:

```text
make -C tests check
```

Expected: compile failure because `screen_to_tile` and projection-aware `Game_window` state do not exist.

- [ ] **Step 3: Centralize `Game_window` placement**

Add an `IsoProjection projection` member. Keep the current inline legacy helper unchanged in behavior. For non-legacy `get_shape_location`, normalize tile deltas relative to `scrolltx/scrollty`, call `projection.project`, subtract the existing one-pixel shape anchor adjustment, and apply smooth-scroll low parts after projection. `get_shape_rect` uses transformed frame offsets/bounds in non-legacy mode and the current rectangle in legacy mode.

- [ ] **Step 4: Replace orthogonal screen-to-tile assumptions**

Implement `screen_to_tile` using the projection inverse after adding `scrolltx_lo/scrollty_lo`; legacy uses the current integer division. Update `get_flat`, `find_object`, and `show_game_location` to call it. `find_object` enumerates a two-tile projected neighborhood around the inverse candidate, checks `get_shape_rect`, then calls `has_projected_point` in non-legacy mode.

- [ ] **Step 5: Route effects and world-only cheat overlays**

Replace direct `scrolltx * c_tilesize`, `scrollty * c_tilesize`, and fixed lift arithmetic in `effects.cc` with `gwin->get_shape_location(Tile_coord(...), x, y)` plus the effect’s local offsets. Update world tile-grid and selected-tile code in `cheat.cc`/`gamerend.cc` to draw projected bounds. Leave `Dragging_info::paint` and gump object painting screen-space because they are cursor/UI previews.

- [ ] **Step 6: Run inverse and effect tests green**

Run:

```text
make -C tests check
```

Expected: all representative tile round trips pass, transformed shape containment agrees with drawing, effects share terrain anchors, and legacy click coordinates remain unchanged.

- [ ] **Step 7: Commit projection-aware interaction**

```text
git add gamewin.h gamewin.cc effects.cc cheat.cc drag.cc exult.cc tests
git commit -m "feat: make world interaction projection-aware"
```

### Task 6: Load and expose the projection setting with safe cache invalidation

**Files:**
- Modify: `gamewin.cc`
- Modify: `gumps/GameDisplayOptions_gump.h`
- Modify: `gumps/GameDisplayOptions_gump.cc`

**Interfaces:**
- Configuration key: `config/video/projection`.
- `Game_window::set_projection(IsoKind)` invalidates world render state, resets incompatible interpolation offsets, and marks the full window dirty.
- Display options show `Legacy`, `Diamond`, `True Iso`, and `Dimetric`, save the canonical lower-case config value, and apply it before returning to gameplay.

- [ ] **Step 1: Add failing configuration tests**

Add cases for missing, invalid, and each accepted value. Assert canonical names and legacy fallback:

```cpp
assert(IsoProjection::from_name("").kind == IsoKind::Legacy);
assert(IsoProjection::from_name("true_iso").kind == IsoKind::TrueIso);
assert(IsoProjection::from_name("dimetric").kind == IsoKind::Dimetric);
```

- [ ] **Step 2: Run configuration tests red**

Run:

```text
make -C tests check
```

Expected: the accepted-name tests fail until startup and option wiring use the new selector.

- [ ] **Step 3: Load the setting during `Game_window` initialization**

Read `config/video/projection` with default `legacy`, call `set_projection(IsoProjection::from_name(value).kind)`, and write the canonical value back through the existing configuration object. Do not serialize the selection into `gamedat` or savegame streams.

- [ ] **Step 4: Apply projection changes safely**

In `set_projection`, return early for the same mode. Otherwise update `projection`, clear `avposx_ld`/`avposy_ld`, reset low scroll offsets, keep transformed-frame slots keyed by mode so no stale entry can be reused, and call `set_all_dirty()` on the window; effects are repainted as part of the normal world paint pass.

- [ ] **Step 5: Add the display-options control**

Add an integer selection member to `GameDisplayOptions_gump`, load the canonical config name, insert a four-option toggle beside smooth scrolling, save `config/video/projection`, and call `Game_window::get_instance()->set_projection(...)` after saving. The gump continues using normal `ShapeID::paint_shape` calls.

- [ ] **Step 6: Run configuration tests green and commit**

Run:

```text
make -C tests check
```

Expected: missing/invalid values select legacy, all valid values persist canonically, and changing modes marks the complete world dirty.

```text
git add gamewin.cc gumps/GameDisplayOptions_gump.h gumps/GameDisplayOptions_gump.cc tests
git commit -m "feat: add runtime projection selection"
```

### Task 7: Integrate all production and test sources into supported builds

**Files:**
- Modify: `Makefile.am`
- Modify: `Makefile.common`
- Modify: `Makefile.mingw`
- Modify: `configure.ac`
- Modify: `tests/Makefile.am`
- Modify: `msvcstuff/vs2019/Exult.vcxproj`
- Modify: `msvcstuff/vs2019/Exult.vcxproj.filters`

- [ ] **Step 1: Add production source lists**

Add `gamerend/iso_projection.cc`, `gamerend/iso_raster.cc`, and their headers to `EXULTSOURCES` in `Makefile.am`, `gamerend/iso_projection.o` and `gamerend/iso_raster.o` to `MAIN_OBJS` in `Makefile.common`, and the matching object/source entries in `Makefile.mingw`.

- [ ] **Step 2: Add the native test target to generated builds**

Use this `tests/Makefile.am` shape so tests compile the pure projection/raster units without a game-data installation:

```make
AM_CPPFLAGS = -I$(top_srcdir) -I$(top_srcdir)/headers
check_PROGRAMS = iso_projection_test iso_raster_test
TESTS = $(check_PROGRAMS)
iso_projection_test_SOURCES = iso_projection_test.cc $(top_srcdir)/gamerend/iso_projection.cc
iso_raster_test_SOURCES = iso_raster_test.cc $(top_srcdir)/gamerend/iso_projection.cc $(top_srcdir)/gamerend/iso_raster.cc
```

Keep integration smoke checks in the normal Exult build test invocation so they do not require a second renderer binary.

- [ ] **Step 3: Add Visual Studio entries**

Add both `.cc` files to the `ClCompile` item group, both headers to the `ClInclude` item group, and matching `ClCompile`/`ClInclude` filter entries under the existing Exult source filters. Do not add the test executable to the shipping Exult project.

- [ ] **Step 4: Regenerate and compile the test target**

Run:

```text
autoreconf -fi
configure
make -C tests check
```

Expected: both test executables build and pass from a clean generated build tree.

- [ ] **Step 5: Build the maintained Visual Studio target**

Run:

```text
msbuild msvcstuff/vs2019/Exult.sln /p:Configuration=Release /p:Platform=x64 /t:Exult /m
```

Expected: the Exult target compiles the new projection and raster sources without missing include or duplicate-symbol errors.

- [ ] **Step 6: Commit build integration**

```text
git add Makefile.am Makefile.common Makefile.mingw configure.ac tests/Makefile.am msvcstuff/vs2019/Exult.vcxproj msvcstuff/vs2019/Exult.vcxproj.filters
git commit -m "build: include isometric renderer sources"
```

### Task 8: Document behavior and perform final verification

**Files:**
- Modify: `docs/iso_projection.md`
- Modify: `docs/superpowers/specs/2026-08-29-isometric-view-design.md` only if implementation decisions require a factual correction

- [ ] **Step 1: Update projection documentation**

Document the four canonical values, `legacy` as the default compatibility mode, the indexed nearest-neighbor transform, the fact that UI remains screen-space, configuration location, and live application through the display-options dialog. Remove claims that diamond is byte-identical to the current renderer or that true/dimetric output remains unchanged.

- [ ] **Step 2: Run focused tests and diff checks**

Run:

```text
make -C tests check
git diff --check HEAD
```

Expected: all native tests pass and Git reports no whitespace errors.

- [ ] **Step 3: Run the full supported build**

Run:

```text
msbuild msvcstuff/vs2019/Exult.sln /p:Configuration=Release /p:Platform=x64 /t:Exult /m
```

Expected: the Release Exult target succeeds. If the current checkout lacks the generated autotools build dependencies, record that limitation separately while still requiring the native MSBuild verification.

- [ ] **Step 4: Inspect the final diff for scope safety**

Run:

```text
git status --short
git diff -- gamewin.cc gamerend.cc shapes/vgafile.cc effects.cc gumps/GameDisplayOptions_gump.cc
```

Confirm that unrelated user files remain unstaged/unmodified, screen-space gump call sites still use `paint_shape`, legacy placement is unchanged, and no savegame serialization was added.

- [ ] **Step 5: Commit documentation and verification notes**

```text
git add docs/iso_projection.md
git commit -m "docs: describe isometric view modes"
```
