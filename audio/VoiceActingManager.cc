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

#include <cstdint>
#include <cstdio>
#include <iostream>

using std::cerr;
using std::endl;
using std::string;

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

	// Don't auto-stop previous voice here. For conversation text,
	// click_to_continue() handles stopping when the player advances.
	// For say-text, lines are short enough that overlap is acceptable.
	return audio->play_voice_file(path);
}

/*
 *  Play voice acting for conversation text.
 *  Filename: <funcID>_<offset_key>_<segment>.wav
 *  e.g., 0401_af_151_254_0.wav
 */
bool VoiceActingManager::play_for_conversation(
		int function_id, const string& offset_key,
		int segment, const char* text) {
	char func_hex[16];
	std::snprintf(func_hex, sizeof(func_hex), "%04x", function_id);
	string filename = string(func_hex) + "_" + offset_key + "_"
					  + std::to_string(segment) + ".wav";
	string path = get_system_path("<PATCH>/voice_acting/" + filename);

	// Log with the displayed text for verification.
	string text_preview;
	if (text) {
		text_preview = string(text, std::min(strlen(text), size_t(50)));
		if (strlen(text) > 50) text_preview += "..";
	}
	cerr << "VoiceActing: file=" << filename
	     << " text=\"" << text_preview << "\"" << endl;

	return try_play(path);
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

