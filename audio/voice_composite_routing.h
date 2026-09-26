#ifndef EXULT_VOICE_COMPOSITE_ROUTING_H
#define EXULT_VOICE_COMPOSITE_ROUTING_H

#include "gameplay_translation.h"

#include <algorithm>
#include <cerrno>
#include <cctype>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <istream>
#include <map>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace U6VoiceRouting {

enum class VoiceGender { Male, Female };

struct DynamicVoiceSourcePart {
	VoiceCompositeFragmentKind kind = VoiceCompositeFragmentKind::Literal;
	int source_function_id = -1;
	std::uint32_t source_offset = 0;
	std::uint32_t string_offset = 0;
	std::uint32_t variable_index = 0;
	std::uint32_t ordinal = 0;
	std::string text;
	std::string semantic_type = "unknown";
	std::string pronoun_form;
};

struct DynamicVoiceMetadata {
	int function_id = -1;
	std::string offset_key;
	std::size_t segment = 0;
	std::string key;
	std::string source_template_en;
	bool player_gender_variant = false;
	std::vector<DynamicVoiceSourcePart> source_parts;
	std::vector<VoiceCompositeRoleSpan> role_spans;
};

struct VoiceRouteContext {
	int speaker_npc = 0;
	int caller_npc = 0;
	std::string speaker_name;
	VoiceGender speaker_gender = VoiceGender::Male;
	VoiceGender player_gender = VoiceGender::Male;
	bool speaker_gender_known = true;
	bool player_gender_known = true;
};

using ClipCandidateGroups = std::vector<std::vector<std::string>>;

struct ResolvedVoiceClip {
	std::string name;
	std::string path;
	std::vector<char> packed_data;
	bool packed = false;
};

namespace detail {

struct JsonValue {
	enum class Type { Null, Boolean, Number, String, Array, Object } type = Type::Null;
	std::string scalar;
	std::vector<JsonValue> array;
	std::map<std::string, JsonValue> object;
};

class JsonParser {
public:
	explicit JsonParser(std::string_view source) : source_(source) {}

	bool parse(JsonValue& value, std::string& error) {
		if (!parse_value(value, 0, error)) {
			return false;
		}
		skip_space();
		if (position_ != source_.size()) {
			error = "trailing data after JSON value";
			return false;
		}
		return true;
	}

private:
	std::string_view source_;
	std::size_t position_ = 0;

	void skip_space() {
		while (position_ < source_.size()
				&& (source_[position_] == ' ' || source_[position_] == '\t'
						|| source_[position_] == '\r' || source_[position_] == '\n')) {
			++position_;
		}
	}

	static void append_utf8(std::string& output, std::uint32_t codepoint) {
		if (codepoint <= 0x7fU) {
			output.push_back(static_cast<char>(codepoint));
		} else if (codepoint <= 0x7ffU) {
			output.push_back(static_cast<char>(0xc0U | (codepoint >> 6)));
			output.push_back(static_cast<char>(0x80U | (codepoint & 0x3fU)));
		} else if (codepoint <= 0xffffU) {
			output.push_back(static_cast<char>(0xe0U | (codepoint >> 12)));
			output.push_back(static_cast<char>(0x80U | ((codepoint >> 6) & 0x3fU)));
			output.push_back(static_cast<char>(0x80U | (codepoint & 0x3fU)));
		} else {
			output.push_back(static_cast<char>(0xf0U | (codepoint >> 18)));
			output.push_back(static_cast<char>(0x80U | ((codepoint >> 12) & 0x3fU)));
			output.push_back(static_cast<char>(0x80U | ((codepoint >> 6) & 0x3fU)));
			output.push_back(static_cast<char>(0x80U | (codepoint & 0x3fU)));
		}
	}

	bool parse_hex4(std::uint32_t& value) {
		if (source_.size() - position_ < 4) {
			return false;
		}
		value = 0;
		for (unsigned index = 0; index < 4; ++index) {
			const char ch = source_[position_++];
			unsigned digit;
			if (ch >= '0' && ch <= '9') {
				digit = static_cast<unsigned>(ch - '0');
			} else if (ch >= 'a' && ch <= 'f') {
				digit = static_cast<unsigned>(ch - 'a' + 10);
			} else if (ch >= 'A' && ch <= 'F') {
				digit = static_cast<unsigned>(ch - 'A' + 10);
			} else {
				return false;
			}
			value = (value << 4) | digit;
		}
		return true;
	}

