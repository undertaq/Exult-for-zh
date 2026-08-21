/*
 *  Copyright (C) 2001-2025  The Exult Team
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

#include "conversation.h"

#include "Face_stats.h"
#include "Gump_manager.h"
#include "ShortcutBar_gump.h"
#include "actors.h"
#include "bilingual_manager.h"
#include "data/exult_bg_flx.h"
#include "effects.h"
#include "exult.h"
#include "game.h"
#include "gamewin.h"
#include "gump_utils.h"
#include "miscinf.h"
#include "mouse.h"
#include "touchui.h"
#include "tqueue.h"
#include "useval.h"
#include <algorithm>
#include <cstring>
#include <iostream>

using std::size_t;
using std::string;

// TODO: show_face & show_avatar_choices seem to share code?
// TODO: show_avatar_choices shouldn't first convert to char**, probably

bool Conversation::noface = false;

/*
 *  Store information about an NPC's face and text on the screen during
 *  a conversation:
 */
class Npc_face_info {
public:
	ShapeID shape;
	int     face_num;    // NPC's face shape #.
	// int frame;
	bool text_pending;    // Text has been written, but user
	//   has not yet been prompted.
	bool     no_show_face;        // Whether this specific face should be hidden
	TileRect face_rect;           // Rectangle where face is shown.
	TileRect text_rect;           // Rectangle NPC statement is shown in.
	bool     large_face;          // Guardian, snake.
	bool     cjk_mode;            // Whole message contains CJK; every page
	                              // must render with CJK metrics.
	int      last_text_height;    // Height of last text painted.
	string   cur_text;            // Current text being shown.

	Npc_face_info(ShapeID& sid, int num)
		: shape(sid), face_num(num), text_pending(false), no_show_face(false), large_face(false), cjk_mode(false) {}
};

Conversation::~Conversation() {
	delete[] conv_choices;
}

void Conversation::clear_answers() {
	answers.clear();
}

void Conversation::add_answer(const char* str) {
	remove_answer(str);
	const string s(str);
	answers.push_back(s);
}

/*
 *  Add an answer to the list.
 */

void Conversation::add_answer(Usecode_value& val) {
	const char* str;
	const int   size = val.get_array_size();
	if (size) {    // An array?
		for (int i = 0; i < size; i++) {
			add_answer(val.get_elem(i));
		}
	} else if ((str = val.get_str_value()) != nullptr) {
		add_answer(str);
	}
}

void Conversation::remove_answer(const char* str) {
	auto it = std::find(answers.cbegin(), answers.cend(), str);

	if (it != answers.cend()) {
		answers.erase(it);
	}
}

/*
 *  Remove an answer from the list.
 */

void Conversation::remove_answer(Usecode_value& val) {
	const char* str;
	if (val.is_array()) {
		const int size = val.get_array_size();
		for (int i = 0; i < size; i++) {
			str = val.get_elem(i).get_str_value();
			if (str) {
				remove_answer(str);
			}
		}
	} else {
		str = val.get_str_value();
		remove_answer(str);
	}
}

/*
 *  Initialize face list.
 */

void Conversation::init_faces() {
	for (Npc_face_info*& finfo : face_info) {
		delete finfo;
		finfo = nullptr;
		if (!gwin->main_actor_dont_move()) {
			if (touchui != nullptr && !gumpman->gump_mode()) {
				touchui->showGameControls();
			}
			if (!Face_stats::Visible()) {
				Face_stats::ShowGump();
			}
			if (!ShortcutBar_gump::Visible()) {
				ShortcutBar_gump::ShowGump();
			}
		}
	}
	num_faces       = 0;
	last_face_shown = -1;
}

