#include "objs/objs.h"

#include <type_traits>

// Fixed scenery must own a paint override so wall classification is applied
// only to IFIX objects, without changing the generic sprite path.
static_assert(std::is_same_v<
		decltype(&Ifix_game_object::paint), void (Ifix_game_object::*)()>);

int main() {
	return 0;
}
