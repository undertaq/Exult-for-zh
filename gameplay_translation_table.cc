#include "gameplay_translation_table.h"

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace {

constexpr char kTableVersion[] = "# u6-translation-v1";
constexpr char kTableColumns[] = "# kind\tkey\tsource_sha256\tzh";

constexpr std::array<std::uint32_t, 64> kSha256Constants = {{
		0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
		0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
		0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
		0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
		0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
		0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
		0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
		0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
		0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
		0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
		0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
		0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
		0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
		0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
		0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
		0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
}};

constexpr std::array<std::uint32_t, 8> kSha256InitialState = {{
		0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
		0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
}};

std::uint32_t rotate_right(std::uint32_t value, unsigned int count) {
	return (value >> count) | (value << (32U - count));
}

std::uint32_t choose(std::uint32_t x, std::uint32_t y, std::uint32_t z) {
	return (x & y) ^ (~x & z);
}

std::uint32_t majority(std::uint32_t x, std::uint32_t y, std::uint32_t z) {
	return (x & y) ^ (x & z) ^ (y & z);
}

std::uint32_t big_sigma_0(std::uint32_t value) {
	return rotate_right(value, 2) ^ rotate_right(value, 13)
			^ rotate_right(value, 22);
}

std::uint32_t big_sigma_1(std::uint32_t value) {
	return rotate_right(value, 6) ^ rotate_right(value, 11)
			^ rotate_right(value, 25);
}

std::uint32_t small_sigma_0(std::uint32_t value) {
	return rotate_right(value, 7) ^ rotate_right(value, 18) ^ (value >> 3);
}

std::uint32_t small_sigma_1(std::uint32_t value) {
	return rotate_right(value, 17) ^ rotate_right(value, 19) ^ (value >> 10);
}

void compress_sha256_block(
		const std::uint8_t* block, std::array<std::uint32_t, 8>& state) {
	std::array<std::uint32_t, 64> schedule = {{}};
	for (std::size_t i = 0; i < 16; ++i) {
		schedule[i] = (static_cast<std::uint32_t>(block[i * 4]) << 24)
				| (static_cast<std::uint32_t>(block[i * 4 + 1]) << 16)
				| (static_cast<std::uint32_t>(block[i * 4 + 2]) << 8)
				| static_cast<std::uint32_t>(block[i * 4 + 3]);
	}
	for (std::size_t i = 16; i < schedule.size(); ++i) {
		schedule[i] = small_sigma_1(schedule[i - 2]) + schedule[i - 7]
				+ small_sigma_0(schedule[i - 15]) + schedule[i - 16];
	}

	std::uint32_t a = state[0];
	std::uint32_t b = state[1];
	std::uint32_t c = state[2];
	std::uint32_t d = state[3];
	std::uint32_t e = state[4];
	std::uint32_t f = state[5];
	std::uint32_t g = state[6];
	std::uint32_t h = state[7];
	for (std::size_t i = 0; i < schedule.size(); ++i) {
		const std::uint32_t temp1 = h + big_sigma_1(e) + choose(e, f, g)
				+ kSha256Constants[i] + schedule[i];
		const std::uint32_t temp2 = big_sigma_0(a) + majority(a, b, c);
		h = g;
		g = f;
		f = e;
		e = d + temp1;
		d = c;
		c = b;
		b = a;
		a = temp1 + temp2;
	}

	state[0] += a;
	state[1] += b;
	state[2] += c;
	state[3] += d;
	state[4] += e;
	state[5] += f;
	state[6] += g;
	state[7] += h;
}

std::string sha256_hex_impl(std::string_view source) {
	std::vector<std::uint8_t> padded(source.begin(), source.end());
	padded.push_back(0x80);
	while ((padded.size() + 8) % 64 != 0) {
		padded.push_back(0);
	}

	std::uint64_t bit_length = source.size();
	bit_length *= 8;
	for (int shift = 56; shift >= 0; shift -= 8) {
		padded.push_back(
				static_cast<std::uint8_t>(bit_length >> shift));
	}

	std::array<std::uint32_t, 8> state = kSha256InitialState;
	for (std::size_t offset = 0; offset < padded.size(); offset += 64) {
		compress_sha256_block(padded.data() + offset, state);
	}

	static constexpr char kHex[] = "0123456789abcdef";
	std::string result;
	result.reserve(64);
	for (std::uint32_t word : state) {
		for (int shift = 28; shift >= 0; shift -= 4) {
			result.push_back(kHex[(word >> shift) & 0x0f]);
		}
	}
	return result;
}

bool is_valid_utf8(std::string_view text) {
	std::size_t index = 0;
	while (index < text.size()) {
		const unsigned char first =
				static_cast<unsigned char>(text[index]);
		if (first <= 0x7f) {
			++index;
			continue;
		}

		std::size_t continuation_count = 0;
		unsigned char second_min = 0x80;
		unsigned char second_max = 0xbf;
		if (first >= 0xc2 && first <= 0xdf) {
			continuation_count = 1;
		} else if (first == 0xe0) {
			continuation_count = 2;
			second_min = 0xa0;
		} else if (first >= 0xe1 && first <= 0xec) {
			continuation_count = 2;
		} else if (first == 0xed) {
			continuation_count = 2;
			second_max = 0x9f;
		} else if (first >= 0xee && first <= 0xef) {
			continuation_count = 2;
		} else if (first == 0xf0) {
			continuation_count = 3;
			second_min = 0x90;
		} else if (first >= 0xf1 && first <= 0xf3) {
			continuation_count = 3;
		} else if (first == 0xf4) {
			continuation_count = 3;
			second_max = 0x8f;
		} else {
			return false;
		}

		if (index + continuation_count >= text.size()) {
			return false;
		}
		const unsigned char second =
				static_cast<unsigned char>(text[index + 1]);
		if (second < second_min || second > second_max) {
			return false;
		}
		for (std::size_t offset = 2; offset <= continuation_count;
				offset++) {
			const unsigned char continuation = static_cast<unsigned char>(
					text[index + offset]);
			if (continuation < 0x80 || continuation > 0xbf) {
				return false;
			}
		}
		index += continuation_count + 1;
	}
	return true;
}

bool parse_kind(std::string_view value, GameplayTranslationKind& kind) {
	if (value == "dialogue") {
		kind = GameplayTranslationKind::Dialogue;
	} else if (value == "choice") {
		kind = GameplayTranslationKind::Choice;
	} else if (value == "textmsg") {
		kind = GameplayTranslationKind::TextMessage;
	} else if (value == "item") {
		kind = GameplayTranslationKind::Item;
	} else if (value == "location") {
		kind = GameplayTranslationKind::Location;
	} else if (value == "misc") {
		kind = GameplayTranslationKind::Misc;
	} else if (value == "spell") {
		kind = GameplayTranslationKind::Spell;
	} else {
		return false;
	}
	return true;
}

bool valid_hash(std::string_view value) {
	if (value.size() != 64) {
		return false;
	}
	for (const char character : value) {
		if (!((character >= '0' && character <= '9')
				|| (character >= 'a' && character <= 'f'))) {
			return false;
		}
	}
	return true;
}

void remove_line_ending(std::string& line) {
	if (!line.empty() && line.back() == '\r') {
		line.pop_back();
	}
}

bool fail_load(std::string& error, std::size_t line_number,
		std::string_view reason) {
	error = "line " + std::to_string(line_number) + ": "
				+ std::string(reason);
	return false;
}

} // namespace

