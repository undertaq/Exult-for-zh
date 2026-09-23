#include "gameplay_translation_table.h"

#define private public
#include "gameplay_translation.h"
#undef private

#include <cassert>
#include <cstdlib>
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

void assert_u6_shared_voice_lookup_contract() {
	std::ifstream voice_source("audio/VoiceActingManager.cc");
	const std::string voice(
			(std::istreambuf_iterator<char>(voice_source)),
			std::istreambuf_iterator<char>());
	assert(!voice.empty());
	// U6 voice manifests use the original runtime identity as the shared
	// English/Chinese filename stem. Cross-language remapping is optional and
	// must never replace that identity when no bilingual map is available.
	assert(voice.find("string base = string(func_hex) + \"_\" + offset_key")
			!= std::string::npos);
	assert(voice.find(
				"if (BilingualManager::get().is_bilingual_available() && map_needed)")
			!= std::string::npos);

	std::ifstream usecode_source("usecode/ucinternal.cc");
	const std::string usecode(
			(std::istreambuf_iterator<char>(usecode_source)),
			std::istreambuf_iterator<char>());
	assert(!usecode.empty());
	// The same captured function/offset/segment tuple drives both consumers.
	assert(usecode.find("VoiceActingManager::play_for_conversation(")
			!= std::string::npos);
	assert(usecode.find("make_dialogue_translation_key(")
			!= std::string::npos);

	std::ifstream deploy_source("tools/u6_translation/deploy.py");
	const std::string deploy(
			(std::istreambuf_iterator<char>(deploy_source)),
			std::istreambuf_iterator<char>());
	assert(!deploy.empty());
	// U6 deployment is display-time translation plus optional voice archives;
	// it must not manufacture U7's alternate-usecode/map artifacts.
	assert(deploy.find("usecode.zh") == std::string::npos);
	assert(deploy.find("usecode.dual") == std::string::npos);
	assert(deploy.find("bilingual_map.dat") == std::string::npos);
	assert(deploy.find("dual_map.dat") == std::string::npos);

	std::ifstream readme_source("tools/u6_translation/README.md");
	const std::string readme(
			(std::istreambuf_iterator<char>(readme_source)),
			std::istreambuf_iterator<char>());
	assert(!readme.empty());
	assert(readme.find("compiled `usecode.zh` alternate-usecode binary is not staged")
			!= std::string::npos);
}

void assert_u6_nested_voice_speaker_restoration_contract() {
	std::ifstream frame_source("usecode/stackframe.h");
	const std::string frame(
			(std::istreambuf_iterator<char>(frame_source)),
			std::istreambuf_iterator<char>());
	assert(!frame.empty());
	// A helper usecode function may temporarily show another NPC's face.
	// Its caller must regain its prior voice identity when the helper returns.
	assert(frame.find("voice_face_npc_before") != std::string::npos);
	// A single function can also hand the face to another NPC and remove it
	// before continuing. That transition needs an intra-frame LIFO restore.
	assert(frame.find("voice_face_npc_stack") != std::string::npos);

	std::ifstream usecode_source("usecode/ucinternal.cc");
	const std::string usecode(
			(std::istreambuf_iterator<char>(usecode_source)),
			std::istreambuf_iterator<char>());
	assert(!usecode.empty());
	assert(usecode.find("frame->voice_face_npc_before = voice_current_face_npc")
			!= std::string::npos);
	assert(usecode.find("voice_current_face_npc = frame->call_depth == 0")
			!= std::string::npos);
	assert(usecode.find(": frame->voice_face_npc_before")
			!= std::string::npos);
	assert(usecode.find("voice_face_npc_stack.push_back") != std::string::npos);
	assert(usecode.find("voice_face_npc_stack.back()") != std::string::npos);
	assert(usecode.find("voice_face_npc_stack.pop_back") != std::string::npos);
}

void assert_placeholder_translation_has_no_dynamic_registry_dependency() {
	std::ifstream translation_source("gameplay_translation.cc");
	const std::string implementation(
			(std::istreambuf_iterator<char>(translation_source)),
			std::istreambuf_iterator<char>());
	assert(!implementation.empty());
	// Placeholder rows are part of the normal translation table. Runtime must
	// not open or iterate a finite dynamic_templates.tsv registry.
	assert(implementation.find("dynamic_templates.tsv") == std::string::npos);
	assert(implementation.find("dynamic_templates_") == std::string::npos);

	std::ifstream header_source("gameplay_translation.h");
	const std::string header(
			(std::istreambuf_iterator<char>(header_source)),
			std::istreambuf_iterator<char>());
	assert(!header.empty());
	assert(header.find("dynamic_templates_") == std::string::npos);

	std::ifstream ucinternal_source("usecode/ucinternal.cc");
	const std::string ucinternal(
			(std::istreambuf_iterator<char>(ucinternal_source)),
			std::istreambuf_iterator<char>());
	assert(!ucinternal.empty());
	assert(ucinternal.find(
				"translate_dialogue_placeholders_if_available(")
			== std::string::npos);
}

void assert_provenance_templates_use_source_stable_keys() {
	const std::string source = "@Hello <VAR0>!@";
	const std::string key = make_dialogue_template_translation_key(0x043e, source);
	assert(key == "dialogue:0x043e:fallback_"
			+ sha256_hex(normalize_translation_source(source)).substr(0, 16)
			+ ":0");
	assert(key.find("snaz") == std::string::npos);
}

void assert_runtime_provenance_is_value_scoped() {
	std::ifstream ucinternal_source("usecode/ucinternal.cc");
	const std::string ucinternal(
			(std::istreambuf_iterator<char>(ucinternal_source)),
			std::istreambuf_iterator<char>());
	assert(!ucinternal.empty());
	// PUSHS values can be assembled in a local and appended later by ADDSV.
	// Their literal anchors must follow the VM value, not a global history of
	// every PUSHS executed by the conversation/menu code.
	assert(ucinternal.find("voice_stack_fragments") != std::string::npos);
	assert(ucinternal.find("voice_local_fragments") != std::string::npos);
	assert(ucinternal.find("take_voice_fragments") != std::string::npos);
}

