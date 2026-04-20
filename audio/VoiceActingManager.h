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

#ifndef VOICEACTINGMANAGER_H
#define VOICEACTINGMANAGER_H

#include <fstream>
#include <string>

/*
 *  Manages AI-generated voice acting audio for dialog text.
 *
 *  Voice acting files are WAV files stored in <PATCH>/voice_acting/ named
 *  by their usecode origin: function ID, addsi offset key, and segment index.
 *
 *  Naming convention:
 *    <PATCH>/voice_acting/<funcID>_<offsets>_<segment>.wav  (conversation text)
 *
 *  Also maintains a runtime log at <PATCH>/voice_acting/voice_acting_log.csv
 *  that records every conversation line encountered for auditing.
 */
class VoiceActingManager {
public:
	// Play voice for conversation text, keyed by function_id + addsi offset key + segment.
	// speaker_npc is the NPC currently speaking (from show_npc_face tracking).
	// caller_npc is the NPC that originated the conversation (from call stack).
	static bool play_for_conversation(
			int function_id, const std::string& offset_key,
			int segment, const char* text = nullptr,
			int speaker_npc = -1, int caller_npc = -1);

	// Stop any currently playing voice line.
	static void stop();

	// Check if voice is currently playing.
	static bool is_playing();

private:
	// Try to play a voice file at the given path.
	static bool try_play(const std::string& path);

	// Write an entry to the runtime log. `path` is the resolved full path
	// on disk (used to infer the source directory for auditing); pass an
	// empty string when the file was not found.
	static void log_entry(
			const std::string& filename, const std::string& path,
			int function_id,
			const std::string& offset_key, int segment,
			const char* text, const std::string& status,
			int speaker_npc, int caller_npc);

	// Ensure the log file is open and has a header if needed.
	static void ensure_log_open();

	static std::ofstream log_file;
	static std::string   session_id;
	static bool          log_initialized;
};

#endif
