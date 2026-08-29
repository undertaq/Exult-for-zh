/*
 *  iso_projection.cc - Pluggable isometric projection for the world view.
 *
 *  Copyright (C) 2026  The Exult Team
 *
 *  This program is free software; you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation; either version 2 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program; if not, write to the Free Software
 *  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
 */

#ifdef HAVE_CONFIG_H
#	include "config.h"
#endif

#include "iso_projection.h"

#include <algorithm>
#include <cmath>

namespace {

// Active projection (single global; engine is single-threaded for state).
IsoKind g_current_kind = IsoKind::Legacy;

struct Basis {
	double x;
	double y;
};

constexpr double kTrueIsoX = 0.8660254037844386 * c_tilesize;
constexpr double kTrueIsoY = 0.5 * c_tilesize;
constexpr double kDimetricX = kTrueIsoX;
constexpr double kDimetricY = 0.4 * c_tilesize;
// Standing art above its world origin needs a little more vertical span,
// while pixels on the ground must retain the terrain's exact edge angle.
constexpr double kWorldSpriteVerticalScale = 1.5;

double projected_lift_depth(IsoKind kind) {
	return kind == IsoKind::Diamond ? 2.0 : kWorldSpriteVerticalScale;
}

double sprite_elevation_for(
		int px, int py, int footprint_width, int footprint_height,
		int elevation_height) {
	const double highest = std::min(
			{static_cast<double>(std::max(0, elevation_height)),
			 static_cast<double>(-px), static_cast<double>(-py)});
	const double lowest = std::max(
			{0.0, static_cast<double>(-std::max(1, footprint_width) - px),
			 static_cast<double>(-std::max(1, footprint_height) - py)});
	if (highest >= lowest) {
		return highest;
	}
	// Decorative pixels can extend outside the collision box. Keep them at
	// the closest valid elevation instead of introducing a discontinuity.
	return std::clamp(
			std::min(static_cast<double>(-px), static_cast<double>(-py)),
			0.0, static_cast<double>(std::max(0, elevation_height)));
}

inline Basis basis_for(IsoKind k) {
	switch (k) {
	case IsoKind::Legacy:
		return {static_cast<double>(c_tilesize), static_cast<double>(c_tilesize)};
	case IsoKind::Diamond:
		return {c_tilesize / 2.0, c_tilesize / 4.0};
	case IsoKind::TrueIso:
		return {kTrueIsoX, kTrueIsoY};
	case IsoKind::Dimetric:
		return {kDimetricX, kDimetricY};
	}
	return {static_cast<double>(c_tilesize), static_cast<double>(c_tilesize)};
}

}    // namespace

const char* IsoProjection::name() const {
	switch (kind) {
	case IsoKind::Legacy:
		return "legacy";
	case IsoKind::Diamond:
		return "diamond";
	case IsoKind::TrueIso:
		return "true_iso";
	case IsoKind::Dimetric:
		return "dimetric";
	default:
		return "legacy";
	}
}

IsoProjection IsoProjection::from_name(const std::string& value) {
	if (value == "diamond") {
		return IsoProjection(IsoKind::Diamond);
	}
	if (value == "true_iso") {
		return IsoProjection(IsoKind::TrueIso);
	}
	if (value == "dimetric") {
		return IsoProjection(IsoKind::Dimetric);
	}
	return IsoProjection(IsoKind::Legacy);
}

double IsoProjection::projected_depth(int tx, int ty, int tz) const {
	if (kind == IsoKind::Legacy) {
		return tx + ty;
	}
	return tx + ty + tz * projected_lift_depth(kind);
}

int IsoProjection::compare_projected_objects(
		int tx1, int ty1, int tz1, int tx2, int ty2, int tz2) const {
	const double depth1 = projected_depth(tx1, ty1, tz1);
	const double depth2 = projected_depth(tx2, ty2, tz2);
	if (std::abs(depth1 - depth2) > 1e-9) {
		return depth1 < depth2 ? -1 : 1;
	}
	if (tx1 != tx2) {
		return tx1 < tx2 ? -1 : 1;
	}
	if (ty1 != ty2) {
		return ty1 > ty2 ? -1 : 1;
	}
	return 0;
}

