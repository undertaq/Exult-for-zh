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

constexpr int            kWallFixedFractionBits = 20;
constexpr std::int64_t   kWallFixedOne = std::int64_t{1} << kWallFixedFractionBits;
constexpr std::int64_t   kWallFixedHalf = kWallFixedOne / 2;
using Wall_fixed = std::int64_t;

Wall_fixed wall_to_fixed(double value) {
	return static_cast<Wall_fixed>(std::llround(value * kWallFixedOne));
}

Wall_fixed wall_fixed_multiply(Wall_fixed lhs, Wall_fixed rhs) {
	return (lhs * rhs) / kWallFixedOne;
}

int wall_fixed_round(Wall_fixed value) {
	if (value >= 0) {
		return static_cast<int>((value + kWallFixedHalf) / kWallFixedOne);
	}
	return -static_cast<int>((-value + kWallFixedHalf) / kWallFixedOne);
}

struct Wall_projected_bounds {
	double min_x = 0.0;
	double max_x = 0.0;
	double min_y = 0.0;
	double max_y = 0.0;
	bool   initialized = false;

	void include(double x, double y) {
		if (!initialized) {
			min_x = max_x = x;
			min_y = max_y = y;
			initialized = true;
			return;
		}
		min_x = std::min(min_x, x);
		max_x = std::max(max_x, x);
		min_y = std::min(min_y, y);
		max_y = std::max(max_y, y);
	}
};

struct Wall_fixed_mapper {
	Wall_fixed ground_y;
	Wall_fixed inverse_ground_x;
	Wall_fixed inverse_vertical;
	Wall_fixed source_y_step_x;
	Wall_fixed source_y_step_y;

	Wall_fixed source_x_at(int screen_x) const {
		return static_cast<Wall_fixed>(screen_x) * inverse_ground_x;
	}

	Wall_fixed source_y_at(int screen_x, int screen_y) const {
		const Wall_fixed source_x = source_x_at(screen_x);
		const Wall_fixed screen_y_fixed = static_cast<Wall_fixed>(screen_y) * kWallFixedOne;
		return wall_fixed_multiply(
				screen_y_fixed - wall_fixed_multiply(ground_y, source_x),
				inverse_vertical);
	}
};

Wall_fixed_mapper make_wall_fixed_mapper(
		const IsoProjection& projection, int wall_height_lifts,
		IsoWallOrientation orientation) {
	double ground_x = 0.0;
	double ground_y = 0.0;
	if (orientation == IsoWallOrientation::WorldX) {
		projection.project_pixel(1.0, 0.0, ground_x, ground_y);
	} else {
		projection.project_pixel(0.0, 1.0, ground_x, ground_y);
	}
	const int source_height_pixels = std::max(1, wall_height_lifts * c_tilesize / 2);
	const double screen_height = projection.liftpix_for(wall_height_lifts);
	const double vertical_scale = screen_height / source_height_pixels;
	const Wall_fixed fixed_ground_y = wall_to_fixed(ground_y);
	const Wall_fixed inverse_ground_x = wall_to_fixed(1.0 / ground_x);
	const Wall_fixed inverse_vertical = wall_to_fixed(1.0 / vertical_scale);
	return {
			fixed_ground_y,
			inverse_ground_x,
			inverse_vertical,
			-wall_fixed_multiply(
					wall_fixed_multiply(fixed_ground_y, inverse_ground_x),
					inverse_vertical),
			inverse_vertical};
}

void project_wall_pixel(
		const IsoProjection& projection, double px, double py,
		double vertical_scale, IsoWallOrientation orientation, double& sx,
		double& sy) {
	double ground_x = 0.0;
	double ground_y = 0.0;
	if (orientation == IsoWallOrientation::WorldX) {
		projection.project_pixel(px, 0.0, ground_x, ground_y);
	} else {
		projection.project_pixel(0.0, px, ground_x, ground_y);
	}
	sx = ground_x;
	sy = ground_y + py * vertical_scale;
}

