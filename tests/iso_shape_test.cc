#include "iso_projection.h"

#include "ibuf8.h"
#include "shapeid.h"
#include "vgafile.h"

#include <algorithm>
#include <cassert>
#include <memory>
#include <vector>

static std::vector<unsigned char> render_shape(Shape_frame& frame, IsoKind kind, unsigned char background = 0) {
	Image_buffer8 target(64, 64);
	target.fill8(background);
	target.set_clip(0, 0, 64, 64);
	frame.paint_projected(&target, 32, 32, kind, nullptr, 0, nullptr);
	return std::vector<unsigned char>(target.get_bits(), target.get_bits() + 64 * 64);
}

static std::unique_ptr<unsigned char[]> sample_pixels() {
	auto pixels = std::make_unique<unsigned char[]>(64);
	std::fill_n(pixels.get(), 64, 0);
	pixels[0]  = 1;
	pixels[7]  = 2;
	pixels[56] = 3;
	pixels[63] = 4;
	return pixels;
}

static std::unique_ptr<unsigned char[]> sample_sprite_pixels() {
	auto pixels = std::make_unique<unsigned char[]>(16 * 16);
	std::fill_n(pixels.get(), 16 * 16, 255);
	for (int y = 3; y < 13; ++y) {
		for (int x = 5; x < 11; ++x) {
			pixels[y * 16 + x] = static_cast<unsigned char>(1 + (x + y) % 4);
		}
	}
	return pixels;
}

static std::unique_ptr<unsigned char[]> opaque_palette_255_tile() {
	auto pixels = std::make_unique<unsigned char[]>(64);
	std::fill_n(pixels.get(), 64, 255);
	return pixels;
}

static std::vector<unsigned char> render_unprojected(Shape_frame& frame) {
	Image_buffer8 target(64, 64);
	target.fill8(0);
	target.set_clip(0, 0, 64, 64);
	frame.paint(&target, 32, 32);
	return std::vector<unsigned char>(target.get_bits(), target.get_bits() + 64 * 64);
}

static std::vector<unsigned char> render_world_shape(Shape_frame& frame, IsoKind kind) {
	IsoProjection::set_current(kind);
	Image_buffer8 target(64, 64);
	target.fill8(0);
	target.set_clip(0, 0, 64, 64);
	Shape_frame::set_to_render(&target);
	// paint_world_shape is independent of Shape_manager state for an opaque
	// shape. Use unconstructed storage so this focused test need not load VGA
	// assets just to exercise the routing decision.
	alignas(Shape_manager) unsigned char storage[sizeof(Shape_manager)]{};
	auto* manager = reinterpret_cast<Shape_manager*>(storage);
	manager->paint_world_shape(32, 32, &frame, false, nullptr);
	return std::vector<unsigned char>(target.get_bits(), target.get_bits() + 64 * 64);
}

static std::vector<unsigned char> render_world_tile(Shape_frame& frame, IsoKind kind) {
	IsoProjection::set_current(kind);
	Image_buffer8 target(64, 64);
	target.fill8(0);
	target.set_clip(0, 0, 64, 64);
	Shape_frame::set_to_render(&target);
	alignas(Shape_manager) unsigned char storage[sizeof(Shape_manager)]{};
	auto* manager = reinterpret_cast<Shape_manager*>(storage);
	manager->paint_world_tile(32, 32, &frame, false, nullptr);
	return std::vector<unsigned char>(target.get_bits(), target.get_bits() + 64 * 64);
}

static std::pair<int, int> occupied_size(const std::vector<unsigned char>& pixels) {
	int min_x = 64;
	int min_y = 64;
	int max_x = -1;
	int max_y = -1;
	for (int y = 0; y < 64; ++y) {
		for (int x = 0; x < 64; ++x) {
			if (pixels[y * 64 + x] == 0) {
				continue;
			}
			min_x = std::min(min_x, x);
			min_y = std::min(min_y, y);
			max_x = std::max(max_x, x);
			max_y = std::max(max_y, y);
		}
	}
	return {max_x - min_x + 1, max_y - min_y + 1};
}