	bool parse_string(std::string& value, std::string& error) {
		if (position_ >= source_.size() || source_[position_++] != '"') {
			error = "expected JSON string";
			return false;
		}
		value.clear();
		while (position_ < source_.size()) {
			const unsigned char ch = static_cast<unsigned char>(source_[position_++]);
			if (ch == '"') {
				return true;
			}
			if (ch < 0x20U) {
				error = "unescaped control character in JSON string";
				return false;
			}
			if (ch != '\\') {
				value.push_back(static_cast<char>(ch));
				continue;
			}
			if (position_ >= source_.size()) {
				error = "truncated JSON escape";
				return false;
			}
			const char escape = source_[position_++];
			switch (escape) {
			case '"': value.push_back('"'); break;
			case '\\': value.push_back('\\'); break;
			case '/': value.push_back('/'); break;
			case 'b': value.push_back('\b'); break;
			case 'f': value.push_back('\f'); break;
			case 'n': value.push_back('\n'); break;
			case 'r': value.push_back('\r'); break;
			case 't': value.push_back('\t'); break;
			case 'u': {
				std::uint32_t first;
				if (!parse_hex4(first)) {
					error = "invalid Unicode escape in JSON string";
					return false;
				}
				if (first >= 0xd800U && first <= 0xdbffU) {
					if (source_.size() - position_ < 6
							|| source_[position_] != '\\'
							|| source_[position_ + 1] != 'u') {
						error = "unpaired high surrogate in JSON string";
						return false;
					}
					position_ += 2;
					std::uint32_t second;
					if (!parse_hex4(second) || second < 0xdc00U || second > 0xdfffU) {
						error = "invalid low surrogate in JSON string";
						return false;
					}
					first = 0x10000U + ((first - 0xd800U) << 10)
							+ (second - 0xdc00U);
				} else if (first >= 0xdc00U && first <= 0xdfffU) {
					error = "unpaired low surrogate in JSON string";
					return false;
				}
				append_utf8(value, first);
				break;
			}
			default:
				error = "unknown JSON string escape";
				return false;
			}
		}
		error = "unterminated JSON string";
		return false;
	}

