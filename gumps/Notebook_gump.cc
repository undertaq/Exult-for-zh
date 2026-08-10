/*
Copyright (C) 2000-2025 The Exult Team

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
*/

#ifdef HAVE_CONFIG_H
#	include <config.h>
#endif

#include "Notebook_gump.h"

#include "Configuration.h"
#include "Gump_button.h"
#include "Gump_manager.h"
#include "U7file.h"
#include "actors.h"
#include "Audio.h"
#include "cheat.h"
#include "effects.h"
#include "exult.h"
#include "exult_flx.h"
#include "fnames.h"
#include "game.h"
#include "gameclk.h"
#include "gamewin.h"
#include "items.h"
#include "msgfile.h"
#include "touchui.h"

using std::cout;
using std::endl;
using std::ifstream;
using std::ofstream;
using std::ostream;
using std::string;
using std::vector;
#include <sstream>

class Strings : public GumpStrings {
public:
	static auto Day() {
		return get_text_msg(0x658 - msg_file_start);
	}

	static auto am() {
		return get_text_msg(0x659 - msg_file_start);
	}

	static auto pm() {
		return get_text_msg(0x65A - msg_file_start);
	}
};

vector<One_note*>    Notebook_gump::notes;
bool                 Notebook_gump::initialized           = false;    // Set when read in.
bool                 Notebook_gump::initialized_auto_text = false;
Notebook_gump*       Notebook_gump::instance              = nullptr;
vector<Notebook_top> Notebook_gump::page_info;
vector<string>       Notebook_gump::auto_text;
NoteCategory         Notebook_gump::active_filter         = NoteCategory::GENERAL;
string               Notebook_gump::search_query          = "";
bool                 Notebook_gump::show_completed        = true;
int                  Notebook_gump::unread_count          = 0;
bool                 Notebook_gump::dirty                 = false;
vector<int>          Notebook_gump::visible;

/*
 *  Defines in 'gumps.vga':
 */
#define LEFTPAGE  (GAME_BG ? 44 : 39)    // At top-left of left page.
#define RIGHTPAGE (GAME_BG ? 45 : 40)    // At top-right of right page.

const int font  = 4;    // Small black.
const int vlead = 1;    // Extra inter-line spacing.
#if defined(SDL_PLATFORM_IOS) || defined(ANDROID)
const int pagey = 7;    // Top of text area of page.
#else
const int pagey = 10;    // Top of text area of page.
#endif
const int lpagex = 36, rpagex = 174;    // X-coord. of text area of page.

class One_note {
	int          day = 0, hour = 0, minute = 0;    // Game time when note was written.
	int          tx = 0, ty = 0;                   // Tile coord. where written.
	string       text;                             // Text, 0-delimited.
	int          gflag = -1;                       // >=0 if created automatically when
	//   the global flag was set.
	bool         is_new = false;                   // Newly created at cur. time/place.
	NoteCategory category = NoteCategory::GENERAL; // Category tag.
	bool         is_completed = false;             // Quest status.
	bool         is_unread = false;                // Unread status.
	int          dest_x = -1, dest_y = -1;    // Curated map destination; <0 = none.
	string       npcs;                        // Related NPC names, comma separated.
public:
	friend class Notebook_gump;
	One_note() = default;

	void set_time(int d, int h, int m) {
		day    = d;
		hour   = h;
		minute = m;
	}

	void set_loc(int x, int y) {
		tx = x;
		ty = y;
	}

	void set_text(const string& txt) {
		text = txt;
	}

	void set_gflag(int gf) {
		gflag = gf;
	}

	void set_category(NoteCategory cat) {
		category = cat;
	}

	void set_completed(bool done) {
		is_completed = done;
	}

	void set_unread(bool unread) {
		is_unread = unread;
	}

	void set_dest(int x, int y) {
		dest_x = x;
		dest_y = y;
	}

	bool get_dest(int& x, int& y) const {
		if (dest_x < 0 || dest_y < 0) {
			return false;
		}
		x = dest_x;
		y = dest_y;
		return true;
	}

	void set_npcs(const string& n) {
		npcs = n;
	}

	const string& get_npcs() const {
		return npcs;
	}

	NoteCategory get_category() const {
		return category;
	}

	bool get_completed() const {
		return is_completed;
	}

	bool get_unread() const {
		return is_unread;
	}

	void set(int d, int h, int m, int x, int y, const string& txt, int gf = -1, bool isnew = false, NoteCategory cat = NoteCategory::GENERAL, bool done = false, bool unread = false) {
		set_time(d, h, m);
		set_loc(x, y);
		set_text(txt);
		gflag        = gf;
		is_new       = isnew;
		category     = cat;
		is_completed = done;
		is_unread    = unread;
	}

	One_note(int d, int h, int m, int x, int y, const string& txt = "", int gf = -1, bool isnew = false, NoteCategory cat = NoteCategory::GENERAL, bool done = false, bool unread = false) {
		set(d, h, m, x, y, txt, gf, isnew, cat, done, unread);
	}

	// Insert text.
	void insert(int chr, int offset) {
		text.insert(offset, 1, chr);
	}

	// Delete text.
	bool del(int offset) {
		if (offset < 0 || static_cast<size_t>(offset) >= text.length()) {
			return false;
		} else {
			text.erase(offset, 1);
			return true;
		}
	}

	void write(ostream& out);    // Write out as XML.
	void add_text_with_line_breaks(const std::string& text);
};

int Notebook_gump::get_unread_count() {
	int count = 0;
	for (const auto* note : notes) {
		if (note && note->get_unread()) {
			count++;
		}
	}
	unread_count = count;
	return count;
}

bool Notebook_gump::note_matches_filter(const One_note* note) {
	if (!note) {
		return false;
	}
	if (!show_completed && note->get_completed()) {
		return false;
	}
	if (active_filter != NoteCategory::GENERAL) {
		if (note->get_category() != active_filter) {
			return false;
		}
	}
	if (!search_query.empty()) {
		string text = note->text;
		string query = search_query;
		for (char& c : text) {
			c = static_cast<char>(tolower(static_cast<unsigned char>(c)));
		}
		for (char& c : query) {
			c = static_cast<char>(tolower(static_cast<unsigned char>(c)));
		}
		if (text.find(query) == string::npos) {
			return false;
		}
	}
	return true;
}

/*
 *  Rebuild the "visible" note list after filter/search/status changes.
 *  Visibility decides which notes take part in page layout; the master
 *  notes[] list is never reordered.
 */
void Notebook_gump::rebuild_visible() {
	visible.clear();
	for (int i = 0; i < static_cast<int>(notes.size()); ++i) {
		if (note_matches_filter(notes[i])) {
			visible.push_back(i);
		}
	}
}

/*
 *  Locations of all active (not completed) quest notes, newest first,
 *  capped at 8. A note's curated [map=x,y] destination wins over the
 *  tile where the note was written. Reads the notebook from disk if it
 *  was never opened, so the map works before the first journal visit.
 */
std::vector<Quest_marker> Notebook_gump::get_quest_markers() {
	if (!initialized) {
		initialize();
	}
	std::vector<Quest_marker> out;
	const int                 max_markers = 8;
	for (int i = static_cast<int>(notes.size()) - 1; i >= 0 && static_cast<int>(out.size()) < max_markers; --i) {
		One_note* n = notes[i];
		if (!n || n->get_category() != NoteCategory::QUEST || n->get_completed()) {
			continue;
		}
		Quest_marker m;
		m.note_index = i;
		if (!n->get_dest(m.tx, m.ty)) {
			m.tx = n->tx;
			m.ty = n->ty;
		}
		out.push_back(m);
	}
	return out;
}

