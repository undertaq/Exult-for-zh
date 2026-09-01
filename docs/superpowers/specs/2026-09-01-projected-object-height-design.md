# Projected Object Height and Stacked-Level Alignment

## Status

Proposed design for review. This document covers the approved raster-based
approach: absolute world lift and local object height are separate inputs.

## Context

Non-legacy rendering currently places an object anchor with
`Game_window::get_shape_location()`, which projects the object's world
`Tile_coord::tz`. `ShapeID::paint_world_shape()` then supplies the shape's
footprint and `Shape_info::get_3d_height()` to
`Shape_frame::get_projected_sprite_raster()`. The raster path projects the
source bitmap with `project_sprite_pixel()` and estimates a per-pixel
elevation with `sprite_elevation_for()`.

This mixes two different concepts:

* absolute elevation: where the object is placed in the world;
* local geometry: the height of the object above its own base.

It also treats a wall's vertical artwork as a ground-plane bitmap, which
compresses its height. The immediate goal is to restore wall height and make
roofs/second-floor objects align with the wall top. The previously observed
bending effect is explicitly out of scope for this change.

## Goals

1. Preserve wall height according to the existing 3D shape metadata.
2. Place an upper-level object at exactly `base_z + wall_height`.
3. Use one canonical conversion from lift units to screen pixels.
4. Keep floating-point work out of the per-pixel raster loop.
5. Ensure fixed-point output has no visible or semantic difference from a
   floating-point reference for the same transform.
6. Preserve indexed-palette behavior, including palette index 0 and
   transparent coverage.

## Non-goals

* Correcting the current per-pixel bending/elevation heuristic.
* Replacing the 2D raster path with a general 3D mesh renderer.
* Reauthoring or manually editing game sprites.
* Changing legacy projection behavior.

## Design

### 1. Separate absolute lift from local height

The coordinate contract will be:

```text
base_z       = object's world elevation (`Tile_coord::tz`)
local_height = object's intrinsic height (`get_3d_height()`)

screen_anchor = project(world_x, world_y, base_z)
```

The raster cache and local raster transform must not include `base_z`; a
change in world elevation is a translation of the cached raster. This keeps
the cache reusable for all objects of the same shape, projection, geometry,
and orientation.

For a wall:

```text
wall_bottom_z = base_z
wall_top_z    = base_z + local_height
```

For a roof or second-level object, its world `Tile_coord::tz` must be
`wall_top_z`. Its own intrinsic height remains local to that object. Both
placements use the same `IsoProjection::liftpix_for()` conversion.

When a wall raster needs a relative top displacement, calculate it as the
difference between the canonical absolute endpoints:

```text
screen_delta_z = liftpix_for(base_z + local_height)
                 - liftpix_for(base_z)
```

This avoids a one-pixel mismatch caused by independently rounding two
floating-point products.

### 2. Add explicit raster projection profiles

The raster path will distinguish geometry instead of inferring all geometry
from pixel coordinates. The initial profiles are:

* `GroundFace`: existing ground/top-face behavior. It may continue using
  `sprite_elevation_for()` while the bending issue is deferred.
* `VerticalFace`: the source's vertical extent maps to local world Z. Its
  screen height is controlled by `local_height`, not by the ground-plane
  vertical coefficient.
* `Billboard`: reserved for a later upright/decorative sprite path and not
  required by this change.

The profile must be explicit at the shape-rendering boundary. It should be
represented by a small geometry/profile value passed to the raster transform,
not by another global scale. Existing shape metadata supplies the footprint
and height; a projection-profile policy supplies whether the shape is a
ground face or vertical face. A small override table is acceptable for
exceptions where the original data does not identify the face type.

For `VerticalFace`, the mapping is conceptually:

```text
screen = ground_anchor
         + projected_horizontal_axis(horizontal_source_coordinate)
         - lift_pixels(local_z)
```

The source vertical coordinate must not contribute to the ground-plane
`screen_x` direction and must not be reduced by the ground-plane `0.5` or
`0.4` Y scale. The horizontal wall axis still uses the selected isometric
basis. The profile carries the wall orientation so the two world ground axes
can use their correct signs.

### 3. Keep one source of truth for vertical conversion

`IsoProjection::liftpix_for()` will remain the authoritative mapping from
world lift units to screen pixels. The local-height projection helper,
object-anchor placement, projected bounds, and depth-related tests must all
use the same scale and rounding policy.