std::string normalize_translation_source(std::string_view source) {
	std::string normalized;
	normalized.reserve(source.size());
	for (std::size_t index = 0; index < source.size(); ++index) {
		if (source[index] == '\r') {
			if (index + 1 < source.size() && source[index + 1] == '\n') {
				++index;
			}
			normalized.push_back('\n');
		} else {
			normalized.push_back(source[index]);
		}
	}
	return normalized;
}

std::string sha256_hex(std::string_view source) {
	return sha256_hex_impl(source);
}

std::string escape_translation_field(std::string_view field) {
	std::string escaped;
	escaped.reserve(field.size());
	for (const char character : field) {
		switch (character) {
		case '\\':
			escaped += "\\\\";
			break;
		case '\t':
			escaped += "\\t";
			break;
		case '\n':
			escaped += "\\n";
			break;
		case '\r':
			escaped += "\\r";
			break;
		default:
			escaped.push_back(character);
			break;
		}
	}
	return escaped;
}

std::optional<std::string> unescape_translation_field(
		std::string_view field, std::string& error) {
	error.clear();
	std::string unescaped;
	unescaped.reserve(field.size());
	for (std::size_t index = 0; index < field.size(); ++index) {
		if (field[index] != '\\') {
			unescaped.push_back(field[index]);
			continue;
		}
		if (index + 1 >= field.size()) {
			error = "trailing escape";
			return std::nullopt;
		}
		switch (field[++index]) {
		case '\\':
			unescaped.push_back('\\');
			break;
		case 't':
			unescaped.push_back('\t');
			break;
		case 'n':
			unescaped.push_back('\n');
			break;
		case 'r':
			unescaped.push_back('\r');
			break;
		default:
			error = "unknown escape sequence";
			return std::nullopt;
		}
	}
	return unescaped;
}