/*
 *  Reset pagination from the top after the visible notes changed.
 */
void Notebook_gump::reset_view() {
	rebuild_visible();
	page_info.clear();
	if (visible.empty()) {
		page_info.emplace_back(-1, 0);    // No notes match: blank pages.
	} else {
		page_info.emplace_back(0, 0);
	}
	curpage       = 0;
	curnote       = 0;
	cursor.offset = 0;
	updnx         = 0;
	dirty         = true;
	paint();
}

/*
 *  Write out as XML.
 */

void One_note::write(ostream& out) {
	out << "<note>" << endl;
	out << "<category> " << note_category_to_string(category) << " </category>" << endl;
	if (is_completed) {
		out << "<status> completed </status>" << endl;
	}
	if (is_unread) {
		out << "<unread> true </unread>" << endl;
	}
	out << "<time> " << day << ':' << hour << ':' << minute << " </time>" << endl;
	out << "<place> " << tx << ':' << ty << " </place>" << endl;
	if (dest_x >= 0 && dest_y >= 0) {
		out << "<dest> " << dest_x << ':' << dest_y << " </dest>" << endl;
	}
	if (!npcs.empty()) {
		out << "<npcs> " << npcs << " </npcs>" << endl;
	}
	if (gflag >= 0) {
		out << "<gflag> " << gflag << " </gflag>" << endl;
	}
	out << "<text>" << endl;
	// Encode entities (prevents crashes on load with ampersands).
	out << encode_entity(text);
	out << endl << "</text>" << endl;
	out << "</note>" << endl;
}

/*
 *  Get left/right text area.
 */

inline TileRect Get_text_area(bool right, bool startnote) {
	const int ninf = 12;    // Space for note info.
	if (!startnote) {
		return right ? TileRect(rpagex, pagey, 122, 130) : TileRect(lpagex, pagey, 122, 130);
	} else {
		return right ? TileRect(rpagex, pagey + ninf, 122, 130 - ninf) : TileRect(lpagex, pagey + ninf, 122, 130 - ninf);
	}
}

/*
 *  Remap tables for dimmed (completed) text and green "NEW" highlight.
 *  Fonts paint glyph pixels at 0..255; mapping every pixel to a reduced
 *  value dims the text, mapping to the special green gives a bright "NEW"
 *  marker. Pixel 0 (transparent) is always preserved.
 */
static unsigned char* DimTable() {
	static unsigned char table[256];
	static bool          inited = false;
	if (!inited) {
		for (int i = 0; i < 256; ++i) {
			table[i] = static_cast<unsigned char>(i ? (i * 3) / 5 : 0);
		}
		inited = true;
	}
	return table;
}

static unsigned char* NewTable() {
	static unsigned char table[256];
	static bool          inited = false;
	if (!inited) {
		const unsigned char green = static_cast<unsigned char>(
				Shape_manager::get_instance()->get_special_pixel(POISON_PIXEL));
		for (int i = 0; i < 256; ++i) {
			table[i] = static_cast<unsigned char>(i ? green : 0);
		}
		inited = true;
	}
	return table;
}

/*
 *  A 'page-turner' button.
 */
class Notebook_page_button : public Gump_button {
	int leftright;    // 0=left, 1=right.
public:
	Notebook_page_button(Gump* par, int px, int py, int lr) : Gump_button(par, lr ? RIGHTPAGE : LEFTPAGE, px, py), leftright(lr) {}

	// What to do when 'clicked':
	bool activate(MouseButton button) override;

	bool push(MouseButton button) override {
		ignore_unused_variable_warning(button);
		return false;
	}

	void unpush(MouseButton button) override {
		ignore_unused_variable_warning(button);
	}
};

/*
 *  Handle click.
 */

bool Notebook_page_button::activate(MouseButton button) {
	if (button != MouseButton::Left) {
		return false;
	}
	static_cast<Notebook_gump*>(parent)->change_page(leftright ? 1 : -1);
	return true;
}

/*
 *  Invisble button that swallows a click (returned from on_button when a
 *  click is handled directly, e.g. the quest checkbox).
 */
class Notebook_null_button : public Gump_button {
public:
	Notebook_null_button(Gump* par) : Gump_button(par, -1, 0, 0) {}

	bool on_widget(int mx, int my) const override {
		ignore_unused_variable_warning(mx, my);
		return false;
	}
};

/*
 *  Bottom-strip interactive chip: category tab, search box or the
 *  show-completed toggle. Self-contained drawing (font 4 only; CJK
 *  safe), hit-testing against a gump-relative rect, and activation.
 */
class Notebook_chip_button : public Gump_button {
	int          rx, ry, rw, rh;    // Gump-relative rect.
	NoteCategory cat;               // For tabs.
	bool         is_search;         // This is the search box.
	bool         is_toggle;         // This is the hide/show completed toggle.
public:
	Notebook_chip_button(Gump* par, int gx, int gy, int gw, int gh, NoteCategory c = NoteCategory::GENERAL, bool search = false,
						 bool toggle = false)
			: Gump_button(par, -1, gx, gy), rx(gx), ry(gy), rw(gw), rh(gh), cat(c), is_search(search), is_toggle(toggle) {}

	bool on_widget(int mx, int my) const override {
		const int gx = parent->get_x();
		const int gy = parent->get_y();
		return mx >= gx + rx && mx < gx + rx + rw && my >= gy + ry && my < gy + ry + rh;
	}

	bool activate(MouseButton button) override;

	void paint() override;
};

/*
 *  Chip clicked (mouse released over it).
 */
bool Notebook_chip_button::activate(MouseButton button) {
	if (button != MouseButton::Left) {
		return false;
	}
	Notebook_gump* nb = static_cast<Notebook_gump*>(parent);
	SDL_Window* window = gwin->get_win()->get_screen_window();
	if (is_search) {
		nb->search_focused = !nb->search_focused;
		if (nb->search_focused) {
			if (!SDL_TextInputActive(window)) {
				TouchUI::startTextInput(window);
			}
		} else {
			if (SDL_TextInputActive(window)) {
				SDL_StopTextInput(window);
			}
		}
		nb->paint();
		return true;
	}
	if (is_toggle) {
		Notebook_gump::show_completed = !Notebook_gump::show_completed;
		nb->reset_view();
		return true;
	}
	Notebook_gump::set_filter(cat);
	nb->reset_view();
	return true;
}

/*
 *  Paint a chip: parchment-colored background, thin border, label text.
 */
