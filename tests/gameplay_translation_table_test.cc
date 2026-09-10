#include "gameplay_translation_table.h"
#include "gameplay_translation.h"

#include <cassert>
#include <fstream>
#include <iterator>
#include <sstream>
#include <string>
#include <string_view>

namespace {

const char* const kAbcSha256 =
		"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

void assert_load_fails(const std::string& input) {
	GameplayTranslationTable table;
	std::istringstream stream(input);
	std::string error;
	assert(!table.load(stream, error));
	assert(!error.empty());
}

const char* active_usecode_policy(TextLanguage language,
		const char* english, const char* chinese, const char* dual) {
	switch (language) {
	case TextLanguage::CHINESE:
		return chinese != nullptr ? chinese : english;
	case TextLanguage::DUAL:
		return dual != nullptr ? dual : english;
	case TextLanguage::ENGLISH:
		return english;
	}
	return english;
}

void assert_usecode_fallback_policy() {
	const char* const english = "english";
	const char* const chinese = "chinese";
	const char* const dual = "dual";

	assert(active_usecode_policy(TextLanguage::ENGLISH, english, chinese, dual)
			== english);
	assert(active_usecode_policy(TextLanguage::CHINESE, english, nullptr, dual)
			== english);
	assert(active_usecode_policy(TextLanguage::DUAL, english, chinese, nullptr)
			== english);
	assert(active_usecode_policy(TextLanguage::CHINESE, english, chinese, dual)
			== chinese);
	assert(active_usecode_policy(TextLanguage::DUAL, english, chinese, dual)
			== dual);
}

void assert_table_only_active_machine_source_policy() {
	std::ifstream source("bilingual_manager.cc");
	const std::string implementation(
			(std::istreambuf_iterator<char>(source)),
			std::istreambuf_iterator<char>());
	assert(!implementation.empty());
	assert(implementation.find(
			"gwin->set_usecode(get_active_usecode());") != std::string::npos);
	assert(implementation.find(
			"return active != nullptr ? active : usecode_en;")
			!= std::string::npos);
	assert(implementation.find(
			"    }\n    current_lang = lang;\n"
			"    GameplayTranslationManager::get().set_text_language(lang);\n"
			"    if (gwin) {\n        gwin->set_all_dirty();")
			!= std::string::npos);
}

void assert_safe_catalog_paths() {
	assert(is_safe_catalog_path("u6_runtime_catalog.tsv"));
	assert(is_safe_catalog_path("translation/catalog.tsv"));
	assert(!is_safe_catalog_path("/tmp/catalog.tsv"));
	assert(!is_safe_catalog_path("translation/../catalog.tsv"));
	assert(!is_safe_catalog_path("../catalog.tsv"));
}

void assert_conversation_display_changes_only_copy_get_answer_stays_byte_for_byte_identical() {
	std::ifstream conversation_header("usecode/conversation.h");
	const std::string header(
			(std::istreambuf_iterator<char>(conversation_header)),
			std::istreambuf_iterator<char>());
	assert(!header.empty());
	assert(header.find(
			"void set_choice_context(int function_id, int callsite_offset);")
			!= std::string::npos);
	assert(header.find("void clear_choice_context();") != std::string::npos);
	assert(header.find("const char* get_answer(int num)") != std::string::npos);
	assert(header.find("return answers[num].c_str();") != std::string::npos);

	std::ifstream conversation_source("usecode/conversation.cc");
	const std::string conversation(
			(std::istreambuf_iterator<char>(conversation_source)),
			std::istreambuf_iterator<char>());
	assert(!conversation.empty());
	assert(conversation.find("GameplayTranslationKind::Choice")
			!= std::string::npos);
	assert(conversation.find(
			"std::vector<std::string> display_answers;")
			!= std::string::npos);
	assert(conversation.find(
			"display_answers.push_back(translations.translate(")
			!= std::string::npos);
	assert(conversation.find(
			"show_avatar_choices(static_cast<int>(answers.size()), result.data());")
			!= std::string::npos);

	std::ifstream ucinternal_source("usecode/ucinternal.cc");
	const std::string ucinternal(
			(std::istreambuf_iterator<char>(ucinternal_source)),
			std::istreambuf_iterator<char>());
	assert(!ucinternal.empty());
	assert(ucinternal.find("GameplayTranslationKind::Dialogue")
			!= std::string::npos);
	assert(ucinternal.find("const int segment_index = segment++;")
			!= std::string::npos);
	const size_t dialogue_record = ucinternal.find(
			"translations.record_runtime_source(");
	const size_t dialogue_record_english = ucinternal.find(
			"GameplayTranslationKind::Dialogue, key, english);",
			dialogue_record);
	const size_t dialogue_translate = ucinternal.find(
			"const std::string display = translations.translate(",
			dialogue_record_english);
	const size_t dialogue_translate_english = ucinternal.find(
			"GameplayTranslationKind::Dialogue, key, english);",
			dialogue_translate);
	const size_t dialogue_display = ucinternal.find(
			"conv->show_npc_message(display.c_str());", dialogue_translate_english);
	assert(dialogue_record != std::string::npos);
	assert(dialogue_record_english != std::string::npos);
	assert(dialogue_translate != std::string::npos);
	assert(dialogue_translate_english != std::string::npos);
	assert(dialogue_display != std::string::npos);
	assert(dialogue_record < dialogue_translate);
	assert(dialogue_translate < dialogue_display);
	assert(ucinternal.find("conv->set_choice_context(")
			!= std::string::npos);
	assert(ucinternal.find("const char* ans = conv->get_answer(choice_num);")
			!= std::string::npos);
	std::ifstream spellbook("gumps/Spellbook_gump.cc");
	assert(spellbook.good());
	const std::string spellbook_source(
			(std::istreambuf_iterator<char>(spellbook)), std::istreambuf_iterator<char>());
	assert(spellbook_source.find("GameplayTranslationKind::Spell") != std::string::npos);
	assert(spellbook_source.find("record_runtime_source") != std::string::npos);
	assert(spellbook_source.find("spell:0x") != std::string::npos);

	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0401:1a_2f:0\t"
			"4e47826698bb4630fb4451010062fadbf85d61427cbdfaed7ad0f23f239bed89\t"
			"你好\n"
			"choice\tchoice:0x0401:0x0088:0\t"
			"7692c3ad3540bb803c020b3aee66cd8887123234ea0c6e7143c0add73ff431ed\t一\n"
			"choice\tchoice:0x0401:0x0088:1\t"
			"3fc4ccfe745870e2c0d99f71f30ff0656c8dedd41cc1d7d3d376b0dbe685e2f3\t二\n"
			"choice\tchoice:0x0401:0x0088:2\t"
			"b49f425a7e1f9cff3856329ada223f2f9d368f15a00cf48df16ca95986137fe8\t告辭\n";
	std::string error;
	std::istringstream input(table_text);
	assert(manager.load_table(input, error));
	assert(error.empty());

	const std::string dialogue_key =
			make_dialogue_translation_key(0x0401, "1a_2f", 0);
	assert(dialogue_key == "dialogue:0x0401:1a_2f:0");
	assert(manager.translate(GameplayTranslationKind::Dialogue,
			dialogue_key, "Hello there") == "你好");

	std::string answers[] = {"one", "two", "bye"};
	const char* const display_answers[] = {"一", "二", "告辭"};
	for (int ordinal = 0; ordinal < 3; ++ordinal) {
		const std::string original_answer = answers[ordinal];
		const std::string choice_key =
				make_choice_translation_key(0x0401, 0x0088, ordinal);
		assert(choice_key == "choice:0x0401:0x0088:" + std::to_string(ordinal));
		assert(manager.translate(GameplayTranslationKind::Choice,
				choice_key, answers[ordinal]) == display_answers[ordinal]);
		assert(answers[ordinal] == original_answer);
	}
}

} // namespace