int main() {
	Shape_frame raw(sample_pixels(), 8, 8, 4, 4, false);
	Shape_frame rle(sample_pixels(), 8, 8, 4, 4, true);
	const auto legacy = render_shape(raw, IsoKind::Legacy);
	const auto diamond = render_shape(raw, IsoKind::Diamond);
	assert(legacy != diamond);
	assert(diamond == render_shape(rle, IsoKind::Diamond));

	// Raw terrain tiles are always opaque, including palette index 255.
	Shape_frame opaque_255(opaque_palette_255_tile(), 8, 8, 4, 4, false);
	const auto  true_iso_255 = render_shape(opaque_255, IsoKind::TrueIso, 7);
	assert(std::find(true_iso_255.begin(), true_iso_255.end(), 255) != true_iso_255.end());

	// World sprites use a separate projection path. Their horizontal ground
	// component changes with the selected basis, while their vertical pixels
	// retain full height instead of being compressed into the ground plane.
	Shape_frame sprite(sample_sprite_pixels(), 16, 16, 8, 8, true);
	const auto source_sprite = render_unprojected(sprite);
	assert(source_sprite == render_shape(sprite, IsoKind::Legacy));
	assert(source_sprite == render_world_shape(sprite, IsoKind::Diamond));
	const auto true_iso_sprite = render_world_shape(sprite, IsoKind::TrueIso);
	const auto dimetric_sprite = render_world_shape(sprite, IsoKind::Dimetric);
	const auto true_iso_ground_transform = render_shape(sprite, IsoKind::TrueIso);
	const auto dimetric_ground_transform = render_shape(sprite, IsoKind::Dimetric);
	assert(source_sprite != true_iso_sprite);
	assert(source_sprite != dimetric_sprite);
	assert(occupied_size(true_iso_sprite).first == occupied_size(true_iso_ground_transform).first);
	assert(occupied_size(dimetric_sprite).first == occupied_size(dimetric_ground_transform).first);
	assert(occupied_size(true_iso_sprite).second > occupied_size(true_iso_ground_transform).second);
	assert(occupied_size(dimetric_sprite).second > occupied_size(dimetric_ground_transform).second);

	// Pixels on the footprint must keep the same ground-plane edges as
	// terrain; elevation correction is applied along the legacy lift axis.
	for (const IsoKind kind : {IsoKind::TrueIso, IsoKind::Dimetric}) {
		const IsoProjection projection(kind);
		int               tile_x = 0;
		int               tile_y = 0;
		int               sprite_x = 0;
		int               sprite_y = 0;
		projection.project_pixel(c_tilesize, 0, tile_x, tile_y);
		projection.project_sprite_pixel(c_tilesize, 0, sprite_x, sprite_y);
		assert(sprite_x == tile_x && sprite_y == tile_y);
		projection.project_pixel(0, c_tilesize, tile_x, tile_y);
		projection.project_sprite_pixel(0, c_tilesize, sprite_x, sprite_y);
		assert(sprite_x == tile_x && sprite_y == tile_y);
	}
	const IsoProjection true_iso(IsoKind::TrueIso);
	int               sprite_x = 0;
	int               sprite_y = 0;
	true_iso.project_sprite_pixel(0, -c_tilesize, sprite_x, sprite_y);
	assert(sprite_x == 7);
	assert(sprite_y == -4);

	// RLE entries in terrain chunks are world sprites, not raw ground tiles.
	assert(source_sprite == render_world_tile(sprite, IsoKind::Diamond));
	assert(source_sprite != render_world_tile(sprite, IsoKind::TrueIso));
	assert(source_sprite != render_world_tile(sprite, IsoKind::Dimetric));
	return 0;
}
