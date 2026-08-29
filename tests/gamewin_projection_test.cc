#include "gamewin.h"

#include <type_traits>
#include <utility>

template <typename T, typename = void>
struct has_screen_to_tile : std::false_type {};

template <typename T>
struct has_screen_to_tile<T, std::void_t<decltype(std::declval<const T&>().screen_to_tile(
		0, 0, std::declval<Tile_coord&>()))>> : std::true_type {};

static_assert(has_screen_to_tile<Game_window>::value, "Game_window must expose projected screen-to-tile picking");

int main() {
	return 0;
}
