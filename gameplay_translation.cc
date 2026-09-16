#include "gameplay_translation.h"

#ifndef GAMEPLAY_TRANSLATION_TABLE_TEST
#include "Configuration.h"
#include "fnames.h"
#include "utils.h"
#endif

#include <iomanip>
#include <iostream>
#include <filesystem>
#include <sstream>
#include <utility>

namespace {

constexpr char kTranslationTablePath[] = "<PATCH>/zh_translation.tsv";
constexpr char kCatalogHeader[] =
		"# u6-runtime-catalog-v1\n"
		"# kind\tkey\tsource_sha256\tenglish\n";
constexpr char kDefaultCatalogPath[] = "u6_runtime_catalog.tsv";
constexpr char kSpeakerHeader[] =
		"# u6-runtime-speakers-v1\n"
		"# kind\tkey\tspeaker_id\tspeaker\n";
constexpr char kDefaultSpeakerPath[] = "u6_runtime_speakers.tsv";

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

	if (!is_system_path_defined("<PATCH>")) {
		std::cerr << "[GameplayTranslation] <PATCH> is not defined; translation "
				<< "table disabled" << std::endl;
	} else if (!U7exists(kTranslationTablePath)) {
		std::cerr << "[GameplayTranslation] Translation table not found at "
				<< get_system_path(kTranslationTablePath) << std::endl;
	} else {
		try {
			std::unique_ptr<std::istream> input =
					U7open_in(kTranslationTablePath, true);
			if (input) {
				std::string error;
				if (!load_table(*input, error)) {
					std::cerr << "[GameplayTranslation] Failed to load "
							<< kTranslationTablePath << ": " << error << std::endl;
				} else {
					std::cout << "[GameplayTranslation] Loaded " << table_.size()
							<< " rows from " << get_system_path(kTranslationTablePath)
							<< std::endl;
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
		if (capture && !catalog_path.empty()
				&& is_safe_catalog_path(catalog_path)) {
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

		std::string speaker_path;
		config->value("config/debug/translation/speaker_path", speaker_path,
				kDefaultSpeakerPath);
		if (capture && !speaker_path.empty()
				&& is_safe_catalog_path(speaker_path)) {
			try {
				const std::string path = std::string(GAMEDAT) + speaker_path;
				speaker_stream_ = U7open_out(path.c_str(), true);
				if (speaker_stream_) {
					*speaker_stream_ << kSpeakerHeader << std::flush;
				}
			} catch (const std::exception& exception) {
				std::cerr << "[GameplayTranslation] Failed to open speaker "
						<< speaker_path << ": " << exception.what() << std::endl;
			}
		}
	}
#endif
}

bool is_safe_catalog_path(std::string_view path) {
	const std::filesystem::path candidate{std::string(path)};
	if (candidate.empty() || candidate.is_absolute()) {
		return false;
	}
	for (const auto& component : candidate) {
		if (component == "..") {
			return false;
		}
	}
	return true;
}

void GameplayTranslationManager::shutdown() {
	catalog_stream_.reset();
	catalog_rows_.clear();
	speaker_stream_.reset();
	speaker_rows_.clear();
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
	// DUAL falls back to the English usecode when this mod has no alternate
	// usecode.dual/usecode.zh. In that configuration the TSV is the only
	// Chinese text source, including for book pages. If an alternate usecode
	// was loaded, legacy_alternate_usecode_active_ keeps the table disabled so
	// already-translated strings are not translated a second time.
	return (current_language_ == TextLanguage::CHINESE
				|| current_language_ == TextLanguage::DUAL) && table_valid_
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
	if ((kind == GameplayTranslationKind::Dialogue
				|| kind == GameplayTranslationKind::Choice
				|| kind == GameplayTranslationKind::Item)
				&& result.status != TranslationLookupStatus::Hit) {
		TranslationLookup source_fallback{std::string(english),
				TranslationLookupStatus::Missing};
		if (kind == GameplayTranslationKind::Dialogue) {
			source_fallback = table_.lookup_dialogue_by_source(key, english);
		} else if (kind == GameplayTranslationKind::Choice) {
			source_fallback = table_.lookup_choice_by_source(english);
		} else {
			source_fallback = table_.lookup_item_by_source(english);
		}
		if (source_fallback.status == TranslationLookupStatus::SourceFallback) {
			++diagnostics_.hits;
			if (result.status == TranslationLookupStatus::SourceMismatch) {
				++diagnostics_.source_mismatches;
			}
			return source_fallback.text;
		}
		if (kind == GameplayTranslationKind::Dialogue) {
			const TranslationLookup global_source_fallback =
					table_.lookup_dialogue_by_source_globally(english);
			if (global_source_fallback.status
					== TranslationLookupStatus::SourceFallback) {
				++diagnostics_.hits;
				if (result.status == TranslationLookupStatus::SourceMismatch) {
					++diagnostics_.source_mismatches;
				}
				return global_source_fallback.text;
			}
		}
	}
	switch (result.status) {
	case TranslationLookupStatus::Hit:
	case TranslationLookupStatus::SourceFallback:
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

std::string GameplayTranslationManager::translate_by_source(
		GameplayTranslationKind kind, std::string_view english) {
	if (!table_only_enabled()) {
		++diagnostics_.fallbacks;
		return std::string(english);
	}

	TranslationLookup result{std::string(english),
			TranslationLookupStatus::Missing};
	if (kind == GameplayTranslationKind::Dialogue) {
		result = table_.lookup_dialogue_by_source_globally(english);
	} else if (kind == GameplayTranslationKind::Choice) {
		result = table_.lookup_choice_by_source(english);
	} else if (kind == GameplayTranslationKind::Item) {
		result = table_.lookup_item_by_source(english);
	}

	if (result.status == TranslationLookupStatus::SourceFallback
			|| result.status == TranslationLookupStatus::Hit) {
		++diagnostics_.hits;
		return result.text;
	}
	++diagnostics_.misses;
	++diagnostics_.fallbacks;
	return std::string(english);
}

std::string GameplayTranslationManager::translate_book_text(
		std::string_view english) {
	// A Chinese/dual alternate usecode can contain translated dialogue while
	// still leaving book pages in English. The general table gate is disabled
	// for that usecode to avoid translating its Chinese strings twice, so book
	// pages need their own source lookup. Already-translated pages simply have
	// no matching English source hash and are returned unchanged.
	auto translate_book_segment = [&](std::string_view segment) {
		if (table_only_enabled()) {
			return translate_by_source(GameplayTranslationKind::Dialogue, segment);
		}
		if ((current_language_ == TextLanguage::CHINESE
				|| current_language_ == TextLanguage::DUAL) && table_valid_) {
			const TranslationLookup result =
					table_.lookup_dialogue_by_source_globally(segment);
			if (result.status == TranslationLookupStatus::SourceFallback
					|| result.status == TranslationLookupStatus::Hit) {
				++diagnostics_.hits;
				return result.text;
			}
		}
		++diagnostics_.fallbacks;
		return std::string(segment);
	};

	std::string translated;
	std::size_t segment_start = 0;
	while (segment_start <= english.size()) {
		const std::size_t separator = english.find('~', segment_start);
		const std::size_t segment_end = separator == std::string_view::npos
				? english.size()
				: separator;
		std::string_view segment = english.substr(
				segment_start, segment_end - segment_start);
		std::size_t page_markers = 0;
		while (page_markers < segment.size() && segment[page_markers] == '*') {
			++page_markers;
		}
		translated.append(page_markers, '*');
		translated += translate_book_segment(segment.substr(page_markers));
		if (separator == std::string_view::npos) {
			break;
		}
		translated += '~';
		segment_start = separator + 1;
	}
	return translated;
}

std::string GameplayTranslationManager::translate_book_text_parts(
		std::string_view english, const std::vector<BookTextPart>& parts) {
	std::string reconstructed;
	std::string translated;
	for (const BookTextPart& part : parts) {
		reconstructed += part.text;
		if (!part.translate) {
			translated += part.text;
			continue;
		}

		std::string part_translation;
		if (table_only_enabled() && !part.translation_key.empty()) {
			TranslationLookup result = table_.lookup(
					GameplayTranslationKind::Dialogue,
					part.translation_key, part.text);
			if (result.status == TranslationLookupStatus::Hit) {
				part_translation = std::move(result.text);
			} else {
				// U6's English usecode uses the original data offset while the
				// fallback rows use a separate namespace to avoid collisions with
				// active-mod rows. Try that corresponding fallback key directly;
				// this also avoids ambiguous global source matches.
				const std::string prefix = "dialogue:";
				const std::size_t function_end =
						part.translation_key.find(':', prefix.size());
				const std::size_t marker_end =
						part.translation_key.find(':', function_end + 1);
				if (function_end != std::string_view::npos
						&& marker_end != std::string_view::npos) {
					const std::string marker(part.translation_key.substr(
							function_end + 1,
							marker_end - function_end - 1));
					if (marker.find("fallback_") != 0) {
						const std::string fallback_key =
								std::string(part.translation_key.substr(0, function_end + 1))
								+ "fallback_" + marker
								+ std::string(part.translation_key.substr(marker_end));
						result = table_.lookup(
								GameplayTranslationKind::Dialogue,
								fallback_key, part.text);
						if (result.status == TranslationLookupStatus::Hit) {
							part_translation = std::move(result.text);
						}
					}
				}
			}
		}
		translated += part_translation.empty()
					? translate_book_text(part.text)
					: part_translation;
	}
	if (reconstructed != english) {
		// The usecode trace can be incomplete for unusual string-building
		// paths. Retain the safe whole-string behavior in that case.
		return translate_book_text(english);
	}
	return translated;
}

std::optional<std::string>
		GameplayTranslationManager::translate_dialogue_by_source_if_available(
				std::string_view english) {
	if (!table_only_enabled()) {
		return std::nullopt;
	}

	const TranslationLookup result =
			table_.lookup_dialogue_by_source_globally(english);
	if (result.status != TranslationLookupStatus::SourceFallback
				&& result.status != TranslationLookupStatus::Hit) {
		return std::nullopt;
	}

	++diagnostics_.hits;
	return result.text;
}

std::optional<std::string>
		GameplayTranslationManager::translate_dialogue_template_if_available(
				std::string_view english, std::string_view source_template,
				std::string_view placeholder) {
	if (placeholder.empty()) {
		return std::nullopt;
	}

	const std::size_t template_placeholder = source_template.find(placeholder);
	if (template_placeholder == std::string_view::npos
				|| source_template.find(placeholder,
						template_placeholder + placeholder.size())
							!= std::string_view::npos) {
		return std::nullopt;
	}

	const std::string_view prefix = source_template.substr(0, template_placeholder);
	const std::string_view suffix = source_template.substr(
			template_placeholder + placeholder.size());
	if (english.size() < prefix.size() + suffix.size()
				|| english.compare(0, prefix.size(), prefix) != 0
				|| english.compare(english.size() - suffix.size(), suffix.size(), suffix)
						!= 0) {
		return std::nullopt;
	}

	const std::string runtime_value = std::string(english.substr(
			prefix.size(), english.size() - prefix.size() - suffix.size()));
	const std::vector<std::pair<std::string, std::string>> substitutions = {
			{std::string(placeholder), runtime_value}};
	return translate_dialogue_template_if_available(
				english, source_template, substitutions);
}

std::optional<std::string>
		GameplayTranslationManager::translate_dialogue_template_if_available(
				std::string_view english, std::string_view source_template,
				const std::vector<std::pair<std::string, std::string>>& substitutions) {
	if (!table_only_enabled() || substitutions.empty()) {
		return std::nullopt;
	}

	// Split the source template into literal portions around each placeholder
	// and verify that the runtime string has the same literal portions in the
	// same order.  Dynamic values may differ from their table representation,
	// so the caller supplies the values that should be put into the translation.
	std::vector<std::string_view> literals;
	literals.reserve(substitutions.size() + 1);
	std::size_t template_position = 0;
	for (const auto& substitution : substitutions) {
		const std::string_view placeholder = substitution.first;
		if (placeholder.empty()) {
			return std::nullopt;
		}

		const std::size_t placeholder_position =
				source_template.find(placeholder, template_position);
		if (placeholder_position == std::string_view::npos
					|| source_template.find(placeholder,
							placeholder_position + placeholder.size())
								!= std::string_view::npos) {
			return std::nullopt;
		}

		literals.push_back(source_template.substr(
				template_position, placeholder_position - template_position));
		template_position = placeholder_position + placeholder.size();
	}
	literals.push_back(source_template.substr(template_position));

	std::size_t runtime_position = 0;
	for (std::size_t i = 0; i < substitutions.size(); ++i) {
		const std::string_view literal = literals[i];
		if (runtime_position > english.size()
				|| literal.size() > english.size() - runtime_position
				|| english.compare(runtime_position, literal.size(), literal) != 0) {
			return std::nullopt;
		}
		runtime_position += literal.size();

		if (i + 1 < substitutions.size()) {
			const std::string_view next_literal = literals[i + 1];
			const std::size_t next_position =
					english.find(next_literal, runtime_position);
			if (next_position == std::string_view::npos) {
				return std::nullopt;
			}
			runtime_position = next_position;
		} else {
			const std::string_view suffix = literals.back();
			if (suffix.size() > english.size()
					|| english.compare(english.size() - suffix.size(), suffix.size(),
							suffix) != 0
					|| runtime_position > english.size() - suffix.size()) {
				return std::nullopt;
			}
		}
	}

	const TranslationLookup result =
			table_.lookup_dialogue_by_source_globally(source_template);
	if (result.status != TranslationLookupStatus::SourceFallback
				&& result.status != TranslationLookupStatus::Hit) {
		return std::nullopt;
	}

	std::string translated = result.text;
	for (const auto& substitution : substitutions) {
		const std::string_view placeholder = substitution.first;
		const std::size_t translated_placeholder = translated.find(placeholder);
		if (translated_placeholder == std::string::npos
					|| translated.find(placeholder,
							translated_placeholder + placeholder.size())
								!= std::string::npos) {
			return std::nullopt;
		}
		translated.replace(translated_placeholder, placeholder.size(),
					substitution.second);
	}
	++diagnostics_.hits;
	return translated;
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

void GameplayTranslationManager::record_runtime_speaker(
		std::string_view key, int speaker_id, std::string_view speaker_name) {
	if (!speaker_stream_) {
		return;
	}

	const std::string identity = std::string(key) + '\0'
			+ std::to_string(speaker_id) + '\0' + std::string(speaker_name);
	if (!speaker_rows_.insert(identity).second) {
		return;
	}

	*speaker_stream_ << "dialogue\t" << escape_translation_field(key) << '\t'
			<< speaker_id << '\t' << escape_translation_field(speaker_name)
			<< '\n' << std::flush;
	if (!*speaker_stream_) {
		speaker_stream_.reset();
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

std::string strip_usecode_dialogue_markers(std::string_view text) {
	std::string result;
	result.reserve(text.size());
	for (const char character : text) {
		if (character != '@') {
			result.push_back(character);
		}
	}
	return result;
}
