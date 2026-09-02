#include "shapeid.h"

#include <cassert>

int main() {
	assert(iso_wall_orientation_for_shape(151, 0) == IsoWallOrientation::WorldY);
	assert(iso_wall_orientation_for_shape(151, 32) == IsoWallOrientation::WorldX);
	assert(iso_wall_orientation_for_shape(152, 0) == IsoWallOrientation::WorldX);
	assert(!iso_wall_orientation_for_shape(869, 0).has_value());
	assert(iso_wall_orientation_for_shape(869, 8) == IsoWallOrientation::WorldX);
	assert(iso_wall_orientation_for_shape(869, 9) == IsoWallOrientation::WorldX);
	assert(iso_wall_orientation_for_shape(869, 13) == IsoWallOrientation::WorldX);
	assert(!iso_wall_orientation_for_shape(18, 0).has_value());

	const auto long_x = iso_wall_profile_for_shape(152, 0, 53, 28, 5);
	assert(long_x);
	assert(long_x->footprint_width_tiles == 4);
	assert(long_x->footprint_height_tiles == 1);
	assert(long_x->top.width == 32 && long_x->top.height == 8);
	assert(long_x->front.y == 8 && long_x->front.width == 32);
	assert(long_x->right.x == 32 && long_x->right.height == 8);

	const auto long_y = iso_wall_profile_for_shape(151, 0, 33, 54, 5);
	assert(long_y);
	assert(long_y->footprint_width_tiles == 1);
	assert(long_y->footprint_height_tiles == 4);
	assert(long_y->top.width == 8 && long_y->top.height == 32);
	assert(long_y->right.x == 8 && long_y->right.width == 25);
	assert(!iso_wall_profile_for_shape(869, 0, 53, 28, 5));
	return 0;
}
