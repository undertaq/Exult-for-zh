#include "gameplay_translation_table.h"
#include "gameplay_translation.h"

#include <cassert>
#include <fstream>
#include <iterator>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

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

void assert_mod_usecode_is_loaded_for_all_language_modes() {
	std::ifstream ucinternal_source("usecode/ucinternal.cc");
	const std::string ucinternal(
			(std::istreambuf_iterator<char>(ucinternal_source)),
			std::istreambuf_iterator<char>());
	assert(!ucinternal.empty());
	assert(ucinternal.find(
			"if (is_system_path_defined(\"<PATCH>\") && U7exists(PATCH_USECODE)) {")
			!= std::string::npos);
	assert(ucinternal.find("!(in_game && !Game::is_chinese_mode())")
			== std::string::npos);
	assert(ucinternal.find("if (!patch || !symtbl) {")
			!= std::string::npos);

	std::ifstream bilingual_source("bilingual_manager.cc");
	const std::string bilingual(
			(std::istreambuf_iterator<char>(bilingual_source)),
			std::istreambuf_iterator<char>());
	assert(!bilingual.empty());
	const size_t zh_source = bilingual.find(
			"usecode_zh->read_usecode(*pFile);");
	const size_t zh_patch = bilingual.find(
			"load_patch_usecode(usecode_zh);");
	const size_t dual_source = bilingual.find(
			"usecode_dual->read_usecode(*pFile);");
	const size_t dual_patch = bilingual.find(
			"load_patch_usecode(usecode_dual);");
	assert(zh_source != std::string::npos);
	assert(zh_patch != std::string::npos);
	assert(zh_source < zh_patch);
	assert(dual_source != std::string::npos);
	assert(dual_patch != std::string::npos);
	assert(dual_source < dual_patch);

	std::ifstream gamewin_source("gamewin.cc");
	const std::string gamewin(
			(std::istreambuf_iterator<char>(gamewin_source)),
			std::istreambuf_iterator<char>());
	assert(!gamewin.empty());
	assert(gamewin.find("load_patch_usecode(usecode);")
			!= std::string::npos);
}

void assert_safe_catalog_paths() {
	assert(is_safe_catalog_path("u6_runtime_catalog.tsv"));
	assert(is_safe_catalog_path("translation/catalog.tsv"));
	assert(!is_safe_catalog_path("/tmp/catalog.tsv"));
	assert(!is_safe_catalog_path("translation/../catalog.tsv"));
	assert(!is_safe_catalog_path("../catalog.tsv"));
}

void assert_runtime_speaker_capture_source_policy() {
	std::ifstream translation_header("gameplay_translation.h");
	const std::string header(
			(std::istreambuf_iterator<char>(translation_header)),
			std::istreambuf_iterator<char>());
	assert(!header.empty());
	assert(header.find("record_runtime_speaker(") != std::string::npos);

	std::ifstream translation_source("gameplay_translation.cc");
	const std::string implementation(
			(std::istreambuf_iterator<char>(translation_source)),
			std::istreambuf_iterator<char>());
	assert(!implementation.empty());
	assert(implementation.find("u6-runtime-speakers-v1") != std::string::npos);
	assert(implementation.find("u6_runtime_speakers.tsv") != std::string::npos);
	assert(implementation.find("config/debug/translation/speaker_path")
			!= std::string::npos);

	std::ifstream ucinternal_source("usecode/ucinternal.cc");
	const std::string ucinternal(
			(std::istreambuf_iterator<char>(ucinternal_source)),
			std::istreambuf_iterator<char>());
	assert(!ucinternal.empty());
	assert(ucinternal.find("record_runtime_speaker(") != std::string::npos);
	assert(ucinternal.find("gwin->get_npc(") != std::string::npos);
	assert(ucinternal.find("get_npc_name()") != std::string::npos);
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
			"translations.translate(",
			dialogue_record);
	const size_t dialogue_display = ucinternal.find(
			"conv->show_npc_message(display.c_str());", dialogue_translate);
	assert(dialogue_record != std::string::npos);
	assert(dialogue_record_english != std::string::npos);
	assert(dialogue_translate != std::string::npos);
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

