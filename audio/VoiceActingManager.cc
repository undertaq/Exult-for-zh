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
#include "Configuration.h"
#include "pent_include.h"
#include "utils.h"

#include <chrono>
#include <cstdio>
#include <ctime>
#include <iomanip>
#include <sstream>

using std::string;

// Static members.
std::ofstream VoiceActingManager::log_file;
std::string   VoiceActingManager::session_id;
bool          VoiceActingManager::log_initialized = false;
bool          VoiceActingManager::voice_enabled   = true;
std::string   VoiceActingManager::voice_language  = "zh";

/*
 *  Read voice acting config: enabled flag and language.
 */
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

bool VoiceActingManager::is_voice_enabled() {
	return voice_enabled;
}

const std::string& VoiceActingManager::get_voice_language() {
	return voice_language;
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
	return false;
}

/*
 *  Play voice acting for conversation text.
 *  Tries NPC-specific file first, then falls back to generic:
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
	char func_hex[16];
	std::snprintf(func_hex, sizeof(func_hex), "%04x", function_id);
	string base = string(func_hex) + "_" + offset_key + "_"
				  + std::to_string(segment);

	// Try NPC-specific file first (using absolute NPC number).
	string filename;
	string path;
	bool   exists = false;

	if (speaker_npc != 0) {
		char npc_suffix[16];
		std::snprintf(npc_suffix, sizeof(npc_suffix), "_npc%d",
					  speaker_npc < 0 ? -speaker_npc : speaker_npc);
		exists = find_voice_file(base + npc_suffix, path);
		if (exists) {
			// Reflect the actual extension resolved (.ogg or .wav) in the
			// log, so auditing can distinguish compressed vs. raw builds.
			filename = path.substr(path.find_last_of("/\\") + 1);
		} else {
			filename = base + npc_suffix + ".wav";
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