bool sample_wall_source(
		const IsoRaster& source, Wall_fixed source_x, Wall_fixed source_y,
		unsigned char& pixel) {
	const int raster_x = wall_fixed_round(source_x) + source.xleft;
	const int raster_y = wall_fixed_round(source_y) + source.yabove;
	if (raster_x < 0 || raster_x >= source.width || raster_y < 0
			|| raster_y >= source.height) {
		return false;
	}
	const size_t index = static_cast<size_t>(raster_y) * source.width + raster_x;
	if (!source.is_covered(index)) {
		return false;
	}
	pixel = source.pixels[index];
	return true;
}

IsoRaster transform_wall_raster(
		const IsoRaster& source, IsoKind kind, int wall_height_lifts,
		IsoWallOrientation orientation) {
	if (kind == IsoKind::Legacy || kind == IsoKind::Diamond
			|| source.width == 0 || source.height == 0 || wall_height_lifts <= 0) {
		return source;
	}
	const IsoProjection projection(kind);
	const int source_height_pixels = std::max(1, wall_height_lifts * c_tilesize / 2);
	const double vertical_scale = static_cast<double>(projection.liftpix_for(wall_height_lifts))
			/ source_height_pixels;
	const double min_source_x = -source.xleft - 0.5;
	const double max_source_x = source.width - source.xleft - 0.5;
	const double min_source_y = -source.yabove - 0.5;
	const double max_source_y = source.height - source.yabove - 0.5;
	const double corners[4][2] = {
			{min_source_x, min_source_y}, {max_source_x, min_source_y},
			{min_source_x, max_source_y}, {max_source_x, max_source_y}};
	Wall_projected_bounds bounds;
	for (const auto& corner : corners) {
		double projected_x = 0.0;
		double projected_y = 0.0;
		project_wall_pixel(
				projection, corner[0], corner[1], vertical_scale, orientation,
				projected_x, projected_y);
		bounds.include(projected_x, projected_y);
	}
	const double centers[4][2] = {
			{min_source_x + 0.5, min_source_y + 0.5},
			{max_source_x - 0.5, min_source_y + 0.5},
			{min_source_x + 0.5, max_source_y - 0.5},
			{max_source_x - 0.5, max_source_y - 0.5}};
	for (const auto& center : centers) {
		double projected_x = 0.0;
		double projected_y = 0.0;
		project_wall_pixel(
				projection, center[0], center[1], vertical_scale, orientation,
				projected_x, projected_y);
		bounds.include(projected_x, projected_y);
	}
	const int min_x = static_cast<int>(std::floor(bounds.min_x + 0.5));
	const int min_y = static_cast<int>(std::floor(bounds.min_y + 0.5));
	const int width = std::max(
			1, static_cast<int>(std::ceil(bounds.max_x - bounds.min_x)));
	const int height = std::max(
			1, static_cast<int>(std::ceil(bounds.max_y - bounds.min_y)));
	IsoRaster transformed{
			width,
			height,
			-min_x,
			-min_y,
			std::vector<unsigned char>(static_cast<size_t>(width) * height, 0),
			std::vector<unsigned char>(static_cast<size_t>(width) * height, 0)};
	const Wall_fixed_mapper mapper = make_wall_fixed_mapper(
			projection, wall_height_lifts, orientation);
	const Wall_fixed sample_offsets[4] = {
			-3 * kWallFixedOne / 8, -kWallFixedOne / 8,
			 kWallFixedOne / 8,  3 * kWallFixedOne / 8};
	for (int y = 0; y < height; ++y) {
		const int screen_y = y + min_y;
		Wall_fixed source_x = mapper.source_x_at(min_x);
		Wall_fixed source_y = mapper.source_y_at(min_x, screen_y);
		for (int x = 0; x < width; ++x) {
			const size_t index = static_cast<size_t>(y) * width + x;
			unsigned char pixel = 0;
			bool sampled = sample_wall_source(source, source_x, source_y, pixel);
			if (!sampled) {
				for (const Wall_fixed offset_y : sample_offsets) {
					for (const Wall_fixed offset_x : sample_offsets) {
						const Wall_fixed candidate_x = source_x
								+ wall_fixed_multiply(mapper.inverse_ground_x, offset_x);
						const Wall_fixed candidate_y = source_y
								+ wall_fixed_multiply(
										mapper.source_y_step_x, offset_x)
								+ wall_fixed_multiply(
										mapper.source_y_step_y, offset_y);
						if (sample_wall_source(source, candidate_x, candidate_y, pixel)) {
							sampled = true;
							break;
						}
					}
					if (sampled) {
						break;
					}
				}
			}
			if (sampled) {
				transformed.pixels[index] = pixel;
				transformed.coverage[index] = 1;
			}
			source_x += mapper.inverse_ground_x;
			source_y += mapper.source_y_step_x;
		}
	}
	return transformed;
}