bool GameplayTranslationTable::load(
		std::istream& input, std::string& error) {
	error.clear();
	std::map<EntryKey, Entry> new_entries;
	std::string line;
	std::size_t line_number = 1;

	if (!std::getline(input, line)) {
		return fail_load(error, line_number, "missing table header");
	}
	remove_line_ending(line);
	if (line != kTableVersion) {
		return fail_load(error, line_number, "invalid table version");
	}

	++line_number;
	if (!std::getline(input, line)) {
		return fail_load(error, line_number, "missing column header");
	}
	remove_line_ending(line);
	if (line != kTableColumns) {
		return fail_load(error, line_number, "invalid column header");
	}

	++line_number;
	while (std::getline(input, line)) {
		remove_line_ending(line);
		std::vector<std::string_view> fields;
		std::size_t start = 0;
		while (true) {
			const std::size_t separator = line.find('\t', start);
			if (separator == std::string::npos) {
				fields.emplace_back(line.data() + start, line.size() - start);
				break;
			}
			fields.emplace_back(line.data() + start, separator - start);
			start = separator + 1;
		}
		if (fields.size() != 4) {
			return fail_load(error, line_number, "expected four fields");
		}

		std::array<std::string, 4> values;
		for (std::size_t index = 0; index < fields.size(); ++index) {
			std::string field_error;
			std::optional<std::string> value =
					unescape_translation_field(fields[index], field_error);
			if (!value.has_value()) {
				return fail_load(error, line_number, field_error);
			}
			values[index] = std::move(*value);
		}

		GameplayTranslationKind kind;
		if (!parse_kind(values[0], kind)) {
			return fail_load(error, line_number, "unknown translation kind");
		}
		if (values[1].empty()) {
			return fail_load(error, line_number, "empty translation key");
		}
		if (!valid_hash(values[2])) {
			return fail_load(error, line_number, "invalid source hash");
		}
		if (values[3].empty()) {
			return fail_load(error, line_number, "empty Chinese text");
		}
		if (!is_valid_utf8(values[0]) || !is_valid_utf8(values[1])
				|| !is_valid_utf8(values[3])) {
			return fail_load(error, line_number, "invalid UTF-8");
		}

		const EntryKey key(static_cast<int>(kind), values[1]);
		const auto inserted = new_entries.emplace(
				key, Entry{values[2], values[3]});
		if (!inserted.second) {
			return fail_load(error, line_number, "duplicate translation key");
		}
		++line_number;
	}
	if (input.bad()) {
		return fail_load(error, line_number, "failed while reading table");
	}

	entries_.swap(new_entries);
	return true;
}

TranslationLookup GameplayTranslationTable::lookup(
		GameplayTranslationKind kind, std::string_view key,
		std::string_view english) const {
	const EntryKey entry_key(static_cast<int>(kind), std::string(key));
	const auto entry = entries_.find(entry_key);
	if (entry == entries_.end()) {
		return TranslationLookup{std::string(english),
				TranslationLookupStatus::Missing};
	}
	if (entry->second.source_sha256
				!= sha256_hex(normalize_translation_source(english))) {
		return TranslationLookup{std::string(english),
				TranslationLookupStatus::SourceMismatch};
	}
	return TranslationLookup{entry->second.text, TranslationLookupStatus::Hit};
}

std::size_t GameplayTranslationTable::size() const {
	return entries_.size();
}
