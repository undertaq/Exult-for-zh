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
};

IsoRaster decode_raw_raster(
		const unsigned char* pixels, int width, int height, int xleft, int yabove);
IsoRaster decode_rle_raster(
		const unsigned char* encoded, int width, int height, int xleft, int yabove);
IsoRaster transform_iso_raster(const IsoRaster& source, IsoKind kind);

#endif
