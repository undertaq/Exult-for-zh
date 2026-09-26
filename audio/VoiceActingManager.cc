/*
 *  Copyright (C) 2025  The Exult Team
 *
 *  This program is free software; you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation; either version 2 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program; if not, write to the Free Software
 *  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
 */

#ifdef HAVE_CONFIG_H
#	include <config.h>
#endif

#include "VoiceActingManager.h"

#include "Audio.h"
#include "actors.h"
#include "Configuration.h"
#include "bilingual_manager.h"
#include "gamewin.h"
#include "gameplay_translation.h"
#include "pent_include.h"
#include "utils.h"
#include "voice_composite_routing.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdint>
#include <ctime>
#include <iomanip>
#include <sstream>

using std::string;

// Static members.
bool         VoiceActingManager::use_packed = false;
std::string  VoiceActingManager::pak_path;
std::string  VoiceActingManager::idx_path;
std::vector<VoiceActingManager::VoicePackedEntry> VoiceActingManager::index;
std::ifstream VoiceActingManager::pak_stream;
static std::string packed_lang;  // language currently loaded in packed index

std::ofstream VoiceActingManager::log_file;
std::string   VoiceActingManager::session_id;
bool          VoiceActingManager::log_initialized = false;
bool          VoiceActingManager::voice_enabled   = true;
std::string   VoiceActingManager::voice_language  = "zh";

/*
 *  Load the packed voice archive index for the configured language.
 *  On success, sets use_packed = true.
 */
void VoiceActingManager::load_packed_index(const std::string& lang) {
	pak_path = get_system_path("<PATCH>/voice_acting/" + lang + "_voices.pak");
	idx_path = get_system_path("<PATCH>/voice_acting/" + lang + "_voices.idx");

	pout << "[VoiceActing] Trying packed archive: lang=" << lang
		 << " pak=" << pak_path << " idx=" << idx_path << std::endl;

	// Check both files exist.
	std::ifstream idx_file(idx_path, std::ios::binary);
	if (!idx_file.is_open()) {
		pout << "[VoiceActing] Index file not found: " << idx_path << std::endl;
		return;
	}
	std::ifstream pak_test(pak_path, std::ios::binary);
	if (!pak_test.is_open()) {
		pout << "[VoiceActing] Pak file not found: " << pak_path << std::endl;
		idx_file.close();
		return;
	}
	pak_stream.open(pak_path, std::ios::binary);
	if (!pak_stream.is_open()) {
		pout << "[VoiceActing] Failed to open pak stream: " << pak_path << std::endl;
		idx_file.close();
		return;
	}

	// Read entire .idx into memory.
	idx_file.seekg(0, std::ios::end);
	std::streamsize idx_size = idx_file.tellg();
	idx_file.seekg(0, std::ios::beg);
	std::vector<char> idx_buf(static_cast<size_t>(idx_size));
	if (!idx_file.read(idx_buf.data(), idx_size)) {
		idx_file.close();
		pak_stream.close();
		return;
	}
	idx_file.close();

	// Parse header: magic(4) + version(4) + count(4).
	const char* p = idx_buf.data();
	if (idx_size < 12 || std::memcmp(p, "VAIX", 4) != 0) {
		pak_stream.close();
		return;
	}
	uint32_t version;
	uint32_t count;
	std::memcpy(&version, p + 4, 4);
	std::memcpy(&count, p + 8, 4);
	// Note: little-endian format; on big-endian platforms, byte-swap.
	if (version != 1) {
		pak_stream.close();
		return;
	}

	// Parse entries.
	index.clear();
	index.reserve(count);
	size_t pos = 12;
	for (uint32_t i = 0; i < count; i++) {
		if (pos + 2 > static_cast<size_t>(idx_size)) {
			break;
		}
		uint16_t name_len;
		std::memcpy(&name_len, p + pos, 2);
		pos += 2;
		if (pos + name_len + 12 > static_cast<size_t>(idx_size)) {
			break;
		}
		std::string name(p + pos, name_len);
		pos += name_len;
		VoicePackedEntry entry;
		entry.name = std::move(name);
		std::memcpy(&entry.offset, p + pos, 8);
		std::memcpy(&entry.size, p + pos + 8, 4);
		pos += 12;
		index.push_back(std::move(entry));
	}

	use_packed = true;
}