struct Wall_atlas_uv {
	double u;
	double v;
};

struct Wall_atlas_face_mapper {
	Wall_fixed u0 = 0;
	Wall_fixed u_step_x = 0;
	Wall_fixed u_step_y = 0;
	Wall_fixed v0 = 0;
	Wall_fixed v_step_x = 0;
	Wall_fixed v_step_y = 0;
	IsoWallFace face;

	bool valid() const {
		return face.width > 0 && face.height > 0;
	}

	Wall_fixed u_at(Wall_fixed screen_x, Wall_fixed screen_y) const {
		return u0 + wall_fixed_multiply(u_step_x, screen_x)
				+ wall_fixed_multiply(u_step_y, screen_y);
	}

	Wall_fixed v_at(Wall_fixed screen_x, Wall_fixed screen_y) const {
		return v0 + wall_fixed_multiply(v_step_x, screen_x)
				+ wall_fixed_multiply(v_step_y, screen_y);
	}
};

template <typename Uv_mapper>
Wall_atlas_face_mapper make_wall_atlas_face_mapper(
		const IsoWallFace& face, Uv_mapper&& uv_mapper) {
	Wall_atlas_face_mapper mapper;
	mapper.face = face;
	if (face.width <= 0 || face.height <= 0) {
		return mapper;
	}
	const Wall_atlas_uv origin = uv_mapper(0.0, 0.0);
	const Wall_atlas_uv step_x = uv_mapper(1.0, 0.0);
	const Wall_atlas_uv step_y = uv_mapper(0.0, 1.0);
	mapper.u0 = wall_to_fixed(origin.u);
	mapper.u_step_x = wall_to_fixed(step_x.u - origin.u);
	mapper.u_step_y = wall_to_fixed(step_y.u - origin.u);
	mapper.v0 = wall_to_fixed(origin.v);
	mapper.v_step_x = wall_to_fixed(step_x.v - origin.v);
	mapper.v_step_y = wall_to_fixed(step_y.v - origin.v);
	return mapper;
}

bool sample_wall_atlas_face(
		const IsoRaster& source, const Wall_atlas_face_mapper& mapper,
		Wall_fixed screen_x, Wall_fixed screen_y, unsigned char& pixel) {
	if (!mapper.valid()) {
		return false;
	}
	const int local_x = wall_fixed_round(mapper.u_at(screen_x, screen_y));
	const int local_y = wall_fixed_round(mapper.v_at(screen_x, screen_y));
	if (local_x < 0 || local_x >= mapper.face.width || local_y < 0
			|| local_y >= mapper.face.height) {
		return false;
	}
	const int source_x = mapper.face.x + local_x;
	const int source_y = mapper.face.y + local_y;
	if (source_x < 0 || source_x >= source.width || source_y < 0
			|| source_y >= source.height) {
		return false;
	}
	const size_t index = static_cast<size_t>(source_y) * source.width + source_x;
	if (!source.is_covered(index)) {
		return false;
	}
	pixel = source.pixels[index];
	return true;
}

