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

#include <string>

/*
 *  Manages AI-generated voice acting audio for dialog text.
 *
 *  Voice acting files are WAV files stored in <PATCH>/voice_acting/ named
 *  by their usecode origin: function ID, addsi offset key, and segment index.
 *
 *  Naming convention:
 *    <PATCH>/voice_acting/<funcID>_<offsets>_<segment>.wav  (conversation text)
 *    <PATCH>/voice_acting/t_<hash>.wav                     (say-text fallback)
 */
class VoiceActingManager {
public:
	// Play voice for conversation text, keyed by function_id + addsi offset key + segment.
	// offset_key is e.g. "af_151_254" built from the addsi offsets in the say() call.
	static bool play_for_conversation(
			int function_id, const std::string& offset_key,
			int segment, const char* text = nullptr);

	// Stop any currently playing voice line.
	static void stop();

	// Check if voice is currently playing.
	static bool is_playing();

private:
	// Try to play a voice file at the given path.
	static bool try_play(const std::string& path);
};

#endif