int IsoProjection::compare_projected_objects(
		int tx1, int ty1, int tz1, int xs1, int ys1, int zs1,
		int tx2, int ty2, int tz2, int xs2, int ys2, int zs2) const {
	const int xspan1 = std::max(1, xs1);
	const int yspan1 = std::max(1, ys1);
	const int zspan1 = std::max(1, zs1);
	const int xspan2 = std::max(1, xs2);
	const int yspan2 = std::max(1, ys2);
	const int zspan2 = std::max(1, zs2);
	const double far1 = projected_depth(
			tx1 - xspan1 + 1, ty1 - yspan1 + 1, tz1);
	const double near1 = projected_depth(
			tx1, ty1, tz1 + zspan1 - 1);
	const double far2 = projected_depth(
			tx2 - xspan2 + 1, ty2 - yspan2 + 1, tz2);
	const double near2 = projected_depth(
			tx2, ty2, tz2 + zspan2 - 1);
	if (near1 < far2 - 1e-9) {
		return -1;
	}
	if (far1 > near2 + 1e-9) {
		return 1;
	}
	return 0;
}

void IsoProjection::project(int tx, int ty, int tz, int& sx, int& sy, int& depth) const {
	depth = kind == IsoKind::Legacy
			? projected_object_depth(tx, ty)
			: static_cast<int>(std::lround(projected_depth(tx, ty, tz)));
	if (kind == IsoKind::Legacy) {
		const int lift = (tz * c_tilesize) / 2;
		sx = tx * c_tilesize - lift;
		sy = ty * c_tilesize - lift;
		return;
	}
	const Basis basis = basis_for(kind);
	sx = static_cast<int>(std::lround((tx - ty) * basis.x));
	sy = static_cast<int>(std::lround((tx + ty) * basis.y)) - liftpix_for(tz);
}

bool IsoProjection::unproject(int sx, int sy, int& tx, int& ty) const {
	const Basis basis = basis_for(kind);
	if (basis.x == 0.0 || basis.y == 0.0) {
		return false;
	}
	const double a = sx / basis.x;
	const double b = sy / basis.y;
	tx = static_cast<int>(std::lround((a + b) * 0.5));
	ty = static_cast<int>(std::lround((b - a) * 0.5));
	return true;
}

void IsoProjection::project_pixel(int px, int py, int& sx, int& sy) const {
	if (kind == IsoKind::Legacy) {
		sx = px;
		sy = py;
		return;
	}
	const Basis basis = basis_for(kind);
	sx = static_cast<int>(std::lround((px - py) * basis.x / c_tilesize));
	sy = static_cast<int>(std::lround((px + py) * basis.y / c_tilesize));
}

void IsoProjection::unproject_pixel(int sx, int sy, int& px, int& py) const {
	if (kind == IsoKind::Legacy) {
		px = sx;
		py = sy;
		return;
	}
	const Basis basis = basis_for(kind);
	const double a = sx * c_tilesize / basis.x;
	const double b = sy * c_tilesize / basis.y;
	px = static_cast<int>(std::lround((a + b) * 0.5));
	py = static_cast<int>(std::lround((b - a) * 0.5));
}

void IsoProjection::project_sprite_pixel(int px, int py, int& sx, int& sy) const {
	project_sprite_pixel(
			px, py, c_tilesize, c_tilesize, c_tilesize, sx, sy);
}

void IsoProjection::project_sprite_pixel(
		int px, int py, int footprint_width, int footprint_height,
		int elevation_height, int& sx, int& sy) const {
	if (kind == IsoKind::Legacy || kind == IsoKind::Diamond) {
		sx = px;
		sy = py;
		return;
	}
	const Basis basis = basis_for(kind);
	const double ground_x = basis.x / c_tilesize;
	const double ground_y = basis.y / c_tilesize;
	const double elevation = sprite_elevation_for(
			px, py, footprint_width, footprint_height, elevation_height);
	sx = static_cast<int>(std::lround((px - py) * ground_x));
	sy = static_cast<int>(std::lround(
			(px + py - 2.0 * (kWorldSpriteVerticalScale - 1.0) * elevation)
			* ground_y));
}

void IsoProjection::unproject_sprite_pixel(int sx, int sy, int& px, int& py) const {
	unproject_sprite_pixel(
			sx, sy, c_tilesize, c_tilesize, c_tilesize, px, py);
}

