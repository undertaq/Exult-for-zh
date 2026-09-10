#ifndef EXULT_GAMEPLAY_TRANSLATION_H
#define EXULT_GAMEPLAY_TRANSLATION_H

#include "bilingual_manager.h"
#include "gameplay_translation_table.h"

#include <cstddef>
#include <iosfwd>
#include <memory>
#include <set>
#include <string>
#include <string_view>

struct TranslationDiagnostics {
	std::size_t rows = 0;
	std::size_t hits = 0;
	std::size_t misses = 0;
	std::size_t source_mismatches = 0;
	std::size_t malformed_rows = 0;
	std::size_t fallbacks = 0;
};

class GameplayTranslationManager {
public:
	static GameplayTranslationManager& get();

	~GameplayTranslationManager();

	void init();
	void shutdown();
	bool load_table(std::istream& input, std::string& error);
	void set_text_language(TextLanguage language);
	bool table_only_enabled() const;
	std::string translate(GameplayTranslationKind kind,
			std::string_view key, std::string_view english);
	void record_runtime_source(GameplayTranslationKind kind,
			std::string_view key, std::string_view english);
	TranslationDiagnostics diagnostics() const;

private:
	GameplayTranslationManager() = default;
	GameplayTranslationManager(const GameplayTranslationManager&) = delete;
	GameplayTranslationManager& operator=(const GameplayTranslationManager&) = delete;

	TextLanguage current_language_ = TextLanguage::ENGLISH;
	GameplayTranslationTable table_;
	TranslationDiagnostics diagnostics_;
	bool table_valid_ = false;
	bool legacy_alternate_usecode_active_ = false;
	std::unique_ptr<std::ostream> catalog_stream_;
	std::set<std::string> catalog_rows_;
};

std::string make_dialogue_translation_key(
		int function_id, std::string_view offset_key, int segment);
std::string make_choice_translation_key(
		int function_id, int callsite_offset, int ordinal);
std::string make_item_translation_key(int shape, int frame, int quality);
bool is_safe_catalog_path(std::string_view path);

#endif
