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

IsoRaster decode_raw_raster(
		const unsigned char* pixels, int width, int height, int xleft, int yabove);
IsoRaster decode_rle_raster(
		const unsigned char* encoded, int width, int height, int xleft, int yabove);
IsoRaster transform_iso_raster(const IsoRaster& source, IsoKind kind);
IsoRaster transform_iso_sprite_raster(
		const IsoRaster& source, IsoKind kind, int footprint_width,
		int footprint_height, int elevation_height);

#endif