void Notebook_chip_button::paint() {
	Shape_manager* sman = Shape_manager::get_instance();
	Image_window8* win  = gwin->get_win();
	const int      x    = parent->get_x() + rx;
	const int      y    = parent->get_y() + ry;
	// Parchment-ish background + dark border, from the game palette.
	const int      border_px   = sman->get_special_pixel(BLACK_PIXEL);
	const int      parchment_px = sman->get_special_pixel(PROTECT_PIXEL);
	bool           is_active    = false;
	if (!is_search && !is_toggle) {
		is_active = static_cast<Notebook_gump*>(parent)->get_filter() == cat;
	}
	const int bg_px = is_active ? sman->get_special_pixel(POISON_PIXEL) : parchment_px;
	// Background.
	win->fill8(bg_px, rw, rh, x, y);
	// 1px border.
	win->fill8(border_px, rw, 1, x, y);
	win->fill8(border_px, rw, 1, x, y + rh - 1);
	win->fill8(border_px, 1, rh - 2, x, y + 1);
	win->fill8(border_px, 1, rh - 2, x + rw - 1, y + 1);
	if (is_toggle) {
		// Checkbox + label "Done".
		const int cbsz = 8;
		const int cbx  = x + 3;
		const int cby  = y + (rh - cbsz) / 2;
		win->fill8(border_px, cbsz, 1, cbx, cby);
		win->fill8(border_px, cbsz, 1, cbx, cby + cbsz - 1);
		win->fill8(border_px, 1, cbsz, cbx, cby);
		win->fill8(border_px, 1, cbsz, cbx + cbsz - 1, cby);
		if (Notebook_gump::show_completed) {    // Tick.
			for (int i = 0; i < cbsz - 2; ++i) {
				win->fill8(border_px, 1, 1, cbx + 1 + i, cby + cbsz - 2 - i);
			}
		}
		sman->paint_text(4, "Done", cbx + cbsz + 3, y + 1);
		return;
	}
	if (is_search) {
		// Search chip: right-aligned query, caret when focused.
		const string& q    = Notebook_gump::get_search_query();
		const int     maxw = rw - 6;
		string        shown;
		if (q.empty()) {
			shown = "Search";    // Placeholder.
		} else {
			shown = q;
			while (!shown.empty() && sman->get_text_width(font, shown.c_str()) > maxw) {
				const unsigned char c = static_cast<unsigned char>(shown[0]);
				const size_t chlen = (c & 0xF0) == 0xF0 ? 4 : (c & 0xE0) == 0xE0 ? 3 : (c & 0xC0) == 0xC0 ? 2 : 1;
				shown = shown.substr(chlen);
			}
		}
		const int tw = sman->get_text_width(font, shown.c_str());
		if (q.empty()) {
			sman->paint_text(font, shown.c_str(), x + 3, y + 1);
		} else {
			sman->paint_text(font, shown.c_str(), x + rw - 3 - tw, y + 1);
		}
		if (static_cast<Notebook_gump*>(parent)->search_focused) {
			const int cx = x + rw - 3 - (q.empty() ? 0 : tw);
			win->fill8(border_px, 1, rh - 4, cx, y + 2);
		}
		return;
	}
	// Category tab.
	const char* tablabels[5] = {"All","Quest","Clue","Loc","NPC"};
	const char* label        = tablabels[static_cast<int>(cat)];
	const int   tw           = sman->get_text_width(font, label);
	sman->paint_text(font, label, x + (rw - tw) / 2, y + 1);
}

/*
 *  Read in notes the first time.
 */

void Notebook_gump::initialize() {
	initialized = true;
	read();
}

/*
 *  Clear out.
 */

void Notebook_gump::clear() {
	while (!notes.empty()) {
		One_note* note = notes.back();
		delete note;
		notes.pop_back();
	}
	page_info.clear();
	visible.clear();
	initialized = false;
}

static NoteCategory parse_note_category(const string& input_text, string& clean_text) {
	clean_text = input_text;
	if (clean_text.empty()) {
		return NoteCategory::GENERAL;
	}

	// Trim leading whitespace
	size_t start = clean_text.find_first_not_of(" \t\r\n");
	if (start != string::npos && start > 0) {
		clean_text = clean_text.substr(start);
	}

	if (!clean_text.empty() && clean_text.front() == '[') {
		size_t close_bracket = clean_text.find(']');
		if (close_bracket != string::npos) {
			string tag = clean_text.substr(1, close_bracket - 1);
			string tag_lower = tag;
			for (char& c : tag_lower) {
				c = static_cast<char>(tolower(static_cast<unsigned char>(c)));
			}

			NoteCategory cat = NoteCategory::GENERAL;
			if (tag_lower == "quest" || tag == "任务") {
				cat = NoteCategory::QUEST;
			} else if (tag_lower == "clue" || tag == "线索" || tag == "綫索") {
				cat = NoteCategory::CLUE;
			} else if (tag_lower == "location" || tag_lower == "loc" || tag == "地点") {
				cat = NoteCategory::LOCATION;
			} else if (tag_lower == "npc" || tag == "人物") {
				cat = NoteCategory::NPC;
			}

			if (cat != NoteCategory::GENERAL) {
				clean_text = clean_text.substr(close_bracket + 1);
				size_t post_start = clean_text.find_first_not_of(" \t");
				if (post_start != string::npos) {
					clean_text = clean_text.substr(post_start);
				}
				return cat;
			}
		}
	}
	return NoteCategory::GENERAL;
}

/*
 *  Pull structured markers out of note text:
 *      [map=x,y]   destination tile for the world map.
 *      [npc=A,B]   related NPC names.
 *  The bracketed tokens are removed from the displayed text; values are
 *  written back through the out-params. Missing tokens leave dest_x/dest_y
 *  at -1 and npcs empty. Case-insensitive; a lone "[" without "]" is left
 *  alone.
 */
static void parse_note_metadata(string& text, int& dest_x, int& dest_y, string& npcs) {
	dest_x = dest_y = -1;
	npcs.clear();
	const string map_key = "[map=";
	const string npc_key = "[npc=";
	auto lowerify = [](const string& s, string& out) {
		out = s;
		for (char& c : out) {
			c = static_cast<char>(tolower(static_cast<unsigned char>(c)));
		}
	};
	auto extract = [&](const string& key, string& out) {
		string lower;
		lowerify(text, lower);
		size_t pos = lower.find(key);
		while (pos != string::npos) {
			const size_t close = text.find(']', pos);
			if (close == string::npos) {
				pos = lower.find(key, pos + key.size());
				continue;
			}
			out = text.substr(pos + key.size(), close - pos - key.size());
			const size_t s = out.find_first_not_of(" \t\r\n");
			const size_t e = out.find_last_not_of(" \t\r\n");
			if (s == string::npos) {
				out.clear();
			} else {
				out = out.substr(s, e - s + 1);
			}
			text.erase(pos, close - pos + 1);
			lowerify(text, lower);
			pos = lower.find(key);
		}
	};
	string mapraw;
	extract(map_key, mapraw);
	if (!mapraw.empty()) {
		int x;
		int y;
		if (sscanf(mapraw.c_str(), "%d,%d", &x, &y) == 2) {
			dest_x = x;
			dest_y = y;
		}
	}
	extract(npc_key, npcs);
	while (!text.empty() && (text.back() == ' ' || text.back() == '\n' || text.back() == '\t')) {
		text.pop_back();    // Tidy whitespace left by tag removal.
	}
}

/*
 *  Add a new note at the current time/place.
 */

void Notebook_gump::add_new(const string& text, int gflag) {
	Game_clock*      clk  = gwin->get_clock();
	const Tile_coord t    = gwin->get_main_actor()->get_tile();
	string clean_text;
	int    dest_x;
	int    dest_y;
	string npcs;
	NoteCategory cat  = parse_note_category(text, clean_text);
	parse_note_metadata(clean_text, dest_x, dest_y, npcs);
	// Game journal entries (gflag >= 0) are quests unless tagged otherwise.
	if (cat == NoteCategory::GENERAL && gflag >= 0) {
		cat = NoteCategory::QUEST;
	}
	auto*        note = new One_note(clk->get_day(), clk->get_hour(), clk->get_minute(), t.tx, t.ty, clean_text, gflag, true, cat, false, true);
	note->set_dest(dest_x, dest_y);
	note->set_npcs(npcs);
	notes.push_back(note);
	rebuild_visible();
}

/*
 *  Create notebook gump.
 */

