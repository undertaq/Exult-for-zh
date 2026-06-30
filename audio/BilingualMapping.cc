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

std::unordered_map<BilingualMapping::Key, std::string, BilingualMapping::KeyHash>
	BilingualMapping::map_;

// Helper: read bytes from file, return false and log on failure.
static bool read_or_fail(
		std::ifstream& file, char* buf, std::streamsize n,
		const char* field, std::ifstream::pos_type& last_good) {
	if (!file.read(buf, n)) {
		// Restore to last known good position for a more useful diagnostic.
		file.clear();
		file.seekg(last_good);
		pout << "[BilingualMapping] Failed to read " << field << std::endl;
		return false;
	}
	last_good = file.tellg();
	return true;
}

template <typename T>
static bool read_int(std::ifstream& file, T& val, const char* field, std::ifstream::pos_type& last_good) {
	return read_or_fail(
			file, reinterpret_cast<char*>(&val), sizeof(val), field, last_good);
}

bool BilingualMapping::load(const std::string& path) {
	map_.clear();

	std::ifstream file(path, std::ios::binary);
	if (!file.is_open()) {
		pout << "[BilingualMapping] Cannot open: " << path << std::endl;
		return false;
	}

	std::ifstream::pos_type last_good = 0;

	char magic[4];
	if (!read_or_fail(file, magic, 4, "magic", last_good)) {
		return false;
	}
	if (std::memcmp(magic, "BLMP", 4) != 0) {
		pout << "[BilingualMapping] Bad magic" << std::endl;
		return false;
	}

	uint16 version;
	if (!read_int(file, version, "version", last_good)) {
		return false;
	}
	if (version != 1) {
		pout << "[BilingualMapping] Unsupported version: " << version << std::endl;
		return false;
	}

	uint32 num_entries;
	if (!read_int(file, num_entries, "num_entries", last_good)) {
		return false;
	}

	for (uint32 i = 0; i < num_entries; i++) {
		uint16 func_id;
		if (!read_int(file, func_id, "func_id", last_good)) {
			return false;
		}

		uint16 key_len;
		if (!read_int(file, key_len, "key_len", last_good)) {
			return false;
		}
		if (key_len > 1024) {
			pout << "[BilingualMapping] key_len too large: " << key_len << std::endl;
			return false;
		}
		std::string offset_key(key_len, '\0');
		if (!read_or_fail(file, &offset_key[0], key_len, "offset_key", last_good)) {
			return false;
		}

		uint16 segment;
		if (!read_int(file, segment, "segment", last_good)) {
			return false;
		}

		uint32 text_len;
		if (!read_int(file, text_len, "text_len", last_good)) {
			return false;
		}
		if (text_len > 65536) {
			pout << "[BilingualMapping] text_len too large: " << text_len << std::endl;
			return false;
		}
		std::string text(text_len, '\0');
		if (!read_or_fail(file, &text[0], text_len, "text", last_good)) {
			return false;
		}

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