void assert_dialogue_source_fallback_is_function_scoped() {
	const std::string question = "@A question assembled at runtime?@";
	const std::string question_hash = sha256_hex(
			normalize_translation_source(question));
	const std::string runtime_collision_source = "Spirituality";
	const std::string runtime_collision_hash = sha256_hex(
			normalize_translation_source(runtime_collision_source));
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0464:d7b:0\t"
			+ question_hash + "\t這是一個問題\n"
			"dialogue\tdialogue:0x0464:2e2:0\t"
			+ runtime_collision_hash + "\t精神\n"
			"dialogue\tdialogue:0x0401:2e2:0\t"
			+ question_hash + "\t另一個問題\n";

	GameplayTranslationTable table;
	std::string error;
	std::istringstream input(table_text);
	assert(table.load(input, error));
	assert(error.empty());

	TranslationLookup result = table.lookup_dialogue_by_source(
			"dialogue:0x0464:0x0002:0", question);
	assert(result.status == TranslationLookupStatus::SourceFallback);
	assert(result.text == "這是一個問題");

	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::istringstream manager_input(table_text);
	assert(manager.load_table(manager_input, error));
	assert(manager.translate(
			GameplayTranslationKind::Dialogue,
			"dialogue:0x0464:2e2:0", question) == "這是一個問題");

	result = table.lookup_dialogue_by_source(
			"dialogue:0x9999:0x0002:0", question);
	assert(result.status == TranslationLookupStatus::Missing);
	assert(result.text == question);

	const std::string duplicate_table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0464:1:0\t"
			+ question_hash + "\t甲\n"
			"dialogue\tdialogue:0x0464:2:0\t"
			+ question_hash + "\t乙\n";
	std::istringstream duplicate_input(duplicate_table_text);
	assert(table.load(duplicate_input, error));
	result = table.lookup_dialogue_by_source(
			"dialogue:0x0464:0x0003:0", question);
	assert(result.status == TranslationLookupStatus::Missing);
	assert(result.text == question);
}

void assert_dynamic_dialogue_template_replaces_runtime_name() {
	const std::string source_template =
			"@The path of the Avatar lies beneath thy feet, worthy "
			"<PLAYER_NAME>@, the gypsy intones. With a mysterious smile, "
			"she passes you the flask of shimmering liquids.";
	const std::string runtime_source =
			"@The path of the Avatar lies beneath thy feet, worthy Joe@, "
			"the gypsy intones. With a mysterious smile, she passes you the "
			"flask of shimmering liquids.";
	const std::string source_hash = sha256_hex(
			normalize_translation_source(source_template));
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0464:template_gypsy_path:0\t"
			+ source_hash +
			"\t聖者之路就在你腳下，可敬的 <PLAYER_NAME>，"
			"吉普賽人吟誦著。帶著神秘的微笑，她將一瓶閃爍的液體遞給你。\n";

	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	std::istringstream input(table_text);
	assert(manager.load_table(input, error));
	assert(error.empty());

	const std::optional<std::string> translated =
			manager.translate_dialogue_template_if_available(
					runtime_source, source_template, "<PLAYER_NAME>");
	assert(translated.has_value());
	assert(*translated ==
			"聖者之路就在你腳下，可敬的 Joe，吉普賽人吟誦著。"
			"帶著神秘的微笑，她將一瓶閃爍的液體遞給你。");
}

void assert_iolo_dynamic_dialogue_template_replaces_runtime_name() {
	const std::string source_template =
			"@Well, <PLAYER_NAME>, do you need help with something? Or maybe "
			"you've got time for a story, eh?@";
	const std::string runtime_source =
			"@Well, Joe, do you need help with something? Or maybe you've got "
			"time for a story, eh?@";
	const std::string source_hash = sha256_hex(
			normalize_translation_source(source_template));
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0401:template_iolo_greeting:0\t"
			+ source_hash +
			"\t@嗯，<PLAYER_NAME>，你需要幫忙嗎？或者你有時間聽個故事，嗯？@\n";

	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	std::istringstream input(table_text);
	assert(manager.load_table(input, error));
	assert(error.empty());

	const std::optional<std::string> translated =
			manager.translate_dialogue_template_if_available(
					runtime_source, source_template, "<PLAYER_NAME>");
	assert(translated.has_value());
	assert(*translated ==
			"@嗯，Joe，你需要幫忙嗎？或者你有時間聽個故事，嗯？@");

	std::ifstream ucinternal_source("usecode/ucinternal.cc");
	const std::string ucinternal(
			(std::istreambuf_iterator<char>(ucinternal_source)),
			std::istreambuf_iterator<char>());
	assert(!ucinternal.empty());
	assert(ucinternal.find("iolo_greeting_template") != std::string::npos);
}