The existing conversion at the call site from `get_3d_height()` to source
pixel units should be removed or isolated behind the geometry/profile API.
The raster layer should receive a clearly named local height in lift units,
rather than an ambiguous `elevation_height` value that is partly pixels and
partly inferred Z.

### 4. Fixed-point rasterization without visual artifacts

The production rasterizer will use precomputed fixed-point inverse mapping:

* calculate projection coefficients once per raster/profile;
* store coefficients and accumulators in signed 64-bit Q32.32 fixed-point
  form; this gives sub-nanopixel coefficient resolution while retaining
  sufficient range for the largest supported raster;
* step source coordinates by integer additions across each destination row;
* use deterministic signed round-to-nearest behavior matching
  `std::lround()` at the public projection boundary;
* use source pixel-cell bounds, not only rounded source centers, when finding
  the destination extent;
* sample destination pixel centers with nearest-neighbor semantics;
* perform a small deterministic edge-sample fallback only when the center is
  outside a source cell, so thin wall edges are not lost;
* keep coverage separate from palette values.

A test-only floating-point reference implementation will use the same
pixel-center, nearest-neighbor, bounds, and coverage rules, and will consume
the same quantized Q32.32 coefficients as the production mapper. This makes
the comparison test the raster algorithm rather than two slightly different
projection definitions. For synthetic wall, roof, diagonal-edge, sparse,
and palette-index-0 rasters, tests will compare fixed-point and reference
results for:

* raster bounds and origin;
* coverage bitmap;
* destination palette values;
* wall top/bottom alignment.

Any mismatch is a test failure. This makes fixed-point precision a verified
compatibility requirement rather than a visual judgment. Additional numeric
tests will compare Q32.32 coordinates with the ideal double-precision
projection and require the error to remain below 1/256 screen pixel. The
reference code will not be used by the game renderer.

### 5. Caching and placement

The projected-raster cache key will include:

* projection kind;
* geometry/profile kind;
* footprint dimensions;
* local height;
* wall orientation, when applicable.

It will not include absolute `base_z`. `base_z` affects only the screen
anchor, so upper-level objects translate without producing duplicate raster
copies.

## Data flow

```text
Game_object::paint()
  -> get_shape_location(obj)
       -> project(tile.x, tile.y, tile.tz)
  -> ShapeID::paint_world_shape()
       -> profile + footprint + local_height
  -> Shape_frame::get_projected_sprite_raster()
       -> fixed-point profile transform
  -> copy projected raster at the already-lifted anchor
```

The wall and its roof must share a testable relationship:

```text
roof_anchor(base_z = wall_base_z + wall_height)
  == wall_anchor(base_z = wall_base_z) + wall_top_screen_delta
```

## Testing strategy

Add unit tests for:

1. `liftpix_for()` endpoint differences at several elevations and both
   non-legacy projection kinds.
2. A vertical-face wall whose top and bottom markers differ by exactly the
   metadata-defined local height.
3. A roof/second-floor anchor placed at the wall top.
4. Translation invariance: changing `base_z` moves the complete raster by
   the canonical lift delta without changing its pixels or coverage.
5. Fixed-point versus floating-point reference output for synthetic rasters,
   including thin one-pixel edges and transparent gaps.
6. Existing ground/top-face regression tests to ensure the deferred bending
   behavior and current terrain alignment are unchanged.

## Alternatives rejected

* Changing `kWorldSpriteVerticalScale` globally: cannot distinguish local
  wall height from ground-plane geometry and can break stacked alignment.
* Increasing `elevation_height` at the call site: changes the physical object
  height and makes the metadata-to-world-unit contract incorrect.
* Applying a post-transform vertical stretch: may make one sprite look right,
  but cannot guarantee that its top aligns with an independently placed upper
  object.
* Using floating point per pixel: unnecessary for indexed raster mapping and
  makes the performance requirement harder to guarantee.

## Acceptance criteria

The design is complete when a wall's rendered top is at the same projected
height as an object whose world Z equals the wall base plus its metadata
height, the wall does not suffer ground-plane vertical compression, and the
fixed-point raster output matches the floating-point reference for all test
fixtures. The existing bending behavior may remain until a later profile/
face-classification change.