void VoiceActingManager::init() {
	string s;
	config->value("config/audio/speech/voice/enabled", s, "yes");
	voice_enabled = (s != "no");
	config->set("config/audio/speech/voice/enabled", voice_enabled ? "yes" : "no", false);

	config->value("config/audio/speech/voice/language", voice_language, "");
	if (voice_language.empty()) {
		config->value("config/gameplay/language", voice_language, "zh");
	}
	config->set("config/audio/speech/voice/language", voice_language, false);
}

void VoiceActingManager::ensure_packed_loaded() {
	ensure_packed_loaded(get_voice_language());
}

void VoiceActingManager::ensure_packed_loaded(const std::string& lang) {
	if (use_packed && packed_lang == lang) {
		return;  // Already loaded for this language.
	}
	if (use_packed || pak_stream.is_open()) {
		// Language changed — close old index and reload.
		pak_stream.close();
		index.clear();
		use_packed = false;
		packed_lang.clear();
	}
	load_packed_index(lang);
	if (use_packed) {
		packed_lang = lang;
		pout << "[VoiceActing] Loaded packed archive: " << pak_path
			 << " (" << index.size() << " entries)" << std::endl;
	} else {
		pout << "[VoiceActing] No packed archive found, using separate files"
			 << std::endl;
	}
}

bool VoiceActingManager::is_voice_enabled() {
	return voice_enabled;
}

const std::string& VoiceActingManager::get_voice_language() {
	return voice_language;
}

/*
 *  Look up a voice file by name in the packed archive.
 *  Returns true and fills out_data if found.
 */
bool VoiceActingManager::find_in_pak(
		const std::string& name, std::vector<char>& out_data) {
	// Binary search on sorted index.
	auto it = std::lower_bound(index.begin(), index.end(), name,
		[](const VoicePackedEntry& e, const std::string& n) {
			return e.name < n;
		});
	if (it == index.end() || it->name != name) {
		return false;
	}

	// Seek and read from the open pak stream.
	pak_stream.seekg(static_cast<std::streamoff>(it->offset), std::ios::beg);
	if (!pak_stream) {
		return false;
	}
	out_data.resize(it->size);
	pak_stream.read(out_data.data(), static_cast<std::streamsize>(it->size));
	if (!pak_stream) {
		return false;
	}
	return true;
}

/*
 *  Play voice from a packed archive entry. Writes data to a temp file
 *  and plays it, then removes the temp file.
 */
bool VoiceActingManager::try_play_packed(
		const std::string& name, const std::vector<char>& data) {
	const std::string& lang = get_voice_language();
	std::string temp_path = get_system_path(
		"<PATCH>/voice_acting/" + lang + "/." + name + ".ogg");
	// Ensure the language directory exists.
	std::string dir = temp_path.substr(0, temp_path.find_last_of("/\\"));
	U7mkdir(dir.c_str(), 0755);

	std::ofstream out(temp_path, std::ios::binary);
	if (!out.is_open()) {
		return false;
	}
	out.write(data.data(), static_cast<std::streamsize>(data.size()));
	out.close();

	bool played = try_play(temp_path);
	std::remove(temp_path.c_str());
	return played;
}

/*
 *  Escape a string for CSV: double any quotes and wrap in quotes.
 */
static string csv_escape(const string& s) {
	string result = "\"";
	for (char c : s) {
		if (c == '"') {
			result += "\"\"";
		} else {
			result += c;
		}
	}
	result += "\"";
	return result;
}

/*
 *  Ensure the log file is open. Appends to existing file.
 *  Writes CSV header only if the file is new/empty.
 */
