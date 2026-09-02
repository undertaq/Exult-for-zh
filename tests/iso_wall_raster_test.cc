#include "iso_raster.h"

#include <cassert>
#include <fstream>
#include <string>
#include <vector>

static IsoRaster make_wall_sprite() {
	// A narrow synthetic wall makes the vertical-only effect easy to inspect:
	// its source x coordinate never changes, while its upper pixels are lifted.
	return IsoRaster{
			1, 17, 8, 16, std::vector<unsigned char>(17, 7),
			std::vector<unsigned char>(17, 1)};
}

static void write_pgm(const std::string& path, const IsoRaster& raster) {
	std::ofstream output(path, std::ios::binary);
	assert(output);
	output << "P5\n" << raster.width << ' ' << raster.height << "\n255\n";
	for (size_t index = 0; index < raster.pixels.size(); ++index) {
		output.put(static_cast<char>(raster.is_covered(index) ? raster.pixels[index] : 0));
	}
}

static IsoRaster make_wall_atlas() {
	IsoRaster atlas{
			16, 16, 0, 0, std::vector<unsigned char>(16 * 16, 0),
			std::vector<unsigned char>(16 * 16, 1)};
	for (int y = 0; y < 8; ++y) {
		for (int x = 0; x < 8; ++x) {
			atlas.pixels[static_cast<size_t>(y) * atlas.width + x] = 10;
			atlas.pixels[static_cast<size_t>(y) * atlas.width + 8 + x] = 30;
			atlas.pixels[static_cast<size_t>(8 + y) * atlas.width + x] = 20;
		}
	}
	return atlas;
}

static bool contains_color(const IsoRaster& raster, unsigned char color) {
	for (size_t index = 0; index < raster.pixels.size(); ++index) {
		if (raster.is_covered(index) && raster.pixels[index] == color) {
			return true;
		}
	}
	return false;
}

int main(int argc, char** argv) {
	const IsoRaster source = make_wall_sprite();
	const IsoRaster normal = transform_iso_sprite_raster(
			source, IsoKind::TrueIso, 8, 8, 8);
	const IsoRaster wall = transform_iso_wall_raster(
			source, IsoKind::TrueIso, 4, IsoWallOrientation::WorldX);
	assert(wall.height > normal.height);

	IsoWallProfile profile;
	profile.footprint_width_tiles = 1;
	profile.footprint_height_tiles = 1;
	profile.wall_height_lifts = 2;
	profile.top = {0, 0, 8, 8};
	profile.front = {0, 8, 8, 8};
	profile.right = {8, 0, 8, 8};
	const IsoRaster atlas = transform_iso_wall_atlas_raster(
			make_wall_atlas(), IsoKind::TrueIso, profile);
	assert(contains_color(atlas, 10));
	assert(contains_color(atlas, 20));
	assert(contains_color(atlas, 30));
	assert(atlas.yabove >= IsoProjection(IsoKind::TrueIso).liftpix_for(2));

	int first_covered_row = atlas.height;
	int last_covered_row = -1;
	for (int y = 0; y < atlas.height; ++y) {
		for (int x = 0; x < atlas.width; ++x) {
			if (atlas.is_covered(static_cast<size_t>(y) * atlas.width + x)) {
				first_covered_row = std::min(first_covered_row, y);
				last_covered_row = std::max(last_covered_row, y);
			}
		}
	}
	assert(first_covered_row <= last_covered_row);
	for (int y = first_covered_row; y <= last_covered_row; ++y) {
		bool row_covered = false;
		for (int x = 0; x < atlas.width; ++x) {
			row_covered = row_covered
					|| atlas.is_covered(static_cast<size_t>(y) * atlas.width + x);
		}
		assert(row_covered);
	}

	// U7Revisited anchors a cuboid at its nearest tile corner and places its
	// footprint at pos + (-width + 1, -depth + 1).  The projected raster must
	// use that same anchor or a wall's roof and vertical faces separate by one
	// tile.  For a 4x1 wall of height 5, the TrueIso top is 42 pixels above the
	// anchor (30 pixels of lift plus 12 pixels of ground-plane depth).
	IsoRaster long_atlas{
			40, 30, 0, 0, std::vector<unsigned char>(40 * 30, 0),
			std::vector<unsigned char>(40 * 30, 1)};
	IsoWallProfile long_profile;
	long_profile.footprint_width_tiles = 4;
	long_profile.footprint_height_tiles = 1;
	long_profile.wall_height_lifts = 5;
	long_profile.top = {0, 0, 32, 8};
	long_profile.front = {0, 8, 32, 20};
	long_profile.right = {32, 0, 8, 8};
	const IsoRaster long_wall = transform_iso_wall_atlas_raster(
			long_atlas, IsoKind::TrueIso, long_profile);
	assert(long_wall.yabove == 42);

	// Pass a filename prefix to create two inspectable images without starting
	// the game: <prefix>_normal.pgm and <prefix>_wall.pgm.
	if (argc > 1) {
		const std::string prefix(argv[1]);
		write_pgm(prefix + "_normal.pgm", normal);
		write_pgm(prefix + "_wall.pgm", wall);
	}
	return 0;
}
