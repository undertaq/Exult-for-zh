#include "iso_projection.h"

#include "ibuf8.h"
#include "vgafile.h"

#include <algorithm>
#include <cassert>
#include <memory>
#include <vector>

static std::vector<unsigned char> render_shape(Shape_frame& frame, IsoKind kind) {
	Image_buffer8 target(64, 64);
	target.fill8(0);
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

static std::vector<unsigned char> render_unprojected(Shape_frame& frame) {
	Image_buffer8 target(64, 64);
	target.fill8(0);
	target.set_clip(0, 0, 64, 64);
	frame.paint(&target, 32, 32);
	return std::vector<unsigned char>(target.get_bits(), target.get_bits() + 64 * 64);
}

int main() {
	Shape_frame raw(sample_pixels(), 8, 8, 4, 4, false);
	Shape_frame rle(sample_pixels(), 8, 8, 4, 4, true);
	const auto legacy = render_shape(raw, IsoKind::Legacy);
	const auto diamond = render_shape(raw, IsoKind::Diamond);
	assert(legacy != diamond);
	assert(diamond == render_shape(rle, IsoKind::Diamond));

	// Ground tiles are explicitly projected, while billboard-shaped world
	// sprites retain their source geometry until projection-aware assets exist.
	Shape_frame sprite(sample_sprite_pixels(), 16, 16, 8, 8, true);
	const auto source_sprite = render_unprojected(sprite);
	assert(source_sprite == render_shape(sprite, IsoKind::Legacy));
	assert(source_sprite != render_shape(sprite, IsoKind::Dimetric));
	return 0;
}
