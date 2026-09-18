#include "gameplay_translation.h"

#ifndef GAMEPLAY_TRANSLATION_TABLE_TEST
#include "Configuration.h"
#include "fnames.h"
#include "utils.h"
#endif

#include <iomanip>
#include <iostream>
#include <filesystem>
#include <limits>
#include <algorithm>
#include <cctype>
#include <stdexcept>
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

struct TemplateShape {
	std::vector<std::string> literals;
	std::vector<std::string> placeholders;
};

bool is_placeholder_name(std::string_view name) {
	if (name.empty() || !std::isalpha(static_cast<unsigned char>(name.front()))) {
		return false;
	}
	for (const char character : name) {
		if (!std::isalnum(static_cast<unsigned char>(character)) && character != '_') {
			return false;
		}
	}
	return true;
}

std::optional<TemplateShape> parse_template(std::string_view source) {
	TemplateShape shape;
	std::size_t literal_start = 0;
	std::size_t search = 0;
	while ((search = source.find('<', search)) != std::string_view::npos) {
		const std::size_t close = source.find('>', search + 1);
		if (close == std::string_view::npos) {
			return std::nullopt;
		}
		const std::string_view name = source.substr(search + 1, close - search - 1);
		if (!is_placeholder_name(name)) {
			search++;
			continue;
		}
		shape.literals.emplace_back(source.substr(literal_start, search - literal_start));
		shape.placeholders.emplace_back(source.substr(search, close - search + 1));
		literal_start = close + 1;
		search = close + 1;
	}
	if (shape.placeholders.empty()) {
		return std::nullopt;
	}
	shape.literals.emplace_back(source.substr(literal_start));
	return shape;
}

bool ends_with_at(std::string_view value, std::string_view suffix) {
	return value.size() >= suffix.size()
			&& value.compare(value.size() - suffix.size(), suffix.size(), suffix) == 0;
}

bool ends_with_ascii_word(std::string_view value, std::string_view word) {
	while (!value.empty()
				&& std::isspace(static_cast<unsigned char>(value.back()))) {
		value.remove_suffix(1);
	}
	return value.size() >= word.size()
			&& value.compare(value.size() - word.size(), word.size(), word) == 0
			&& (value.size() == word.size()
					|| !std::isalnum(static_cast<unsigned char>(
							value[value.size() - word.size() - 1])));
}

// Time-of-day values are also used as ordinary nouns ("this fine
// afternoon"). Only a source literal ending in the greeting word ``Good``
// receives the Taiwan greeting form; all other contexts keep the ordinary
// time translation from the table. This follows template provenance rather
// than an NPC or sentence registry.
std::optional<std::string> translate_greeting_time(
		std::string_view literal_before, std::string_view value) {
	if (!ends_with_ascii_word(literal_before, "Good")) {
		return std::nullopt;
	}
	if (value == "morning") {
		return "早安";
	}
	if (value == "afternoon") {
		return "午安";
	}
	if (value == "evening") {
		return "晚安";
	}
	return std::nullopt;
}

std::optional<std::vector<std::string>> extract_template_values(
		std::string_view runtime, const TemplateShape& shape) {
	std::vector<std::string> values;
	values.reserve(shape.placeholders.size());
	std::size_t runtime_position = 0;
	for (std::size_t index = 0; index < shape.placeholders.size(); ++index) {
		const std::string_view literal = shape.literals[index];
		if (runtime_position > runtime.size()
				|| literal.size() > runtime.size() - runtime_position
				|| runtime.compare(runtime_position, literal.size(), literal) != 0) {
			return std::nullopt;
		}
		runtime_position += literal.size();
		const std::string_view trailing = shape.literals[index + 1];
		if (index + 1 == shape.placeholders.size()) {
			if (!ends_with_at(runtime, trailing)
					|| runtime_position > runtime.size() - trailing.size()) {
				return std::nullopt;
			}
			values.emplace_back(runtime.substr(
					runtime_position, runtime.size() - trailing.size() - runtime_position));
			runtime_position = runtime.size() - trailing.size();
		} else {
			if (trailing.empty()) {
				return std::nullopt;    // Adjacent placeholders are ambiguous.
			}
			const std::size_t next = runtime.find(trailing, runtime_position);
			if (next == std::string_view::npos
					|| runtime.find(trailing, next + trailing.size())
							!= std::string_view::npos) {
				// A literal occurring more than once cannot identify a unique
				// dynamic boundary without guessing.
				return std::nullopt;
			}
			values.emplace_back(runtime.substr(runtime_position, next - runtime_position));
			runtime_position = next;
		}
	}
	if (runtime_position > runtime.size()
			|| shape.literals.back().size() > runtime.size() - runtime_position
			|| runtime.compare(runtime_position, shape.literals.back().size(),
					shape.literals.back()) != 0
			|| runtime_position + shape.literals.back().size() != runtime.size()) {
		return std::nullopt;
	}
	return values;
}