void assert_item_say_uses_runtime_provenance_for_overhead_text() {
	std::ifstream ucinternal_source("usecode/ucinternal.cc");
	const std::string ucinternal(
			(std::istreambuf_iterator<char>(ucinternal_source)),
			std::istreambuf_iterator<char>());
	assert(!ucinternal.empty());
	// item_say must consume the same VM fragment provenance as SAY.  Its
	// overhead path cannot recover a placeholder from the completed sentence.
	assert(ucinternal.find("item_say_fragments") != std::string::npos);
	assert(ucinternal.find(
			"translate_dialogue_fragments_if_available(") != std::string::npos);
	const size_t capture = ucinternal.find("item_say_fragments");
	const size_t execute = ucinternal.find("Execute_Intrinsic", capture);
	assert(capture != std::string::npos);
	assert(execute != std::string::npos);
	assert(capture < execute);
}

void assert_static_item_say_fragments_translate() {
	const std::string source = "@Oh, my aching back...@";
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x092e:23:0\t"
			+ sha256_hex(normalize_translation_source(source))
			+ "\t@噢，我的背好痛...@\n";
	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	std::istringstream input(table_text);
	assert(manager.load_table(input, error));

	const auto translated = manager.translate_dialogue_fragments_if_available(
			0x092e, source,
			std::vector<DialogueTranslationPart>{{
					source, "dialogue:0x092e:23:0", false}});
	assert(translated.has_value());
	assert(*translated == "@噢，我的背好痛...@");
}

void assert_protected_professional_terms_use_source_global_rows() {
	std::ifstream table_file("tools/u6_translation/deploy/mods/Ultima6v1.3/patch/zh_translation.tsv");
	assert(table_file);
	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	assert(manager.load_table(table_file, error));
	assert(error.empty());

	// Runtime fragments can arrive without an NPC-specific key.  The
	// glossary-backed runtime rows keep the singular/plural professional terms
	// English in dialogue, choices, books, items, and overhead text alike.
	assert(manager.translate_by_source(
			GameplayTranslationKind::Dialogue, "wisp") == "wisp");
	assert(manager.translate_by_source(
			GameplayTranslationKind::Dialogue, "wisps") == "wisps");
	assert(manager.translate_by_source(
			GameplayTranslationKind::Choice, "wisps") == "wisps");
	assert(manager.translate_by_source(
			GameplayTranslationKind::Item, "wisp") == "wisp");
}

void assert_gwenneth_static_anchor_template_is_translated() {
	const std::string source_template =
			"Turning to you, Gwenneth says, @And what can I do for "
			"Iolo's friend this fine <VAR0>?@";
	const std::string runtime_source =
			"Turning to you, Gwenneth says, @And what can I do for "
			"Iolo's friend this fine afternoon?@";

	std::ifstream table_file("tools/u6_translation/deploy/mods/Ultima6v1.3/patch/zh_translation.tsv");
	assert(table_file);
	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	assert(manager.load_table(table_file, error));
	assert(error.empty());

	const std::optional<std::string> translated =
			manager.translate_dialogue_template_if_available(
					runtime_source, source_template);
	assert(translated.has_value());
	assert(*translated ==
				"轉過身對著你，Gwenneth 說，@在這美好的午後，我能為 "
				"Iolo 的朋友做些什麼？@");
}

void assert_gwenneth_hello_again_static_anchor_template_is_translated() {
	const std::string source_template =
			"@Hello again. What can I do for thee this fine <VAR0>?@";
	const std::string runtime_source =
			"@Hello again. What can I do for thee this fine afternoon?@";

	std::ifstream table_file("tools/u6_translation/deploy/mods/Ultima6v1.3/patch/zh_translation.tsv");
	assert(table_file);
	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	assert(manager.load_table(table_file, error));
	assert(error.empty());

	const std::optional<std::string> translated =
			manager.translate_dialogue_template_if_available(
					runtime_source, source_template);
	assert(translated.has_value());
	assert(*translated == "@再次見面了。在這美好的午後，我能為你做些什麼？@");
}

void assert_shamino_wait_here_template_is_translated() {
	const std::string source_template =
			"Very well, <VAR0>, I shall wait here until thy return.@";
	const std::string runtime_source =
			"Very well, Avatar, I shall wait here until thy return.@";

	std::ifstream table_file("tools/u6_translation/deploy/mods/Ultima6v1.3/patch/zh_translation.tsv");
	assert(table_file);
	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	assert(manager.load_table(table_file, error));
	assert(error.empty());

	const std::optional<std::string> translated =
			manager.translate_dialogue_template_if_available(
					runtime_source, source_template);
	assert(translated.has_value());
	assert(*translated == "很好，聖者，我會在這裡等你回來。@");
}

void assert_structural_fragment_fallback_translates_missing_template() {
	const std::string prefix = "Very well, ";
	const std::string value = "Avatar";
	const std::string suffix = ", I shall wait here until thy return.@";
	const std::string source_template =
			"Very well, <VAR0>, I shall wait here until thy return.@";
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0403:700:0\t"
			+ sha256_hex(normalize_translation_source(prefix)) + "\t很好，\n"
			"dialogue\tdialogue:0x0403:701:0\t"
			+ sha256_hex(normalize_translation_source(suffix))
			+ "\t我會在這裡等你回來。@\n";

	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::istringstream input(table_text);
	std::string error;
	assert(manager.load_table(input, error));
	assert(error.empty());

	const std::vector<std::pair<std::string, std::string>> substitutions{
			{"<VAR0>", "聖者"}};
	assert(!manager.translate_dialogue_template_values_if_available(
			source_template, substitutions));

	const std::optional<std::string> translated =
			manager.translate_dialogue_fragments_if_available(
					0x0403, prefix + value + suffix,
					std::vector<DialogueTranslationPart>{
							{prefix, "dialogue:0x0403:700:0", false},
							{value, "", true},
							{suffix, "dialogue:0x0403:701:0", false}});
	assert(translated.has_value());
	assert(*translated == "很好，Avatar我會在這裡等你回來。@");
}

