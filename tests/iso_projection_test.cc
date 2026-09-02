#include "iso_projection.h"
#include "dir.h"

#include <cassert>
#include <string>

static void expect(bool condition) {
	assert(condition);
}

int main() {
	const IsoProjection legacy(IsoKind::Legacy);
	int               sx = 0;
	int               sy = 0;
	int               depth = 0;
	legacy.project(3, 5, 2, sx, sy, depth);
	expect(sx == 16);
	expect(sy == 32);
	expect(depth == 8);

	for (const IsoKind kind : {IsoKind::Diamond, IsoKind::TrueIso, IsoKind::Dimetric}) {
		const IsoProjection projection(kind);
		projection.project(7, 4, 0, sx, sy, depth);
		int tx = 0;
		int ty = 0;
		expect(projection.unproject(sx, sy, tx, ty));
		expect(tx == 7 && ty == 4);
		int x = 0;
		int y = 0;
		int w = 0;
		int h = 0;
		projection.tile_bounds(7, 4, 0, x, y, w, h);
		expect(w > 0 && h > 0);
	}

	expect(IsoProjection::from_name("invalid").kind == IsoKind::Legacy);
	expect(IsoProjection::from_name("isometric").kind == IsoKind::TrueIso);
	expect(IsoProjection::from_name("true_iso").kind == IsoKind::TrueIso);
	expect(IsoProjection::from_name("diamond").kind == IsoKind::Legacy);
	expect(IsoProjection::from_name("dimetric").kind == IsoKind::Legacy);
	expect(std::string(IsoProjection(IsoKind::TrueIso).name()) == "isometric");

	const IsoTileRange visible = IsoProjection(IsoKind::Diamond).visible_tiles(-4, 0, 8, 4, 1);
	expect(visible.min_tx <= 0 && visible.max_tx >= 1);
	expect(visible.min_ty <= 0 && visible.max_ty >= 1);

	// Tile coordinates grow southward on Y, while Get_direction uses
	// Cartesian Y where positive means north.
	expect(Get_direction_from_tile_delta(0, -1) == north);
	expect(Get_direction_from_tile_delta(1, 0) == east);
	expect(Get_direction_from_tile_delta(0, 1) == south);
	expect(Get_direction_from_tile_delta(-1, 0) == west);

	// A raised 8x8 top face must remain a translated copy of the terrain
	// diamond. Treating source Y alone as height bends one edge and creates
	// the visible staircase along adjacent wall sections.
	const IsoProjection true_iso(IsoKind::TrueIso);
	// An object's render depth is determined by its nearest ground-plane
	// corner. This keeps a character in front of a second-floor wall when
	// their projected pixels overlap.
	expect(true_iso.projected_object_depth(11, 20) > true_iso.projected_object_depth(10, 20));
	expect(true_iso.projected_object_depth(10, 20) == 30);
	expect(IsoProjection(IsoKind::Dimetric).projected_object_depth(10, 20) == 30);
	// Objects on opposite world axes can overlap after projection. Their
	// painter order must still follow projected depth, with elevation deciding
	// the order of stacked floors at the same ground depth.
	expect(true_iso.compare_projected_objects(10, 20, 0, 11, 19, 0) < 0);
	expect(true_iso.compare_projected_objects(11, 19, 0, 10, 20, 0) > 0);
	expect(true_iso.compare_projected_objects(10, 20, 0, 11, 19, 1) < 0);
	expect(true_iso.compare_projected_objects(10, 20, 1, 11, 19, 0) > 0);
	// Two True Iso lift units have the same projected depth as three ground
	// units. This case must not collapse to the lexicographic tx+ty/tz
	// tie-break used by the old comparator.
	expect(true_iso.compare_projected_objects(10, 20, 2, 12, 20, 0) > 0);
	// Dimetric uses a different, fractional vertical depth contribution.
	const IsoProjection dimetric_depth(IsoKind::Dimetric);
	expect(dimetric_depth.compare_projected_objects(10, 20, 2, 12, 20, 0) > 0);
	// Ordering must use the full ground footprint. A wide object can reach
	// the same projected depth as a later anchor, so anchor-only ordering
	// would incorrectly force a dependency between the two shapes.
	expect(true_iso.compare_projected_objects(10, 20, 0, 1, 1, 1, 12, 20, 0, 5, 1, 1) == 0);
	// The painter depth must use the same lift scale as transformed sprites.
	expect(true_iso.projected_depth(0, 0, 2) == 3.0);
	expect(dimetric_depth.projected_depth(0, 0, 2) == 3.0);
	true_iso.project_sprite_pixel(-16, -8, sx, sy);
	expect(sx == -7 && sy == -16);
	true_iso.project_sprite_pixel(-8, -8, sx, sy);
	expect(sx == 0 && sy == -12);
	true_iso.project_sprite_pixel(-8, -16, sx, sy);
	expect(sx == 7 && sy == -16);
	// A separately placed upper-floor object must use the same vertical
	// displacement as the transformed top of the wall supporting it.
	int wall_top_x = 0;
	int wall_top_y = 0;
	int upper_x = 0;
	int upper_y = 0;
	true_iso.project_sprite_pixel(-20, -20, 8, 8, 20, wall_top_x, wall_top_y);
	true_iso.project(0, 0, 5, upper_x, upper_y, depth);
	expect(upper_x == wall_top_x && upper_y == wall_top_y);

	const IsoProjection dimetric(IsoKind::Dimetric);
	dimetric.project_sprite_pixel(-16, -8, sx, sy);
	expect(sx == -7 && sy == -13);
	dimetric.project_sprite_pixel(-8, -8, sx, sy);
	expect(sx == 0 && sy == -10);
	dimetric.project_sprite_pixel(-8, -16, sx, sy);
	expect(sx == 7 && sy == -13);
	dimetric.project_sprite_pixel(-20, -20, 8, 8, 20, wall_top_x, wall_top_y);
	dimetric.project(0, 0, 5, upper_x, upper_y, depth);
	expect(upper_x == wall_top_x && upper_y == wall_top_y);

	// Multi-tile walls use their actual footprint. A 1x3 wall top must keep
	// the same long edge as three adjacent projected terrain tiles.
	true_iso.project_sprite_pixel(-8, -32, 8, 24, 8, sx, sy);
	expect(sx == 21 && sy == -24);
	true_iso.project_sprite_pixel(-8, -8, 8, 24, 8, sx, sy);
	expect(sx == 0 && sy == -12);
	dimetric.project_sprite_pixel(-8, -32, 8, 24, 8, sx, sy);
	expect(sx == 21 && sy == -19);
	dimetric.project_sprite_pixel(-8, -8, 8, 24, 8, sx, sy);
	expect(sx == 0 && sy == -10);
	return 0;
}