void assert_multi_placeholder_dialogue_template_replaces_runtime_values() {
	const std::string source_template =
			"@Good <TIME_OF_DAY>, <PLAYER_NAME>. What wouldst thou speak of?@";
	const std::string runtime_source =
			"@Good afternoon, Joe. What wouldst thou speak of?@";
	const std::string source_hash = sha256_hex(
			normalize_translation_source(source_template));
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0494:template_lord_british_greeting:0\t"
			+ source_hash +
			"\t@美好的<TIME_OF_DAY>，<PLAYER_NAME>。汝欲談何事？@\n";

	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	std::istringstream input(table_text);
	assert(manager.load_table(input, error));
	assert(error.empty());

	const std::vector<std::pair<std::string, std::string>> substitutions = {
			{"<TIME_OF_DAY>", "午後"},
			{"<PLAYER_NAME>", "Joe"}};
	const std::optional<std::string> translated =
			manager.translate_dialogue_template_if_available(
					runtime_source, source_template, substitutions);
	assert(translated.has_value());
	assert(*translated == "@美好的午後，Joe。汝欲談何事？@");
}

void assert_lord_british_untraced_dialogue_templates_replace_runtime_name() {
	const std::string return_source_template =
			"@<PLAYER_NAME>! 'Tis good to see thee again. Much hath happened since "
			"thou last departed our realm.@";
	const std::string return_runtime_source =
			"@Joe! 'Tis good to see thee again. Much hath happened since thou last "
			"departed our realm.@";
	const std::string honesty_source_template =
			"@<PLAYER_NAME>, I knowest Honesty is one of the virtues and all..@";
	const std::string honesty_runtime_source =
			"@Joe, I knowest Honesty is one of the virtues and all..@";
	const std::string return_source_hash = sha256_hex(
			normalize_translation_source(return_source_template));
	const std::string honesty_source_hash = sha256_hex(
			normalize_translation_source(honesty_source_template));
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0494:template_lord_british_return_greeting:0\t"
			+ return_source_hash
			+ "\t@<PLAYER_NAME>! 很高興再次見到你。自你上次離開我們王國以來，"
			"發生了很多事情。@\n"
			"dialogue\tdialogue:0x0494:template_lord_british_honesty:0\t"
			+ honesty_source_hash
			+ "\t@<PLAYER_NAME>，我知道誠實是美德之一...@\n";

	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	std::istringstream input(table_text);
	assert(manager.load_table(input, error));
	assert(error.empty());

	const std::optional<std::string> return_translation =
			manager.translate_dialogue_template_if_available(
					return_runtime_source, return_source_template, "<PLAYER_NAME>");
	assert(return_translation.has_value());
	assert(*return_translation ==
			"@Joe! 很高興再次見到你。自你上次離開我們王國以來，發生了很多事情。@");

	const std::optional<std::string> honesty_translation =
			manager.translate_dialogue_template_if_available(
					honesty_runtime_source, honesty_source_template, "<PLAYER_NAME>");
	assert(honesty_translation.has_value());
	assert(*honesty_translation ==
			"@Joe，我知道誠實是美德之一...@");

	std::ifstream ucinternal_source("usecode/ucinternal.cc");
	const std::string ucinternal(
			(std::istreambuf_iterator<char>(ucinternal_source)),
			std::istreambuf_iterator<char>());
	assert(!ucinternal.empty());
	assert(ucinternal.find("lord_british_return_greeting_template")
			!= std::string::npos);
	assert(ucinternal.find("lord_british_honesty_template")
			!= std::string::npos);
}

