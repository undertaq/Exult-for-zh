#ifndef EXULT_GAMEPLAY_TRANSLATION_H
#define EXULT_GAMEPLAY_TRANSLATION_H

#include "bilingual_manager.h"
#include "gameplay_translation_table.h"

#include <cstddef>
#include <cstdint>
#include <iosfwd>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

struct TranslationDiagnostics {
	std::size_t rows = 0;
	std::size_t hits = 0;
	std::size_t misses = 0;
	std::size_t source_mismatches = 0;
	std::size_t malformed_rows = 0;
	std::size_t fallbacks = 0;
};

struct BookTextPart {
	std::string_view text;
	std::string_view translation_key;
	bool             translate = true;
};

struct DialogueTranslationPart {
	std::string source;
	std::string translation_key;
	bool        dynamic = false;
};

enum class VoiceCompositeKind {
	LegacySingle,
	StaticSequence,
	DynamicTemplate
};

enum class VoiceCompositeFragmentKind {
	Literal,
	Dynamic
};

struct VoiceCompositeFragment {
	VoiceCompositeFragmentKind kind = VoiceCompositeFragmentKind::Literal;
	std::size_t source_start = 0;
	std::string source;
	std::string translation_key;
	int         source_function_id = -1;
	std::uint32_t source_offset = 0;
	std::uint32_t string_offset = 0;
	std::uint32_t variable_index = 0;
	std::uint32_t ordinal = 0;
	std::string semantic_type = "unknown";
	std::string pronoun_form;
	std::string runtime_value;
};

struct VoiceCompositeRoleSpan {
	std::string role;
	std::size_t start_char = 0;
	std::size_t end_char = 0;
};

struct VoiceCompositePlan {
	VoiceCompositeKind kind = VoiceCompositeKind::LegacySingle;
	int function_id = -1;
	std::size_t visible_segment = 0;
	std::string source_template_en;
	std::vector<VoiceCompositeFragment> fragments;
	std::vector<VoiceCompositeRoleSpan> role_spans;
};

VoiceCompositeFragment make_voice_composite_literal_fragment(
		std::size_t source_start, std::string source,
		int source_function_id, std::uint32_t instruction_offset,
		std::uint32_t string_offset);
VoiceCompositeFragment make_voice_composite_dynamic_fragment(
		std::size_t source_start, std::string runtime_value,
		int source_function_id, std::uint32_t instruction_offset,
		std::uint32_t variable_index,
		std::string semantic_type = "unknown");
VoiceCompositePlan make_voice_composite_plan(
		int function_id, std::size_t visible_segment,
		std::string source_template_en,
		std::vector<VoiceCompositeFragment> fragments,
		std::vector<VoiceCompositeRoleSpan> role_spans = {});
std::vector<VoiceCompositePlan> make_voice_composite_plans(
		int function_id, std::string_view source_text,
		const std::vector<VoiceCompositeFragment>& source_fragments,
		const std::vector<std::vector<VoiceCompositeRoleSpan>>& role_spans = {});
std::string serialize_dynamic_voice_identity(const VoiceCompositePlan& plan);
std::string dynamic_voice_template_key(const VoiceCompositePlan& plan);

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
	std::string translate_by_source(GameplayTranslationKind kind,
			std::string_view english);
	std::string translate_book_text(std::string_view english);
	std::string translate_book_text_parts(
			std::string_view english, const std::vector<BookTextPart>& parts);
	std::optional<std::string> translate_dialogue_by_source_if_available(
			std::string_view english);
	std::optional<std::string> translate_dialogue_template_if_available(
			std::string_view english, std::string_view source_template,
			std::string_view placeholder);
	std::optional<std::string> translate_dialogue_template_if_available(
			std::string_view english, std::string_view source_template,
			const std::vector<std::pair<std::string, std::string>>& substitutions);
	std::optional<std::string> translate_dialogue_template_values_if_available(
			std::string_view source_template,
			const std::vector<std::pair<std::string, std::string>>& substitutions);
	std::optional<std::string> translate_dialogue_template_if_available(
			std::string_view english, std::string_view source_template);
	std::optional<std::string> translate_dialogue_fragments_if_available(
			int function_id, std::string_view english,
			const std::vector<DialogueTranslationPart>& parts);
	void record_runtime_source(GameplayTranslationKind kind,
			std::string_view key, std::string_view english);
	void record_runtime_speaker(std::string_view key, int speaker_id,
			std::string_view speaker_name);
	TranslationDiagnostics diagnostics() const;

private:
	GameplayTranslationManager() = default;
	GameplayTranslationManager(const GameplayTranslationManager&) = delete;
	GameplayTranslationManager& operator=(const GameplayTranslationManager&) = delete;

	TextLanguage current_language_ = TextLanguage::ENGLISH;
	GameplayTranslationTable table_;
	TranslationDiagnostics diagnostics_;
	bool table_valid_ = false;
	std::unique_ptr<std::ostream> catalog_stream_;
	std::set<std::string> catalog_rows_;
	std::unique_ptr<std::ostream> speaker_stream_;
	std::set<std::string> speaker_rows_;
};

std::string make_dialogue_translation_key(
		int function_id, std::string_view offset_key, int segment);
std::string make_dialogue_template_translation_key(
		int function_id, std::string_view source_template);
std::string make_choice_translation_key(
		int function_id, int callsite_offset, int ordinal);
std::string make_item_translation_key(int shape, int frame, int quality);
// Convert usecode's paired '@' speech markers into display quotes.  The
// markers remain in source/table strings so translation lookup and auditing
// stay byte-stable; this helper is only for the final rendered copy.
std::string format_usecode_dialogue_quotes(
		std::string_view text, TextLanguage language);
std::string strip_usecode_dialogue_markers(std::string_view text);
bool is_safe_catalog_path(std::string_view path);

#endif