void Conversation::set_face_rect(Npc_face_info* info, Npc_face_info* prev, int screenw, int screenh) {
	const int base_text_height = sman->get_text_line_height(0);
	const int max_text_height = std::max(base_text_height, 22);
	// Figure starting y-coord.
	// Get character's portrait.
	Shape_frame* face   = info->shape.get_shapenum() >= 0 ? info->shape.get_shape() : nullptr;
	int          face_w = 32;
	int          face_h = 32;
	if (face) {
		face_w = face->get_width();
		face_h = face->get_height();
	}
	int startx;
	int extraw;
	if (face_w >= 119) {
		startx           = (screenw - face_w) / 2;
		extraw           = 0;
		info->large_face = true;
	} else {
		startx = 8;
		extraw = 4;
	}
	int starty;
	int extrah;
	if (face_h >= 142) {
		starty = (screenh - face_h) / 2;
		extrah = 0;
	} else if (prev) {
		starty = prev->text_rect.y + prev->last_text_height;
		if (starty < prev->face_rect.y + prev->face_rect.h) {
			starty = prev->face_rect.y + prev->face_rect.h;
		}
		starty += 10;
		if (starty + face_h > screenh - 1) {
			starty = screenh - face_h - 1;
		}
		extrah = 4;
	} else {
		starty = 5;
		extrah = 4;
	}
	info->face_rect      = gwin->clip_to_win(TileRect(startx, starty, face_w + extraw, face_h + extrah));
	const TileRect& fbox = info->face_rect;
	int lines_allowed = 5; // Allow up to 5 lines to prevent text overflowing bounding box and overlapping the next portrait
	if (info->large_face) {
		info->text_rect = gwin->clip_to_win(TileRect(fbox.x + 8, fbox.y + fbox.h + 8, fbox.w - 16, lines_allowed * max_text_height));
		info->last_text_height = info->text_rect.h;
	} else {
		info->text_rect = gwin->clip_to_win(
				TileRect(fbox.x + fbox.w + 8, fbox.y - 1, screenw - fbox.x - fbox.w - 16, lines_allowed * max_text_height));
		info->last_text_height = info->text_rect.h + 5; // Compensate for the -5 shift so layout doesn't move faces up
	}
}

/*
 *  Show a "face" on the screen.  Npc_text_rect is also set.
 *  If shape < 0, an empty space is shown.
 */

void Conversation::show_face(int shape, int frame, int slot) {
	ShapeID face_sid(shape, frame, SF_FACES_VGA);

	// Make sure mode is set right.
	Palette* pal = gwin->get_pal();    // Watch for weirdness (lightning).
	if (pal->get_brightness() >= 300) {
		pal->set(-1, 100);
	}

	// Get screen dims.
	const int      screenw = gwin->get_width();
	const int      screenh = gwin->get_height();
	Npc_face_info* info    = nullptr;
	// See if already on screen.
	for (size_t i = 0; i < face_info.size(); i++) {
		if (face_info[i] && face_info[i]->face_num == shape) {
			info            = face_info[i];
			last_face_shown = i;
			break;
		}
	}
	if (!info) {    // New one?
		if (static_cast<unsigned>(num_faces) == face_info.size()) {
			// None free?  Steal last one.
			remove_slot_face(face_info.size() - 1);
		}
		info = new Npc_face_info(face_sid, shape);
		if (noface) {
			info->no_show_face = true;
		}
		if (slot == -1) {    // Want next one?
			slot = num_faces;
		}
		// Get last one shown.
		Npc_face_info* prev = slot ? face_info[slot - 1] : nullptr;
		last_face_shown     = slot;
		if (!face_info[slot]) {
			num_faces++;    // We're adding one (not replacing).
		} else {
			delete face_info[slot];
		}
		face_info[slot] = info;
		set_face_rect(info, prev, screenw, screenh);
	}
	gwin->get_win()->set_clip(0, 0, screenw, screenh);
	paint_faces();    // Paint all faces.
	if (touchui != nullptr) {
		touchui->hideGameControls();
	}
	if (Face_stats::Visible()) {
		Face_stats::HideGump();
	}
	if (ShortcutBar_gump::Visible()) {
		ShortcutBar_gump::HideGump();
	}
	gwin->get_win()->clear_clip();
}

/*
 *  Change the frame of the face on given slot.
 */

void Conversation::change_face_frame(int frame, int slot) {
	// Make sure mode is set right.
	Palette* pal = gwin->get_pal();    // Watch for weirdness (lightning).
	if (pal->get_brightness() >= 300) {
		pal->set(-1, 100);
	}

	if (static_cast<unsigned>(slot) >= face_info.size() || !face_info[slot]) {
		return;    // Invalid slot.
	}

	last_face_shown     = slot;
	Npc_face_info* info = face_info[slot];
	// These are needed in case conversation is done.
	if (info->shape.get_shapenum() < 0 || frame > info->shape.get_num_frames()) {
		return;    // Invalid frame.
	}

	if (frame == info->shape.get_framenum()) {
		return;    // We are done here.
	}

	info->shape.set_frame(frame);
	// Get screen dims.
	const int      screenw = gwin->get_width();
	const int      screenh = gwin->get_height();
	Npc_face_info* prev    = slot ? face_info[slot - 1] : nullptr;
	set_face_rect(info, prev, screenw, screenh);

	gwin->get_win()->set_clip(0, 0, screenw, screenh);
	paint_faces();    // Paint all faces.
	gwin->get_win()->clear_clip();
}

