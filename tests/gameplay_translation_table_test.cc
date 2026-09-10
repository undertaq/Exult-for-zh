#include "gameplay_translation_table.h"

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
			"# kind\tkey\tsource_sha256\t\n"
			"dialogue\tkey\t"
			"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\t\n");

	return 0;
}