Notebook_gump::Notebook_gump() : Gump(nullptr, EXULT_FLX_NOTEBOOK_SHP, SF_EXULT_FLX) {
#if defined(SDL_PLATFORM_IOS) || defined(ANDROID)
	// on iOS the Notebook gump needs to be aligned with the top
	set_pos(5, -2);
#endif
	handles_kbd   = true;
	cursor.offset = 0;
	cursor.x = cursor.y = -1;
	cursor.line = cursor.nlines = 0;
	// (Obj. area doesn't matter.)
	set_object_area(TileRect(36, 10, 100, 100), 23, 28);
	if (page_info.empty()) {
		page_info.emplace_back(0, 0);
	}
	// Where to paint page marks:
	const int lpagex  = 35;
	const int rpagex  = 298;
	const int lrpagey = 12;
	leftpage          = new Notebook_page_button(this, lpagex, lrpagey, 0);
	rightpage         = new Notebook_page_button(this, rpagex, lrpagey, 1);
	// Bottom-strip chips: 5 category tabs, search box, hide/show completed.
	const int chipy  = pagey + 130 + 8;
	const int tabw   = 30;
	const int tabh   = 13;
	const int startx = 36;
	for (int i = 0; i < 5; ++i) {
		tab_buttons[i] = new Notebook_chip_button(
				this, startx + i * tabw, chipy, tabw, tabh, static_cast<NoteCategory>(i));
		add_elem(tab_buttons[i]);    // Needed for Gump::has_point() hit-testing.
	}
	search_button = new Notebook_chip_button(this, startx + 5 * tabw + 3, chipy, 62, tabh, NoteCategory::GENERAL, true);
	toggle_button = new Notebook_chip_button(this, startx + 5 * tabw + 3 + 62 + 3, chipy, 48, tabh, NoteCategory::GENERAL, false, true);
	add_elem(search_button);
	add_elem(toggle_button);
	null_button   = new Notebook_null_button(this);
	add_new("");    // Add new note to end.
	rebuild_visible();
}

Notebook_gump* Notebook_gump::create() {
	if (!initialized) {
		initialize();
	}
	if (!instance) {
		instance = new Notebook_gump;
		// Opening the journal reads all entries: clear unread marks.
		bool any_unread = false;
		for (One_note* n : notes) {
			if (n->get_unread()) {
				n->set_unread(false);
				any_unread = true;
			}
		}
		if (any_unread) {
			dirty = true;
		}
		if (touchui != nullptr) {
			touchui->hideGameControls();
			SDL_Window* window = gwin->get_win()->get_screen_window();
			if (!SDL_TextInputActive(window)) {
				TouchUI::startTextInput(window);
			}
		}
		// Open on the most recent entry so the latest quest is visible.
		if (nb_note_count() > 0) {
			instance->jump_to_last_entry();
		}
	}
	return instance;
}

/*
 *  Cleanup.
 */
Notebook_gump::~Notebook_gump() {
	if (!notes.empty()) {
		// Check for empty 'new' note.
		One_note* note = notes.back();
		if (note->is_new && !note->text.length()) {
			notes.pop_back();
			delete note;
		} else {
			note->is_new = false;
		}
	}
	delete leftpage;
	delete rightpage;
	// tab_buttons/search/toggle are registered in elems and are deleted by
	// the base Gump destructor. null_button is only a returned pointer.
	delete null_button;
	null_button = nullptr;
	if (this == instance) {
		instance = nullptr;
	}
	if (touchui != nullptr) {
		Gump_manager* gumpman = gwin->get_gump_man();
		if (!gumpman->gump_mode()) {
			touchui->showGameControls();
		}
		SDL_Window* window = gwin->get_win()->get_screen_window();
		if (SDL_TextInputActive(window)) {
			SDL_StopTextInput(window);
		}
	}
	if (dirty) {
		write();
		dirty = false;
	}
}

/*
 *  Paint a page and find where its text ends.
 *
 *  Output: True if finished entire note.
 *      Cursor.x is possibly set.
 */

bool Notebook_gump::paint_page(
		const TileRect& box,       // Display box rel. to gump.
		One_note*       note,      // Note to print.
		int&            offset,    // Starting offset into text.  Updated.
		int             pagenum) {
	const bool find_cursor = (note == nb_note(curnote) && cursor.x < 0);
	const bool completed   = note->get_completed();
	// Remap table dims already-painted font pixels by ~60% brightness.
	const unsigned char* dim_trans = completed ? DimTable() : nullptr;
	if (offset == 0) {    // Print note info. at start.
		char        buf[60];
		const char* ampm = Strings::am();
		int         h    = note->hour;
		if (h >= 12) {
			h -= 12;
			ampm = Strings::pm();
		}
		snprintf(buf, sizeof(buf), "%s %d, %02d:%02d%s", Strings::Day(), note->day, h ? h : 12, note->minute, ampm);
#if defined(SDL_PLATFORM_IOS) || defined(ANDROID)
		const int fontnum = 4;
		const int yoffset = 0;
#else
		const int fontnum = 2;
		const int yoffset = 4;
#endif
		if (dim_trans) {
			sman->get_font(fontnum)->paint_text(gwin->get_win()->get_ib8(), buf, x + box.x, y + pagey, const_cast<unsigned char*>(dim_trans));
		} else {
			sman->paint_text(fontnum, buf, x + box.x, y + pagey);
		}
		// when cheating show location of entry (in dec - could use sextant
		// postions)
		if (cheat()) {
			snprintf(buf, sizeof(buf), "%d, %d", note->tx, note->ty);
			sman->paint_text(4, buf, x + box.x + 80, y + pagey - yoffset);
		}
		// "NEW" badge for unread entries, straight after the date.
		if (note->get_unread()) {
			const int wl = sman->get_text_width(fontnum, buf);
			sman->get_font(fontnum)->paint_text(
					gwin->get_win()->get_ib8(), "NEW", x + box.x + wl + 8, y + pagey, const_cast<unsigned char*>(NewTable()));
		}
		// Quest entries get a completion checkbox on the info row.
		if (note->get_category() == NoteCategory::QUEST) {
			const int cbx = x + box.x + box.w - 19;
			const int cby = y + pagey;
			const int blk = sman->get_special_pixel(BLACK_PIXEL);
			const int pap = sman->get_special_pixel(PROTECT_PIXEL);
			// Border + interior.
			gwin->get_win()->fill8(blk, 9, 1, cbx, cby);
			gwin->get_win()->fill8(blk, 9, 1, cbx, cby + 8);
			gwin->get_win()->fill8(blk, 1, 9, cbx, cby);
			gwin->get_win()->fill8(blk, 1, 9, cbx + 8, cby);
			gwin->get_win()->fill8(pap, 7, 7, cbx + 1, cby + 1);
			if (note->get_completed()) {    // Tick mark.
				for (int i = 0; i < 3; ++i) {
					gwin->get_win()->put_pixel8(blk, cbx + 1 + i, cby + 6 - i);
				}
				for (int i = 0; i < 5; ++i) {
					gwin->get_win()->put_pixel8(blk, cbx + 3 + i, cby + 4 - i);
				}
			}
		}
		// Use bright green for automatic text.
		gwin->get_win()->fill8(
				sman->get_special_pixel(note->gflag >= 0 ? POISON_PIXEL : CHARMED_PIXEL), box.w, 1, x + box.x, y + box.y - 3);
	}
	const char* str = note->text.c_str() + offset;
	cursor.offset -= offset;
	int endoff;
	if (dim_trans) {
		endoff = sman->get_font(font)->paint_text_box(
				gwin->get_win()->get_ib8(), str, x + box.x, y + box.y, box.w, box.h, vlead, false, false,
				find_cursor ? &cursor : nullptr, const_cast<unsigned char*>(dim_trans));
	} else {
		endoff = sman->paint_text_box(
				font, str, x + box.x, y + box.y, box.w, box.h, vlead, false, false, -1, find_cursor ? &cursor : nullptr);
	}
	cursor.offset += offset;
	if (endoff > 0) {    // All painted?
		// Value returned is height.
		str = note->text.c_str() + note->text.length();
	} else {    // Out of room.
		str += -endoff;
	}
	if (find_cursor && cursor.x >= 0) {
		gwin->get_win()->fill8(sman->get_special_pixel(POISON_PIXEL), 1, sman->get_text_height(font), cursor.x - 1, cursor.y - 1);
		curpage = pagenum;
	}
	offset = str - note->text.c_str();    // Return offset past end.
	// Watch for exactly filling page.
	return endoff > 0 && endoff < box.h;
}