/*
 *  Remove face from screen.
 */

void Conversation::remove_face(int shape) {
	for (size_t i = 0; i < face_info.size(); i++) {
		if (face_info[i] && face_info[i]->face_num == shape) {
			remove_slot_face(i);
			return;
		}
	}
}

/*
 *  Remove face from indicated slot (SI).
 */

void Conversation::remove_slot_face(int slot) {
	if (static_cast<unsigned>(slot) >= face_info.size() || !face_info[slot]) {
		return;    // Invalid.
	}
	Npc_face_info* info = face_info[slot];
	// These are needed in case conversation is done.
	if (info->large_face) {
		gwin->set_all_dirty();
	} else {
		gwin->add_dirty(info->face_rect);
		gwin->add_dirty(info->text_rect);
	}
	delete face_info[slot];
	face_info[slot] = nullptr;
	num_faces--;
	if (last_face_shown == slot) {    // Just in case.
		size_t j;
		for (j = face_info.size(); j > 0; j--) {
			if (face_info[j - 1]) {
				break;
			}
		}
		last_face_shown = j - 1;
		if (!gwin->main_actor_dont_move() && num_faces == 0) {
			if (touchui != nullptr) {
				touchui->showGameControls();
			}
			if (!Face_stats::Visible()) {
				Face_stats::ShowGump();
			}
			if (!ShortcutBar_gump::Visible()) {
				ShortcutBar_gump::ShowGump();
			}
		}
	}
}

/*
 *  Show what the NPC had to say.
 */

namespace {
// Runtime variable substitution for zh/dual dialogue. Merged "ZH\nEN"
// pairs carry placeholder tokens (<PLAYER_NAME>, <HONORIFIC>, <PRONOUN>,
// <GENDER_FLAG>, <VAR>) baked in by the dual-usecode generator. Only the
// runtime knows the avatar's name/gender, so tokens resolve here, using
// zh words in the zh half of the pair and en words in the en half.
std::string resolve_dialogue_tokens(std::string text) {
	Actor*      avatar = Game_window::get_instance()->get_main_actor();
	std::string pname;
	std::string honor_zh, honor_en, pronoun_zh, pronoun_en, flag_zh, flag_en;
	if (avatar) {
		pname = avatar->get_npc_name();
		if (avatar->get_type_flag(Actor::tf_sex)) {    // Female.
			honor_zh   = "\xe5\xa5\xb3\xe5\xa3\xab";    // 女士
			honor_en   = "madam";
			pronoun_zh = "\xe5\xa5\xb9";                // 她
			pronoun_en = "she";
			flag_zh    = "\xe5\xa5\xb3\xe6\x80\xa7";    // 女性
			flag_en    = "woman";
		} else {                                       // Male.
			honor_zh   = "\xe5\x85\x88\xe7\x94\x9f";    // 先生
			honor_en   = "sir";
			pronoun_zh = "\xe4\xbb\x96";                // 他
			pronoun_en = "he";
			flag_zh    = "\xe7\x94\xb7\xe6\x80\xa7";    // 男性
			flag_en    = "man";
		}
	}
	auto replace = [](std::string& s, const char* what, const std::string& with) {
		if (!*what) {
			return;
		}
		size_t at = 0;
		const size_t wlen = std::strlen(what);
		while ((at = s.find(what, at)) != std::string::npos) {
			s.replace(at, wlen, with);
		}
	};
	const size_t bnd     = text.find('\n');
	std::string  zhpart  = text.substr(0, bnd);
	std::string  enpart  = bnd == std::string::npos ? "" : text.substr(bnd);
	const char*  ztoks[] = { "<PLAYER_NAME>", "<HONORIFIC>", "<PRONOUN>",
		"<GENDER_FLAG>", "<VAR>" };
	const std::string zw[] = { pname, honor_zh, pronoun_zh, flag_zh, "" };
	const std::string ew[] = { pname, honor_en, pronoun_en, flag_en, "" };
	for (int i = 0; i < 5; i++) {
		replace(zhpart, ztoks[i], zw[i]);
		replace(enpart, ztoks[i], ew[i]);
	}
	std::string out = zhpart + enpart;
	// Collapse double spaces left by removed <VAR> tokens.
	size_t d = 0;
	while ((d = out.find("  ", d)) != std::string::npos) {
		out.erase(d, 1);
	}
	return out;
}
}    // namespace