void VoiceActingManager::ensure_log_open() {
	if (log_initialized) {
		return;
	}
	log_initialized = true;

	// Generate a session ID from the current timestamp.
	auto        now = std::chrono::system_clock::now();
	std::time_t t   = std::chrono::system_clock::to_time_t(now);
	std::tm     tm  = *std::localtime(&t);

	std::ostringstream ss;
	ss << std::put_time(&tm, "%Y%m%d_%H%M%S");
	session_id = ss.str();

	// Open the log file in append mode.
	string log_path = get_system_path("<PATCH>/voice_acting/voice_acting_log.csv");
	bool   is_new   = !U7exists(log_path.c_str());

	log_file.open(log_path, std::ios::app);
	if (!log_file.is_open()) {
		return;
	}

	// Write header only if this is a new file.
	if (is_new) {
		log_file << "session,func_id,offset_key,segment,filename,"
		         << "source,status,speaker_npc,caller_npc,text"
		         << std::endl;
	}
}

/*
 *  Extract the source tag for a resolved voice file - "primary",
 *  "second_source", or "" for missing files. Used by the runtime log so we
 *  can tell at a glance which directory served each line.
 */
static string source_tag_for(const string& path) {
	if (path.empty()) {
		return "";
	}
	// Match on the directory name just above the filename.
	string normalized = path;
	for (char& c : normalized) {
		if (c == '\\') c = '/';
	}
	size_t last = normalized.find_last_of('/');
	if (last == string::npos) {
		return "";
	}
	size_t prev = normalized.find_last_of('/', last - 1);
	string parent = normalized.substr(
			prev == string::npos ? 0 : prev + 1, last - (prev + 1));
	if (parent == "second_source") {
		return "second_source";
	}
	if (parent == "voice_acting") {
		return "primary";
	}
	return parent;
}

/*
 *  Write an entry to the runtime log.
 */
void VoiceActingManager::log_entry(
		const string& filename, const string& path, int function_id,
		const string& offset_key, int segment,
		const char* text, const string& status,
		int speaker_npc, int caller_npc) {
	ensure_log_open();
	if (!log_file.is_open()) {
		return;
	}

	char func_hex[16];
	std::snprintf(func_hex, sizeof(func_hex), "0x%04x", function_id);

	string text_str = text ? text : "";
	string source   = source_tag_for(path);

	log_file << session_id << ","
	         << func_hex << ","
	         << offset_key << ","
	         << segment << ","
	         << filename << ","
	         << source << ","
	         << status << ","
	         << speaker_npc << ","
	         << caller_npc << ","
	         << csv_escape(text_str)
	         << std::endl;
}

/*
 *  Try to play a voice acting file at the given path. Returns true if successful.
 */
bool VoiceActingManager::try_play(const string& path) {
	Audio* audio = Audio::get_ptr();
	if (!audio || !audio->is_speech_enabled()) {
		return false;
	}

	if (!U7exists(path)) {
		return false;
	}

	return audio->play_voice_file(path);
}

/*
 *  Try to locate a voice file by base name (without extension), checking
 *  each source directory in order and preferring .ogg over .wav within each
 *  directory. This lets a primary distribution ship compressed .ogg files
 *  while still working if someone has loose .wav files handy, and lets a
 *  second-source generation run drop files into a sibling folder without
 *  overwriting the primary set.
 *
 *  The search directories include the configured language subdirectory,
 *  e.g. <PATCH>/voice_acting/zh/ or <PATCH>/voice_acting/en/.
 *
 *  `base_filename` is the filename without extension (e.g.
 *  "0401_af_151_254_0"). On hit, writes the resolved path into `out_path`
 *  and returns true.
 */
