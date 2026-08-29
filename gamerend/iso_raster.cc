/*
 *  iso_raster.cc - Indexed rasters used by projected world shapes.
 */

#ifdef HAVE_CONFIG_H
#	include <config.h>
#endif

#include "iso_raster.h"

#include "exult_constants.h"

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace {

IsoRaster make_raster(int width, int height, int xleft, int yabove) {
	if (width < 0 || height < 0) {
		width = height = 0;
	}
	return IsoRaster{width, height, xleft, yabove,
					 std::vector<unsigned char>(static_cast<size_t>(width) * static_cast<size_t>(height), 0)};
}

std::uint16_t read_le16(const unsigned char*& in) {
	const std::uint16_t value = static_cast<std::uint16_t>(in[0])
			| (static_cast<std::uint16_t>(in[1]) << 8);
	in += 2;
	return value;
}

std::int16_t read_signed_le16(const unsigned char*& in) {
	return static_cast<std::int16_t>(read_le16(in));
}

void put_pixel(IsoRaster& raster, int x, int y, unsigned char pixel) {
	if (x >= 0 && x < raster.width && y >= 0 && y < raster.height) {
		raster.pixels[static_cast<size_t>(y) * raster.width + x] = pixel;
	}
}

}    // namespace

IsoRaster decode_raw_raster(
		const unsigned char* pixels, int width, int height, int xleft, int yabove) {
	IsoRaster raster = make_raster(width, height, xleft, yabove);
	if (!pixels) {
		return raster;
	}
	std::copy(pixels, pixels + raster.pixels.size(), raster.pixels.begin());
	return raster;
}

IsoRaster decode_rle_raster(
		const unsigned char* encoded, int width, int height, int xleft, int yabove) {
	IsoRaster raster = make_raster(width, height, xleft, yabove);
	if (!encoded) {
		return raster;
	}

	const unsigned char* in = encoded;
	while (true) {
		const std::uint16_t packed_length = read_le16(in);
		if (packed_length == 0) {
			break;
		}
		const bool encoded_line = (packed_length & 1) != 0;
		int       remaining    = packed_length >> 1;
		const int  scan_x       = read_signed_le16(in) + xleft;
		const int  scan_y       = read_signed_le16(in) + yabove;
		int        offset       = 0;
		if (!encoded_line) {
			while (remaining-- > 0) {
				put_pixel(raster, scan_x + offset++, scan_y, *in++);
			}
			continue;
		}
		while (remaining > 0) {
			const unsigned char packed_count = *in++;
			const int            count = packed_count >> 1;
			if (count <= 0) {
				break;
			}
			const bool repeat = (packed_count & 1) != 0;
			if (repeat) {
				const unsigned char pixel = *in++;
				for (int i = 0; i < count && remaining > 0; ++i, --remaining) {
					put_pixel(raster, scan_x + offset++, scan_y, pixel);
				}
			} else {
				for (int i = 0; i < count && remaining > 0; ++i, --remaining) {
					put_pixel(raster, scan_x + offset++, scan_y, *in++);
				}
			}
		}
	}
	return raster;
}

IsoRaster transform_iso_raster(const IsoRaster& source, IsoKind kind) {
	if (kind == IsoKind::Legacy || source.width == 0 || source.height == 0) {
		return source;
	}

	int min_x = 0;
	int max_x = 0;
	int min_y = 0;
	int max_y = 0;
	bool initialized = false;
	for (int y = 0; y < source.height; ++y) {
		for (int x = 0; x < source.width; ++x) {
			int projected_x = 0;
			int projected_y = 0;
			IsoProjection(kind).project_pixel(x - source.xleft, y - source.yabove, projected_x, projected_y);
			if (!initialized) {
				min_x = max_x = projected_x;
				min_y = max_y = projected_y;
				initialized = true;
			} else {
				min_x = std::min(min_x, projected_x);
				max_x = std::max(max_x, projected_x);
				min_y = std::min(min_y, projected_y);
				max_y = std::max(max_y, projected_y);
			}
		}
	}

	IsoRaster transformed{max_x - min_x + 1, max_y - min_y + 1, -min_x, -min_y,
							std::vector<unsigned char>(static_cast<size_t>(max_x - min_x + 1)
																	* static_cast<size_t>(max_y - min_y + 1), 0)};
	const IsoProjection projection(kind);
	// Preserve source samples first. Some projections downsample the source,
	// so this keeps distinct source colors that would otherwise collide under
	// inverse nearest-neighbor sampling.
	for (int y = 0; y < source.height; ++y) {
		for (int x = 0; x < source.width; ++x) {
			const unsigned char pixel = source.pixels[static_cast<size_t>(y) * source.width + x];
			// RLE gaps are decoded as zero; raw shape transparency is 255.
			if (pixel == 0 || pixel == 255) {
				continue;
			}
			int projected_x = 0;
			int projected_y = 0;
			projection.project_pixel(x - source.xleft, y - source.yabove, projected_x, projected_y);
			put_pixel(transformed, projected_x - min_x, projected_y - min_y, pixel);
		}
	}
	for (int y = 0; y < transformed.height; ++y) {
		for (int x = 0; x < transformed.width; ++x) {
			if (transformed.pixels[static_cast<size_t>(y) * transformed.width + x] != 0) {
				continue;
			}
			const int projected_x = x + min_x;
			const int projected_y = y + min_y;
			int       source_x    = 0;
			int       source_y    = 0;
			projection.unproject_pixel(projected_x, projected_y, source_x, source_y);
			source_x += source.xleft;
			source_y += source.yabove;
			if (source_x < 0 || source_x >= source.width || source_y < 0 || source_y >= source.height) {
				continue;
			}
			const unsigned char pixel = source.pixels[static_cast<size_t>(source_y) * source.width + source_x];
			// RLE gaps are decoded as zero; raw shape transparency is 255.
			if (pixel != 0 && pixel != 255) {
				transformed.pixels[static_cast<size_t>(y) * transformed.width + x] = pixel;
			}
		}
	}
	return transformed;
}