void Conversation::show_npc_message(const char* msg) {
	if (last_face_shown == -1) {
		return;
	}
	// Strip leading/trailing '@' usecode string delimiters
	// (original USECODE uses @...@, e.g. pushs + call 0x08FF path).
	std::string clean;
	const char* display = msg;
	if (msg && msg[0] == '@') {
		clean = msg;
		if (clean.front() == '@')
			clean.erase(0, 1);
		if (!clean.empty() && clean.back() == '@')
			clean.pop_back();
		display = clean.c_str();
	}
	// Resolve <PLAYER_NAME>/<HONORIFIC>/... tokens baked into merged
	// zh/dual strings at generation time (runtime knows the avatar).
	std::string resolved;
	if (BilingualManager::get().is_zh_text()) {
		resolved = resolve_dialogue_tokens(display);
		display  = resolved.c_str();
	}
	// Voice playback is now triggered from say_string() in ucinternal.cc
	// using usecode function ID + segment index as the key.
	// Wait for any sprite effects to finish before showing text.
	Effects_manager* eman = gwin->get_effects();
	if (eman->has_active_sprites()) {
		// Pause the queue so only 'always' entries fire (no usecode).
		const uint32 now = SDL_GetTicks();
		gwin->get_tqueue()->pause(now);
		eman->set_sprites_always(true);
		while (eman->has_active_sprites()) {
			Delay();
			const uint32 ticks = SDL_GetTicks();
			Game::set_ticks(ticks);
			gwin->get_tqueue()->activate(ticks);
			gwin->paint();
			gwin->show();
		}
		eman->set_sprites_always(false);
		gwin->get_tqueue()->resume(SDL_GetTicks());
	}
	Npc_face_info* info = face_info[last_face_shown];
	int font = info->large_face ? 7 : 0;
	if (info->large_face) {
		int pal_idx = gwin->get_pal()->get_palette_index();
		if (gwin->get_pal()->get_brightness() < 60 || pal_idx == 2 || pal_idx == 7 || pal_idx == 11 || pal_idx == 12) {
			font = 0;
		}
	}
	info->cur_text      = "";

	bool has_chinese = false;
	for (const char* p = display; p && *p; p++) {
		if (static_cast<unsigned char>(*p) >= 0x80) {
			has_chinese = true;
			break;
		}
	}

	if (BilingualManager::get().get_text_language() == TextLanguage::DUAL) {
		const size_t dlen   = std::strlen(display);
		const size_t show   = std::min<size_t>(dlen, 96);
		std::cerr << "[DUALDBG] gwin_machine=" << (const void*)gwin->get_usecode()
				  << " active_machine=" << (const void*)BilingualManager::get().get_active_usecode()
				  << " en=" << (const void*)BilingualManager::get().get_usecode(TextLanguage::ENGLISH)
				  << " zh=" << (const void*)BilingualManager::get().get_usecode(TextLanguage::CHINESE)
				  << " dual=" << (const void*)BilingualManager::get().get_usecode(TextLanguage::DUAL)
				  << " len=" << dlen << " hex=";
		for (size_t i = 0; i < show; i++) {
			std::cerr << std::hex << (static_cast<unsigned char>(display[i]) & 0xff) << ' ';
		}
		std::cerr << std::dec << " utf8=" << std::string(display, show) << std::endl;
	}

	int pairs = 1;    // # of "ZH\nEN" pairs (1 if no embedded newline).
	if (display) {
		for (const char* p = display; *p; p++) {
			if (*p == '\n') {
				pairs++;
			}
		}
	}

	int line_height = sman->get_text_line_height(0);
	if (has_chinese) {
		line_height = std::max(line_height, 22);
	}

	if (info->large_face && has_chinese) {
		info->text_rect.x = 8;
		info->text_rect.w = gwin->get_width() - 16;

		int needed_h = line_height * 2;
		if (pairs > 1) {
			needed_h = std::min(pairs * 2, 6) * line_height;
		}
		if (info->text_rect.h < needed_h) {
			info->text_rect.h = needed_h;
			info->text_rect.y = gwin->get_height() - needed_h - 4;
		}
	}

	const TileRect& box = info->text_rect;
	//	gwin->paint(box);        // Clear what was there before.
	//	paint_faces();
	gwin->paint();
	int height;    // Break at punctuation.
	
	int render_box_h = 4 * line_height;
	if (pairs > 1 && has_chinese) {
		render_box_h = std::max(render_box_h, std::min(pairs * 2, 6) * line_height);
	}
	if (render_box_h > box.h) {
		render_box_h = box.h;
	}

	int shading = info->large_face ? -1 : gwin->get_text_bg();
	// Keep the CJK font mode that the WHOLE message needs on every page, so a
	// page-2 tail that is pure English doesn't switch to the (larger) pixel
	// font metrics.
	info->cjk_mode = has_chinese;
	/* NOTE:  The original centers text for Guardian, snake.    */
	while ((height = sman->paint_text_box(font, display, box.x, box.y, box.w, render_box_h, -1, true, info->large_face, shading, nullptr, has_chinese))
		   < 0) {
		// More to do?
		info->cur_text = string(display, -height);
		int  x;
		int  y;
		char c;
		gwin->paint();    // Paint scenery beneath
		Get_click(x, y, Mouse::hand, &c, false, this, true);
		gwin->paint();
		display += -height;
	}
	// All fit?  Store height painted.
	info->last_text_height = height;
	info->cur_text         = display;
	info->text_pending     = true;
	gwin->set_painted();
	//	gwin->show();
}

