#ifndef EXULT_GAMEPLAY_TRANSLATION_TABLE_H
#define EXULT_GAMEPLAY_TRANSLATION_TABLE_H

#include <cstddef>
#include <istream>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <utility>

enum class GameplayTranslationKind {
	Dialogue,
	Choice,
	TextMessage,
	Item,
	Location,
	Misc,
	Spell
};

enum class TranslationLookupStatus {
	Hit,
	Missing,
	SourceMismatch,
	Disabled
};

struct TranslationLookup {
	std::string text;
	TranslationLookupStatus status;
};

std::string normalize_translation_source(std::string_view source);
std::string sha256_hex(std::string_view source);
std::string escape_translation_field(std::string_view field);
std::optional<std::string> unescape_translation_field(
		std::string_view field, std::string& error);

class GameplayTranslationTable {
public:
	bool load(std::istream& input, std::string& error);
	TranslationLookup lookup(
			GameplayTranslationKind kind,
			std::string_view key,
			std::string_view english) const;
	std::size_t size() const;

private:
	struct Entry {
		std::string source_sha256;
		std::string text;
	};

	using EntryKey = std::pair<int, std::string>;
	std::map<EntryKey, Entry> entries_;
};

#endif