/*
 *  Change page.
 */

void Notebook_gump::change_page(int delta) {
	if (delta == 0) {
		return;
	}

	const int topleft = curpage & ~1;
	int       new_page;

	if (delta > 0) {
		new_page = topleft + 2;
		if (new_page >= static_cast<int>(page_info.size())) {
			return;
		}
	} else {
		if (topleft == 0) {
			return;
		}
		new_page = topleft - 2;
	}

	curpage = new_page;
	curnote = page_info[curpage].notenum;
	updnx = cursor.offset = 0;
	paint();
}

/*
 *  Is a given screen point on one of our buttons?  If not, we try to
 *  set cursor pos. within the text.
 *
 *  Output: ->button if so.
 */

Gump_button* Notebook_gump::on_button(
		int mx, int my    // Point in window.
) {
	// Bottom-strip chips get first chance.
	for (int i = 0; i < 5; ++i) {
		if (tab_buttons[i]->on_button(mx, my)) {
			return tab_buttons[i];
		}
	}
	if (search_button->on_button(mx, my)) {
		return search_button;
	}
	if (toggle_button->on_button(mx, my)) {
		return toggle_button;
	}
	if (leftpage->on_button(mx, my)) {
		return leftpage;
	} else if (rightpage->on_button(mx, my)) {
		return rightpage;
	}
	const int cbtopl   = curpage & ~1;
	// Quest completion checkbox on the note-info row of the left page.
	{
		int       notenum = page_info[cbtopl].notenum;
		const int looset  = page_info[cbtopl].offset;
		if (notenum >= 0 && looset == 0) {
			One_note* n   = nb_note(notenum);
			TileRect  box = Get_text_area(false, true);
			box.shift(x, y);    // Window area.
			if (n->get_category() == NoteCategory::QUEST && TileRect(box.x + box.w - 19, box.y - 12, 9, 9).has_point(mx, my)) {
				n->set_completed(!n->get_completed());
				dirty = true;
				paint();
				return null_button;    // Swallow the click.
			}
		}
	}
	Gump_button* btn = Gump::on_button(mx, my);
	if (btn) {
		return btn;
	}
	const int topleft = curpage & ~1;
	int       notenum = page_info[topleft].notenum;
	if (notenum < 0) {
		return nullptr;
	}
	int         offset = page_info[topleft].offset;
	TileRect    box    = Get_text_area(false, offset == 0);    // Left page.
	One_note*   note   = nb_note(notenum);
	int         coff   = sman->find_cursor(font, note->text.c_str() + offset, x + box.x, y + box.y, box.w, box.h, mx, my, vlead);
	SDL_Window* window = gwin->get_win()->get_screen_window();
	if (coff >= 0) {    // Found it?
		curpage       = topleft;
		curnote       = page_info[curpage].notenum;
		cursor.offset = offset + coff;
		paint();
		updnx = cursor.x - x - lpagex;
		if (!SDL_TextInputActive(window)) {
			TouchUI::startTextInput(window);
		}
	} else {
		offset += -coff;    // New offset.
		if (offset >= static_cast<int>(note->text.length())) {
			if (notenum == nb_note_count() - 1) {
				return nullptr;    // No more.
			}
			note   = nb_note(++notenum);
			offset = 0;
		}
		box = Get_text_area(true, offset == 0);    // Right page.
		box.shift(x, y);                           // Window area.
		coff = box.has_point(mx, my)
					   ? sman->find_cursor(font, note->text.c_str() + offset, box.x, box.y, box.w, box.h, mx, my, vlead)
					   : -1;
		if (coff >= 0) {    // Found it?
			curpage       = curpage | 1;
			curnote       = page_info[curpage].notenum;
			cursor.offset = offset + coff;
			paint();
			updnx = cursor.x - x - rpagex;
			if (!SDL_TextInputActive(window)) {
				TouchUI::startTextInput(window);
			}
		}
	}
	return nullptr;
}

/*
 *  Paint notebook.
 */

void Notebook_gump::paint() {
	Gump::paint();    // Shape + elems (the chip buttons paint themselves here).
	if (curpage > 0) {    // Not the first?
		leftpage->paint();
	}
	const int topleft = curpage & ~1;
	int       notenum = page_info[topleft].notenum;
	if (notenum < 0) {
		return;
	}
	int       offset = page_info[topleft].offset;
	One_note* note   = nb_note(notenum);
	cursor.x         = -1;
	// Paint left page.
	if (paint_page(Get_text_area(false, offset == 0), note, offset, topleft)) {
		// Finished note?
		if (notenum == nb_note_count() - 1) {
			return;
		}
		++notenum;
		note   = nb_note(notenum);
		offset = 0;
	}
	if (topleft + 1 >= static_cast<int>(page_info.size())) {    // Store right-page info.
		page_info.resize(topleft + 2);
	}
	page_info[topleft + 1].notenum = notenum;
	page_info[topleft + 1].offset  = offset;
	// Paint right page.
	if (paint_page(Get_text_area(true, offset == 0), note, offset, topleft + 1)) {
		// Finished note?
		if (notenum == nb_note_count() - 1) {
			return;    // No more.
		}
		++notenum;
		offset = 0;
	}
	rightpage->paint();
	const int nxt = topleft + 2;    // For next pair of pages.
	if (nxt >= static_cast<int>(page_info.size())) {
		page_info.resize(nxt + 1);
	}
	page_info[nxt].notenum = notenum;
	page_info[nxt].offset  = offset;
}

/*
 *  Move to end of prev. page.
 */

void Notebook_gump::prev_page() {
	if (!curpage) {
		return;
	}
	const Notebook_top& pinfo = page_info[curpage];
	--curpage;
	curnote = page_info[curpage].notenum;
	if (!pinfo.offset) {    // Going to new note?
		cursor.offset = nb_note(curnote)->text.length();
	} else {
		cursor.offset = pinfo.offset - 1;
	}
}

/*
 *  Move to next page.
 */

void Notebook_gump::next_page() {
	if (curpage >= static_cast<int>(page_info.size())) {
		return;
	}
	++curpage;
	const Notebook_top& pinfo = page_info[curpage];
	curnote                   = pinfo.notenum;
	cursor.offset             = pinfo.offset;    // Start of page.
}

/*
 *  See if on last/first line of current page.
 *  Note:   These assume paint() was done, so cursor is correct.
 */

bool Notebook_gump::on_last_page_line() {
	return cursor.line == cursor.nlines - 1;
}

bool Notebook_gump::on_first_page_line() {
	return cursor.line == 0;
}

/*
 *  Handle down/up arrows.
 */