/*
 *  Is there NPC text that the user hasn't had a chance to read?
 */

bool Conversation::is_npc_text_pending() {
	for (const Npc_face_info* finfo : face_info) {
		if (finfo && finfo->text_pending) {
			return true;
		}
	}
	return false;
}

/*
 *  Clear text-pending flags.
 */

void Conversation::clear_text_pending() {
	for (Npc_face_info* finfo : face_info) {    // Clear 'pending' flags.
		if (finfo) {
			finfo->text_pending = false;
		}
	}
}

namespace {
// # of rendered rows for a choice: 1 + count of embedded '\n'.
int choice_line_count(const char* choice) {
	int lines = 1;
	for (const char* p = choice; p && *p; p++) {
		if (*p == '\n') {
			lines++;
		}
	}
	return lines;
}
// Display width: max over '\n'-split parts; the circle prefix is
// prepended to the first (Chinese) part only.
int choice_max_line_width(const char* choice, bool has_chinese) {
	const char* start = choice;
	int         part  = 0;
	int         maxw  = 0;
	for (const char* p = choice;; p++) {
		if (*p == '\n' || *p == '\0') {
			std::string piece;
			if (part == 0) {
				piece.push_back(static_cast<char>(127));
			}
			piece.append(start, p - start);
			maxw = std::max(maxw,
							Shape_manager::get_instance()->get_text_width(0, piece.c_str(), has_chinese));
			part++;
			if (*p == '\0') {
				break;
			}
			start = p + 1;
		}
	}
	return maxw;
}
}    // namespace

/*
 *  Show the Avatar's conversation choices (and face).
 */