void assert_choice_source_fallback_reuses_legacy_dialogue_rows() {
	const std::string option = "give up bounty";
	const std::string option_hash = sha256_hex(
			normalize_translation_source(option));
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0464:1789:0\t"
			+ option_hash + "\t放棄賞金\n";
	GameplayTranslationTable table;
	std::string error;
	std::istringstream input(table_text);
	assert(table.load(input, error));

	TranslationLookup result = table.lookup_choice_by_source(option);
	assert(result.status == TranslationLookupStatus::SourceFallback);
	assert(result.text == "放棄賞金");

	const std::string stable_choice_table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"choice\tchoice:0x0956:0x1234567890abcdef:0\t"
			+ option_hash + "\t放棄賞金\n";
	std::istringstream stable_choice_input(stable_choice_table_text);
	assert(table.load(stable_choice_input, error));
	result = table.lookup(
			GameplayTranslationKind::Choice,
			"choice:0x0956:0x1234567890abcdef:0", option);
	assert(result.status == TranslationLookupStatus::Hit);
	assert(result.text == "放棄賞金");

	const std::string ambiguous_table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0464:1:0\t"
			+ option_hash + "\t甲\n"
			"dialogue\tdialogue:0x0464:2:0\t"
			+ option_hash + "\t乙\n";
	std::istringstream ambiguous_input(ambiguous_table_text);
	assert(table.load(ambiguous_input, error));
	result = table.lookup_choice_by_source(option);
	assert(result.status == TranslationLookupStatus::Missing);
	assert(result.text == option);
}

void assert_choice_source_fallback_reuses_textmsg_rows() {
	const std::string yes_hash = sha256_hex(
			normalize_translation_source("Yes"));
	const std::string no_hash = sha256_hex(
			normalize_translation_source("No"));
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"textmsg\ttextmsg:0x0195\t" + yes_hash + "\t是\n"
			"textmsg\ttextmsg:0x0196\t" + no_hash + "\t否\n";
	GameplayTranslationTable table;
	std::string error;
	std::istringstream input(table_text);
	assert(table.load(input, error));

	TranslationLookup result = table.lookup_choice_by_source("Yes");
	assert(result.status == TranslationLookupStatus::SourceFallback);
	assert(result.text == "是");
	result = table.lookup_choice_by_source("No");
	assert(result.status == TranslationLookupStatus::SourceFallback);
	assert(result.text == "否");
}

void assert_dupre_untraced_dialogue_template_replaces_runtime_name() {
	const std::string source_template = "@Yes, <PLAYER_NAME>?@";
	const std::string runtime_source = "@Yes, Joe?@";
	const std::string source_hash = sha256_hex(
			normalize_translation_source(source_template));
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0404:template_dupre_greeting:0\t"
			+ source_hash + "\t@是的，<PLAYER_NAME>？@\n";
	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	std::istringstream input(table_text);
	assert(manager.load_table(input, error));

	const std::optional<std::string> translation =
			manager.translate_dialogue_template_if_available(
					runtime_source, source_template, "<PLAYER_NAME>");
	assert(translation.has_value());
	assert(*translation == "@是的，Joe？@");

	std::ifstream ucinternal_source("usecode/ucinternal.cc");
	const std::string ucinternal(
			(std::istreambuf_iterator<char>(ucinternal_source)),
			std::istreambuf_iterator<char>());
	assert(!ucinternal.empty());
	assert(ucinternal.find("dupre_greeting_template") != std::string::npos);
}

