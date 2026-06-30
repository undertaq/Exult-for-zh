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

#ifdef HAVE_CONFIG_H
#	include <config.h>
#endif

#include "BilingualMapping.h"
#include "pent_include.h"
#include "utils.h"
#include <cstring>
#include <fstream>
#include <vector>

std::unordered_map<BilingualMapping::Key, std::string, BilingualMapping::KeyHash>
	BilingualMapping::map_;

bool BilingualMapping::load(const std::string& path) {
	map_.clear();

	std::ifstream file(path, std::ios::binary);
	if (!file.is_open()) {
		pout << "[BilingualMapping] Cannot open: " << path << std::endl;
		return false;
	}

	// Read header
	char magic[4];
	file.read(magic, 4);
	if (std::memcmp(magic, "BLMP", 4) != 0) {
		pout << "[BilingualMapping] Bad magic" << std::endl;
		return false;
	}

	uint16 version;
	file.read(reinterpret_cast<char*>(&version), sizeof(version));
	if (version != 1) {
		pout << "[BilingualMapping] Unsupported version: " << version << std::endl;
		return false;
	}

	uint32 num_entries;
	file.read(reinterpret_cast<char*>(&num_entries), sizeof(num_entries));

	for (uint32 i = 0; i < num_entries; i++) {
		uint16 func_id;
		file.read(reinterpret_cast<char*>(&func_id), sizeof(func_id));

		uint16 key_len;
		file.read(reinterpret_cast<char*>(&key_len), sizeof(key_len));
		std::string offset_key(key_len, '\0');
		file.read(&offset_key[0], key_len);

		uint16 segment;
		file.read(reinterpret_cast<char*>(&segment), sizeof(segment));

		uint32 text_len;
		file.read(reinterpret_cast<char*>(&text_len), sizeof(text_len));
		std::string text(text_len, '\0');
		file.read(&text[0], text_len);

		map_[Key{func_id, offset_key, segment}] = text;
	}

	pout << "[BilingualMapping] Loaded " << map_.size() << " entries" << std::endl;
	return true;
}

const std::string* BilingualMapping::lookup(
		int func_id, const std::string& offset_key, int segment) {
	auto it = map_.find(Key{func_id, offset_key, segment});
	if (it != map_.end()) {
		return &it->second;
	}
	return nullptr;
}