void Conversation::show_avatar_choices(int num_choices, char** choices) {
	const bool  SI         = Game::get_game_type() == SERPENT_ISLE;
	Main_actor* main_actor = gwin->get_main_actor();
	// Get screen rectangle.
	const TileRect sbox = gwin->get_game_rect();
	int            x    = 0;
	int            y    = 0;    // Keep track of coords. in box.

	bool has_chinese = false;
	for (int i = 0; i < num_choices; i++) {
		if (choices[i]) {
			for (const char* p = choices[i]; *p; p++) {
				if (static_cast<unsigned char>(*p) >= 0x80) {
					has_chinese = true;
					break;
				}
			}
		}
		if (has_chinese) {
			break;
		}
	}
	struct AvatarChoicesFontAdjuster {
		AvatarChoicesFontAdjuster() {
			Font::is_painting_avatar_choices = true;
			Font::avatar_choices_font_size_adjust = 0;
		}
		~AvatarChoicesFontAdjuster() {
			Font::is_painting_avatar_choices = false;
			Font::avatar_choices_font_size_adjust = 0;
		}
	} font_adjuster;

	// Get main actor's portrait, checking for Petra flag.
	int shape = Shapeinfo_lookup::GetFaceReplacement(0);
	int frame = 0;

	if (shape == 0) {
		Skin_data* skin = Shapeinfo_lookup::GetSkinInfoSafe(main_actor);
		if (main_actor->get_flag(Obj_flags::tattooed)) {
			shape = skin->alter_face_shape;
			frame = skin->alter_face_frame;
		} else {
			shape = skin->face_shape;
			frame = skin->face_frame;
		}
	}

	const ShapeID face_sid(shape, frame, SF_FACES_VGA);
	Shape_frame*  face = face_sid.get_shape();
	size_t        empty;    // Find face prev. to 1st empty slot.
	for (empty = 0; empty < face_info.size(); empty++) {
		if (!face_info[empty]) {
			break;
		}
	}
	// Get last one shown.
	Npc_face_info* prev = empty ? face_info[empty - 1] : nullptr;

	int line_height = 0;
	int space_width = 0;
	int fx = 0, fy = 0;
	int tbox_x_offset = 8, tbox_w_offset = 16;
	int needed_h = 0;

	for (int retry = 0; retry < 4; ++retry) {
		Font::avatar_choices_font_size_adjust = retry;

		// paint_text shifts each glyph down by 'highest', so a row occupies
		// [y, y + highest + lowest] – not just get_text_height().
		// Use the actual rendered span as the base for row spacing in all cases.
		std::shared_ptr<Font> font0       = sman->get_font(0);
		line_height = sman->get_text_line_height(0);    // default fallback
		if (font0) {
			const int rendered_h = font0->get_rendered_line_height();
			// +2: 1px gap + 1px for descender shadow pixel
			line_height = rendered_h + font0->get_ver_lead() + 2;
		}
		if (has_chinese) {
			// Query the actual rendered height for CJK glyphs to dynamically support font size changes.
			int cjk_h = font0 ? font0->get_rendered_line_height_for("\x80") : 15;
			const int cjk_min = (std::max(22, cjk_h + 4) - retry) + (font0 ? font0->get_ver_lead() : 0);
			if (line_height < cjk_min) {
				line_height = cjk_min;
			}
		}
		space_width = sman->get_text_width(0, " ", has_chinese);

		fx = prev ? prev->face_rect.x + prev->face_rect.w + 4 : 16;
		if (has_chinese) {
			// Move Avatar face to the left edge to maximize horizontal text space
			fx = 16;
		}
		
		int min_fy;
		if (SI) {
			if (static_cast<unsigned>(num_faces) == face_info.size()) {
				// Remove face #1 if still there.
				remove_slot_face(face_info.size() - 1);
			}
			min_fy = sbox.h - 2 - face->get_height();
			fx = 8;
		} else if (!prev) {
			min_fy = sbox.h - face->get_height() - 3 * line_height;
		} else {
			min_fy = prev->text_rect.y + prev->last_text_height;
			if (min_fy < prev->face_rect.y + prev->face_rect.h) {
				min_fy = prev->face_rect.y + prev->face_rect.h;
			}
			min_fy += 10;
		}
		fy = min_fy;

		tbox_x_offset = 8;
		tbox_w_offset = 16;

		auto calc_height = [&]() {
			int test_tbox_w = sbox.w - fx - face->get_width() - tbox_w_offset;
			int temp_x = 0;
			int temp_y = 0;
			int temp_line_step = has_chinese ? line_height : line_height - 1;
			int temp_bottom = 0;
			for (int i = 0; i < num_choices; i++) {
				const bool multiline = strchr(choices[i], '\n') != nullptr;
				const int  nlines    = choice_line_count(choices[i]);
				char       text[512];
				text[0] = 127;    // A circle.
				strcpy(&text[1], choices[i]);
				const int width = multiline ? choice_max_line_width(choices[i], has_chinese)
				                            : sman->get_text_width(0, text, has_chinese);
				if (!multiline && temp_x > 0 && temp_x + width >= test_tbox_w) {
					temp_x = 0;
					temp_y += temp_line_step;
				}
				temp_bottom = std::max(temp_bottom,
				                       temp_y + (multiline ? nlines : 1) * temp_line_step);
				if (multiline) {
					temp_y = temp_bottom;
					temp_x = 0;
				} else {
					temp_x += width + space_width;
				}
			}
			return temp_bottom;
		};

		int total_choices_height = calc_height();
		needed_h = std::max(face->get_height(), 4 + total_choices_height);

		// If choices exceed screen height and we have horizontal room to spare, widen the layout
		if (fy + needed_h > sbox.h && fx > 8) {
			fx = 8;
			tbox_x_offset = 4;
			tbox_w_offset = 8;
			// Recalculate with the wider layout
			total_choices_height = calc_height();
			needed_h = std::max(face->get_height(), 4 + total_choices_height);
		}

		// If it still exceeds the bottom of the screen, push them up
		if (fy + needed_h > sbox.h) {
			fy = sbox.h - needed_h;
			if (fy < 0) fy = 0;
		}

		// Check if shifting up caused overlap with previous portrait/text.
		// If it didn't overlap (or if we don't care because no prev), layout is good! Break early.
		bool overlap = (prev && fy < min_fy && !SI);
		if (!overlap && fy + needed_h <= sbox.h) {
			break;
		}
	}



	TileRect mbox(fx, fy, face->get_width(), face->get_height());
	mbox        = mbox.intersect(sbox);
	avatar_face = mbox;    // Repaint entire width.
	// Set to where to draw sentences.
	TileRect tbox(mbox.x + mbox.w + tbox_x_offset, mbox.y - 1, sbox.w - mbox.x - mbox.w - tbox_w_offset,
				  5 * line_height);    // Try 5 lines.
	tbox = tbox.intersect(sbox);
	// Draw portrait.
	sman->paint_shape(mbox.x + face->get_xleft(), mbox.y + face->get_yabove(), face);
	
	delete[] conv_choices;    // Set up new list of choices.
	conv_choices      = new TileRect[num_choices + 1];
	const int text_bg = gwin->get_text_bg();
	// For CJK text the pixel-font formula gives a negative offset; just align to row top.
	const int bg_offset = has_chinese ? 0 : (sman->get_text_height(0) - line_height) / 2;
	// First pass: determine positions and draw all backgrounds.
	for (int i = 0; i < num_choices; i++) {
		const bool multiline = strchr(choices[i], '\n') != nullptr;
		const int  nlines    = choice_line_count(choices[i]);
		char       text[512];
		text[0] = 127;    // A circle.
		strcpy(&text[1], choices[i]);
		const int width = multiline ? choice_max_line_width(choices[i], has_chinese)
		                            : sman->get_text_width(0, text, has_chinese);
		if (!multiline && x > 0 && x + width >= tbox.w) {
			x = 0;
			y += has_chinese ? line_height : line_height - 1;
		}
		int hit_h = line_height;
		std::shared_ptr<Font> font0 = sman->get_font(0);
		if (has_chinese && font0 && !multiline) {
			int baseline    = font0->get_text_baseline_for("\x80");
			int text_h      = font0->get_text_height_for("\x80");
			int text_bottom = baseline + text_h / 4 + 2;
			hit_h = std::max(line_height, text_bottom);
		} else if (multiline) {
			hit_h = nlines * line_height;
		}
		conv_choices[i] = TileRect(tbox.x + x, tbox.y + y, width, hit_h);
		conv_choices[i] = conv_choices[i].intersect(sbox);
		avatar_face     = avatar_face.add(conv_choices[i]);
		if (text_bg >= 0) {
			gwin->get_win()->fill_translucent8(
					0, width + space_width, hit_h, tbox.x + x, tbox.y + y + bg_offset, sman->get_xform(text_bg));
		}
		if (multiline) {
			y += nlines * (has_chinese ? line_height : line_height - 1);
			x = 0;
		} else {
			x += width + space_width;
		}
	}
	// Second pass: draw all text on top of backgrounds.
	for (int i = 0; i < num_choices; i++) {
		const char* part  = choices[i];
		int         pno   = 0;
		int         py    = 0;
		std::string piece;
		for (;;) {
			const char* nl = strchr(part, '\n');
			piece.clear();
			if (pno == 0) {
				piece.push_back(static_cast<char>(127));    // A circle.
			}
			piece.append(part, nl ? static_cast<int>(nl - part)
			                      : static_cast<int>(strlen(part)));
			sman->paint_text(0, piece.c_str(), conv_choices[i].x,
			                 conv_choices[i].y + py, has_chinese);
			if (!nl) {
				break;
			}
			pno++;
			py += has_chinese ? line_height : line_height - 1;
			part = nl + 1;
		}
	}
	avatar_face.enlarge((3 * c_tilesize) / 4);    // Encloses entire area.
	avatar_face = avatar_face.intersect(sbox);
	// Terminate the list.
	conv_choices[num_choices] = TileRect(0, 0, 0, 0);
	clear_text_pending();
	gwin->set_painted();
}