void assert_inherited_bed_dialogue_fragments_translate() {
	std::ifstream table_file("tools/u6_translation/deploy/mods/Ultima6v1.3/patch/zh_translation.tsv");
	assert(table_file);
	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	assert(manager.load_table(table_file, error));
	assert(error.empty());

	const std::string runtime_source =
			"\"In how many hours shall we wake thee up, Joe?\"";
	const std::optional<std::string> translated =
			manager.translate_dialogue_fragments_if_available(
					0x0622, runtime_source,
					std::vector<DialogueTranslationPart>{
							{"\"In how many hours shall ", "dialogue:0x0622:5:0", false},
							{"we", "", true},
							{" wake thee up, ", "dialogue:0x0622:1f:0", false},
							{"Joe", "", true},
							{"?\"", "dialogue:0x0622:2f:0", false}});
	assert(translated.has_value());
	assert(*translated == "「你想睡多久？我們會叫醒你的， Joe？」");
}

void assert_inherited_bed_dialogue_bark_translates() {
	std::ifstream table_file("tools/u6_translation/deploy/mods/Ultima6v1.3/patch/zh_translation.tsv");
	assert(table_file);
	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	assert(manager.load_table(table_file, error));
	assert(error.empty());

	const std::string runtime_source =
			"Dupre gives you an exasperated look.* \"Never mind, then.\"";
	const std::optional<std::string> translated =
			manager.translate_dialogue_fragments_if_available(
					0x0622, runtime_source,
					std::vector<DialogueTranslationPart>{
							{"Dupre", "", true},
							{" gives you an exasperated look.* \"Never mind, then.\"",
							 "dialogue:0x0622:32:0", false}});
	assert(translated.has_value());
	assert(*translated == "Dupre 給你一個不耐煩的眼神。「算了。」*");
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
	const size_t addsv_fragments = ucinternal.find(
			"for (Voice_string_part& part : local_fragments)");
	const size_t addsv_dynamic = ucinternal.find(
			"part.dynamic = true", addsv_fragments);
	assert(addsv_fragments != std::string::npos);
	assert(addsv_dynamic != std::string::npos);
	assert(addsv_fragments < addsv_dynamic);
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

void assert_snaz_dynamic_dialogue_template_replaces_gendered_word() {
	const std::string source_template = "@Hello my good <VAR0>!@";
	const std::string runtime_source = "@Hello my good man!@";
	const std::string source_hash = sha256_hex(
			normalize_translation_source(source_template));
	const std::string man_hash = sha256_hex(
			normalize_translation_source("man"));
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x043e:template_snaz_good_man:0\t"
			+ source_hash + "\t@您好，我的好<VAR0>！@\n"
			"dialogue\tdialogue:0x043e:6:0\t"
			+ man_hash + "\t人\n";

	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	std::istringstream input(table_text);
	assert(manager.load_table(input, error));
	assert(error.empty());

	const std::string translated_word = manager.translate_by_source(
			GameplayTranslationKind::Dialogue, "man");
	assert(translated_word == "人");
	const std::optional<std::string> translated =
			manager.translate_dialogue_template_if_available(
					runtime_source, source_template,
					{{"<VAR0>", translated_word}});
	assert(translated.has_value());
	assert(*translated == "@您好，我的好人！@");
}

void assert_snaz_runtime_template_hook_is_reachable() {
	std::ifstream ucinternal_source("usecode/ucinternal.cc");
	const std::string ucinternal(
			(std::istreambuf_iterator<char>(ucinternal_source)),
			std::istreambuf_iterator<char>());
	assert(!ucinternal.empty());
	// Snaz's usecode assembles the greeting with pushs/add before one ADDSV,
	// so the generic trace becomes only <VAR0>. All NPCs use the shared
	// provenance-driven template path; no function-specific hook is allowed.
	assert(ucinternal.find("voice_string_parts") != std::string::npos);
	assert(ucinternal.find("if (voice_func_id == 0x043e)")
				== std::string::npos);
	assert(ucinternal.find("if (voice_func_id == 0x0419)")
				== std::string::npos);
	assert(ucinternal.find("snaz_good_greeting_template")
			== std::string::npos);
	assert(ucinternal.find("const std::string b_you") == std::string::npos);
	assert(ucinternal.find("const std::string b_party") == std::string::npos);
	assert(ucinternal.find("const std::string b_avatar") == std::string::npos);
	assert(ucinternal.find("replace_first_placeholder") != std::string::npos);
	assert(ucinternal.find(
			"infer_dialogue_template_candidates_from_static_fragments")
			== std::string::npos);
	assert(ucinternal.find(
			"translate_dialogue_fragments_if_available")
			!= std::string::npos);
}

void assert_generic_dialogue_placeholders_are_extracted_and_translated() {
	const std::string source_template =
			"@Greetings <NPC_NAME> (<VAR0>)!@";
	const std::string runtime_source =
			"@Greetings guard (2)!@";
	const std::string template_hash = sha256_hex(
			normalize_translation_source(source_template));
	const std::string guard_hash = sha256_hex(
			normalize_translation_source("guard"));
	const std::string peyton_source =
			"@Greetings, <PLAYER_NAME>, and welcome to the Wayfarer's Inn!@";
	const std::string peyton_hash = sha256_hex(
			normalize_translation_source(peyton_source));
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0700:template_generic:0\t"
			+ template_hash + "\t@問候<NPC_NAME>（<VAR0>）！@\n"
			"dialogue\tdialogue:0x0700:template_value_guard:0\t"
			+ guard_hash + "\t守衛\n"
			"dialogue\tdialogue:0x0419:template_peyton_greeting:0\t"
			+ peyton_hash + "\t@您好，<PLAYER_NAME>，歡迎來到旅者客棧！@\n";
	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::istringstream input(table_text);
	std::string error;
	assert(manager.load_table(input, error));
	const std::optional<std::string> translated =
			manager.translate_dialogue_template_if_available(
					runtime_source, source_template);
	assert(translated.has_value());
	assert(*translated == "@問候守衛（2）！@");
	const std::optional<std::string> table_translation =
			manager.translate_dialogue_template_if_available(
					"@Greetings, Joe, and welcome to the Wayfarer's Inn!@",
					peyton_source);
	assert(table_translation.has_value());
	assert(*table_translation == "@您好，Joe，歡迎來到旅者客棧！@");
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
	assert(ucinternal.find("translate_dialogue_fragments_if_available(")
			!= std::string::npos);
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
			"\t@<TIME_OF_DAY>，<PLAYER_NAME>。汝欲談何事？@\n";

	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	std::istringstream input(table_text);
	assert(manager.load_table(input, error));
	assert(error.empty());

	const std::vector<std::pair<std::string, std::string>> substitutions = {
			{"<TIME_OF_DAY>", "午安"},
			{"<PLAYER_NAME>", "Joe"}};
	const std::optional<std::string> translated =
			manager.translate_dialogue_template_if_available(
					runtime_source, source_template, substitutions);
	assert(translated.has_value());
	assert(*translated == "@午安，Joe。汝欲談何事？@");
}

void assert_generic_addsv_dialogue_template_replaces_runtime_value() {
	const std::string source_template =
			"@Good <VAR0>, friend Avatar.@";
	const std::string source_hash = sha256_hex(
			normalize_translation_source(source_template));
	const std::string afternoon_hash = sha256_hex(
			normalize_translation_source("afternoon"));
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x041f:template_daver_greeting:0\t"
			+ source_hash + "\t@<VAR0>，聖者朋友。@\n"
			"dialogue\tdialogue:0x041f:af:0\t"
			+ afternoon_hash + "\t午後\n";

	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	std::istringstream input(table_text);
	assert(manager.load_table(input, error));
	assert(error.empty());
	const std::vector<std::pair<std::string, std::string>> substitutions{
			{"<VAR0>", "午安"}};
	const std::optional<std::string> translated =
			manager.translate_dialogue_template_values_if_available(
					source_template, substitutions);
	assert(translated.has_value());
	assert(*translated == "@午安，聖者朋友。@");
}

void assert_dialogue_template_substitutes_placeholders_by_position() {
	GameplayTranslationManager manager;
	const std::string source_template = "@Hello <VAR0>!@";
	const std::string runtime_source = "@Hello man!@";
	const std::string source_hash = sha256_hex(
			normalize_translation_source(source_template));
	std::stringstream table;
	table << "# u6-translation-v1\n"
		  << "# kind\tkey\tsource_sha256\tzh\n"
		  << "dialogue\tdialogue:0x043e:fallback_" << source_hash.substr(0, 16)
		  << ":0\t" << source_hash << "\t@您好，<PLAYER_NAME>！@\n";
	std::string error;
	assert(manager.load_table(table, error));
	manager.set_text_language(TextLanguage::CHINESE);
	const auto translated = manager.translate_dialogue_template_if_available(
			runtime_source, source_template,
			std::vector<std::pair<std::string, std::string>>{
					{"<VAR0>", "man"}});
	assert(translated.has_value());
	assert(*translated == "@您好，man！@");
}

void assert_dialogue_template_preserves_named_reordering_and_repetition() {
	GameplayTranslationManager manager;
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	const std::string reordered_source = "@<LEFT> gave <RIGHT>.@";
	const std::string reordered_hash = sha256_hex(
			normalize_translation_source(reordered_source));
	const std::string repeated_source = "@<NAME> trusts <NAME>.@";
	const std::string repeated_hash = sha256_hex(
			normalize_translation_source(repeated_source));
	std::stringstream table;
	table << "# u6-translation-v1\n"
		  << "# kind\tkey\tsource_sha256\tzh\n"
		  << "dialogue\tdialogue:0x0700:fallback_" << reordered_hash.substr(0, 16)
		  << ":0\t" << reordered_hash << "\t@<RIGHT> 給了 <LEFT>。@\n"
		  << "dialogue\tdialogue:0x0700:fallback_" << repeated_hash.substr(0, 16)
		  << ":0\t" << repeated_hash << "\t@<NAME> 信任 <NAME>。@\n";
	std::string error;
	assert(manager.load_table(table, error));

	const auto reordered = manager.translate_dialogue_template_if_available(
			"@Iolo gave Dupre.@", reordered_source,
			std::vector<std::pair<std::string, std::string>>{
					{"<LEFT>", "Iolo"}, {"<RIGHT>", "Dupre"}});
	assert(reordered.has_value());
	assert(*reordered == "@Dupre 給了 Iolo。@");

	const auto repeated = manager.translate_dialogue_template_if_available(
			"@Ada trusts Ada.@", repeated_source);
	assert(repeated.has_value());
	assert(*repeated == "@Ada 信任 Ada。@");
}

void assert_dialogue_template_rejects_ambiguous_literal_boundaries() {
	GameplayTranslationManager manager;
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	const std::string source_template = "@Tell <FIRST>, <SECOND>.@";
	const std::string source_hash = sha256_hex(
			normalize_translation_source(source_template));
	std::stringstream table;
	table << "# u6-translation-v1\n"
		  << "# kind\tkey\tsource_sha256\tzh\n"
		  << "dialogue\tdialogue:0x0701:fallback_" << source_hash.substr(0, 16)
		  << ":0\t" << source_hash << "\t@告訴 <FIRST> 去 <SECOND>。@\n";
	std::string error;
	assert(manager.load_table(table, error));
	const auto translated = manager.translate_dialogue_template_if_available(
			"@Tell one, two, three.@", source_template);
	assert(!translated.has_value());
}

void assert_checked_in_placeholder_rows_use_canonical_runtime_sources() {
	std::ifstream input("tools/u6_translation/deploy/mods/Ultima6v1.3/patch/zh_translation.tsv");
	assert(input.good());
	GameplayTranslationManager manager;
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	assert(manager.load_table(input, error));
	assert(error.empty());

	const auto peyton = manager.translate_dialogue_template_if_available(
			"@Greetings, Joe, and welcome to the Wayfarer's Inn!@",
			"@Greetings, <VAR0>, and welcome to the Wayfarer's Inn!@");
	assert(peyton.has_value());
	assert(*peyton == "@您好，Joe，歡迎來到旅者客棧！@");

	const auto daver = manager.translate_dialogue_template_if_available(
			"@Good afternoon, friend Avatar.@",
			"@Good <VAR0>, friend Avatar.@");
	assert(daver.has_value());
	assert(*daver == "@午安，聖者朋友。@");

	const auto blaine = manager.translate_dialogue_template_if_available(
			"@Good afternoon.@", "@Good <VAR0>.@");
	assert(blaine.has_value());
	assert(*blaine == "@午安。@");
	const auto blaine_overhead = manager.translate_dialogue_fragments_if_available(
			0x041b, "@Good afternoon.@",
			std::vector<DialogueTranslationPart>{
					{"@Good ", "dialogue:0x041b:23:0", false},
					{"afternoon", "", true},
					{".@", "dialogue:0x041b:2a:0", false}});
	assert(blaine_overhead.has_value());
	assert(*blaine_overhead == "@午安。@");
	// UC_ADDSV can carry a value returned by a helper as one provenance
	// expression.  The interpreter may therefore mark every copied fragment as
	// dynamic even though the source still has no sentence-specific pattern.
	const auto blaine_delayed = manager.translate_dialogue_fragments_if_available(
			0x041b, "@Good afternoon.@",
			std::vector<DialogueTranslationPart>{
					{"@Good ", "", true},
					{"afternoon", "", true},
					{".@", "", true}});
	assert(blaine_delayed.has_value());
	assert(*blaine_delayed == "@午安。@");

	const auto blaine_morning = manager.translate_dialogue_template_if_available(
			"@Good morning.@", "@Good <VAR0>.@");
	assert(blaine_morning.has_value());
	assert(*blaine_morning == "@早安。@");

	// A compiled ADDSI can carry multiple `~` dialogue segments in one VM
	// value.  Extraction/audit split those segments into ordinal rows, so the
	// runtime fragment path must do the same before looking up the provenance
	// key.  This is the shape used by Chuckles's congratulatory hint.
	const std::string chuckles_source =
			"@Congratulations! You're exactly right!  I won't tell you the "
			"clue.....But I will give you this hint that may lead you to it..."
			"~Search the chest in Nystul's room.";
	const auto chuckles = manager.translate_dialogue_fragments_if_available(
			0x0437, chuckles_source,
			std::vector<DialogueTranslationPart>{{
					chuckles_source, "dialogue:0x0437:8f5:0", false}});
	assert(chuckles.has_value());
	assert(*chuckles ==
				"@恭喜！你完全答對了！我不會告訴你線索.....但我給你的這個提示也許能引導你找到它..."
				"~搜尋 Nystul 房間裡的箱子。");
	const auto chuckles_dynamic = manager.translate_dialogue_fragments_if_available(
				0x0437, chuckles_source,
				std::vector<DialogueTranslationPart>{{chuckles_source, "", true}});
	assert(chuckles_dynamic.has_value());
	assert(*chuckles_dynamic == *chuckles);

	const auto snaz = manager.translate_dialogue_template_if_available(
			"@Hello my good man!@", "@Hello my good <VAR0>!@");
	assert(snaz.has_value());
	assert(*snaz == "@您好，我的好人！@");

	const auto lord_british = manager.translate_dialogue_template_if_available(
			"@Good afternoon, Joe. What wouldst thou speak of?@",
			"@Good <VAR0>, <VAR1>. What wouldst thou speak of?@");
	assert(lord_british.has_value());
	assert(*lord_british == "@午安，Joe。汝欲談何事？@");

	const auto milord = manager.translate_dialogue_fragments_if_available(
			0x0416, "@I recongize thee! Thou art Iolo's friend, milord!@",
			std::vector<DialogueTranslationPart>{
					{"@I recongize thee! Thou art Iolo's friend, ",
						"dialogue:0x0416:25d:0", false},
					{"milord", "", true},
					{"!@", "dialogue:0x0416:289:0", false}});
	assert(milord.has_value());
	assert(*milord == "@我認識你！你是 Iolo 的朋友，大人!@");
	assert(manager.translate_by_source(GameplayTranslationKind::Dialogue, "milord")
				== "大人");
}

void assert_optional_release_table_loads() {
	const char* const path = std::getenv("U6_ZH_TRANSLATION_TABLE");
	if (path == nullptr || *path == '\0') {
		return;
	}
	std::ifstream input(path);
	assert(input.good());
	GameplayTranslationTable table;
	std::string error;
	assert(table.load(input, error));
	assert(error.empty());
	assert(table.size() > 0);
	const TranslationLookup wake = table.lookup_dialogue_by_source_globally(
			"\"In how many hours shall <VAR0> wake thee up, <VAR1>?\"");
	assert(wake.status == TranslationLookupStatus::SourceFallback);
	assert(wake.text == "「你想睡多久？<VAR0>會叫醒你的， <VAR1>？」");
	const TranslationLookup bark = table.lookup_dialogue_by_source_globally(
			"<VAR0> gives you an exasperated look.* \"Never mind, then.\"");
	assert(bark.status == TranslationLookupStatus::SourceFallback);
	assert(bark.text == "<VAR0> 給你一個不耐煩的眼神。「算了。」*");
	const TranslationLookup maldric = table.lookup(
			GameplayTranslationKind::Dialogue,
			"dialogue:0x0430:50:0",
			"A bare chested, muscular man, his body gleaming with sweat.");
	assert(maldric.status == TranslationLookupStatus::Hit);
	assert(maldric.text == "一個赤裸上身、肌肉發達的男人，他身上閃著汗水的亮光。");
	const TranslationLookup maldric_secret = table.lookup(
			GameplayTranslationKind::Dialogue,
			"dialogue:0x0430:491:0",
			"@The secret is in the spices. It's an old family recipe.@");
	assert(maldric_secret.status == TranslationLookupStatus::Hit);
	assert(maldric_secret.text == "祕密在於香料。這是一份古老的家族食譜。");
}

void assert_numeric_dialogue_fragments_keep_the_runtime_value() {
	std::ifstream table_file("tools/u6_translation/deploy/mods/Ultima6v1.3/patch/zh_translation.tsv");
	assert(table_file);
	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	assert(manager.load_table(table_file, error));
	assert(error.empty());

	const auto translated = manager.translate_dialogue_fragments_if_available(
			0x0425, "@That'll be 4 gold coins, okay?@",
			std::vector<DialogueTranslationPart>{
					{"@That'll be ", "dialogue:0x0425:61:0", false},
					{"4", "", true},
					{" gold coins, okay?@", "dialogue:0x0425:6e:0", false}});
	assert(translated.has_value());
	assert(*translated == "@總計是4金幣，好嗎？@");
}

void assert_numeric_uc_add_provenance_is_preserved() {
	std::ifstream ucinternal_source("usecode/ucinternal.cc");
	const std::string ucinternal(
			(std::istreambuf_iterator<char>(ucinternal_source)),
			std::istreambuf_iterator<char>());
	assert(!ucinternal.empty());
	// UC_ADD converts an integer to text whenever the other operand is a
	// string. Keep that converted value as a dynamic provenance part so a
	// later ADDSV can translate the surrounding literal fragments generically.
	assert(ucinternal.find("const bool string_concatenation")
			!= std::string::npos);
	assert(ucinternal.find("value.is_int()") != std::string::npos);
	assert(ucinternal.find("std::to_string(value.get_int_value())")
			!= std::string::npos);
}

void assert_fragment_fallback_restores_split_speech_markers() {
	GameplayTranslationManager manager;
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	const std::string prefix = "@Hello my good ";
	const std::string value = "man";
	const std::string suffix = "!@";
	std::stringstream table;
	table << "# u6-translation-v1\n"
		  << "# kind\tkey\tsource_sha256\tzh\n"
		  << "dialogue\tdialogue:0x043e:31:0\t"
		  << sha256_hex(normalize_translation_source(prefix))
		  << "\t你好，尊敬的\n"
		  << "dialogue\tdialogue:0x043e:6:0\t"
		  << sha256_hex(normalize_translation_source(value))
		  << "\t人\n"
		  << "dialogue\tdialogue:0x043e:41:0\t"
		  << sha256_hex(normalize_translation_source(suffix))
		  << "\t!\n";
	std::string error;
	assert(manager.load_table(table, error));
	const auto translated = manager.translate_dialogue_fragments_if_available(
			0x043e, prefix + value + suffix,
			std::vector<DialogueTranslationPart>{
					{prefix, "dialogue:0x043e:31:0", true},
					{value, "", true},
					{suffix, "dialogue:0x043e:41:0", true}});
	assert(translated.has_value());
	assert(*translated == "@你好，尊敬的人!@");
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
	assert(ucinternal.find("translate_dialogue_fragments_if_available(")
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

void assert_item_source_fallback_reuses_raw_quantity_and_misc_rows() {
	const std::string gold_nugget = "/gold nugget//s";
	const std::string quill = "quill";
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"item\titem:0x0285:0:0\t"
			+ sha256_hex(normalize_translation_source(gold_nugget))
			+ "\t/金塊//s\n"
			"misc\tmisc:0x002e\t"
			+ sha256_hex(normalize_translation_source(quill))
			+ "\t羽毛筆\n";

	GameplayTranslationTable table;
	std::string error;
	std::istringstream input(table_text);
	assert(table.load(input, error));
	assert(error.empty());

	TranslationLookup result = table.lookup_item_by_source(gold_nugget);
	assert(result.status == TranslationLookupStatus::SourceFallback);
	assert(result.text == "/金塊//s");
	result = table.lookup_item_by_source(quill);
	assert(result.status == TranslationLookupStatus::SourceFallback);
	assert(result.text == "羽毛筆");

	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::istringstream manager_input(table_text);
	assert(manager.load_table(manager_input, error));
	assert(manager.translate_by_source(GameplayTranslationKind::Item, gold_nugget)
			== "/金塊//s");
	assert(manager.translate_by_source(GameplayTranslationKind::Item, quill)
			== "羽毛筆");
}

void assert_book_text_uses_dialogue_source_fallback() {
	const std::string source = "A page of book text";
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0282:10:0\t"
			+ sha256_hex(normalize_translation_source(source)) + "\t一頁書中文字\n"
			"dialogue\tdialogue:0x0282:11:0\t"
			+ sha256_hex(normalize_translation_source("Second page"))
			+ "\t第二頁\n";

	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	std::istringstream input(table_text);
	assert(manager.load_table(input, error));
	assert(manager.translate_book_text(source) == "一頁書中文字");
	assert(manager.translate_book_text("*A page of book text~Second page")
			== "*一頁書中文字~第二頁");
	const std::string first_part = "A page ";
	const std::string last_part = " of book text";
	const std::string parts_table =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0282:fallback_10:0\t"
			+ sha256_hex(normalize_translation_source(first_part))
			+ "\t一頁\n"
			"dialogue\tdialogue:0x0282:fallback_11:0\t"
			+ sha256_hex(normalize_translation_source(last_part))
			+ "\t書中文字\n"
			"dialogue\tdialogue:0x0200:1:0\t"
			+ sha256_hex(normalize_translation_source(first_part))
			+ "\t其他內容\n";
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::istringstream parts_input(parts_table);
	assert(manager.load_table(parts_input, error));
	assert(manager.translate_book_text_parts(
			"A page Morgan of book text",
			{{first_part, "dialogue:0x0282:10:0", true},
			 {"Morgan", "", false},
			 {last_part, "dialogue:0x0282:11:0", true}})
			== "一頁Morgan書中文字");

	std::ifstream ucinternal_source("usecode/ucinternal.cc");
	const std::string ucinternal(
			(std::istreambuf_iterator<char>(ucinternal_source)),
			std::istreambuf_iterator<char>());
	assert(!ucinternal.empty());
	assert(ucinternal.find("translate_book_text_parts(") != std::string::npos);

	std::ifstream text_gump_source("gumps/Text_gump.cc");
	const std::string text_gump(
			(std::istreambuf_iterator<char>(text_gump_source)),
			std::istreambuf_iterator<char>());
	assert(!text_gump.empty());
	assert(text_gump.find("translate_book_text(") == std::string::npos);
}

void assert_book_text_matches_legacy_u6_bytes() {
	// UCXT decodes U6's legacy bytes as Latin-1 before the catalog hashes the
	// source as UTF-8.  0x92 is the apostrophe byte used by several book pages.
	const std::string source =
			std::string("THE ARCHER") + std::string(1, static_cast<char>(0x92))
			+ "S LAMENT ";
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0cdb:3369:0\t"
			"e5280910db908226c7cab27198a3b39ee733d422ba7d29297ac9e7d71a48df7b"
			"\t射箭者的哀歌 \n";

	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	std::istringstream input(table_text);
	assert(manager.load_table(input, error));
	assert(manager.translate_book_text(source) == "射箭者的哀歌 ");
}

void assert_book_text_matches_utf8_bytes_recorded_as_legacy_latin1() {
	// Some U6 book strings contain valid UTF-8 bytes in the usecode.  The
	// extractor still records those bytes as Latin-1 code points, so the table
	// contains the mojibake source hash while the runtime receives UTF-8.
	const std::string runtime_source =
			std::string("THE ARCHER") + std::string("\xe2\x80\x99", 3)
			+ "S LAMENT ";
	const std::string catalog_source =
			std::string("THE ARCHER")
			+ std::string("\xc3\xa2\xc2\x80\xc2\x99", 6)
			+ "S LAMENT ";
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0282:33ba:0\t"
			+ sha256_hex(normalize_translation_source(catalog_source))
			+ "\t弓箭手的哀歌 \n";

	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	std::istringstream input(table_text);
	assert(manager.load_table(input, error));
	assert(manager.translate_book_text(runtime_source) == "弓箭手的哀歌 ");
}

void assert_book_text_uses_table_in_dual_fallback_mode() {
	const std::string source = "A page of book text";
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0282:10:0\t"
			+ sha256_hex(normalize_translation_source(source)) + "\t一頁書中文字\n";

	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::DUAL);
	std::string error;
	std::istringstream input(table_text);
	assert(manager.load_table(input, error));
	// U6 has no alternate-language usecode in the mod patch. In this
	// fallback configuration DUAL uses the English usecode plus the Chinese
	// table, so book text must still go through the table lookup.
	assert(manager.table_only_enabled());
	assert(manager.translate_book_text(source) == "一頁書中文字");
}

void assert_alternate_usecode_english_fallbacks_still_use_the_table() {
	const std::string source = "An English fallback emitted by alternate usecode";
	const std::string table_text =
			"# u6-translation-v1\n"
			"# kind\tkey\tsource_sha256\tzh\n"
			"dialogue\tdialogue:0x0282:10:0\t"
			+ sha256_hex(normalize_translation_source(source))
			+ "\t替代 usecode 書頁\n";

	GameplayTranslationManager& manager = GameplayTranslationManager::get();
	manager.shutdown();
	manager.set_text_language(TextLanguage::CHINESE);
	std::string error;
	std::istringstream input(table_text);
	assert(manager.load_table(input, error));
	assert(manager.table_only_enabled());
	assert(manager.translate_by_source(GameplayTranslationKind::Dialogue, source)
			== "替代 usecode 書頁");
	// Chinese emitted by the alternate usecode has no English table source and
	// must pass through without a second translation.
	assert(manager.translate_by_source(GameplayTranslationKind::Dialogue,
				"已翻譯的替代 usecode 文字")
			== "已翻譯的替代 usecode 文字");

	std::ifstream translation_source("gameplay_translation.cc");
	const std::string translation(
			(std::istreambuf_iterator<char>(translation_source)),
			std::istreambuf_iterator<char>());
	assert(!translation.empty());
	assert(translation.find("legacy_alternate_usecode_active_")
			== std::string::npos);
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
	assert(ucinternal.find("translate_dialogue_fragments_if_available(")
			!= std::string::npos);
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
	assert(conversation.find("format_usecode_dialogue_quotes(")
			!= std::string::npos);
	assert(conversation.find("hit_area.intersect(gwin->get_game_rect())")
			!= std::string::npos);
	assert(conversation.find("TileRect hit_area(text_rect.x, text_rect.y, width + space_width, hit_h)")
			!= std::string::npos);
	assert(conversation.find("hit_rect.x += gwin->get_win()->get_start_x()")
			== std::string::npos);
	assert(conversation.find("hit_rect.y -= line_height")
			== std::string::npos);

	std::ifstream effects_source("effects.cc");
	const std::string effects(
			(std::istreambuf_iterator<char>(effects_source)),
			std::istreambuf_iterator<char>());
	assert(!effects.empty());
	assert(effects.find("translate_by_source(") != std::string::npos);
	assert(effects.find("format_usecode_dialogue_quotes") != std::string::npos);
	assert(effects.find("record_runtime_source(") != std::string::npos);
	assert(effects.find("make_dialogue_translation_key(0, \"0\", 0)")
			!= std::string::npos);

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

void assert_dialogue_at_markers_render_mode_specific_quotes() {
	const std::string marked =
			"The speaker says @Hello again.@ Then @goodbye.@";
	assert(format_usecode_dialogue_quotes(marked, TextLanguage::ENGLISH)
			== "The speaker says \"Hello again.\" Then \"goodbye.\"");
	assert(format_usecode_dialogue_quotes(marked, TextLanguage::CHINESE)
			== "The speaker says 「Hello again.」 Then 「goodbye.」");
	assert(format_usecode_dialogue_quotes("unfinished @speech", TextLanguage::ENGLISH)
			== "unfinished speech");
	assert(format_usecode_dialogue_quotes(
				"@你好@\n@Hello@", TextLanguage::DUAL)
			== "「你好」\n\"Hello\"");
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

void assert_deferred_text_blit_preserves_surface_origin() {
	std::ifstream deferred_text_source("imagewin/deferred_text.cc");
	const std::string deferred_text(
			(std::istreambuf_iterator<char>(deferred_text_source)),
			std::istreambuf_iterator<char>());
	assert(!deferred_text.empty());

	// draw_glyph writes to text_surface in the full inter-surface coordinate
	// space.  The source and destination of the compositor copy must therefore
	// have the same origin; applying ibuf's viewport offset only to the source
	// shifts text left/up relative to the already-scaled game image.
	assert(deferred_text.find(
				"int src_x = (x + guard_band) * scale;\n"
				"\tint src_y = (y + guard_band) * scale;\n"
				"\tint dst_x = src_x;\n"
				"\tint dst_y = src_y;")
			!= std::string::npos);
	assert(deferred_text.find(
				"int src_x = (x + ox + guard_band) * scale;")
			== std::string::npos);
}

void assert_conversation_choice_hit_rects_stay_in_game_coordinates() {
	std::ifstream conversation_source("usecode/conversation.cc");
	const std::string conversation(
			(std::istreambuf_iterator<char>(conversation_source)),
			std::istreambuf_iterator<char>());
	assert(!conversation.empty());
	// Get_click converts screen coordinates back to the game coordinate space;
	// both legacy and deferred text choices must use that same space.  Adding
	// Image_window::get_start_* again shifts the hit boxes and makes the final
	// (right-most) choices miss their visible text.
	assert(conversation.find("TileRect hit_rect = hit_area.intersect(gwin->get_game_rect())")
			!= std::string::npos);
	assert(conversation.find("hit_rect.x += gwin->get_win()->get_start_x()")
			== std::string::npos);
	assert(conversation.find("hit_rect.y += gwin->get_win()->get_start_y()")
			== std::string::npos);
}

void assert_conversation_choice_hit_rect_includes_visible_spacing() {
	std::ifstream conversation_source("usecode/conversation.cc");
	const std::string conversation(
			(std::istreambuf_iterator<char>(conversation_source)),
			std::istreambuf_iterator<char>());
	assert(!conversation.empty());
	// The painted choice background includes the gap after the text.  That
	// visible gap must be part of the clipped game-space hit box too, including
	// for the right-most option on a line.
	assert(conversation.find(
				"const TileRect hit_area(text_rect.x, text_rect.y, "
				"width + space_width, hit_h);")
			!= std::string::npos);
}

} // namespace

int main() {
	assert_usecode_fallback_policy();
	assert_table_only_active_machine_source_policy();
	assert_mod_usecode_is_loaded_for_all_language_modes();
	assert_safe_catalog_paths();
	assert_runtime_speaker_capture_source_policy();
	assert_u6_shared_voice_lookup_contract();
	assert_u6_nested_voice_speaker_restoration_contract();
	assert_placeholder_translation_has_no_dynamic_registry_dependency();
	assert_provenance_templates_use_source_stable_keys();
	assert_runtime_provenance_is_value_scoped();
	assert_gwenneth_static_anchor_template_is_translated();
	assert_gwenneth_hello_again_static_anchor_template_is_translated();
	assert_shamino_wait_here_template_is_translated();
	assert_structural_fragment_fallback_translates_missing_template();
	assert_inherited_bed_dialogue_fragments_translate();
	assert_inherited_bed_dialogue_bark_translates();

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
	assert_snaz_dynamic_dialogue_template_replaces_gendered_word();
	assert_snaz_runtime_template_hook_is_reachable();
	assert_generic_dialogue_placeholders_are_extracted_and_translated();
	assert_item_say_uses_runtime_provenance_for_overhead_text();
	assert_static_item_say_fragments_translate();
	assert_protected_professional_terms_use_source_global_rows();
	assert_iolo_dynamic_dialogue_template_replaces_runtime_name();
	assert_multi_placeholder_dialogue_template_replaces_runtime_values();
	assert_generic_addsv_dialogue_template_replaces_runtime_value();
	assert_dialogue_template_substitutes_placeholders_by_position();
	assert_dialogue_template_preserves_named_reordering_and_repetition();
	assert_dialogue_template_rejects_ambiguous_literal_boundaries();
	assert_checked_in_placeholder_rows_use_canonical_runtime_sources();
	assert_optional_release_table_loads();
	assert_numeric_dialogue_fragments_keep_the_runtime_value();
	assert_numeric_uc_add_provenance_is_preserved();
	assert_fragment_fallback_restores_split_speech_markers();
	assert_lord_british_untraced_dialogue_templates_replace_runtime_name();
	assert_choice_source_fallback_reuses_legacy_dialogue_rows();
	assert_item_source_fallback_reuses_raw_quantity_and_misc_rows();
	assert_book_text_uses_dialogue_source_fallback();
	assert_book_text_matches_legacy_u6_bytes();
	assert_book_text_matches_utf8_bytes_recorded_as_legacy_latin1();
	assert_book_text_uses_table_in_dual_fallback_mode();
	assert_alternate_usecode_english_fallbacks_still_use_the_table();
	assert_choice_source_fallback_reuses_textmsg_rows();
	assert_dupre_untraced_dialogue_template_replaces_runtime_name();
	assert_overhead_dialogue_translation_and_rendering_policy();
	assert_dialogue_at_markers_render_mode_specific_quotes();
	assert_deferred_text_preserves_cursor_layer();
	assert_deferred_text_blit_preserves_surface_origin();
	assert_conversation_choice_hit_rects_stay_in_game_coordinates();
	assert_conversation_choice_hit_rect_includes_visible_spacing();

	return 0;
}
