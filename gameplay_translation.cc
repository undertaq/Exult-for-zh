#include "gameplay_translation.h"

#ifndef GAMEPLAY_TRANSLATION_TABLE_TEST
#include "Configuration.h"
#include "fnames.h"
#include "utils.h"
#endif

#include <iomanip>
#include <iostream>
#include <sstream>
#include <utility>

namespace {

constexpr char kTranslationTablePath[] = "<PATCH>/zh_translation.tsv";
constexpr char kCatalogHeader[] =
		"# u6-runtime-catalog-v1\n"
		"# kind\tkey\tsource_sha256\tenglish\n";
constexpr char kDefaultCatalogPath[] = "u6_runtime_catalog.tsv";

std::string format_hex_id(int value) {
	std::ostringstream output;
	output << "0x" << std::hex << std::nouppercase << std::setfill('0')
			<< std::setw(4) << static_cast<unsigned int>(value);
	return output.str();
}

const char* translation_kind_name(GameplayTranslationKind kind) {
	switch (kind) {
	case GameplayTranslationKind::Dialogue:
		return "dialogue";
	case GameplayTranslationKind::Choice:
		return "choice";
	case GameplayTranslationKind::TextMessage:
		return "textmsg";
	case GameplayTranslationKind::Item:
		return "item";
	case GameplayTranslationKind::Location:
		return "location";
	case GameplayTranslationKind::Misc:
		return "misc";
	case GameplayTranslationKind::Spell:
		return "spell";
	}
	return "misc";
}

} // namespace

GameplayTranslationManager& GameplayTranslationManager::get() {
	static GameplayTranslationManager instance;
	return instance;
}

GameplayTranslationManager::~GameplayTranslationManager() = default;

void GameplayTranslationManager::init() {
	shutdown();

#ifdef GAMEPLAY_TRANSLATION_TABLE_TEST
	return;
#else
	BilingualManager& bilingual = BilingualManager::get();
	current_language_ = bilingual.get_text_language();
	legacy_alternate_usecode_active_ = bilingual.is_bilingual_available()
			|| bilingual.is_dual_available();

	if (is_system_path_defined("<PATCH>") && U7exists(kTranslationTablePath)) {
		try {
			std::unique_ptr<std::istream> input =
					U7open_in(kTranslationTablePath, true);
			if (input) {
				std::string error;
				if (!load_table(*input, error)) {
					std::cerr << "[GameplayTranslation] Failed to load "
							<< kTranslationTablePath << ": " << error << std::endl;
				}
			}
		} catch (const std::exception& exception) {
			std::cerr << "[GameplayTranslation] Failed to open "
					<< kTranslationTablePath << ": " << exception.what()
					<< std::endl;
		}
	}

	if (config) {
		bool capture = false;
		std::string catalog_path;
		config->value("config/debug/translation/catalog_capture", capture,
				false);
		config->value("config/debug/translation/catalog_path", catalog_path,
				kDefaultCatalogPath);
		if (capture && !catalog_path.empty()) {
			try {
				const std::string path = std::string(GAMEDAT) + catalog_path;
				catalog_stream_ = U7open_out(path.c_str(), true);
				if (catalog_stream_) {
					*catalog_stream_ << kCatalogHeader << std::flush;
				}
			} catch (const std::exception& exception) {
				std::cerr << "[GameplayTranslation] Failed to open catalog "
						<< catalog_path << ": " << exception.what() << std::endl;
			}
		}
	}
#endif
}

void GameplayTranslationManager::shutdown() {
	catalog_stream_.reset();
	catalog_rows_.clear();
	table_ = GameplayTranslationTable();
	diagnostics_ = TranslationDiagnostics();
	table_valid_ = false;
	legacy_alternate_usecode_active_ = false;
	current_language_ = TextLanguage::ENGLISH;
}

bool GameplayTranslationManager::load_table(
		std::istream& input, std::string& error) {
	table_ = GameplayTranslationTable();
	diagnostics_ = TranslationDiagnostics();
	table_valid_ = false;

	if (!table_.load(input, error)) {
		diagnostics_.malformed_rows = 1;
		return false;
	}

	diagnostics_.rows = table_.size();
	table_valid_ = true;
	return true;
}

void GameplayTranslationManager::set_text_language(TextLanguage language) {
	current_language_ = language;
}

bool GameplayTranslationManager::table_only_enabled() const {
	return current_language_ == TextLanguage::CHINESE && table_valid_
			&& !legacy_alternate_usecode_active_;
}

std::string GameplayTranslationManager::translate(
		GameplayTranslationKind kind, std::string_view key,
		std::string_view english) {
	if (!table_only_enabled()) {
		++diagnostics_.fallbacks;
		return std::string(english);
	}

	const TranslationLookup result = table_.lookup(kind, key, english);
	switch (result.status) {
	case TranslationLookupStatus::Hit:
		++diagnostics_.hits;
		return result.text;
	case TranslationLookupStatus::Missing:
		++diagnostics_.misses;
		++diagnostics_.fallbacks;
		return std::string(english);
	case TranslationLookupStatus::SourceMismatch:
		++diagnostics_.source_mismatches;
		++diagnostics_.fallbacks;
		return std::string(english);
	case TranslationLookupStatus::Disabled:
		++diagnostics_.fallbacks;
		return std::string(english);
	}
	++diagnostics_.fallbacks;
	return std::string(english);
}

void GameplayTranslationManager::record_runtime_source(
		GameplayTranslationKind kind, std::string_view key,
		std::string_view english) {
	if (!catalog_stream_) {
		return;
	}

	const std::string normalized_source = normalize_translation_source(english);
	const std::string source_hash = sha256_hex(normalized_source);
	const std::string identity = std::to_string(static_cast<int>(kind))
			+ '\0' + std::string(key) + '\0' + source_hash;
	if (!catalog_rows_.insert(identity).second) {
		return;
	}

	*catalog_stream_ << translation_kind_name(kind) << '\t'
			<< escape_translation_field(key) << '\t' << source_hash << '\t'
			<< escape_translation_field(english) << '\n' << std::flush;
	if (!*catalog_stream_) {
		catalog_stream_.reset();
	}
}

TranslationDiagnostics GameplayTranslationManager::diagnostics() const {
	return diagnostics_;
}

std::string make_dialogue_translation_key(
		int function_id, std::string_view offset_key, int segment) {
	return "dialogue:" + format_hex_id(function_id) + ":"
			+ std::string(offset_key) + ":" + std::to_string(segment);
}

std::string make_choice_translation_key(
		int function_id, int callsite_offset, int ordinal) {
	return "choice:" + format_hex_id(function_id) + ":"
			+ format_hex_id(callsite_offset) + ":" + std::to_string(ordinal);
}

std::string make_item_translation_key(int shape, int frame, int quality) {
	return "item:" + format_hex_id(shape) + ":" + std::to_string(frame)
			+ ":" + std::to_string(quality);
}
