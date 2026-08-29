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

int main() {
	Shape_frame raw(sample_pixels(), 8, 8, 4, 4, false);
	Shape_frame rle(sample_pixels(), 8, 8, 4, 4, true);
	const auto legacy = render_shape(raw, IsoKind::Legacy);
	const auto diamond = render_shape(raw, IsoKind::Diamond);
	assert(legacy != diamond);
	assert(diamond == render_shape(rle, IsoKind::Diamond));
	return 0;
}