	bool parse_value(JsonValue& value, unsigned depth, std::string& error) {
		if (depth > 64) {
			error = "JSON nesting is too deep";
			return false;
		}
		skip_space();
		if (position_ >= source_.size()) {
			error = "unexpected end of JSON";
			return false;
		}
		const char ch = source_[position_];
		if (ch == '"') {
			value.type = JsonValue::Type::String;
			return parse_string(value.scalar, error);
		}
		if (ch == '{') {
			++position_;
			value.type = JsonValue::Type::Object;
			skip_space();
			if (position_ < source_.size() && source_[position_] == '}') {
				++position_;
				return true;
			}
			while (position_ < source_.size()) {
				skip_space();
				std::string key;
				if (!parse_string(key, error)) return false;
				skip_space();
				if (position_ >= source_.size() || source_[position_++] != ':') {
					error = "expected ':' in JSON object";
					return false;
				}
				JsonValue member;
				if (!parse_value(member, depth + 1, error)) return false;
				if (!value.object.emplace(std::move(key), std::move(member)).second) {
					error = "duplicate key in JSON object";
					return false;
				}
				skip_space();
				if (position_ < source_.size() && source_[position_] == '}') {
					++position_;
					return true;
				}
				if (position_ >= source_.size() || source_[position_++] != ',') {
					error = "expected ',' in JSON object";
					return false;
				}
			}
		error = "unterminated JSON object";
			return false;
		}
		if (ch == '[') {
			++position_;
			value.type = JsonValue::Type::Array;
			skip_space();
			if (position_ < source_.size() && source_[position_] == ']') {
				++position_;
				return true;
			}
			while (position_ < source_.size()) {
				JsonValue item;
				if (!parse_value(item, depth + 1, error)) return false;
				value.array.push_back(std::move(item));
				skip_space();
				if (position_ < source_.size() && source_[position_] == ']') {
					++position_;
					return true;
				}
				if (position_ >= source_.size() || source_[position_++] != ',') {
					error = "expected ',' in JSON array";
					return false;
				}
			}
			error = "unterminated JSON array";
			return false;
		}
		if (source_.substr(position_, 4) == "true") {
			position_ += 4;
			value.type = JsonValue::Type::Boolean;
			value.scalar = "true";
			return true;
		}
		if (source_.substr(position_, 5) == "false") {
			position_ += 5;
			value.type = JsonValue::Type::Boolean;
			value.scalar = "false";
			return true;
		}
		if (source_.substr(position_, 4) == "null") {
			position_ += 4;
			value.type = JsonValue::Type::Null;
			return true;
		}
		const std::size_t begin = position_;
		if (source_[position_] == '-') ++position_;
		if (position_ >= source_.size() || !std::isdigit(
				static_cast<unsigned char>(source_[position_]))) {
			error = "invalid JSON value";
			return false;
		}
		if (source_[position_] == '0') {
			++position_;
		} else {
			while (position_ < source_.size() && std::isdigit(
					static_cast<unsigned char>(source_[position_]))) ++position_;
		}
		if (position_ < source_.size() && source_[position_] == '.') {
			++position_;
			while (position_ < source_.size() && std::isdigit(
					static_cast<unsigned char>(source_[position_]))) ++position_;
		}
		if (position_ < source_.size()
				&& (source_[position_] == 'e' || source_[position_] == 'E')) {
			++position_;
			if (position_ < source_.size()
					&& (source_[position_] == '+' || source_[position_] == '-')) ++position_;
			while (position_ < source_.size() && std::isdigit(
					static_cast<unsigned char>(source_[position_]))) ++position_;
		}
		value.type = JsonValue::Type::Number;
		value.scalar.assign(source_.substr(begin, position_ - begin));
		return true;
	}
};

inline const JsonValue* member(const JsonValue& value, const char* key) {
	if (value.type != JsonValue::Type::Object) return nullptr;
	const auto found = value.object.find(key);
	return found == value.object.end() ? nullptr : &found->second;
}

inline bool as_string(const JsonValue* value, std::string& output) {
	if (!value || value->type != JsonValue::Type::String) return false;
	output = value->scalar;
	return true;
}

inline bool as_integer(const JsonValue* value, std::uint64_t& output) {
	if (!value || (value->type != JsonValue::Type::Number
			&& value->type != JsonValue::Type::String)) return false;
	const std::string& text = value->scalar;
	if (text.empty() || text.front() == '-') return false;
	char* end = nullptr;
	errno = 0;
	const int base = text.size() > 2 && text[0] == '0'
			&& (text[1] == 'x' || text[1] == 'X') ? 16 : 10;
	const char* begin = text.c_str() + (base == 16 ? 2 : 0);
	const unsigned long long parsed = std::strtoull(begin, &end, base);
	if (errno != 0 || end == begin || *end != '\0') return false;
	output = static_cast<std::uint64_t>(parsed);
	return true;
}

inline bool as_boolean(const JsonValue* value, bool& output) {
	if (!value || value->type != JsonValue::Type::Boolean) return false;
	output = value->scalar == "true";
	return true;
}

inline bool read_uint(const JsonValue& object, const char* key,
		std::uint64_t& output) {
	return as_integer(member(object, key), output);
}

inline bool read_string(const JsonValue& object, const char* key,
		std::string& output) {
	return as_string(member(object, key), output);
}

inline bool decode_utf8_codepoint(std::string_view text, std::size_t& position,
		std::uint32_t& codepoint) {
	if (position >= text.size()) return false;
	const unsigned char lead = static_cast<unsigned char>(text[position]);
	std::size_t length;
	std::uint32_t minimum;
	if (lead <= 0x7fU) {
		length = 1;
		minimum = 0;
		codepoint = lead;
	} else if (lead >= 0xc2U && lead <= 0xdfU) {
		length = 2;
		minimum = 0x80U;
		codepoint = lead & 0x1fU;
	} else if (lead >= 0xe0U && lead <= 0xefU) {
		length = 3;
		minimum = 0x800U;
		codepoint = lead & 0x0fU;
	} else if (lead >= 0xf0U && lead <= 0xf4U) {
		length = 4;
		minimum = 0x10000U;
		codepoint = lead & 0x07U;
	} else {
		return false;
	}
	if (text.size() - position < length) return false;
	for (std::size_t index = 1; index < length; ++index) {
		const unsigned char continuation =
				static_cast<unsigned char>(text[position + index]);
		if ((continuation & 0xc0U) != 0x80U) return false;
		codepoint = (codepoint << 6) | (continuation & 0x3fU);
	}
	if (codepoint < minimum || codepoint > 0x10ffffU
			|| (codepoint >= 0xd800U && codepoint <= 0xdfffU)) {
		return false;
	}
	position += length;
	return true;
}

inline bool is_nonspoken_unicode_punctuation(std::uint32_t codepoint) {
	return (codepoint >= 0x2000U && codepoint <= 0x206fU)
			|| (codepoint >= 0x2e00U && codepoint <= 0x2e7fU)
			|| (codepoint >= 0x3000U && codepoint <= 0x303fU)
			|| (codepoint >= 0xfe10U && codepoint <= 0xfe1fU)
			|| (codepoint >= 0xfe30U && codepoint <= 0xfe4fU)
			|| (codepoint >= 0xff01U && codepoint <= 0xff0fU)
			|| (codepoint >= 0xff1aU && codepoint <= 0xff20U)
			|| (codepoint >= 0xff3bU && codepoint <= 0xff40U)
			|| (codepoint >= 0xff5bU && codepoint <= 0xff65U);
}

inline bool is_spoken_codepoint(std::uint32_t codepoint) {
	if (codepoint < 0x80U) {
		const unsigned char ch = static_cast<unsigned char>(codepoint);
		return std::isalnum(ch) || ch == '_';
	}
	return !is_nonspoken_unicode_punctuation(codepoint)
			&& codepoint != 0x00a0U && codepoint != 0x1680U
			&& !(codepoint >= 0x2000U && codepoint <= 0x200aU)
			&& codepoint != 0x2028U && codepoint != 0x2029U
			&& codepoint != 0x202fU && codepoint != 0x205fU
			&& codepoint != 0x3000U;
}

inline bool role_span_has_spoken_text(std::string_view source_template,
		std::uint64_t start_char, std::uint64_t end_char,
		bool& spoken, std::string& error) {
	std::size_t position = 0;
	std::size_t character = 0;
	spoken = false;
	while (position < source_template.size()) {
		std::uint32_t codepoint;
		if (!decode_utf8_codepoint(source_template, position, codepoint)) {
			error = "dynamic source template contains invalid UTF-8";
			return false;
		}
		if (character >= start_char && character < end_char) {
			if (is_spoken_codepoint(codepoint)) {
				// Treat unfamiliar non-ASCII characters as audible content.  This
				// is deliberately conservative: a bad false flag must never drop
				// spoken words from an otherwise valid composite.
				spoken = true;
			}
		}
		++character;
	}
	if (end_char > character) {
		error = "dynamic role span is outside the source template";
		return false;
	}
	return true;
}

inline bool validate_role_span_coverage(std::string_view source_template,
		const std::vector<VoiceCompositeRoleSpan>& spans, std::string& error) {
	std::vector<unsigned char> spoken;
	std::size_t position = 0;
	while (position < source_template.size()) {
		std::uint32_t codepoint;
		if (!decode_utf8_codepoint(source_template, position, codepoint)) {
			error = "dynamic source template contains invalid UTF-8";
			return false;
		}
		spoken.push_back(is_spoken_codepoint(codepoint) ? 1U : 0U);
	}
	std::vector<unsigned char> coverage(spoken.size(), 0U);
	std::size_t previous_start = 0;
	std::size_t previous_end = 0;
	bool have_previous = false;
	for (const VoiceCompositeRoleSpan& span : spans) {
		if (span.end_char > spoken.size()) {
			error = "dynamic role span is outside the source template";
			return false;
		}
		if (have_previous && span.start_char < previous_start) {
			error = "dynamic role spans are not in source order";
			return false;
		}
		if (have_previous && span.start_char < previous_end) {
			error = "dynamic role spans overlap";
			return false;
		}
		for (std::size_t character = span.start_char;
				character < span.end_char; ++character) {
			if (coverage[character] != 0U) {
				error = "dynamic role spans overlap";
				return false;
			}
			coverage[character] = 1U;
		}
		previous_start = span.start_char;
		previous_end = span.end_char;
		have_previous = true;
	}
	for (std::size_t character = 0; character < spoken.size(); ++character) {
		if (spoken[character] != 0U && coverage[character] == 0U) {
			error = "dynamic role spans omit spoken source text";
			return false;
		}
	}
	return true;
}

inline bool read_role_spans(const JsonValue& row,
		std::string_view source_template,
		std::vector<VoiceCompositeRoleSpan>& spans, std::string& error) {
	const JsonValue* value = member(row, "role_spans");
	if (!value || value->type != JsonValue::Type::Array || value->array.empty()) {
		error = "dynamic voice metadata has no role spans";
		return false;
	}
	spans.clear();
	for (std::size_t index = 0; index < value->array.size(); ++index) {
		const JsonValue& item = value->array[index];
		std::string role;
		std::uint64_t manifest_index = 0, start = 0, end = 0;
		bool requires_audio = true;
		const JsonValue* audio_value = member(item, "requires_audio");
		if (audio_value && !as_boolean(audio_value, requires_audio)) {
			error = "dynamic role span has invalid requires_audio";
			return false;
		}
		if (!read_string(item, "role", role)
				|| (role != "speaker" && role != "narrator")
				|| !read_uint(item, "index", manifest_index)
				|| manifest_index != index
				|| !read_uint(item, "start_char", start)
				|| !read_uint(item, "end_char", end) || end <= start) {
			error = "dynamic voice metadata has an invalid role span";
			return false;
		}
		bool spoken_text = false;
		if (!role_span_has_spoken_text(source_template, start, end,
				spoken_text, error)
				|| requires_audio != spoken_text) {
			if (error.empty()) {
				error = "dynamic role requires_audio flag disagrees with source text";
			}
			return false;
		}
		VoiceCompositeRoleSpan span;
		span.role = std::move(role);
		span.start_char = static_cast<std::size_t>(start);
		span.end_char = static_cast<std::size_t>(end);
		span.requires_audio = requires_audio;
		spans.push_back(std::move(span));
	}
	return true;
}

inline bool read_source_parts(const JsonValue& row,
		std::vector<DynamicVoiceSourcePart>& parts, std::string& error) {
	const JsonValue* value = member(row, "source_parts");
	if (!value || value->type != JsonValue::Type::Array || value->array.empty()) {
		error = "dynamic voice metadata has no source parts";
		return false;
	}
	parts.clear();
	for (const JsonValue& item : value->array) {
		DynamicVoiceSourcePart part;
		std::string kind;
		std::uint64_t function_id = 0, source_offset = 0;
		if (!read_string(item, "kind", kind)
				|| !read_uint(item, "source_func_id", function_id)
				|| function_id > static_cast<std::uint64_t>(INT32_MAX)
				|| !read_uint(item, "source_offset", source_offset)
				|| source_offset > UINT32_MAX) {
			error = "dynamic voice metadata has invalid source provenance";
			return false;
		}
		part.source_function_id = static_cast<int>(function_id);
		part.source_offset = static_cast<std::uint32_t>(source_offset);
		if (kind == "literal") {
			part.kind = VoiceCompositeFragmentKind::Literal;
			std::uint64_t string_offset = 0;
			if (!read_uint(item, "string_offset", string_offset)
					|| string_offset > UINT32_MAX
					|| !read_string(item, "text", part.text)) {
				error = "dynamic voice metadata has invalid literal provenance";
				return false;
			}
			part.string_offset = static_cast<std::uint32_t>(string_offset);
		} else if (kind == "dynamic") {
			part.kind = VoiceCompositeFragmentKind::Dynamic;
			std::uint64_t variable = 0, ordinal = 0;
			if (!read_uint(item, "variable_index", variable)
					|| variable > UINT32_MAX
					|| !read_uint(item, "ordinal", ordinal)
						|| ordinal > UINT32_MAX
					|| !read_string(item, "semantic_type", part.semantic_type)) {
				error = "dynamic voice metadata has invalid slot provenance";
				return false;
			}
			part.variable_index = static_cast<std::uint32_t>(variable);
			part.ordinal = static_cast<std::uint32_t>(ordinal);
			if (const JsonValue* form = member(item, "pronoun_form")) {
				if (!as_string(form, part.pronoun_form)) {
					error = "dynamic voice metadata has an invalid pronoun form";
					return false;
				}
			}
		} else {
			error = "dynamic voice metadata has an unknown source-part kind";
			return false;
		}
		parts.push_back(std::move(part));
	}
	return true;
}

inline bool parse_manifest_row(const JsonValue& row,
		DynamicVoiceMetadata& metadata, std::string& error) {
	std::string schema;
	std::uint64_t function_id = 0, segment = 0;
	if (!read_string(row, "schema", schema)
			|| schema != "u6-dynamic-voice-template-v1"
			|| !read_string(row, "key", metadata.key)
			|| metadata.key.size() != 68
			|| metadata.key.compare(0, 4, "dyn_") != 0
			|| !read_uint(row, "function_id", function_id)
			|| function_id > static_cast<std::uint64_t>(INT32_MAX)
			|| !read_uint(row, "segment", segment)
			|| segment > UINT32_MAX
			|| !read_string(row, "offset_key", metadata.offset_key)
			|| !read_string(row, "source_template_en", metadata.source_template_en)) {
		error = "dynamic voice metadata has an invalid identity";
		return false;
	}
	for (std::size_t index = 4; index < metadata.key.size(); ++index) {
		if (!std::isxdigit(static_cast<unsigned char>(metadata.key[index]))) {
			error = "dynamic voice key is not a full SHA-256 identity";
			return false;
		}
		metadata.key[index] = static_cast<char>(std::tolower(
				static_cast<unsigned char>(metadata.key[index])));
	}
	metadata.function_id = static_cast<int>(function_id);
	metadata.segment = static_cast<std::size_t>(segment);
	metadata.source_template_en = normalize_translation_source(
			metadata.source_template_en);
	const JsonValue* variants = member(row, "player_gender_variants");
	if (!variants || variants->type != JsonValue::Type::Array) {
		error = "dynamic voice metadata has no player-gender variants";
		return false;
	}
	std::size_t null_variants = 0;
	std::size_t male_variants = 0;
	std::size_t female_variants = 0;
	for (const JsonValue& variant : variants->array) {
		if (variant.type == JsonValue::Type::Null) {
			++null_variants;
		} else if (variant.type == JsonValue::Type::String
				&& variant.scalar == "male") {
			++male_variants;
		} else if (variant.type == JsonValue::Type::String
				&& variant.scalar == "female") {
			++female_variants;
		} else {
			error = "dynamic voice metadata has an invalid player-gender variant";
			return false;
		}
	}
	if (!read_source_parts(row, metadata.source_parts, error)) return false;
	const bool gendered_slot = std::any_of(
			metadata.source_parts.begin(), metadata.source_parts.end(),
			[](const DynamicVoiceSourcePart& part) {
				return part.kind == VoiceCompositeFragmentKind::Dynamic
						&& (part.semantic_type == "pronoun"
								|| part.semantic_type == "gender_flag");
			});
	if (gendered_slot) {
		if (variants->array.size() != 2 || null_variants != 0
				|| male_variants != 1 || female_variants != 1) {
			error = "gender-dependent slots require exactly male and female variants";
			return false;
		}
		metadata.player_gender_variant = true;
	} else {
		if (variants->array.size() != 1 || null_variants != 1
				|| male_variants != 0 || female_variants != 0) {
			error = "gender-neutral slots require exactly one default variant";
			return false;
		}
		metadata.player_gender_variant = false;
	}
	return read_role_spans(row, metadata.source_template_en,
			metadata.role_spans, error)
			&& validate_role_span_coverage(metadata.source_template_en,
					metadata.role_spans, error);
}

inline std::string format_hex(std::uint64_t value, unsigned width = 0) {
	std::ostringstream output;
	output << std::hex << std::nouppercase << std::setfill('0')
			<< std::setw(static_cast<int>(width)) << value;
	return output.str();
}

inline std::uint64_t absolute_npc(int npc) {
	const std::int64_t value = npc;
	return static_cast<std::uint64_t>(value < 0 ? -value : value);
}

}  // namespace detail

