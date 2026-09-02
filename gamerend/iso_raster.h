/*
 *  iso_raster.h - Indexed rasters used by projected world shapes.
 */

#ifndef ISO_RASTER_H
#define ISO_RASTER_H

#include "iso_projection.h"

#include <vector>

struct IsoRaster {
	int                      width;
	int                      height;
	int                      xleft;
	int                      yabove;
	std::vector<unsigned char> pixels;
	// Coverage is separate from the indexed palette so every palette entry,
	// including 0 and 255, can remain opaque.
	std::vector<unsigned char> coverage;

	bool is_covered(size_t index) const {
		return coverage.empty() || coverage[index] != 0;
	}
};

// Direction of a vertical wall's horizontal source axis in world space.
enum class IsoWallOrientation : unsigned char {
	WorldX,
	WorldY,
};

// A wall-family VGA frame is a small texture atlas, not one upright bitmap.
// These rectangles describe the three faces of its cuboid representation.
struct IsoWallFace {
	int x = 0;
	int y = 0;
	int width = 0;
	int height = 0;
};

struct IsoWallProfile {
	IsoWallOrientation orientation = IsoWallOrientation::WorldX;
	int                footprint_width_tiles = 1;
	int                footprint_height_tiles = 1;
	int                wall_height_lifts = 1;
	IsoWallFace        top;
	IsoWallFace        front;
	IsoWallFace        right;
};

IsoRaster decode_raw_raster(
		const unsigned char* pixels, int width, int height, int xleft, int yabove);
IsoRaster decode_rle_raster(
		const unsigned char* encoded, int width, int height, int xleft, int yabove);
IsoRaster transform_iso_raster(const IsoRaster& source, IsoKind kind);
IsoRaster transform_iso_sprite_raster(
		const IsoRaster& source, IsoKind kind, int footprint_width,
		int footprint_height, int elevation_height);

// Transform terrain wall/overlay art using an explicit vertical plane. The
// local height is in world lift units; the object's absolute lift is already
// represented by the screen anchor supplied by the caller.
IsoRaster transform_iso_wall_raster(
		const IsoRaster& source, IsoKind kind, int wall_height_lifts,
		IsoWallOrientation orientation = IsoWallOrientation::WorldX);

// Transform a cuboid wall atlas. The returned raster is anchored at the
// cuboid's ground corner, so its top face and vertical faces meet adjacent
// projected terrain without changing ordinary sprite projection.
IsoRaster transform_iso_wall_atlas_raster(
		const IsoRaster& source, IsoKind kind, const IsoWallProfile& profile);

#endif