static bool find_voice_file(const string& base_filename, string& out_path) {
	const string& lang   = VoiceActingManager::get_voice_language();
	const string  dir1   = "<PATCH>/voice_acting/" + lang + "/";
	const string  dir2   = "<PATCH>/voice_acting/" + lang + "/second_source/";
	const char*   dirs[] = {dir1.c_str(), dir2.c_str()};
	static const char* const extensions[] = {".ogg", ".wav"};
	pout << "[VoiceActing] Language: " << lang << std::endl;
	for (const char* dir : dirs) {
		for (const char* ext : extensions) {
			string candidate
					= get_system_path(string(dir) + base_filename + ext);
			pout << "[VoiceActing] Checking: " << candidate;
			if (U7exists(candidate)) {
				pout << " - FOUND" << std::endl;
				out_path = candidate;
				return true;
			}
			pout << " - not found" << std::endl;
		}
	}
	// Fallback: try the other language
	const string& fallback_lang = (lang == "zh") ? "en" : "zh";
	const string  fallback_dir1 = "<PATCH>/voice_acting/" + fallback_lang + "/";
	const string  fallback_dir2 = "<PATCH>/voice_acting/" + fallback_lang + "/second_source/";
	const char*   fallback_dirs[] = {fallback_dir1.c_str(), fallback_dir2.c_str()};
	pout << "[VoiceActing] Not found in " << lang << ", falling back to "
		 << fallback_lang << std::endl;
	for (const char* dir : fallback_dirs) {
		for (const char* ext : extensions) {
			string candidate = get_system_path(string(dir) + base_filename + ext);
			pout << "[VoiceActing] Fallback checking: " << candidate;
			if (U7exists(candidate)) {
				pout << " - FOUND" << std::endl;
				out_path = candidate;
				return true;
			}
			pout << " - not found" << std::endl;
		}
	}
	return false;
}

/* Composite playback only consumes Ogg clips: Audio decodes every piece
 * before submitting one stitched sample, so a WAV fallback is not valid. */
static bool find_composite_voice_file(
		const string& language, const string& base_filename, string& out_path) {
	const string primary = "<PATCH>/voice_acting/" + language + "/";
	const string second = primary + "second_source/";
	for (const string& directory : {primary, second}) {
		const string candidate = get_system_path(directory + base_filename + ".ogg");
		if (U7exists(candidate)) {
			out_path = candidate;
			return true;
		}
	}
	return false;
}

static bool get_dynamic_voice_metadata(
		const std::vector<U6VoiceRouting::DynamicVoiceMetadata>*& metadata,
		string& error) {
	static string cached_path;
	static bool attempted = false;
	static bool loaded = false;
	static string cached_error;
	static std::vector<U6VoiceRouting::DynamicVoiceMetadata> cached_metadata;
	const string path = get_system_path(
			"<PATCH>/voice_acting/u6_dynamic_voice_templates.jsonl");
	if (attempted && cached_path == path) {
		metadata = &cached_metadata;
		error = cached_error;
		return loaded;
	}
	attempted = true;
	cached_path = path;
	cached_metadata.clear();
	std::ifstream input(path);
	if (!input.is_open()) {
		loaded = false;
		cached_error = "U6 dynamic voice manifest is unavailable";
		metadata = &cached_metadata;
		error = cached_error;
		return false;
	}
	loaded = U6VoiceRouting::parse_dynamic_voice_manifest(
			input, cached_metadata, cached_error);
	metadata = &cached_metadata;
	error = cached_error;
	return loaded;
}

/*
 *  Avatar can be male or female depending on the new-game selection.
 *  Return the selected gender suffix for Avatar-specific voice variants.
 */
static string get_avatar_voice_suffix() {
	Game_window* gwin = Game_window::get_instance();
	Actor*       ava  = gwin ? gwin->get_main_actor() : nullptr;
	const bool   female = ava && ava->get_type_flag(Actor::tf_sex);
	return female ? "_avatar_female" : "_avatar_male";
}

/*
 *  Play voice acting for conversation text.
 *  Tries NPC-specific file first, then falls back to generic:
 *    0. <funcID>_<offset_key>_<segment>_avatar_<male|female>  (Avatar only)
 *    1. <funcID>_<offset_key>_<segment>_npc<N>  (per-NPC voice)
 *    2. <funcID>_<offset_key>_<segment>         (generic fallback)
 *  Each base name is searched in <PATCH>/voice_acting/ then in
 *  <PATCH>/voice_acting/second_source/, and within each directory we prefer
 *  .ogg over .wav.
 */
