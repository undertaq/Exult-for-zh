/*
 *  iso_projection.h - Pluggable isometric projection for the world view.
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

#ifndef ISO_PROJECTION_H
#define ISO_PROJECTION_H

#include "exult_constants.h"
#include <string>

enum class IsoKind : int {
	Legacy  = 0,
	Diamond = 1,
	TrueIso = 2,
	Dimetric = 3,
};

struct IsoTileRange {
	int min_tx;
	int min_ty;
	int max_tx;
	int max_ty;
};

struct IsoProjection {
	IsoKind kind;

	explicit IsoProjection(IsoKind projection_kind = IsoKind::Legacy) : kind(projection_kind) {}

	// Project a tile coordinate plus lift (in tiles) into screen-space pixels.
	// Depth is the painter's algorithm order: smaller is farther.
	// Legacy returns the current square screen placement. Other modes use
	// their projected ground-plane basis and a vertical lift.
	void project(int tx, int ty, int tz, int& sx, int& sy, int& depth) const;

	// Return the front-to-back depth of an object's nearest ground-plane
	// corner. Object tile coordinates are anchored at that corner, so the
	// projected depth is independent of the selected ground-plane basis.
	int projected_object_depth(int tx, int ty) const {
		return tx + ty;
	}

	// Full projected depth, including lift. The lift coefficient follows the
	// selected ground-plane basis so True Iso and Dimetric remain consistent.
	double projected_depth(int tx, int ty, int tz) const;

	// Compare two projected object anchors from far to near. Ground-plane
	// depth is primary; elevation is a deterministic tie-break for stacked
	// floors that share the same ground-plane depth.
	int compare_projected_objects(
			int tx1, int ty1, int tz1, int tx2, int ty2, int tz2) const;

	// Inverse of project. Used by click-to-tile.
	// Returns false if the screen point is outside the world footprint.
	bool unproject(int sx, int sy, int& tx, int& ty) const;

	// Project a pixel offset relative to a world-shape origin. This is used
	// when a source bitmap has to be re-rasterized for the selected basis.
	void project_pixel(int px, int py, int& sx, int& sy) const;

	// Inverse of project_pixel, rounded to the nearest source pixel.
	void unproject_pixel(int sx, int sy, int& px, int& py) const;

	// Reproject a world-sprite pixel from the original world view. The
	// overload with dimensions uses the object's 3D box to distinguish its
	// ground footprint from elevation, preserving projected top-face edges.
	void project_sprite_pixel(int px, int py, int& sx, int& sy) const;
	void project_sprite_pixel(
			int px, int py, int footprint_width, int footprint_height,
			int elevation_height, int& sx, int& sy) const;

	// Inverse of project_sprite_pixel(), rounded to the source pixel.
	void unproject_sprite_pixel(int sx, int sy, int& px, int& py) const;
	void unproject_sprite_pixel(
			int sx, int sy, int footprint_width, int footprint_height,
			int elevation_height, int& px, int& py) const;

	// Return a padded logical tile range that may intersect a screen rectangle.
	IsoTileRange visible_tiles(int sx, int sy, int width, int height, int padding = 1) const;

	// Per-projection tile bounding rect in screen pixels (used for hit-tests).
	void tile_bounds(int tx, int ty, int tz, int& x, int& y, int& w, int& h) const;

	// Lift-to-pixel helper. All selectable projections currently use the
	// original 4-pixel vertical lift per world Z step.
	int liftpix_for(int tz) const;

	// Pixels occupied by one tile on the y axis. Diamond == c_tilesize/2.
	int tile_pixels_y() const;

	// Stable string id used in config files and debug overlays.
	const char* name() const;
	bool is_legacy() const {
		return kind == IsoKind::Legacy;
	}

	static IsoProjection from_name(const std::string& name);

	// Currently-active projection (mirrors config value).
	static IsoProjection current();

	// Apply a new selection. Thread-unsafe; called only from main thread.
	static void set_current(IsoKind k);
	static void set_current(const std::string& s);

	// Convenience: project without depth argument.
	inline void project_xy(int tx, int ty, int tz, int& sx, int& sy) const {
		int depth;
		project(tx, ty, tz, sx, sy, depth);
	}
};

// Helper used by call sites that previously performed tile-to-screen math.
void Iso_project_tile(int tx, int ty, int tz, int& x, int& y);

#endif    // ISO_PROJECTION_H
