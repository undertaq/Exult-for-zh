/*
 *  Copyright (C) 2025  The Exult Team
 *
 *  This program is free software; you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation; either version 2 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program; if not, write to the Free Software
 *  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
 */

#ifndef BILINGUALMAPPING_H
#define BILINGUALMAPPING_H

#include <string>
#include <unordered_map>

class BilingualMapping {
public:
	// Load mapping from binary .dat file. Returns true on success.
	static bool load(const std::string& path);

	// Look up Chinese text by English usecode key. Returns nullptr if not found.
	static const std::string* lookup(int func_id, const std::string& offset_key, int segment);

private:
	struct Key {
		int         func_id;
		std::string offset_key;
		int         segment;

		bool operator==(const Key& other) const {
			return func_id == other.func_id
				&& offset_key == other.offset_key
				&& segment == other.segment;
		}
	};

	struct KeyHash {
		std::size_t operator()(const Key& k) const {
			std::size_t h1 = std::hash<int>{}(k.func_id);
			std::size_t h2 = std::hash<std::string>{}(k.offset_key);
			std::size_t h3 = std::hash<int>{}(k.segment);
			// Combine: from boost::hash_combine
			h1 ^= h2 + 0x9e3779b9 + (h1 << 6) + (h1 >> 2);
			h1 ^= h3 + 0x9e3779b9 + (h1 << 6) + (h1 >> 2);
			return h1;
		}
	};

	static std::unordered_map<Key, std::string, KeyHash> map_;
};

#endif