void IsoProjection::unproject_sprite_pixel(
		int sx, int sy, int footprint_width, int footprint_height,
		int elevation_height, int& px, int& py) const {
	if (kind == IsoKind::Legacy || kind == IsoKind::Diamond) {
		px = sx;
		py = sy;
		return;
	}
	const Basis basis = basis_for(kind);
	const double ground_x = basis.x / c_tilesize;
	const double ground_y = basis.y / c_tilesize;
	const double a = sx / ground_x;
	const double b = sy / ground_y;
	const double projected_x = (a + b) * 0.5;
	const double projected_y = (b - a) * 0.5;
	double source_x = projected_x;
	double source_y = projected_y;
	for (int i = 0; i < 6; ++i) {
		const double elevation = sprite_elevation_for(
				static_cast<int>(std::lround(source_x)),
				static_cast<int>(std::lround(source_y)), footprint_width,
				footprint_height, elevation_height);
		source_x = projected_x + (kWorldSpriteVerticalScale - 1.0) * elevation;
		source_y = projected_y + (kWorldSpriteVerticalScale - 1.0) * elevation;
	}
	px = static_cast<int>(std::lround(source_x));
	py = static_cast<int>(std::lround(source_y));
}

IsoTileRange IsoProjection::visible_tiles(int sx, int sy, int width, int height, int padding) const {
	const int corners[4][2] = {{sx, sy}, {sx + width, sy}, {sx, sy + height}, {sx + width, sy + height}};
	IsoTileRange range{0, 0, 0, 0};
	for (int i = 0; i < 4; ++i) {
		int tx = 0;
		int ty = 0;
		if (!unproject(corners[i][0], corners[i][1], tx, ty)) {
			continue;
		}
		if (i == 0) {
			range = {tx, ty, tx, ty};
		} else {
			range.min_tx = std::min(range.min_tx, tx);
			range.min_ty = std::min(range.min_ty, ty);
			range.max_tx = std::max(range.max_tx, tx);
			range.max_ty = std::max(range.max_ty, ty);
		}
	}
	range.min_tx -= padding;
	range.min_ty -= padding;
	range.max_tx += padding;
	range.max_ty += padding;
	return range;
}

void IsoProjection::tile_bounds(int tx, int ty, int tz, int& x, int& y, int& w, int& h) const {
	const int corners[4][2] = {{tx, ty}, {tx + 1, ty}, {tx, ty + 1}, {tx + 1, ty + 1}};
	int       min_x = 0;
	int       max_x = 0;
	int       min_y = 0;
	int       max_y = 0;
	for (int i = 0; i < 4; ++i) {
		int sx = 0;
		int sy = 0;
		int depth = 0;
		project(corners[i][0], corners[i][1], tz, sx, sy, depth);
		if (i == 0) {
			min_x = max_x = sx;
			min_y = max_y = sy;
		} else {
			min_x = std::min(min_x, sx);
			max_x = std::max(max_x, sx);
			min_y = std::min(min_y, sy);
			max_y = std::max(max_y, sy);
		}
	}
	x = min_x;
	y = min_y;
	w = std::max(1, max_x - min_x);
	h = std::max(1, max_y - min_y);
}

int IsoProjection::liftpix_for(int tz) const {
	if (kind == IsoKind::Legacy || kind == IsoKind::Diamond) {
		return (tz * c_tilesize) / 2;
	}
	const Basis basis = basis_for(kind);
	return static_cast<int>(std::lround(tz * basis.y * kWorldSpriteVerticalScale));
}

int IsoProjection::tile_pixels_y() const {
	if (kind == IsoKind::Legacy) {
		return c_tilesize;
	}
	const Basis basis = basis_for(kind);
	return std::max(1, static_cast<int>(std::lround(2.0 * basis.y)));
}

IsoProjection IsoProjection::current() {
	IsoProjection p;
	p.kind = g_current_kind;
	return p;
}

void IsoProjection::set_current(IsoKind k) {
	g_current_kind = k;
}

void IsoProjection::set_current(const std::string& s) {
	g_current_kind = from_name(s).kind;
}

void Iso_project_tile(int tx, int ty, int tz, int& x, int& y) {
	IsoProjection p = IsoProjection::current();
	p.project_xy(tx, ty, tz, x, y);
}