IsoRaster transform_wall_atlas_raster(
		const IsoRaster& source, IsoKind kind, const IsoWallProfile& profile) {
	if (kind == IsoKind::Legacy || kind == IsoKind::Diamond
			|| source.width == 0 || source.height == 0
			|| profile.wall_height_lifts <= 0) {
		return source;
	}

	const int footprint_width = std::max(
			1, profile.footprint_width_tiles * c_tilesize);
	const int footprint_height = std::max(
			1, profile.footprint_height_tiles * c_tilesize);
	const IsoProjection projection(kind);
	const double lift = projection.liftpix_for(profile.wall_height_lifts);
	if (lift <= 0.0) {
		return source;
	}

	// Capture the continuous screen basis once. It is only used while setting
	// up the affine mappers; all destination-pixel sampling below is fixed
	// point and therefore follows the same rounding path on every frame.
	double world_x_sx = 0.0;
	double world_x_sy = 0.0;
	double world_y_sx = 0.0;
	double world_y_sy = 0.0;
	projection.project_pixel(1.0, 0.0, world_x_sx, world_x_sy);
	projection.project_pixel(0.0, 1.0, world_y_sx, world_y_sy);
	const double determinant = world_x_sx * world_y_sy
			- world_y_sx * world_x_sy;
	if (std::abs(determinant) < 1e-9 || std::abs(world_x_sx) < 1e-9
			|| std::abs(world_y_sx) < 1e-9) {
		return source;
	}

	Wall_projected_bounds bounds;
	const auto include = [&projection, &bounds](
			double world_x, double world_y, double vertical) {
		double screen_x = 0.0;
		double screen_y = 0.0;
		projection.project_pixel(world_x, world_y, screen_x, screen_y);
		bounds.include(screen_x, screen_y + vertical);
	};
	// ShapeData::Draw() places a cuboid at pos + (-width + 1, 0,
	// -depth + 1).  The raster anchor supplied by the world renderer is that
	// same nearest corner, so the cuboid spans through the anchor tile and one
	// tile beyond it.  The previous [-footprint, 0] bounds shifted every wall
	// down by one projected tile, leaving a roof-to-wall gap.
	const double left = -static_cast<double>(footprint_width - c_tilesize);
	const double top = -static_cast<double>(footprint_height - c_tilesize);
	const double right = static_cast<double>(c_tilesize);
	const double bottom = static_cast<double>(c_tilesize);
	for (const double world_x : {left, right}) {
		for (const double world_y : {top, bottom}) {
			include(world_x, world_y, -lift);
		}
	}
	for (const double world_x : {left, right}) {
		include(world_x, top, -lift);
		include(world_x, top, 0.0);
	}
	for (const double world_y : {top, bottom}) {
		include(left, world_y, -lift);
		include(left, world_y, 0.0);
	}

	const int min_x = static_cast<int>(std::floor(bounds.min_x + 0.5));
	const int min_y = static_cast<int>(std::floor(bounds.min_y + 0.5));
	const int width = std::max(
			1, static_cast<int>(std::ceil(bounds.max_x - bounds.min_x)));
	const int height = std::max(
			1, static_cast<int>(std::ceil(bounds.max_y - bounds.min_y)));
	IsoRaster transformed{
			width,
			height,
			-min_x,
			-min_y,
			std::vector<unsigned char>(static_cast<size_t>(width) * height, 0),
			std::vector<unsigned char>(static_cast<size_t>(width) * height, 0)};

	const auto ground_from_screen = [
			world_x_sx, world_x_sy, world_y_sx, world_y_sy, determinant](
			double screen_x, double screen_y) {
		const double world_x = (screen_x * world_y_sy
				- world_y_sx * screen_y)
			/ determinant;
		const double world_y = (world_x_sx * screen_y
				- screen_x * world_x_sy)
			/ determinant;
		return std::pair<double, double>{world_x, world_y};
	};

	const auto top_mapper = make_wall_atlas_face_mapper(
			profile.top, [=](double screen_x, double screen_y) {
				const auto ground = ground_from_screen(screen_x, screen_y + lift);
				return Wall_atlas_uv{
						(ground.first - left) * profile.top.width
								/ footprint_width
							- 0.5,
						(ground.second - top) * profile.top.height
								/ footprint_height
							- 0.5};
			});
	const auto front_mapper = make_wall_atlas_face_mapper(
			profile.front, [=](double screen_x, double screen_y) {
				const double world_y = top;
				const double world_x = (screen_x - world_y_sx * world_y)
						/ world_x_sx;
				const double ground_y = world_x * world_x_sy
						+ world_y * world_y_sy;
				return Wall_atlas_uv{
						(world_x - left) * profile.front.width
								/ footprint_width
						- 0.5,
						(screen_y - ground_y + lift) * profile.front.height
								/ lift
						- 0.5};
			});
	const auto right_mapper = make_wall_atlas_face_mapper(
			profile.right, [=](double screen_x, double screen_y) {
				const double world_x = left;
				const double world_y = (screen_x - world_x_sx * world_x)
						/ world_y_sx;
				const double ground_y = world_x * world_x_sy
						+ world_y * world_y_sy;
				return Wall_atlas_uv{
						(world_y - top) * profile.right.width
								/ footprint_height
						- 0.5,
						(screen_y - ground_y + lift) * profile.right.height
								/ lift
						- 0.5};
			});

	const Wall_fixed sample_offsets[4] = {
			-3 * kWallFixedOne / 8,
			-kWallFixedOne / 8,
			 kWallFixedOne / 8,
			  3 * kWallFixedOne / 8};
	for (int y = 0; y < height; ++y) {
		for (int x = 0; x < width; ++x) {
			const size_t index = static_cast<size_t>(y) * width + x;
			const Wall_fixed screen_x = wall_to_fixed(x + min_x);
			const Wall_fixed screen_y = wall_to_fixed(y + min_y);
			unsigned char pixel = 0;
			bool sampled = sample_wall_atlas_face(
					source, top_mapper, screen_x, screen_y, pixel);
			if (!sampled) {
				sampled = sample_wall_atlas_face(
						source, front_mapper, screen_x, screen_y, pixel);
			}
			if (!sampled) {
				sampled = sample_wall_atlas_face(
						source, right_mapper, screen_x, screen_y, pixel);
			}
			if (!sampled) {
				for (const Wall_fixed offset_y : sample_offsets) {
					for (const Wall_fixed offset_x : sample_offsets) {
						const Wall_fixed candidate_x = screen_x + offset_x;
						const Wall_fixed candidate_y = screen_y + offset_y;
						sampled = sample_wall_atlas_face(
								source, top_mapper, candidate_x, candidate_y, pixel);
						if (!sampled) {
							sampled = sample_wall_atlas_face(
									source, front_mapper, candidate_x, candidate_y, pixel);
						}
						if (!sampled) {
							sampled = sample_wall_atlas_face(
									source, right_mapper, candidate_x, candidate_y, pixel);
						}
						if (sampled) {
							break;
						}
					}
					if (sampled) {
						break;
					}
				}
			}
			if (sampled) {
				transformed.pixels[index] = pixel;
				transformed.coverage[index] = 1;
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

IsoRaster transform_iso_wall_raster(
		const IsoRaster& source, IsoKind kind, int wall_height_lifts,
		IsoWallOrientation orientation) {
	return transform_wall_raster(
			source, kind, std::max(0, wall_height_lifts), orientation);
}

IsoRaster transform_iso_wall_atlas_raster(
		const IsoRaster& source, IsoKind kind, const IsoWallProfile& profile) {
	return transform_wall_atlas_raster(source, kind, profile);
}
