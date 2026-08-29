#include "iso_raster.h"

#include "ibuf8.h"

#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <vector>

static void write_le16(std::vector<unsigned char>& bytes, std::int16_t value) {
	const auto raw = static_cast<std::uint16_t>(value);
	bytes.push_back(static_cast<unsigned char>(raw & 0xff));
	bytes.push_back(static_cast<unsigned char>(raw >> 8));
}

static std::vector<unsigned char> make_raw_rle(const IsoRaster& source) {
	std::vector<unsigned char> encoded;
	for (int y = 0; y < source.height; ++y) {
		write_le16(encoded, static_cast<std::int16_t>(source.width * 2));
		write_le16(encoded, static_cast<std::int16_t>(-source.xleft));
		write_le16(encoded, static_cast<std::int16_t>(y - source.yabove));
		encoded.insert(encoded.end(), source.pixels.begin() + y * source.width,
					   source.pixels.begin() + (y + 1) * source.width);
	}
	write_le16(encoded, 0);
	return encoded;
}

static IsoRaster sample() {
	IsoRaster raster{8, 8, 4, 4, std::vector<unsigned char>(64, 255)};
	raster.pixels[0]  = 1;
	raster.pixels[7]  = 2;
	raster.pixels[56] = 3;
	raster.pixels[63] = 4;
	return raster;
}

static bool projected_point_is_inside_source(
		const IsoRaster& source, IsoKind kind, int projected_x, int projected_y) {
	const double basis_x = 0.8660254037844386 * c_tilesize;
	const double basis_y = kind == IsoKind::Dimetric ? 0.4 * c_tilesize : 0.5 * c_tilesize;
	const double a = projected_x * c_tilesize / basis_x;
	const double b = projected_y * c_tilesize / basis_y;
	const int source_x = static_cast<int>(std::lround((a + b) * 0.5)) + source.xleft;
	const int source_y = static_cast<int>(std::lround((b - a) * 0.5)) + source.yabove;
	return source_x >= 0 && source_x < source.width && source_y >= 0 && source_y < source.height;
}

static void assert_no_projected_holes(const IsoRaster& source, IsoKind kind) {
	const IsoRaster transformed = transform_iso_raster(source, kind);
	for (int y = 0; y < transformed.height; ++y) {
		for (int x = 0; x < transformed.width; ++x) {
			const int projected_x = x - transformed.xleft;
			const int projected_y = y - transformed.yabove;
			if (projected_point_is_inside_source(source, kind, projected_x, projected_y)) {
				assert(transformed.pixels[static_cast<size_t>(y) * transformed.width + x] != 255);
			}
		}
	}
}

int main() {
	const IsoRaster source = sample();
	const IsoRaster raw = decode_raw_raster(source.pixels.data(), source.width, source.height, source.xleft, source.yabove);
	const std::vector<unsigned char> encoded = make_raw_rle(source);
	const IsoRaster rle = decode_rle_raster(encoded.data(), source.width, source.height, source.xleft, source.yabove);
	assert(raw.pixels == source.pixels);
	assert(rle.pixels == source.pixels);

	const IsoRaster diamond = transform_iso_raster(source, IsoKind::Diamond);
	const IsoRaster true_iso = transform_iso_raster(source, IsoKind::TrueIso);
	const IsoRaster dimetric = transform_iso_raster(source, IsoKind::Dimetric);
	assert(diamond.width > 0 && diamond.height > 0);
	assert(true_iso.width > diamond.width);
	assert(true_iso.height > diamond.height);
	assert(dimetric.width == true_iso.width);
	assert(dimetric.height < true_iso.height);
	for (unsigned char pixel : {1, 2, 3, 4}) {
		assert(std::find(diamond.pixels.begin(), diamond.pixels.end(), pixel) != diamond.pixels.end());
	}
	assert(std::find(diamond.pixels.begin(), diamond.pixels.end(), 255) != diamond.pixels.end());
	assert(transform_iso_raster(source, IsoKind::Legacy).pixels == source.pixels);
	assert(source.pixels == sample().pixels);

	const IsoRaster solid{8, 8, 4, 4, std::vector<unsigned char>(64, 7)};
	assert_no_projected_holes(solid, IsoKind::TrueIso);
	assert_no_projected_holes(solid, IsoKind::Dimetric);

	Image_buffer8 target(4, 1);
	target.fill8(7);
	target.set_clip(0, 0, 4, 1);
	const unsigned char remapped[] = {1, 0, 2, 254};
	unsigned char       table[256];
	for (int i = 0; i < 256; ++i) {
		table[i] = static_cast<unsigned char>(i);
	}
	table[2]   = 4;
	table[254] = 255;
	target.copy_transparent8(remapped, 4, 1, 0, 0, nullptr, 0, table);
	assert(target.get_pixel8(0, 0) == 1);
	assert(target.get_pixel8(1, 0) == 0);
	assert(target.get_pixel8(2, 0) == 4);
	assert(target.get_pixel8(3, 0) == 7);

	target.fill8(7);
	const unsigned char projected[] = {0, 255};
	target.copy_transparent8(projected, 2, 1, 0, 0, nullptr, 0, nullptr);
	assert(target.get_pixel8(0, 0) == 0);
	assert(target.get_pixel8(1, 0) == 7);

	Xform_palette xform{};
	xform.colors[7] = 9;
	target.fill8(7);
	const unsigned char translucent[] = {254, 0, 1, 2};
	target.copy_transparent8(translucent, 4, 1, 0, 0, &xform, 1, nullptr);
	assert(target.get_pixel8(0, 0) == 9);
	assert(target.get_pixel8(1, 0) == 0);
	assert(target.get_pixel8(2, 0) == 1);
	assert(target.get_pixel8(3, 0) == 2);
	return 0;
}
