#include "gameplay_translation_table.h"
#include "gameplay_translation.h"

#include <cassert>
#include <sstream>
#include <string>

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

} // namespace

int main() {
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

	return 0;
}