int main() {
	assert_usecode_fallback_policy();
	assert_table_only_active_machine_source_policy();
	assert_safe_catalog_paths();

	assert(sha256_hex("abc") == kAbcSha256);
	assert(normalize_translation_source("a\r\nb\rc") == "a\nb\nc");

	const std::string field = "tab\tline\nbackslash\\return\r";
	const std::string escaped = "tab\\tline\\nbackslash\\\\return\\r";
	assert(escape_translation_field(field) == escaped);
	std::string error;
	const std::optional<std::string> unescaped =
			unescape_translation_field(escaped, error);
	assert(unescaped.has_value());
	assert(*unescaped == field);
	assert(!unescape_translation_field("bad\\xescape", error).has_value());
	assert(!error.empty());

	const std::string valid_table =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0401:1a_2f:0\t"
			"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\t"
			"你好\\t世界\n";
	GameplayTranslationTable table;
	std::istringstream valid_input(valid_table);
	assert(table.load(valid_input, error));
	assert(error.empty());
	assert(table.size() == 1);

	TranslationLookup result = table.lookup(
			GameplayTranslationKind::Dialogue,
			"dialogue:0x0401:1a_2f:0",
			"abc");
	assert(result.status == TranslationLookupStatus::Hit);
	assert(result.text == "你好\t世界");

	result = table.lookup(
			GameplayTranslationKind::Dialogue,
			"dialogue:0x0401:missing",
			"English");
	assert(result.status == TranslationLookupStatus::Missing);
	assert(result.text == "English");

	result = table.lookup(
			GameplayTranslationKind::Dialogue,
			"dialogue:0x0401:1a_2f:0",
			"different source");
	assert(result.status == TranslationLookupStatus::SourceMismatch);
	assert(result.text == "different source");

	assert(make_dialogue_translation_key(0x0401, "1a_2f", 0)
			== "dialogue:0x0401:1a_2f:0");
	assert(make_choice_translation_key(0x0401, 0x0088, 0)
			== "choice:0x0401:0x0088:0");
	assert(make_item_translation_key(0x01f4, 2, 7)
			== "item:0x01f4:2:7");

	const std::string manager_table =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0401:1a_2f:0\t"
			"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\t你好\n";
	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::istringstream manager_input(manager_table);
	assert(manager.load_table(manager_input, error));
	assert(manager.table_only_enabled());
	assert(manager.translate(GameplayTranslationKind::Dialogue,
				"dialogue:0x0401:1a_2f:0", "abc") == "你好");
	assert(manager.translate(GameplayTranslationKind::Dialogue,
				"dialogue:missing", "missing English") == "missing English");
	assert(manager.translate(GameplayTranslationKind::Dialogue,
				"dialogue:0x0401:1a_2f:0", "stale English") == "stale English");
	const TranslationDiagnostics diagnostics = manager.diagnostics();
	assert(diagnostics.rows == 1);
	assert(diagnostics.hits == 1);
	assert(diagnostics.misses == 1);
	assert(diagnostics.source_mismatches == 1);
	assert(diagnostics.fallbacks == 2);

	assert_load_fails(
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tduplicate\t"
			"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\t一\n"
			"dialogue\tduplicate\t"
			"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\t二\n");
	assert_load_fails(
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"unknown\tkey\t"
			"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\t中文\n");
	assert_load_fails(
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tkey\tshort-hash\t中文\n");
	assert_load_fails(
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tkey\t"
			"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\t\n");
	for (const char* kind : {"dialogue", "choice", "textmsg", "item", "location", "misc", "spell"}) {
		assert_load_fails(std::string("# u6-translation-v1\n")
				+ "# kind\tkey\tsource_sha256\tzh\n"
				+ kind + "\tmalformed\t"
				+ kAbcSha256 + "\t中文\n");
	}

	assert_conversation_display_changes_only_copy_get_answer_stays_byte_for_byte_identical();

	return 0;
}