void assert_overhead_dialogue_translation_and_rendering_policy() {
	assert(strip_usecode_dialogue_markers(
			"@First sentence.@ The speaker adds @another sentence.@")
			== "First sentence. The speaker adds another sentence.");

	const std::string bark = "@A bark assembled at runtime.@";
	const std::string bark_hash = sha256_hex(
			normalize_translation_source(bark));
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0464:15c:0\t"
			+ bark_hash + "\t一段頭頂文字\n";

	GameplayTranslationTable table;
	std::string error;
	std::istringstream input(table_text);
	assert(table.load(input, error));
	TranslationLookup result = table.lookup_dialogue_by_source_globally(bark);
	assert(result.status == TranslationLookupStatus::SourceFallback);
	assert(result.text == "一段頭頂文字");
	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::istringstream manager_input(table_text);
	assert(manager.load_table(manager_input, error));
	assert(manager.translate_by_source(
			GameplayTranslationKind::Dialogue, bark) == "一段頭頂文字");
	const auto dynamic_translation =
			manager.translate_dialogue_by_source_if_available(bark);
	assert(dynamic_translation.has_value());
	assert(*dynamic_translation == "一段頭頂文字");

	std::ifstream font_header("shapes/font.h");
	const std::string font(
			(std::istreambuf_iterator<char>(font_header)),
			std::istreambuf_iterator<char>());
	assert(!font.empty());
	assert(font.find("uses_ttf_for_english()") != std::string::npos);

	std::ifstream conversation_source("usecode/conversation.cc");
	const std::string conversation(
			(std::istreambuf_iterator<char>(conversation_source)),
			std::istreambuf_iterator<char>());
	assert(!conversation.empty());
	assert(conversation.find("uses_ttf_for_english()") != std::string::npos);
	assert(conversation.find("use_cjk_layout") != std::string::npos);
	assert(conversation.find("conv_choices[i] = hit_rect.intersect(gwin->get_full_rect())")
			!= std::string::npos);
	assert(conversation.find("TileRect hit_rect = text_rect") != std::string::npos);
	assert(conversation.find("hit_rect.x += gwin->get_win()->get_start_x()")
			!= std::string::npos);
	assert(conversation.find("hit_rect.y -= line_height")
			== std::string::npos);

	std::ifstream effects_source("effects.cc");
	const std::string effects(
			(std::istreambuf_iterator<char>(effects_source)),
			std::istreambuf_iterator<char>());
	assert(!effects.empty());
	assert(effects.find("translate_by_source(") != std::string::npos);
	assert(effects.find("strip_usecode_dialogue_markers") != std::string::npos);

	std::ifstream ucinternal_source("usecode/ucinternal.cc");
	const std::string ucinternal(
			(std::istreambuf_iterator<char>(ucinternal_source)),
			std::istreambuf_iterator<char>());
	assert(!ucinternal.empty());
	assert(ucinternal.find("voice_string_parts") != std::string::npos);
	assert(ucinternal.find("translate_dialogue_fragment") != std::string::npos);
	assert(ucinternal.find(
			"return conv->get_choice_rect(index);")
			!= std::string::npos);
	assert(ucinternal.find(
			"Mouse::mouse()->get_current_frame()")
			!= std::string::npos);
	assert(ucinternal.find(
			"cursor_frame->get_xleft() - cursor_frame->get_xright()")
			!= std::string::npos);
	assert(ucinternal.find(
			"cursor_frame->get_yabove() - cursor_frame->get_ybelow()")
			!= std::string::npos);
	assert(ucinternal.find(
			"visual_rect.x -= gwin->get_win()->get_start_x()")
			== std::string::npos);
	assert(ucinternal.find(
			"visual_rect.y -= gwin->get_win()->get_start_y()")
			== std::string::npos);
	std::ifstream conversation_header("usecode/conversation.h");
	const std::string conversation_header_text(
			(std::istreambuf_iterator<char>(conversation_header)),
			std::istreambuf_iterator<char>());
	assert(!conversation_header_text.empty());
	assert(conversation_header_text.find("choice_visual_rects")
			== std::string::npos);
}

void assert_deferred_text_preserves_cursor_layer() {
	std::ifstream deferred_text_source("imagewin/deferred_text.cc");
	const std::string deferred_text(
			(std::istreambuf_iterator<char>(deferred_text_source)),
			std::istreambuf_iterator<char>());
	assert(!deferred_text.empty());

	// The cursor is already present in inter_surface before deferred text is
	// composited.  The mask must therefore compare both objects in that same
	// compositor coordinate space.
	assert(deferred_text.find("int sx_pixel = buffer_x;\n")
			!= std::string::npos);
	assert(deferred_text.find("int sy_pixel = buffer_y;\n")
			!= std::string::npos);
	assert(deferred_text.find(
				"int sx_pixel = buffer_x + image_win->get_start_x();")
			== std::string::npos);
	assert(deferred_text.find(
				"int sy_pixel = buffer_y + image_win->get_start_y();")
			== std::string::npos);
}

} // namespace

int main() {
	assert_usecode_fallback_policy();
	assert_table_only_active_machine_source_policy();
	assert_mod_usecode_is_loaded_for_all_language_modes();
	assert_safe_catalog_paths();
	assert_runtime_speaker_capture_source_policy();

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
	assert_dialogue_source_fallback_is_function_scoped();
	assert_dynamic_dialogue_template_replaces_runtime_name();
	assert_iolo_dynamic_dialogue_template_replaces_runtime_name();
	assert_multi_placeholder_dialogue_template_replaces_runtime_values();
	assert_lord_british_untraced_dialogue_templates_replace_runtime_name();
	assert_choice_source_fallback_reuses_legacy_dialogue_rows();
	assert_choice_source_fallback_reuses_textmsg_rows();
	assert_dupre_untraced_dialogue_template_replaces_runtime_name();
	assert_overhead_dialogue_translation_and_rendering_policy();
	assert_deferred_text_preserves_cursor_layer();

	return 0;
}