void Conversation::show_avatar_choices() {
	char** result;
	size_t i;    // Blame MSVC

	result = new char*[answers.size()];
	for (i = 0; i < answers.size(); i++) {
		result[i] = new char[answers[i].size() + 1];
		strcpy(result[i], answers[i].c_str());
	}
	show_avatar_choices(answers.size(), result);
	for (i = 0; i < answers.size(); i++) {
		delete[] result[i];
	}
	delete[] result;
}

void Conversation::clear_avatar_choices() {
	//	gwin->paint(avatar_face);    // Paint over face and answers.
	gwin->add_dirty(avatar_face);
	avatar_face.w = 0;
}

/*
 *  User clicked during a conversation.
 *
 *  Output: Index (0-n) of choice, or -1 if not on a choice.
 */

int Conversation::conversation_choice(int x, int y) {
	int i;
	for (i = 0; conv_choices[i].w != 0 && !conv_choices[i].has_point(x, y); i++)
		;
	if (conv_choices[i].w != 0) {    // Found one?
		return i;
	} else {
		return -1;
	}
}

/*
 *  Repaint everything.
 */

void Conversation::paint() {
	paint_faces(true);
	if (avatar_face.w) {    // Choices?
		show_avatar_choices();
	}
}

/*
 *  Repaint the faces.   Assumes clip has already been set to screen.
 */