std::optional<std::string> substitute_template_values(
		std::string_view translated, const TemplateShape& shape,
		const std::vector<std::string>& values) {
	if (values.size() != shape.placeholders.size()) {
		return std::nullopt;
	}
	const std::optional<TemplateShape> translated_shape = parse_template(translated);
	if (!translated_shape.has_value()
			|| translated_shape->placeholders.size() != values.size()) {
		return std::nullopt;
	}
	std::vector<std::size_t> bindings(values.size());
	std::vector<bool> used(values.size(), false);
	bool same_placeholder_names = true;
	for (const std::string& source_placeholder : shape.placeholders) {
		const auto source_count = std::count(
				shape.placeholders.begin(), shape.placeholders.end(), source_placeholder);
		const auto translated_count = std::count(
				translated_shape->placeholders.begin(),
				translated_shape->placeholders.end(), source_placeholder);
		if (source_count != translated_count) {
			same_placeholder_names = false;
			break;
		}
	}
	if (same_placeholder_names) {
		for (std::size_t translated_index = 0;
				translated_index < translated_shape->placeholders.size();
				++translated_index) {
			for (std::size_t source_index = 0; source_index < values.size();
					++source_index) {
				if (!used[source_index]
						&& translated_shape->placeholders[translated_index]
								== shape.placeholders[source_index]) {
					bindings[translated_index] = source_index;
					used[source_index] = true;
					break;
				}
			}
		}
	} else {
		for (std::size_t index = 0; index < values.size(); ++index) {
			bindings[index] = index;
		}
	}
	std::string result;
	for (std::size_t index = 0; index < translated_shape->placeholders.size(); ++index) {
		result += translated_shape->literals[index];
		result += values[bindings[index]];
	}
	result += translated_shape->literals.back();
	return result;
}

// UCXT exposes adjacent literal fragments separately.  A fragment can
// therefore contain only the opening or closing half of a protected speech
// marker (for example ``@Good `` and ``.@``).  Translation rows for those
// fragments are intentionally ordinary text rows and may omit that half.  Put
// the source fragment's boundary markers back on the translated fragment so
// the assembled sentence retains the VM's exact display structure.  This is
// provenance based; it does not inspect or pattern-match the English sentence.
std::string preserve_fragment_boundary_markers(
		std::string_view source, std::string translated) {
	for (const char marker : {'@', '~', '*'}) {
		const std::size_t source_count = static_cast<std::size_t>(std::count(
				source.begin(), source.end(), marker));
		const std::size_t translated_count = static_cast<std::size_t>(std::count(
				translated.begin(), translated.end(), marker));
		std::size_t missing = source_count > translated_count
				? source_count - translated_count
				: 0;
		if (!missing) {
			continue;
		}
		if (!source.empty() && source.front() == marker
				&& (translated.empty() || translated.front() != marker)) {
			translated.insert(translated.begin(), marker);
			--missing;
		}
		if (missing && !source.empty() && source.back() == marker
				&& (translated.empty() || translated.back() != marker)) {
			translated.push_back(marker);
			--missing;
		}
		// Interior marker fragments are uncommon, but keeping their count is
		// still safer than dropping a control character.  Edge placement above
		// handles normal speech boundaries without splitting UTF-8 bytes.
		while (missing--) {
			translated.push_back(marker);
		}
	}
	return translated;
}