void Notebook_gump::down_arrow() {
	if (page_info[curpage].notenum < 0) {
		return;
	}
	int       offset = page_info[curpage].offset;
	TileRect  box    = Get_text_area((curpage % 2) != 0, offset == 0);
	const int ht     = sman->get_text_height(font);
	if (on_last_page_line()) {
		if (curpage >= static_cast<int>(page_info.size()) - 1) {
			return;
		}
		next_page();
		paint();
		offset   = page_info[curpage].offset;
		box      = Get_text_area((curpage % 2) != 0, offset == 0);
		cursor.y = y + box.y - ht;
	}
	box.shift(x, y);    // Window coords.
	const int mx      = box.x + updnx + 1;
	const int my      = cursor.y + ht + ht / 2;
	const int notenum = page_info[curpage].notenum;
	One_note* note    = nb_note(notenum);
	const int coff    = sman->find_cursor(font, note->text.c_str() + offset, box.x, box.y, box.w, box.h, mx, my, vlead);
	if (coff >= 0) {    // Found it?
		cursor.offset = offset + coff;
		paint();
	}
}

void Notebook_gump::up_arrow() {
	if (page_info[curpage].notenum < 0) {
		return;
	}
	const Notebook_top& pinfo   = page_info[curpage];
	const int           ht      = sman->get_text_height(font);
	int                 offset  = pinfo.offset;
	int                 notenum = pinfo.notenum;
	if (on_first_page_line()) {    // Above top.
		if (!curpage) {
			return;
		}
		prev_page();
		const Notebook_top& pinfo2 = page_info[curpage];
		notenum                    = pinfo2.notenum;
		if (pinfo.notenum == notenum) {    // Same note?
			cursor.offset = offset - 1;
		} else {
			cursor.offset = nb_note(notenum)->text.length();
		}
		paint();
		offset = pinfo2.offset;
		cursor.y += ht / 2;    // Past bottom line.
	}
	TileRect box = Get_text_area((curpage % 2) != 0, offset == 0);
	box.shift(x, y);    // Window coords.
	const int mx   = box.x + updnx + 1;
	const int my   = cursor.y - ht / 2;
	One_note* note = nb_note(notenum);
	const int coff = sman->find_cursor(font, note->text.c_str() + offset, box.x, box.y, box.w, box.h, mx, my, vlead);
	if (coff >= 0) {    // Found it?
		cursor.offset = offset + coff;
		paint();
	}
}

/*
 *  Handle keystroke.
 */
bool Notebook_gump::handle_kbd_event(void* vev) {
	SDL_Event&  ev      = *static_cast<SDL_Event*>(vev);
	SDL_Keycode unicode = 0;    // Unicode is way different in SDL2
	SDL_Keycode chr     = 0;
	Translate_keyboard(ev, chr, unicode, true);

	if (ev.type == SDL_EVENT_KEY_UP) {
		return true;    // Ignoring key-up at present.
	}
	// Raw UTF-8 text input (IME / keyboard) goes to the search box when focused.
	if (ev.type == SDL_EVENT_TEXT_INPUT) {
		if (search_focused && ev.text.text) {
			search_query += ev.text.text;
			reset_view();
			return true;
		}
		return false;
	}
	if (ev.type != SDL_EVENT_KEY_DOWN) {
		return false;
	}
	if (curpage >= static_cast<int>(page_info.size())) {
		return false;    // Shouldn't happen.
	}
	if (search_focused) {    // Search box owns the keyboard.
		SDL_Window* window = gwin->get_win()->get_screen_window();
		switch (chr) {
		case SDLK_ESCAPE:
		case SDLK_RETURN:
			search_focused = false;
			if (SDL_TextInputActive(window)) {
				SDL_StopTextInput(window);
			}
			paint();
			return true;
		case SDLK_BACKSPACE:
			if (!search_query.empty()) {    // Drop last UTF-8 codepoint.
				size_t i = search_query.size() - 1;
				while (i > 0 && (static_cast<unsigned char>(search_query[i]) & 0xC0) == 0x80) {
					--i;
				}
				search_query.erase(i);
				reset_view();
			}
			return true;
		case SDLK_DELETE:
			if (!search_query.empty()) {
				search_query.clear();
				reset_view();
			}
			return true;
		default:
			return true;    // Swallow everything else while searching.
		}
	}
	const Notebook_top& pinfo = page_info[curpage];
	if (pinfo.notenum < 0) {    // No note on this page (empty filter).
		return true;
	}
	One_note* note = nb_note(pinfo.notenum);
	switch (chr) {
	case SDLK_ESCAPE: {
		// Close the gump.
		if (gwin && gwin->get_gump_man()) {
			gwin->get_gump_man()->close_gump(this);
			return true;
		}
		return false;
	}
	case SDLK_F8:
		// Toggle the interactive search box.
		search_focused = !search_focused;
		{
			SDL_Window* window = gwin->get_win()->get_screen_window();
			if (search_focused) {
				if (!SDL_TextInputActive(window)) {
					TouchUI::startTextInput(window);
				}
			} else {
				if (SDL_TextInputActive(window)) {
					SDL_StopTextInput(window);
				}
			}
		}
		paint();
		return true;
	case SDLK_HOME:
		// Jump to first entry
		jump_to_first_entry();
		break;
	case SDLK_END:
		// Jump to last entry (first page of the last note)
		jump_to_last_entry();
		break;
	case SDLK_RETURN:
		note->insert('\n', cursor.offset);
		++cursor.offset;
		paint();    // (Not very efficient...)
		if (need_next_page()) {
			next_page();
			paint();
		}
		break;
	case SDLK_BACKSPACE:
		if (note->del(cursor.offset - 1)) {
			if (--cursor.offset < pinfo.offset && curpage % 2 == 0) {
				prev_page();
			}
			paint();
		}
		break;
	case SDLK_DELETE:
		if (note->del(cursor.offset)) {
			paint();
		}
		break;
	case SDLK_LEFT:
		if (cursor.offset) {
			if (--cursor.offset < pinfo.offset && curpage % 2 == 0) {
				prev_page();
			}
			paint();
		}
		break;
	case SDLK_RIGHT:
		if (cursor.offset < static_cast<int>(note->text.length())) {
			++cursor.offset;
			paint();
			if (need_next_page()) {
				next_page();
				paint();
			}
		}
		break;
	case SDLK_UP:
		up_arrow();
		return true;    // Don't set updnx.
	case SDLK_DOWN:
		down_arrow();
		return true;    // Don't set updnx.
	case SDLK_PAGEUP:
		change_page(-1);
		break;
	case SDLK_PAGEDOWN:
		change_page(1);
		break;
	default:
		if (unicode < ' ') {
			return true;    // Ignore other special chars.
		}
		if (unicode >= 256 || !isascii(unicode)) {
			return true;
		}
		// Special case: ignore "^" character
		if (unicode == '^') {
			return true;
		}

		// Check if adding this character would make the current word too long
		// by simulating inserting the character and then checking
		string test_text = note->text;
		test_text.insert(cursor.offset, 1, unicode);

		if (word_exceeds_line_length(test_text, cursor.offset + 1, curpage)) {
			// Find the start of the current word
			int word_start = cursor.offset;
			while (word_start > 0 && test_text[word_start - 1] != ' ' && test_text[word_start - 1] != '\n') {
				word_start--;
			}

			// If this is a single word that's too long by itself
			// (rather than a line that's too long because of multiple words)
			if (word_start == 0 || test_text[word_start - 1] == '\n') {
				// Insert a newline BEFORE the character that would make
				// it too long
				note->insert('\n', cursor.offset);
				++cursor.offset;

				// Then insert the character on the new line
				note->insert(unicode, cursor.offset);
				++cursor.offset;
			} else {
				// Normal case - break at word boundary
				note->insert(unicode, cursor.offset);
				++cursor.offset;

				// Insert newline after the most recent space
				int pos = cursor.offset - 1;
				while (pos > 0 && note->text[pos] != ' ') {
					pos--;
				}
				if (pos > 0) {
					note->text[pos] = '\n';
				}
			}
		} else {
			// Normal case, just insert the character
			note->insert(unicode, cursor.offset);
			++cursor.offset;
		}

		paint();    // (Not very efficient...)
		if (need_next_page()) {
			next_page();
			paint();
		}
		break;
	}
	updnx = cursor.x - x - ((curpage % 2) ? rpagex : lpagex);
#ifdef DEBUG
	std::cout << "updnx = " << updnx << std::endl;
//	std::cout << "Notebook chr: " << chr << std::endl;
#endif
	return true;
}