void Conversation::paint_faces(
		bool text    // Show text too.
) {
	if (!num_faces) {
		return;
	}
	for (const Npc_face_info* finfo : face_info) {
		if (!finfo) {
			continue;
		}
		Shape_frame* face = finfo->face_num >= 0 ? finfo->shape.get_shape() : nullptr;

		if (face && !finfo->no_show_face) {
			const int face_xleft  = face->get_xleft();
			const int face_yabove = face->get_yabove();
			const int fx          = finfo->face_rect.x + face_xleft;
			const int fy          = finfo->face_rect.y + face_yabove;
			if (finfo->large_face) {
				// Guardian, serpents: fill whole screen with the
				// background pixel.
				const unsigned char px      = face->get_topleft_pix();
				const int           xfstart = 0xff - sman->get_xforms_cnt();
				const int           fw      = finfo->face_rect.w;
				const int           fh      = finfo->face_rect.h;
				Image_window8*      win     = gwin->get_win();
				const int           gw      = win->get_game_width();
				const int           gh      = win->get_game_height();
				// Fill only if (a) not transparent, (b) is a translucent
				// color and (c) the face is not covering the entire screen.
				if (px >= xfstart && px <= 0xfe && (gw > fw || gh > fh)) {
					const Xform_palette& xform = sman->get_xform(px - xfstart);
					const int            gx    = win->get_start_x();
					const int            gy    = win->get_start_y();
					// Another option: 4 fills outside the face area.
					win->fill_translucent8(0, gw, gh, gx, gy, xform);
				}
			}
			// Use translucency.
			sman->paint_shape(fx, fy, face, true);
		}
		if (text) {    // Show text too?
			const TileRect& box = finfo->text_rect;
			int font = finfo->large_face ? 7 : 0;
			if (finfo->large_face) {
				int pal_idx = gwin->get_pal()->get_palette_index();
				if (gwin->get_pal()->get_brightness() < 60 || pal_idx == 2 || pal_idx == 7 || pal_idx == 11 || pal_idx == 12) {
					font = 0;
				}
			}
			int shading = finfo->large_face ? -1 : gwin->get_text_bg();
			sman->paint_text_box(
					font, finfo->cur_text.c_str(), box.x, box.y, box.w, box.h, -1, true, finfo->large_face, shading, nullptr,
					finfo->cjk_mode);
		}
	}
}

/*
 *  return nr. of conversation option 'str'. -1 if not found
 */

int Conversation::locate_answer(const char* str) {
	int num = 0;
	for (auto& answer : answers) {
		if (answer == str) {
			return num;
		}
		num++;
	}

	return -1;
}

void Conversation::push_answers() {
	answer_stack.push_front(answers);
	answers.clear();
}

void Conversation::pop_answers() {
	answers = answer_stack.front();
	answer_stack.pop_front();
	gwin->paint();    // Really just need to figure tbox.
}
