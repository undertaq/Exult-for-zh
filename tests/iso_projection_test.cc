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
	expect(std::string(IsoProjection(IsoKind::Diamond).name()) == "diamond");

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
	// True Iso's vertical basis is twice the ground depth increment for a
	// one-axis step. This case must not collapse to the lexicographic
	// tx+ty/tz tie-break used by the old comparator.
	expect(true_iso.compare_projected_objects(10, 20, 2, 13, 20, 0) > 0);
	// Dimetric uses a different, fractional vertical depth contribution.
	const IsoProjection dimetric_depth(IsoKind::Dimetric);
	expect(dimetric_depth.compare_projected_objects(10, 20, 2, 13, 20, 0) > 0);
	true_iso.project_sprite_pixel(-16, -8, sx, sy);
	expect(sx == -7 && sy == -16);
	true_iso.project_sprite_pixel(-8, -8, sx, sy);
	expect(sx == 0 && sy == -12);
	true_iso.project_sprite_pixel(-8, -16, sx, sy);
	expect(sx == 7 && sy == -16);

	const IsoProjection dimetric(IsoKind::Dimetric);
	dimetric.project_sprite_pixel(-16, -8, sx, sy);
	expect(sx == -7 && sy == -13);
	dimetric.project_sprite_pixel(-8, -8, sx, sy);
	expect(sx == 0 && sy == -10);
	dimetric.project_sprite_pixel(-8, -16, sx, sy);
	expect(sx == 7 && sy == -13);

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