bool VoiceActingManager::play_for_conversation(
		int function_id, const string& offset_key,
		int segment, const char* text,
		int speaker_npc, int caller_npc) {
	if (!voice_enabled) {
		return false;
	}

	// The Stone Guardian keeps its original in-game recording. Never route
	// its lines to the synthesized lookup, even if a stray file reappears.
	const int abs_speaker = speaker_npc < 0 ? -speaker_npc : speaker_npc;
	const int abs_caller  = caller_npc < 0 ? -caller_npc : caller_npc;
	if (abs_speaker == stone_guardian_npc || abs_caller == stone_guardian_npc) {
		ensure_log_open();
		log_entry("", "", function_id, offset_key, segment, text,
		          "original", speaker_npc, caller_npc);
		return false;
	}

	ensure_packed_loaded();

	char func_hex[16];
	std::snprintf(func_hex, sizeof(func_hex), "%04x", function_id);
	string base = string(func_hex) + "_" + offset_key + "_"
				  + std::to_string(segment);

	// Cross-language voice lookup: when the active usecode (determined by text
	// language) uses different function IDs / offset keys than the voice files in
	// the target voice directory, translate so we look up the right file.
	const std::string& cur_voice_lang = get_voice_language();
	TextLanguage	   text_lang	   = BilingualManager::get().get_text_language();
	bool map_needed = false;
	if (text_lang == TextLanguage::DUAL) {
		map_needed = BilingualManager::get().is_dual_available();
	} else if (cur_voice_lang == "en" && text_lang == TextLanguage::CHINESE) {
		map_needed = true;
	} else if (cur_voice_lang == "zh" && text_lang == TextLanguage::ENGLISH) {
		map_needed = true;
	}
	if (BilingualManager::get().is_bilingual_available() && map_needed) {
		TextLanguage from_lang = text_lang;    // CHINESE, ENGLISH or DUAL.
		int			target_func_id;
		std::string target_offset_key;
		int			target_segment;
		if (BilingualManager::get().map_offset(from_lang, function_id,
											   offset_key, segment,
											   cur_voice_lang,
											   target_func_id,
											   target_offset_key,
											   target_segment)) {
			char target_hex[16];
			std::snprintf(target_hex, sizeof(target_hex), "%04x", target_func_id);
			base = std::string(target_hex) + "_" + target_offset_key + "_"
				   + std::to_string(target_segment);
			const char* dir_label = (cur_voice_lang == "en") ? "zh→en" : "en→zh";
			pout << "[VoiceActing] Cross-language lookup: " << dir_label
				 << " (func " << std::hex << function_id << " → " << target_func_id
				 << std::dec << ", offset " << offset_key << " → " << target_offset_key
				 << ", segment " << segment << " → " << target_segment << ")"
				 << std::endl;
		} else {
			pout << "[VoiceActing] Cross-language lookup failed for func "
				 << std::hex << function_id << std::dec
				 << ", offset " << offset_key << ", segment " << segment << std::endl;
		}
	}

	// Try packed archive first.
	if (use_packed) {
		// Build candidate names in order: avatar → NPC → generic.
		std::vector<std::string> candidates;
		const int speaker_abs_pack = speaker_npc < 0 ? -speaker_npc : speaker_npc;
		const bool avatar_pack = speaker_abs_pack == 356
								|| (speaker_npc == 0 && caller_npc == 0);
		if (avatar_pack) {
			candidates.push_back(base + get_avatar_voice_suffix());
		}
		if (speaker_npc != 0) {
			char npc_suffix[16];
			std::snprintf(npc_suffix, sizeof(npc_suffix), "_npc%d", speaker_abs_pack);
			candidates.push_back(base + npc_suffix);
		}
		candidates.push_back(base);  // generic fallback

		for (const auto& candidate : candidates) {
			std::vector<char> pak_data;
			if (find_in_pak(candidate, pak_data)) {
				bool played = try_play_packed(candidate, pak_data);
				std::string status;
				if (played) {
					status = "played";
				} else {
					status = "error";
				}
				log_entry(candidate + ".ogg", pak_path, function_id,
						  offset_key, segment, text, status,
						  speaker_npc, caller_npc);
				return played;
			}
		}
		// All candidates failed in packed archive — fall through to file search.
	}

	// Try NPC-specific file first (using absolute NPC number).
	string filename;
	string path;
	bool   exists = false;
	const int speaker_abs = speaker_npc < 0 ? -speaker_npc : speaker_npc;
	const bool avatar_speaker = speaker_abs == 356
								|| (speaker_npc == 0 && caller_npc == 0);

	if (avatar_speaker) {
		const string avatar_suffix = get_avatar_voice_suffix();
		exists = find_voice_file(base + avatar_suffix, path);
		if (exists) {
			filename = path.substr(path.find_last_of("/\\") + 1);
		}
	}
	if (speaker_npc != 0) {
		char npc_suffix[16];
		std::snprintf(npc_suffix, sizeof(npc_suffix), "_npc%d",
					  speaker_abs);
		if (!exists) {
			exists = find_voice_file(base + npc_suffix, path);
			if (exists) {
				// Reflect the actual extension resolved (.ogg or .wav) in the
				// log, so auditing can distinguish compressed vs. raw builds.
				filename = path.substr(path.find_last_of("/\\") + 1);
			} else {
				filename = base + npc_suffix + ".wav";
			}
		}
	}

	// Fall back to generic file.
	if (!exists) {
		exists = find_voice_file(base, path);
		if (exists) {
			filename = path.substr(path.find_last_of("/\\") + 1);
		} else {
			filename = base + ".wav";
		}
	}

	bool played = false;
	if (exists) {
		played = try_play(path);
	}

	// Determine status for the log.
	string status;
	if (!exists) {
		status = "missing";
	} else if (played) {
		status = "played";
	} else {
		status = "error";
	}

	log_entry(filename, path, function_id, offset_key, segment, text, status,
			  speaker_npc, caller_npc);

	return played;
}