/*
 *  Automatically add a text entry when a usecode global flag is set.
 */

void Notebook_gump::add_gflag_text(int gflag, const string& text) {
	if (!initialized) {
		initialize();
	}
	// See if already there.
	for (auto* note : notes) {
		if (note->gflag == gflag) {
			return;
		}
	}
	if (gwin->get_allow_autonotes()) {
		instance->add_new_with_line_breaks(text, gflag);
		if (gwin && gwin->get_effects() && gwin->get_main_actor()) {
			gwin->get_effects()->add_text("Journal Updated", gwin->get_main_actor());
		}
		Audio::get_ptr()->play_sound_effect(Audio::game_sfx(74));
	}
}

/*
 *  Add a new note with proper line breaking. Reuses One_note's line breaking
 * logic.
 */
void Notebook_gump::add_new_with_line_breaks(const string& text, int gflag) {
	Game_clock*      clk = gwin->get_clock();
	const Tile_coord t   = gwin->get_main_actor()->get_tile();

	string clean_text;
	int    dest_x;
	int    dest_y;
	string npcs;
	NoteCategory cat = parse_note_category(text, clean_text);
	parse_note_metadata(clean_text, dest_x, dest_y, npcs);
	// Game journal entries (gflag >= 0) are quests unless tagged otherwise.
	if (cat == NoteCategory::GENERAL && gflag >= 0) {
		cat = NoteCategory::QUEST;
	}

	// Create a new note with parsed category and unread state
	One_note* note = new One_note(clk->get_day(), clk->get_hour(), clk->get_minute(), t.tx, t.ty, "", gflag, true, cat, false, true);
	note->set_dest(dest_x, dest_y);
	note->set_npcs(npcs);

	// Use existing line breaking logic from One_note
	note->add_text_with_line_breaks(clean_text);

	// Add the note to the collection
	notes.push_back(note);
	if (instance) {
		instance->reset_view();
	} else {
		rebuild_visible();
	}
}

/*
 *  Write it out.
 */

void Notebook_gump::write() {
	auto pOut = U7open_out(NOTEBOOKXML);
	if (!pOut) {
		return;
	}
	auto& out = *pOut;
	out << "<notebook>" << endl;
	if (initialized) {
		for (auto* note : notes) {
			if (note->text.length() || !note->is_new) {
				note->write(out);
			}
		}
	}
	out << "</notebook>" << endl;
}

/*
 *  Read it in from 'notebook.xml'.
 */

void Notebook_gump::read() {
	const string  root;
	Configuration conf;

	conf.read_abs_config_file(NOTEBOOKXML, root);
	const string identstr;
	// not spamming the terminal with all the notes in normal play
#ifdef DEBUG
	conf.dump(cout, identstr);
#endif
	Configuration::KeyTypeList note_nds;
	const string               basekey = "notebook";
	conf.getsubkeys(note_nds, basekey);
	One_note* note = nullptr;
	for (const auto& notend : note_nds) {
		if (notend.first == "note") {
			note = new One_note();
			notes.push_back(note);
		} else if (notend.first == "note/category") {
			if (note) {
				std::string cat_str = notend.second;
				// trim spaces
				size_t start = cat_str.find_first_not_of(" \t\r\n");
				size_t end = cat_str.find_last_not_of(" \t\r\n");
				if (start != std::string::npos && end != std::string::npos) {
					cat_str = cat_str.substr(start, end - start + 1);
				}
				note->set_category(string_to_note_category(cat_str));
			}
		} else if (notend.first == "note/status") {
			if (note) {
				note->set_completed(notend.second.find("completed") != std::string::npos);
			}
		} else if (notend.first == "note/unread") {
			if (note) {
				note->set_unread(notend.second.find("true") != std::string::npos);
			}
		} else if (notend.first == "note/time") {
			int d;
			int h;
			int m;
			sscanf(notend.second.c_str(), "%d:%d:%d", &d, &h, &m);
			if (note) {
				note->set_time(d, h, m);
			}
		} else if (notend.first == "note/place") {
			int x;
			int y;
			sscanf(notend.second.c_str(), "%d:%d", &x, &y);
			if (note) {
				note->set_loc(x, y);
			}
		} else if (notend.first == "note/dest") {
			int x;
			int y;
			sscanf(notend.second.c_str(), "%d:%d", &x, &y);
			if (note) {
				note->set_dest(x, y);
			}
		} else if (notend.first == "note/npcs") {
			if (note) {
				std::string npc_str = notend.second;
				const size_t start  = npc_str.find_first_not_of(" \t\r\n");
				const size_t end    = npc_str.find_last_not_of(" \t\r\n");
				if (start != std::string::npos && end != std::string::npos) {
					npc_str = npc_str.substr(start, end - start + 1);
				}
				note->set_npcs(npc_str);
			}
		} else if (notend.first == "note/text") {
			if (note) {
				// Add text with line breaks directly to the note
				note->add_text_with_line_breaks(notend.second);
			}
		} else if (notend.first == "note/gflag") {
			int gf;
			sscanf(notend.second.c_str(), "%d", &gf);
			if (note) {
				note->set_gflag(gf);
			}
		}
	}
	rebuild_visible();
}

/*
 *  Read in text to be inserted automatically when global flags are set.
 */

// read in from external file
void Notebook_gump::read_auto_text_file(const char* filename) {
	if (gwin->get_allow_autonotes()) {
		initialized_auto_text     = true;
		IFileDataSource notesfile = [&]() -> IFileDataSource {
			if (is_system_path_defined("<PATCH>") && U7exists(PATCH_AUTONOTES)) {
				cout << "Loading patch autonotes" << endl;
				return IFileDataSource(PATCH_AUTONOTES, true);
			}
			cout << "Loading autonotes from file " << filename << endl;
			return IFileDataSource(filename, true);
		}();
		if (notesfile.good()) {
			Text_msg_file_reader reader(notesfile);
			reader.get_global_section_strings(auto_text);
		}
	}
}

// read in from flx bundled file
void Notebook_gump::read_auto_text() {
	if (gwin->get_allow_autonotes()) {
		initialized_auto_text = true;
		if (is_system_path_defined("<PATCH>") && U7exists(PATCH_AUTONOTES)) {
			cout << "Loading patch autonotes" << endl;
			IFileDataSource notesfile(PATCH_AUTONOTES, true);
			if (notesfile.good()) {
				Text_msg_file_reader reader(notesfile);
				reader.get_global_section_strings(auto_text);
			}
		} else {
			const str_int_pair& resource = game->get_resource("config/autonotes");
			IExultDataSource    notesfile(resource.str, resource.num);
			if (notesfile.good()) {
				cout << "Loading default autonotes" << endl;
				Text_msg_file_reader reader(notesfile);
				reader.get_global_section_strings(auto_text);
			}
		}
	}
}

