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
		for (int x = 0; x < source.width;) {
			if (!source.is_covered(static_cast<size_t>(y) * source.width + x)) {
				++x;
				continue;
			}
			const int start = x;
			while (x < source.width && source.is_covered(static_cast<size_t>(y) * source.width + x)) {
				++x;
			}
			write_le16(encoded, static_cast<std::int16_t>((x - start) * 2));
			write_le16(encoded, static_cast<std::int16_t>(start - source.xleft));
			write_le16(encoded, static_cast<std::int16_t>(y - source.yabove));
			encoded.insert(encoded.end(), source.pixels.begin() + y * source.width + start,
					   source.pixels.begin() + y * source.width + x);
		}
	}
	write_le16(encoded, 0);
	return encoded;
}

static IsoRaster sample() {
	IsoRaster raster{8, 8, 4, 4, std::vector<unsigned char>(64, 255), std::vector<unsigned char>(64, 0)};
	raster.pixels[0]  = 1;
	raster.pixels[7]  = 2;
	raster.pixels[56] = 3;
	raster.pixels[63] = 4;
	raster.coverage[0] = raster.coverage[7] = raster.coverage[56] = raster.coverage[63] = 1;
	return raster;
}

static IsoRaster wall_column() {
	return IsoRaster{
			1, 17, 8, 16, std::vector<unsigned char>(17, 7),
			std::vector<unsigned char>(17, 1)};
}

static IsoRaster wall_line() {
	IsoRaster raster{
			9, 1, 4, 12, std::vector<unsigned char>(9, 0),
			std::vector<unsigned char>(9, 0)};
	for (int x = 0; x < raster.width; ++x) {
		const size_t index = static_cast<size_t>(x);
		raster.pixels[index] = static_cast<unsigned char>(x + 1);
		raster.coverage[index] = 1;
	}
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

static void assert_column_is_continuous(const IsoRaster& raster) {
	int first = -1;
	int last  = -1;
	for (int y = 0; y < raster.height; ++y) {
		if (raster.is_covered(static_cast<size_t>(y) * raster.width)) {
			if (first < 0) {
				first = y;
			}
			last = y;
		}
	}
	assert(first >= 0 && last >= first);
	for (int y = first; y <= last; ++y) {
		assert(raster.is_covered(static_cast<size_t>(y) * raster.width));
	}
}

static void assert_no_projected_holes(const IsoRaster& source, IsoKind kind) {
	const IsoRaster transformed = transform_iso_raster(source, kind);
	for (int y = 0; y < transformed.height; ++y) {
		for (int x = 0; x < transformed.width; ++x) {
			const int projected_x = x - transformed.xleft;
			const int projected_y = y - transformed.yabove;
			if (projected_point_is_inside_source(source, kind, projected_x, projected_y)) {
				assert(transformed.is_covered(static_cast<size_t>(y) * transformed.width + x));
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
	assert(std::all_of(raw.coverage.begin(), raw.coverage.end(), [](unsigned char covered) { return covered != 0; }));
	assert(rle.coverage == source.coverage);
	for (size_t index = 0; index < source.pixels.size(); ++index) {
		if (source.is_covered(index)) {
			assert(rle.pixels[index] == source.pixels[index]);
		}
	}

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
	assert(std::find(diamond.coverage.begin(), diamond.coverage.end(), 0) != diamond.coverage.end());
	assert(transform_iso_raster(source, IsoKind::Legacy).pixels == source.pixels);
	assert(source.pixels == sample().pixels);

	const IsoRaster solid{8, 8, 4, 4, std::vector<unsigned char>(64, 7)};
	assert_no_projected_holes(solid, IsoKind::TrueIso);
	assert_no_projected_holes(solid, IsoKind::Dimetric);

	// Terrain wall profiles use an explicit vertical plane. The old generic
	// sprite path remains unchanged for non-terrain sprites.
	const IsoRaster column = wall_column();
	const IsoRaster generic_column = transform_iso_sprite_raster(
			column, IsoKind::TrueIso, 8, 8, 16);
	const IsoRaster wall_column_raster = transform_iso_wall_raster(
			column, IsoKind::TrueIso, 4);
	assert(generic_column.height == 13);
	assert(wall_column_raster.height == 26);
	assert_column_is_continuous(wall_column_raster);

	// A horizontal wall edge must remain one affine line. A varying inferred
	// elevation would increase this line's projected height.
	const IsoRaster line = wall_line();
	const IsoRaster wall_line_raster = transform_iso_wall_raster(
			line, IsoKind::TrueIso, 4);
	assert(wall_line_raster.height == 6);
	const IsoRaster wall_world_x = transform_iso_wall_raster(
			line, IsoKind::TrueIso, 4, IsoWallOrientation::WorldX);
	const IsoRaster wall_world_y = transform_iso_wall_raster(
			line, IsoKind::TrueIso, 4, IsoWallOrientation::WorldY);
	assert(wall_world_x.pixels != wall_world_y.pixels);
	assert(wall_world_x.coverage != wall_world_y.coverage);

	Image_buffer8 target(4, 1);
	target.fill8(7);
	target.set_clip(0, 0, 4, 1);
	const unsigned char remapped[] = {1, 0, 2, 254};
	const unsigned char remapped_coverage[] = {1, 1, 1, 1};
	unsigned char       table[256];
	for (int i = 0; i < 256; ++i) {
		table[i] = static_cast<unsigned char>(i);
	}
	table[2]   = 4;
	table[254] = 255;
	target.copy_masked8(remapped, 4, 1, 0, 0, remapped_coverage, nullptr, 0, table);
	assert(target.get_pixel8(0, 0) == 1);
	assert(target.get_pixel8(1, 0) == 0);
	assert(target.get_pixel8(2, 0) == 4);
	assert(target.get_pixel8(3, 0) == 7);

	target.fill8(7);
	const unsigned char projected[] = {0, 255};
	const unsigned char projected_coverage[] = {1, 0};
	target.copy_masked8(projected, 2, 1, 0, 0, projected_coverage, nullptr, 0, nullptr);
	assert(target.get_pixel8(0, 0) == 0);
	assert(target.get_pixel8(1, 0) == 7);

	Xform_palette xform{};
	xform.colors[7] = 9;
	target.fill8(7);
	const unsigned char translucent[] = {254, 0, 1, 2};
	const unsigned char translucent_coverage[] = {1, 1, 1, 1};
	target.copy_masked8(translucent, 4, 1, 0, 0, translucent_coverage, &xform, 1, nullptr);
	assert(target.get_pixel8(0, 0) == 9);
	assert(target.get_pixel8(1, 0) == 0);
	assert(target.get_pixel8(2, 0) == 1);
	assert(target.get_pixel8(3, 0) == 2);

	// A projected raster must advance to the next source row after each
	// destination row; reusing row zero creates the repeated terrain bands.
	Image_buffer8 stride_target(2, 2);
	stride_target.fill8(7);
	stride_target.set_clip(0, 0, 2, 2);
	const unsigned char rows[] = {1, 2, 3, 4};
	const unsigned char rows_coverage[] = {1, 1, 1, 1};
	stride_target.copy_masked8(rows, 2, 2, 0, 0, rows_coverage, nullptr, 0, nullptr);
	assert(stride_target.get_pixel8(0, 0) == 1);
	assert(stride_target.get_pixel8(1, 0) == 2);
	assert(stride_target.get_pixel8(0, 1) == 3);
	assert(stride_target.get_pixel8(1, 1) == 4);
	return 0;
}