bool VoiceActingManager::is_u6_composite_voice_enabled() {
	return is_system_path_defined("<PATCH>")
			&& U7exists("<PATCH>/zh_translation.tsv");
}

bool VoiceActingManager::play_composite_for_conversation(
		const VoiceCompositePlan& plan, const std::string& offset_key,
		const char* text, const U6VoiceRouting::VoiceRouteContext& context) {
	if (!voice_enabled) return false;
	ensure_log_open();
	if (U6VoiceRouting::is_stone_guardian_speaker(context)) {
		log_entry("", "", plan.function_id, offset_key,
				static_cast<int>(plan.visible_segment), text, "original",
				context.speaker_npc, context.caller_npc);
		return false;
	}
	Audio* audio = Audio::get_ptr();
	if (!audio || !audio->is_speech_enabled()) {
		log_entry("composite_disabled", "", plan.function_id, offset_key,
				static_cast<int>(plan.visible_segment), text, "disabled",
				context.speaker_npc, context.caller_npc);
		return false;
	}

	VoiceCompositePlan resolved_plan = plan;
	if (resolved_plan.kind == VoiceCompositeKind::DynamicTemplate) {
		const std::vector<U6VoiceRouting::DynamicVoiceMetadata>* metadata = nullptr;
		string error;
		if (!get_dynamic_voice_metadata(metadata, error)
				|| !metadata
				|| !U6VoiceRouting::enrich_dynamic_voice_plan(
						resolved_plan, offset_key, *metadata, error)) {
			pout << "[VoiceActing] Dynamic composite unavailable: " << error << std::endl;
			log_entry("dynamic_manifest", "", plan.function_id, offset_key,
					static_cast<int>(plan.visible_segment), text, "missing",
					context.speaker_npc, context.caller_npc);
			return false;
		}
	}

	U6VoiceRouting::ClipCandidateGroups candidates;
	string error;
	if (!U6VoiceRouting::make_clip_candidates(
			resolved_plan, offset_key, context, candidates, error)) {
		pout << "[VoiceActing] Composite routing rejected: " << error << std::endl;
		log_entry("composite_unresolved", "", plan.function_id, offset_key,
				static_cast<int>(plan.visible_segment), text, "error",
				context.speaker_npc, context.caller_npc);
		return false;
	}

	std::vector<U6VoiceRouting::ResolvedVoiceClip> resolved;
	bool used_packed = false;
	std::size_t missing_group = 0;
	string selected_language;
	for (const string& language :
			U6VoiceRouting::voice_language_order(get_voice_language())) {
		ensure_packed_loaded(language);
		if (U6VoiceRouting::resolve_voice_clips(
				candidates,
				[](const string& name, std::vector<char>& data) {
					return use_packed && find_in_pak(name, data);
				},
				[&language](const string& name, string& path) {
					return find_composite_voice_file(language, name, path);
				},
				resolved, used_packed, &missing_group)) {
			selected_language = language;
			break;
		}
	}
	if (resolved.empty()) {
		const std::size_t failed = std::min(
				missing_group, candidates.empty() ? std::size_t(0) : candidates.size() - 1);
		const string filename = candidates.empty() || candidates[failed].empty()
				? "composite_fragment.ogg"
				: candidates[failed].front() + ".ogg";
		log_entry(filename, "", plan.function_id, offset_key,
				static_cast<int>(plan.visible_segment), text, "missing",
				context.speaker_npc, context.caller_npc);
		return false;
	}

	static std::uint64_t sequence_serial = 0;
	const std::uint64_t sequence_id = ++sequence_serial;
	std::vector<string> sequence_paths;
	std::vector<string> temporary_paths;
	sequence_paths.reserve(resolved.size());
	temporary_paths.reserve(resolved.size());
	for (std::size_t index = 0; index < resolved.size(); ++index) {
		const U6VoiceRouting::ResolvedVoiceClip& clip = resolved[index];
		if (!clip.packed) {
			sequence_paths.push_back(clip.path);
			continue;
		}
		const string relative = "<PATCH>/voice_acting/" + selected_language
				+ "/.voice-sequence-" + std::to_string(sequence_id) + "-"
				+ std::to_string(index) + ".ogg";
		const string path = get_system_path(relative);
		const std::size_t separator = path.find_last_of("/\\");
		if (separator != string::npos) {
			const string directory = path.substr(0, separator);
			U7mkdir(directory.c_str(), 0755);
		}
		std::ofstream output(path, std::ios::binary | std::ios::trunc);
		if (!output.is_open()) {
			for (const string& temporary : temporary_paths) std::remove(temporary.c_str());
			log_entry(clip.name + ".ogg", pak_path, plan.function_id,
					offset_key, static_cast<int>(plan.visible_segment), text,
					"error", context.speaker_npc, context.caller_npc);
			return false;
		}
		output.write(clip.packed_data.data(),
				static_cast<std::streamsize>(clip.packed_data.size()));
		output.close();
		if (!output) {
			std::remove(path.c_str());
			for (const string& temporary : temporary_paths) std::remove(temporary.c_str());
			log_entry(clip.name + ".ogg", pak_path, plan.function_id,
					offset_key, static_cast<int>(plan.visible_segment), text,
					"error", context.speaker_npc, context.caller_npc);
			return false;
		}
		temporary_paths.push_back(path);
		sequence_paths.push_back(path);
	}

	const bool played = audio->play_voice_sequence(sequence_paths, 80);
	for (const string& temporary : temporary_paths) std::remove(temporary.c_str());
	for (const U6VoiceRouting::ResolvedVoiceClip& clip : resolved) {
		log_entry(clip.name + ".ogg", clip.packed ? pak_path : clip.path,
				plan.function_id, offset_key,
				static_cast<int>(plan.visible_segment), text,
				played ? "played" : "error", context.speaker_npc, context.caller_npc);
	}
	return played;
}

/*
 *  Stop any currently playing voice acting line.
 */
void VoiceActingManager::stop() {
	Audio* audio = Audio::get_ptr();
	if (audio) {
		audio->stop_speech();
	}
}

/*
 *  Check if voice acting is currently playing.
 */
bool VoiceActingManager::is_playing() {
	Audio* audio = Audio::get_ptr();
	return audio && audio->is_speech_playing();
}