inline std::string normalize_offset_key(std::string_view offset_key) {
	std::string result;
	std::size_t position = 0;
	while (position <= offset_key.size()) {
		const std::size_t end = offset_key.find('_', position);
		std::string part(offset_key.substr(
				position, end == std::string_view::npos
						? offset_key.size() - position : end - position));
		if (part.size() > 2 && part[0] == '0'
				&& (part[1] == 'x' || part[1] == 'X')) part.erase(0, 2);
		for (char& ch : part) {
			ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
		}
		const std::size_t nonzero = part.find_first_not_of('0');
		part = nonzero == std::string::npos ? "0" : part.substr(nonzero);
		if (!result.empty()) result.push_back('_');
		result += part;
		if (end == std::string_view::npos) break;
		position = end + 1;
	}
	return result;
}

inline bool parse_dynamic_voice_manifest(std::istream& input,
		std::vector<DynamicVoiceMetadata>& output, std::string& error) {
	std::vector<DynamicVoiceMetadata> parsed;
	std::string line;
	std::size_t line_number = 0;
	while (std::getline(input, line)) {
		++line_number;
		if (line.empty()) continue;
		DynamicVoiceMetadata row;
		detail::JsonValue root;
		std::string row_error;
		detail::JsonParser parser(line);
		if (!parser.parse(root, row_error)
				|| !detail::parse_manifest_row(root, row, row_error)) {
			error = "invalid U6 dynamic voice manifest line "
					+ std::to_string(line_number) + ": " + row_error;
			return false;
		}
		parsed.push_back(std::move(row));
	}
	if (input.bad()) {
		error = "failed while reading U6 dynamic voice manifest";
		return false;
	}
	output.swap(parsed);
	error.clear();
	return true;
}

