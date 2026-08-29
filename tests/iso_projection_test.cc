#include "iso_projection.h"

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
	return 0;
}
