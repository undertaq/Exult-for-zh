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
					 std::vector<unsigned char>(static_cast<size_t>(width) * static_cast<size_t>(height), 0),
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
		const size_t index = static_cast<size_t>(y) * raster.width + x;
		raster.pixels[index] = pixel;
		raster.coverage[index] = 1;
	}
}

using Raster_projector = void (*)(
		const IsoProjection&, int, int, int&, int&);

struct Sprite_projector {
	int footprint_width;
	int footprint_height;
	int elevation_height;
};

void project_tile_pixel(
		const IsoProjection& projection, int px, int py, int& sx, int& sy) {
	projection.project_pixel(px, py, sx, sy);
}

void unproject_tile_pixel(
		const IsoProjection& projection, int sx, int sy, int& px, int& py) {
	projection.unproject_pixel(sx, sy, px, py);
}

IsoRaster transform_raster(
		const IsoRaster& source, IsoKind kind, Raster_projector project,
		Raster_projector unproject, bool identity_in_diamond) {
	if (kind == IsoKind::Legacy || (identity_in_diamond && kind == IsoKind::Diamond)
			|| source.width == 0 || source.height == 0) {
		return source;
	}

	int min_x = 0;
	int max_x = 0;
	int min_y = 0;
	int max_y = 0;
	bool initialized = false;
	const IsoProjection projection(kind);
	for (int y = 0; y < source.height; ++y) {
		for (int x = 0; x < source.width; ++x) {
			int projected_x = 0;
			int projected_y = 0;
			project(projection, x - source.xleft, y - source.yabove, projected_x, projected_y);
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

	IsoRaster transformed{
			max_x - min_x + 1, max_y - min_y + 1, -min_x, -min_y,
			std::vector<unsigned char>(static_cast<size_t>(max_x - min_x + 1)
										* static_cast<size_t>(max_y - min_y + 1), 0),
			std::vector<unsigned char>(static_cast<size_t>(max_x - min_x + 1)
										* static_cast<size_t>(max_y - min_y + 1), 0)};
	// Preserve source samples first. Some projections round several source
	// pixels to the same destination coordinate.
	for (int y = 0; y < source.height; ++y) {
		for (int x = 0; x < source.width; ++x) {
			const size_t index = static_cast<size_t>(y) * source.width + x;
			if (!source.is_covered(index)) {
				continue;
			}
			int projected_x = 0;
			int projected_y = 0;
			project(projection, x - source.xleft, y - source.yabove, projected_x, projected_y);
			put_pixel(transformed, projected_x - min_x, projected_y - min_y, source.pixels[index]);
		}
	}
	// Fill gaps introduced by scaling/rounding from the nearest source pixel.
	for (int y = 0; y < transformed.height; ++y) {
		for (int x = 0; x < transformed.width; ++x) {
			const size_t index = static_cast<size_t>(y) * transformed.width + x;
			if (transformed.is_covered(index)) {
				continue;
			}
			int source_x = 0;
			int source_y = 0;
			unproject(projection, x + min_x, y + min_y, source_x, source_y);
			source_x += source.xleft;
			source_y += source.yabove;
			if (source_x < 0 || source_x >= source.width || source_y < 0 || source_y >= source.height) {
				continue;
			}
			const size_t source_index = static_cast<size_t>(source_y) * source.width + source_x;
			if (source.is_covered(source_index)) {
				put_pixel(transformed, x, y, source.pixels[source_index]);
			}
		}
	}
	return transformed;
}

IsoRaster transform_sprite_raster(
		const IsoRaster& source, IsoKind kind, const Sprite_projector& projector) {
	if (kind == IsoKind::Legacy || kind == IsoKind::Diamond
			|| source.width == 0 || source.height == 0) {
		return source;
	}
	const IsoProjection projection(kind);
	auto project = [&](int px, int py, int& sx, int& sy) {
		projection.project_sprite_pixel(
				px, py, projector.footprint_width, projector.footprint_height,
				projector.elevation_height, sx, sy);
	};
	auto unproject = [&](int sx, int sy, int& px, int& py) {
		projection.unproject_sprite_pixel(
				sx, sy, projector.footprint_width, projector.footprint_height,
				projector.elevation_height, px, py);
	};

	int min_x = 0;
	int max_x = 0;
	int min_y = 0;
	int max_y = 0;
	bool initialized = false;
	for (int y = 0; y < source.height; ++y) {
		for (int x = 0; x < source.width; ++x) {
			int projected_x = 0;
			int projected_y = 0;
			project(x - source.xleft, y - source.yabove, projected_x, projected_y);
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

	IsoRaster transformed{
			max_x - min_x + 1, max_y - min_y + 1, -min_x, -min_y,
			std::vector<unsigned char>(static_cast<size_t>(max_x - min_x + 1)
										* static_cast<size_t>(max_y - min_y + 1), 0),
			std::vector<unsigned char>(static_cast<size_t>(max_x - min_x + 1)
										* static_cast<size_t>(max_y - min_y + 1), 0)};
	for (int y = 0; y < source.height; ++y) {
		for (int x = 0; x < source.width; ++x) {
			const size_t index = static_cast<size_t>(y) * source.width + x;
			if (!source.is_covered(index)) {
				continue;
			}
			int projected_x = 0;
			int projected_y = 0;
			project(x - source.xleft, y - source.yabove, projected_x, projected_y);
			put_pixel(transformed, projected_x - min_x, projected_y - min_y, source.pixels[index]);
		}
	}
	for (int y = 0; y < transformed.height; ++y) {
		for (int x = 0; x < transformed.width; ++x) {
			const size_t index = static_cast<size_t>(y) * transformed.width + x;
			if (transformed.is_covered(index)) {
				continue;
			}
			int source_x = 0;
			int source_y = 0;
			unproject(x + min_x, y + min_y, source_x, source_y);
			source_x += source.xleft;
			source_y += source.yabove;
			if (source_x < 0 || source_x >= source.width || source_y < 0 || source_y >= source.height) {
				continue;
			}
			const size_t source_index = static_cast<size_t>(source_y) * source.width + source_x;
			if (source.is_covered(source_index)) {
				put_pixel(transformed, x, y, source.pixels[source_index]);
			}
		}
	}
	return transformed;
}

}    // namespace

IsoRaster decode_raw_raster(
		const unsigned char* pixels, int width, int height, int xleft, int yabove) {
	IsoRaster raster = make_raster(width, height, xleft, yabove);
	if (!pixels) {
		return raster;
	}
	std::copy(pixels, pixels + raster.pixels.size(), raster.pixels.begin());
	std::fill(raster.coverage.begin(), raster.coverage.end(), 1);
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
	return transform_raster(source, kind, project_tile_pixel, unproject_tile_pixel, false);
}

IsoRaster transform_iso_sprite_raster(
		const IsoRaster& source, IsoKind kind, int footprint_width,
		int footprint_height, int elevation_height) {
	return transform_sprite_raster(
			source, kind,
			{std::max(1, footprint_width), std::max(1, footprint_height),
			 std::max(0, elevation_height)});
}