bool Notebook_gump::word_exceeds_line_length(const string& text, int offset, int curpage) {
	// Find the end of the current word.
	int word_end = offset;

	// Find the start of the current word.
	int word_start = word_end;
	while (word_start > 0 && text[word_start - 1] != ' ' && text[word_start - 1] != '\n') {
		--word_start;
	}

	// Calculate the length of the current word.
	int word_length = offset - word_start;

	// Get the text area for the current page.
	TileRect box = Get_text_area((curpage % 2) != 0, false);

	// Calculate the available width on the current line.
	// Find the last newline character before the offset
	int last_newline = 0;
	for (int i = 0; i < word_start; ++i) {
		if (text[i] == '\n') {
			last_newline = i + 1;    // Start after the newline
		}
	}

	// Calculate the width of the current line up to the start of the word
	string current_line = text.substr(last_newline, word_start - last_newline);

	// Calculate line width once and use it consistently
	int current_line_width = sman->get_text_width(font, current_line.c_str());

	// Get the width of the word
	int word_width = sman->get_text_width(font, text.substr(word_start, word_length).c_str());

	// Always treat words with trailing
	// punctuation as if the punctuation weren't there
	bool has_punct       = (word_length > 1 && ispunct(text[word_start + word_length - 1]));
	int  base_word_width = word_width;

	if (has_punct) {
		// Get just the word without the trailing punctuation
		base_word_width = sman->get_text_width(font, text.substr(word_start, word_length - 1).c_str());
	}

	// Use base_word_width for consistency with add_text_with_line_breaks
	return current_line_width + (has_punct ? base_word_width : word_width) > box.w;
}

void One_note::add_text_with_line_breaks(const std::string& input) {
	// If the text contains any non-ASCII characters (e.g. CJK/UTF-8), bypass the legacy 
	// byte-by-byte wrapping logic to prevent corrupting the multi-byte sequences.
	// The underlying paint_text_box renderer already natively supports TTF CJK line wrapping.
	bool has_cjk = false;
	for (char c : input) {
		if (static_cast<unsigned char>(c) >= 0x80) {
			has_cjk = true;
			break;
		}
	}
	
	if (has_cjk) {
		this->text = input;
		return;
	}

	Shape_manager* sman      = Shape_manager::get_instance();
	TileRect       box       = Get_text_area(false, false);
	int            max_width = box.w;

	// Clear existing text before formatting
	this->text = "";

	// Strip existing newlines and replace with spaces
	// to ensure proper re-wrapping of long lines
	std::string processed_input = input;
	for (size_t i = 0; i < processed_input.size(); ++i) {
		if (processed_input[i] == '\n') {
			processed_input[i] = ' ';
		}
	}

	std::istringstream iss(processed_input);
	std::string        word;
	std::string        current_line;
	int                current_line_width = 0;

	// Parse word by word, not line by line
	while (iss >> word) {
		// Calculate word width
		int word_width = sman->get_text_width(font, word.c_str());

		// Handle very long words that need to be broken up
		// mid-word
		if (word_width > max_width) {
			// First add any existing content as its own line
			if (!current_line.empty()) {
				this->text += current_line + "\n";
				current_line       = "";
				current_line_width = 0;
			}

			// Now break up the long word
			std::string remaining_word = word;

			while (!remaining_word.empty()) {
				std::string part       = "";
				int         part_width = 0;

				// Build up the part character by character until it's almost at
				// max width
				for (size_t i = 0; i < remaining_word.length(); ++i) {
					std::string test_part  = part + remaining_word[i];
					int         test_width = sman->get_text_width(font, test_part.c_str());

					if (test_width >= max_width) {
						break;
					}

					part       = std::move(test_part);
					part_width = test_width;
				}

				if (part.empty()) {
					// Even a single character is too wide - take the first char
					// anyway
					part       = remaining_word.substr(0, 1);
					part_width = sman->get_text_width(font, part.c_str());
				}

				// Add this part to the text
				if (!current_line.empty()) {
					this->text += current_line + "\n";
				}
				current_line       = part;
				current_line_width = part_width;

				// Remove the used part from the remaining word
				remaining_word = remaining_word.substr(part.length());

				// If there's more to come, add this part as a complete line
				if (!remaining_word.empty()) {
					this->text += current_line + "\n";
					current_line       = "";
					current_line_width = 0;
				}
			}
			continue;    // Skip the rest of the loop for this word
		}

		// Check for punctuation at the end of the word
		bool has_punct       = (word.length() > 1 && ispunct(word[word.length() - 1]));
		int  base_word_width = word_width;

		if (has_punct) {
			// Get just the word without the trailing punctuation
			base_word_width = sman->get_text_width(font, word.substr(0, word.length() - 1).c_str());
		}

		// Space width (if needed)
		int space_width = current_line_width > 0 ? sman->get_text_width(font, " ") : 0;

		// Check if adding this word would exceed max width
		if (current_line_width > 0 && current_line_width + space_width + base_word_width >= max_width) {
			// Line would be too long, start a new line
			this->text += current_line + "\n";
			current_line       = word;
			current_line_width = word_width;    // Use FULL width for tracking
		} else {
			// Word fits on the current line
			if (!current_line.empty()) {
				current_line += " ";
				current_line_width += space_width;
			}
			current_line += word;
			current_line_width += word_width;
		}
	}

	// Add the final line if there's anything left
	if (!current_line.empty()) {
		this->text += current_line;
	}
}

// Jump to the first entry (beginning of the notebook)
void Notebook_gump::jump_to_first_entry() {
	if (page_info.empty()) {
		page_info.emplace_back(0, 0);
	}
	curpage       = 0;
	curnote       = page_info[0].notenum;
	cursor.offset = 0;
	paint();
}

// Jump to the last entry (first page where the last note begins)
void Notebook_gump::jump_to_last_entry() {
	if (nb_note_count() == 0) {
		return;
	}
	const int last_idx = nb_note_count() - 1;

	// Reset to start so paint() builds page_info forward
	if (page_info.empty()) {
		page_info.emplace_back(0, 0);
	}
	curpage       = 0;
	curnote       = page_info[0].notenum;
	cursor.offset = 0;

	// Build page_info forward by painting subsequent pairs until we reach the
	// end Safety cap to avoid any accidental infinite loop
	for (int safety = 0; safety < 10000; ++safety) {
		paint();    // updates page_info and appends info for next pair (nxt)

		const int nxt = ((curpage & ~1) + 2);
		if (nxt >= static_cast<int>(page_info.size())) {
			break;    // reached end of mapped pages
		}
		curpage       = nxt;
		curnote       = page_info[curpage].notenum;
		cursor.offset = page_info[curpage].offset;
	}

	// Find the first page where the last note begins (offset == 0)
	int found = -1;
	for (int p = 0; p < static_cast<int>(page_info.size()); ++p) {
		if (page_info[p].notenum == last_idx && page_info[p].offset == 0) {
			found = p;
			break;
		}
	}
	// Fallback: any page containing the last note
	if (found < 0) {
		for (int p = static_cast<int>(page_info.size()) - 1; p >= 0; --p) {
			if (page_info[p].notenum == last_idx) {
				found = p;
				break;
			}
		}
	}
	if (found >= 0) {
		curpage       = found;
		curnote       = last_idx;
		cursor.offset = 0;
		paint();
	}
}