inline bool enrich_dynamic_voice_plan(VoiceCompositePlan& plan,
		const std::string& offset_key,
		const std::vector<DynamicVoiceMetadata>& metadata,
		std::string& error) {
	if (plan.kind != VoiceCompositeKind::DynamicTemplate) {
		error = "dynamic metadata requested for a non-dynamic voice plan";
		return false;
	}
	const std::string normalized_offset = normalize_offset_key(offset_key);
	const DynamicVoiceMetadata* match = nullptr;
	for (const DynamicVoiceMetadata& row : metadata) {
		if (row.function_id == plan.function_id
				&& row.segment == plan.visible_segment
				&& normalize_offset_key(row.offset_key) == normalized_offset
				&& row.source_template_en == plan.source_template_en) {
			if (match) {
				error = "multiple dynamic metadata rows match this voice plan";
				return false;
			}
			match = &row;
		}
	}
	if (!match || match->source_parts.size() != plan.fragments.size()) {
		error = "no reviewed dynamic metadata matches this voice plan";
		return false;
	}
	for (std::size_t index = 0; index < plan.fragments.size(); ++index) {
		VoiceCompositeFragment& fragment = plan.fragments[index];
		const DynamicVoiceSourcePart& part = match->source_parts[index];
		if (fragment.kind != part.kind
				|| fragment.source_function_id != part.source_function_id
				|| fragment.source_offset != part.source_offset) {
			error = "dynamic metadata source-origin sequence does not match";
			return false;
		}
		if (fragment.kind == VoiceCompositeFragmentKind::Literal) {
			if (fragment.string_offset != part.string_offset
					|| normalize_translation_source(fragment.source)
							!= normalize_translation_source(part.text)) {
				error = "dynamic metadata literal provenance does not match";
				return false;
			}
			continue;
		}
		if (fragment.variable_index != part.variable_index
				|| fragment.ordinal != part.ordinal
				|| (!fragment.semantic_type.empty()
						&& fragment.semantic_type != "unknown"
						&& fragment.semantic_type != part.semantic_type)
				|| (!fragment.pronoun_form.empty()
						&& fragment.pronoun_form != part.pronoun_form)) {
			error = "dynamic metadata slot provenance does not match";
			return false;
		}
		fragment.semantic_type = part.semantic_type;
		fragment.pronoun_form = part.pronoun_form;
	}
	plan.role_spans = match->role_spans;
	plan.requires_player_gender_variant = match->player_gender_variant;
	if (dynamic_voice_template_key(plan) != match->key) {
		error = "dynamic metadata key does not match captured source provenance";
		return false;
	}
	error.clear();
	return true;
}

