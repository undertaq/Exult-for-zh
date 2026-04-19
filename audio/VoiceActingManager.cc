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
		         << "status,speaker_npc,caller_npc,text"
		         << std::endl;
	}
}

/*
 *  Write an entry to the runtime log.
 */
void VoiceActingManager::log_entry(
		const string& filename, int function_id,
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

	log_file << session_id << ","
	         << func_hex << ","
	         << offset_key << ","
	         << segment << ","
	         << filename << ","
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
 *  Try to locate a voice file by filename, checking the primary directory
 *  first and the secondary source directory as a fallback. Used so that a
 *  second-source generation run can drop files into a sibling folder without
 *  overwriting the primary set.
 *
 *  On hit, writes the resolved path into `out_path` and returns true.
 */
static bool find_voice_file(const string& filename, string& out_path) {
	static const char* const search_dirs[] = {
			"<PATCH>/voice_acting/",
			"<PATCH>/voice_acting/second_source/",
	};
	for (const char* dir : search_dirs) {
		string candidate = get_system_path(dir + filename);
		if (U7exists(candidate)) {
			out_path = candidate;
			return true;
		}
	}
	return false;
}

/*
 *  Play voice acting for conversation text.
 *  Tries NPC-specific file first, then falls back to generic:
 *    1. <funcID>_<offset_key>_<segment>_npc<N>.wav  (per-NPC voice)
 *    2. <funcID>_<offset_key>_<segment>.wav          (generic fallback)
 *  Each filename is searched first in <PATCH>/voice_acting/, then in
 *  <PATCH>/voice_acting/second_source/.
 */
bool VoiceActingManager::play_for_conversation(
		int function_id, const string& offset_key,
		int segment, const char* text,
		int speaker_npc, int caller_npc) {
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
		filename = base + npc_suffix + ".wav";
		exists   = find_voice_file(filename, path);
	}

	// Fall back to generic file.
	if (!exists) {
		filename = base + ".wav";
		exists   = find_voice_file(filename, path);
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

	log_entry(filename, function_id, offset_key, segment, text, status,
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