bool preserves_dialogue_markers(
		std::string_view source, std::string_view translated) {
	for (const char marker : {'@', '~', '*'}) {
		if (std::count(source.begin(), source.end(), marker)
				!= std::count(translated.begin(), translated.end(), marker)) {
			return false;
		}
	}
	return true;
}

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
	// The TSV is an English-source lookup. It is therefore safe to keep it
	// enabled with a Chinese/dual alternate usecode: Chinese strings have no
	// matching English source hash and pass through unchanged, while English
	// fallbacks emitted by an incomplete alternate usecode can be translated.
	return (current_language_ == TextLanguage::CHINESE
				|| current_language_ == TextLanguage::DUAL) && table_valid_;
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
	// An alternate usecode can contain translated dialogue while still leaving
	// book pages in English. English-source lookup handles both safely:
	// already-translated pages simply have no matching English source hash.
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
	const std::optional<TemplateShape> shape = parse_template(source_template);
	if (!shape.has_value()
				|| std::any_of(shape->placeholders.begin(), shape->placeholders.end(),
						[placeholder](const std::string& value) {
							return value != placeholder;
						})) {
		return std::nullopt;
	}
	const std::optional<std::vector<std::string>> values =
			extract_template_values(english, *shape);
	if (!values.has_value()) {
		return std::nullopt;
	}
	std::vector<std::pair<std::string, std::string>> substitutions;
	substitutions.reserve(values->size());
	for (std::size_t index = 0; index < values->size(); ++index) {
		substitutions.emplace_back(shape->placeholders[index], (*values)[index]);
	}
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
	const std::optional<TemplateShape> source_shape = parse_template(source_template);
	if (!source_shape.has_value()
			|| source_shape->placeholders.size() != substitutions.size()) {
		return std::nullopt;
	}
	for (std::size_t index = 0; index < substitutions.size(); ++index) {
		if (source_shape->placeholders[index] != substitutions[index].first) {
			return std::nullopt;
		}
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
		if (placeholder_position == std::string_view::npos) {
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
			if (next_literal.empty()) {
				return std::nullopt;
			}
			const std::size_t next_position =
					english.find(next_literal, runtime_position);
			if (next_position == std::string_view::npos
					|| english.find(next_literal,
							next_position + next_literal.size())
							!= std::string_view::npos) {
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
			if (!suffix.empty()
					&& english.find(suffix, runtime_position)
							!= english.size() - suffix.size()) {
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

	std::vector<std::string> values;
	values.reserve(substitutions.size());
	for (const auto& substitution : substitutions) {
		values.push_back(substitution.second);
	}
	const std::optional<std::string> translated = substitute_template_values(
			result.text, *source_shape, values);
	if (!translated.has_value()) {
		return std::nullopt;
	}
	++diagnostics_.hits;
	return *translated;
}

std::optional<std::string>
		GameplayTranslationManager::translate_dialogue_template_values_if_available(
				std::string_view source_template,
				const std::vector<std::pair<std::string, std::string>>& substitutions) {
	if (!table_only_enabled() || substitutions.empty()) {
		return std::nullopt;
	}
	const std::optional<TemplateShape> source_shape = parse_template(source_template);
	if (!source_shape.has_value()
			|| source_shape->placeholders.size() != substitutions.size()) {
		return std::nullopt;
	}
	for (std::size_t index = 0; index < substitutions.size(); ++index) {
		if (source_shape->placeholders[index] != substitutions[index].first) {
			return std::nullopt;
		}
	}

	const TranslationLookup result =
			table_.lookup_dialogue_by_source_globally(source_template);
	if (result.status != TranslationLookupStatus::SourceFallback
				&& result.status != TranslationLookupStatus::Hit) {
		return std::nullopt;
	}

	std::vector<std::string> values;
	values.reserve(substitutions.size());
	for (const auto& substitution : substitutions) {
		values.push_back(substitution.second);
	}
	const std::optional<std::string> translated = substitute_template_values(
			result.text, *source_shape, values);
	if (!translated.has_value()
				|| !preserves_dialogue_markers(source_template, *translated)) {
		return std::nullopt;
	}
	++diagnostics_.hits;
	return translated;
}

std::optional<std::string>
		GameplayTranslationManager::translate_dialogue_fragments_if_available(
				int function_id, std::string_view english,
				const std::vector<DialogueTranslationPart>& parts) {
	if (!table_only_enabled() || parts.empty()) {
		return std::nullopt;
	}

	std::string reconstructed;
	std::string source_template;
	std::vector<std::pair<std::string, std::string>> substitutions;
	std::vector<std::string> dynamic_sources;
	std::vector<bool> greeting_values;
	std::size_t variable_index = 0;
	bool has_dynamic_value = false;
	std::string previous_source;
	for (const DialogueTranslationPart& part : parts) {
		reconstructed += part.source;
		if (part.dynamic) {
			const std::string placeholder =
					"<VAR" + std::to_string(variable_index++) + ">";
			source_template += placeholder;
			dynamic_sources.push_back(part.source);
			greeting_values.push_back(ends_with_ascii_word(previous_source, "Good"));
			substitutions.emplace_back(placeholder, part.source);
			has_dynamic_value = true;
		} else {
			source_template += part.source;
		}
		previous_source = part.source;
	}
	if (reconstructed != english) {
		return std::nullopt;
	}

	// A single ADDSI/PUSHS value can contain several dialogue pages.  UCXT
	// catalogs those pages as separate ordinal rows, but the VM provenance
	// quite correctly keeps the original value (including `~`) as one part.
	// Translate each runtime segment independently so the fragment path uses
	// the same source/key granularity as extraction and audit.  The key suffix
	// is advanced for later segments when a source-global lookup is ambiguous;
	// no sentence-specific pattern or NPC knowledge is involved.
	auto key_for_segment = [](std::string_view key, std::size_t segment_offset) {
		if (segment_offset == 0 || key.empty()) {
			return std::string(key);
		}
		const std::size_t separator = key.rfind(':');
		if (separator == std::string_view::npos
				|| separator + 1 >= key.size()) {
			return std::string(key);
		}
		const std::string_view ordinal_text = key.substr(separator + 1);
		std::size_t ordinal = 0;
		for (const char character : ordinal_text) {
			if (character < '0' || character > '9') {
				return std::string(key);
			}
			const std::size_t digit = static_cast<std::size_t>(character - '0');
			if (ordinal > (std::numeric_limits<std::size_t>::max() - digit) / 10) {
				return std::string(key);
			}
			ordinal = ordinal * 10 + digit;
		}
		if (ordinal > std::numeric_limits<std::size_t>::max() - segment_offset) {
			return std::string(key);
		}
		return std::string(key.substr(0, separator + 1))
				+ std::to_string(ordinal + segment_offset);
	};

	auto translate_part_segment = [&](const DialogueTranslationPart& part,
				std::string_view source, std::size_t segment_offset,
				bool greeting_value) {
		std::string part_translation;
		if (part.dynamic) {
			if (greeting_value) {
				const auto greeting = translate_greeting_time("Good ", source);
				part_translation = greeting.has_value()
						? *greeting
						: translate_by_source(
								GameplayTranslationKind::Dialogue, source);
			} else {
				part_translation = translate_by_source(
						GameplayTranslationKind::Dialogue, source);
			}
		} else if (!part.translation_key.empty()) {
			part_translation = translate(
					GameplayTranslationKind::Dialogue,
					key_for_segment(part.translation_key, segment_offset), source);
			// UCXT offsets are provenance, not a second source of truth.  A
			// stale or missing offset must not suppress a valid source-global
			// translation row (this is common for assembled overhead text).
			if (part_translation == source) {
				part_translation = translate_by_source(
						GameplayTranslationKind::Dialogue, source);
			}
		} else {
			part_translation = translate_by_source(
					GameplayTranslationKind::Dialogue, source);
		}
		return preserve_fragment_boundary_markers(
				source, std::move(part_translation));
	};

	auto translate_part = [&](const DialogueTranslationPart& part,
				bool greeting_value) {
		std::string translated_part;
		std::size_t segment_start = 0;
		std::size_t segment_offset = 0;
		while (segment_start <= part.source.size()) {
			const std::size_t separator = part.source.find('~', segment_start);
			const std::size_t segment_end = separator == std::string::npos
					? part.source.size()
					: separator;
			translated_part += translate_part_segment(
					part, std::string_view(part.source).substr(
							segment_start, segment_end - segment_start), segment_offset,
							greeting_value);
			if (separator == std::string::npos) {
				break;
			}
			translated_part += '~';
			segment_start = separator + 1;
			++segment_offset;
		}
		return translated_part;
	};

	// item_say overhead helpers often assign one literal PUSHS value to a
	// local and pass it directly to the intrinsic.  There is no ADDSV slot in
	// that shape, but the VM provenance still gives us the authoritative
	// source/key pair.  Translate those static fragments through the same
	// source/key fallback as assembled dialogue; do not require a placeholder
	// template just because the caller is the overhead path.
	if (!has_dynamic_value) {
		std::string translated;
		for (const DialogueTranslationPart& part : parts) {
			translated += translate_part(part, false);
		}
		if (!preserves_dialogue_markers(english, translated)) {
			return std::nullopt;
		}
		return translated;
	}

	const std::string template_key =
			make_dialogue_template_translation_key(function_id, source_template);
	record_runtime_source(
			GameplayTranslationKind::Dialogue, template_key, source_template);
	if (const auto source_shape = parse_template(source_template);
			source_shape.has_value()
					&& source_shape->placeholders.size() == dynamic_sources.size()) {
		for (std::size_t index = 0; index < dynamic_sources.size(); ++index) {
			const auto greeting = translate_greeting_time(
					source_shape->literals[index], dynamic_sources[index]);
			if (greeting.has_value()) {
				substitutions[index].second = *greeting;
			} else if (greeting_values[index]) {
				substitutions[index].second = translate_greeting_time(
						"Good ", dynamic_sources[index])
							.value_or(translate_by_source(
									GameplayTranslationKind::Dialogue,
									 dynamic_sources[index]));
			} else {
				substitutions[index].second = translate_by_source(
						GameplayTranslationKind::Dialogue, dynamic_sources[index]);
			}
		}
	} else {
		for (std::size_t index = 0; index < dynamic_sources.size(); ++index) {
			substitutions[index].second = greeting_values[index]
					? translate_greeting_time("Good ", dynamic_sources[index])
							.value_or(translate_by_source(
									GameplayTranslationKind::Dialogue,
									 dynamic_sources[index]))
					: translate_by_source(
							GameplayTranslationKind::Dialogue, dynamic_sources[index]);
		}
	}
	if (const auto translated = translate_dialogue_template_values_if_available(
				source_template, substitutions);
			translated.has_value()) {
		return translated;
	}

	std::string translated;
	std::size_t dynamic_index = 0;
	for (const DialogueTranslationPart& part : parts) {
		const bool greeting_value = part.dynamic
				&& dynamic_index < greeting_values.size()
				&& greeting_values[dynamic_index++];
		translated += translate_part(part, greeting_value);
	}

	const auto marker_count = [](std::string_view text, char marker) {
		return std::count(text.begin(), text.end(), marker);
	};
	if (marker_count(translated, '@') != marker_count(english, '@')
				|| marker_count(translated, '~') != marker_count(english, '~')
				|| marker_count(translated, '*') != marker_count(english, '*')) {
		return std::nullopt;
	}
	return translated;
}

std::optional<std::string>
		GameplayTranslationManager::translate_dialogue_template_if_available(
				std::string_view english, std::string_view source_template) {
	if (!table_only_enabled()) {
		return std::nullopt;
	}
	const std::optional<TemplateShape> shape = parse_template(source_template);
	if (!shape.has_value()) {
		return std::nullopt;
	}
	const std::optional<std::vector<std::string>> runtime_values =
			extract_template_values(english, *shape);
	if (!runtime_values.has_value()) {
		return std::nullopt;
	}
	const TranslationLookup lookup =
			table_.lookup_dialogue_by_source_globally(source_template);
	if (lookup.status != TranslationLookupStatus::SourceFallback
				&& lookup.status != TranslationLookupStatus::Hit) {
		return std::nullopt;
	}
	std::vector<std::string> translated_values;
	translated_values.reserve(runtime_values->size());
	for (std::size_t index = 0; index < runtime_values->size(); ++index) {
		const std::string& value = (*runtime_values)[index];
		if (const auto greeting = translate_greeting_time(
					shape->literals[index], value);
				greeting.has_value()) {
			translated_values.push_back(*greeting);
		} else {
			translated_values.push_back(translate_by_source(
					GameplayTranslationKind::Dialogue, value));
		}
	}
	const std::optional<std::string> translated = substitute_template_values(
				lookup.text, *shape, translated_values);
	if (!translated.has_value()
				|| !preserves_dialogue_markers(english, *translated)) {
		return std::nullopt;
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

std::string make_dialogue_template_translation_key(
		int function_id, std::string_view source_template) {
	const std::string digest = sha256_hex(
			normalize_translation_source(source_template));
	return make_dialogue_translation_key(
				function_id, "fallback_" + digest.substr(0, 16), 0);
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

std::string format_usecode_dialogue_quotes(
		std::string_view text, TextLanguage language) {
	std::string result;
	result.reserve(text.size());
	std::size_t position = 0;
	while (position < text.size()) {
		const std::size_t marker = text.find('@', position);
		if (marker == std::string_view::npos) {
			result.append(text.substr(position));
			break;
		}
		result.append(text.substr(position, marker - position));
		const std::size_t closing = text.find('@', marker + 1);
		if (closing == std::string_view::npos) {
			// Keep the historical display behavior for malformed/unpaired
			// markers: suppress the marker instead of leaking it onscreen.
			result.append(text.substr(marker + 1));
			break;
		}

		// DUAL strings are rendered as a Chinese half followed by an English
		// half separated by a newline.  Match each half's punctuation while
		// keeping the internal '@' representation unchanged for lookup.
		bool chinese_quotes = language == TextLanguage::CHINESE;
		if (language == TextLanguage::DUAL) {
			chinese_quotes = text.rfind('\n', marker) == std::string_view::npos;
		}
		if (chinese_quotes) {
			result += "「";
		} else {
			result += '"';
		}
		result.append(text.substr(marker + 1, closing - marker - 1));
		if (chinese_quotes) {
			result += "」";
		} else {
			result += '"';
		}
		position = closing + 1;
	}
	return result;
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