inline std::string voice_gender_name(VoiceGender gender) {
	return gender == VoiceGender::Female ? "female" : "male";
}

inline std::vector<std::string> voice_language_order(std::string language) {
	for (char& ch : language) {
		ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
	}
	if (language.empty()) language = "zh";
	return {language, language == "zh" ? "en" : "zh"};
}

inline std::string npc_slug(std::string_view name) {
	std::string result;
	bool previous_separator = false;
	for (const unsigned char ch : name) {
		if ((ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9')) {
			result.push_back(static_cast<char>(ch));
			previous_separator = false;
		} else if (ch >= 'A' && ch <= 'Z') {
			result.push_back(static_cast<char>(ch - 'A' + 'a'));
			previous_separator = false;
		} else if (!result.empty() && !previous_separator) {
			result.push_back('_');
			previous_separator = true;
		}
	}
	while (!result.empty() && result.back() == '_') result.pop_back();
	return result;
}

inline bool is_avatar_speaker(const VoiceRouteContext& context) {
	return detail::absolute_npc(context.speaker_npc) == 356
			|| (context.speaker_npc == 0 && context.caller_npc == 0);
}

inline bool is_stone_guardian_speaker(const VoiceRouteContext& context) {
	return detail::absolute_npc(context.speaker_npc) == 277
			|| detail::absolute_npc(context.caller_npc) == 277;
}

inline bool make_clip_candidates(const VoiceCompositePlan& plan,
		const std::string& offset_key, const VoiceRouteContext& context,
		ClipCandidateGroups& output, std::string& error) {
	output.clear();
	if (is_stone_guardian_speaker(context)) {
		error = "Stone Guardian voice must remain original game audio";
		return false;
	}
	if (plan.kind == VoiceCompositeKind::LegacySingle) {
		error = "legacy single clips use the existing voice resolver";
		return false;
	}
	const bool avatar = is_avatar_speaker(context);
	if ((avatar || plan.kind == VoiceCompositeKind::DynamicTemplate)
			&& !context.speaker_gender_known) {
		error = "active speaker gender is unavailable for the requested voice";
		return false;
	}
	if (plan.kind == VoiceCompositeKind::DynamicTemplate
			&& plan.requires_player_gender_variant
			&& !context.player_gender_known) {
		error = "player gender is unavailable for the reviewed transcript variant";
		return false;
	}
	const std::uint64_t speaker_id = detail::absolute_npc(context.speaker_npc);
	if (plan.kind == VoiceCompositeKind::StaticSequence) {
		if (plan.fragments.empty()) {
			error = "static voice sequence has no fragments";
			return false;
		}
		for (const VoiceCompositeFragment& fragment : plan.fragments) {
			if (fragment.kind != VoiceCompositeFragmentKind::Literal
					|| fragment.source_function_id < 0) {
				error = "static voice sequence has invalid fragment provenance";
				output.clear();
				return false;
			}
			const std::string base = detail::format_hex(
					static_cast<std::uint64_t>(fragment.source_function_id), 4)
					+ "_" + detail::format_hex(fragment.string_offset)
					+ "_" + std::to_string(plan.visible_segment);
			std::vector<std::string> candidates;
			if (avatar) {
				candidates.push_back(base + "_avatar_"
						+ voice_gender_name(context.speaker_gender));
			}
			if (context.speaker_npc != 0) {
				candidates.push_back(base + "_npc" + std::to_string(speaker_id));
			}
			candidates.push_back(base);
			output.push_back(std::move(candidates));
		}
		error.clear();
		return true;
	}
	if (plan.kind != VoiceCompositeKind::DynamicTemplate || plan.fragments.empty()
			|| plan.role_spans.empty()) {
		error = "dynamic voice plan is missing source or role provenance";
		return false;
	}
	const std::string target = avatar ? "avatar" : npc_slug(context.speaker_name);
	if (target.empty()) {
		error = "dynamic voice plan has no canonical active speaker name";
		return false;
	}
	const std::string normalized_offset = normalize_offset_key(offset_key);
	if (normalized_offset.empty()) {
		error = "dynamic voice plan has no U6 shared offset key";
		return false;
	}
	const std::string key = dynamic_voice_template_key(plan);
	const std::string prefix = detail::format_hex(
			static_cast<std::uint64_t>(plan.function_id), 4)
			+ "_" + normalized_offset + "_s"
			+ std::to_string(plan.visible_segment) + "_" + key;
	const std::string player = plan.requires_player_gender_variant
			? voice_gender_name(context.player_gender) : "any";
	for (std::size_t index = 0; index < plan.role_spans.size(); ++index) {
		const VoiceCompositeRoleSpan& span = plan.role_spans[index];
		if (!span.requires_audio) continue;
		if (span.role != "speaker" && span.role != "narrator") {
			error = "dynamic voice plan has an unsupported role span";
			output.clear();
			return false;
		}
		output.push_back({prefix + "_r" + std::to_string(index) + "_"
				+ span.role + "_t" + target + "_p" + player + "_v"
				+ voice_gender_name(context.speaker_gender)});
	}
	if (output.empty()) {
		error = "dynamic voice plan has no audible role spans";
		return false;
	}
	error.clear();
	return true;
}

template <typename LegacyPlayback, typename CompositePlayback>
inline bool dispatch_voice_plan(const VoiceCompositePlan* plan,
		bool has_voice_provenance, LegacyPlayback&& legacy_playback,
		CompositePlayback&& composite_playback) {
	if (plan) {
		if (plan->kind == VoiceCompositeKind::LegacySingle) {
			return legacy_playback();
		}
		return composite_playback(*plan);
	}
	if (has_voice_provenance) return false;
	return legacy_playback();
}

template <typename PackedLookup, typename LooseLookup>
inline bool resolve_voice_clips(const ClipCandidateGroups& candidates,
		PackedLookup&& packed_lookup, LooseLookup&& loose_lookup,
		std::vector<ResolvedVoiceClip>& output, bool& used_packed,
		std::size_t* missing_group = nullptr) {
	output.clear();
	used_packed = false;
	if (missing_group) *missing_group = 0;
	if (candidates.empty()) return false;
	auto resolve_all = [&](bool packed, std::size_t& failed_group) {
		std::vector<ResolvedVoiceClip> resolved;
		resolved.reserve(candidates.size());
		for (std::size_t group_index = 0;
				group_index < candidates.size(); ++group_index) {
			const std::vector<std::string>& group = candidates[group_index];
			if (group.empty()) {
				failed_group = group_index;
				return false;
			}
			bool found = false;
			for (const std::string& name : group) {
				ResolvedVoiceClip clip;
				clip.name = name;
				if (packed) {
					if (!packed_lookup(name, clip.packed_data)
							|| clip.packed_data.empty()) continue;
					clip.packed = true;
				} else {
					if (!loose_lookup(name, clip.path) || clip.path.empty()) continue;
				}
				resolved.push_back(std::move(clip));
				found = true;
				break;
			}
			if (!found) {
				failed_group = group_index;
				return false;
			}
		}
		output.swap(resolved);
		return true;
	};
	std::size_t packed_failure = 0;
	if (resolve_all(true, packed_failure)) {
		used_packed = true;
		return true;
	}
	output.clear();
	std::size_t loose_failure = 0;
	const bool resolved_loose = resolve_all(false, loose_failure);
	if (missing_group) *missing_group = loose_failure;
	return resolved_loose;
}

}  // namespace U6VoiceRouting

#endif
