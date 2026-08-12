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

#ifndef NOTEBOOK_GUMP_H
#define NOTEBOOK_GUMP_H

#include "Gump.h"
#include "font.h"

#include <string>
#include <vector>

class One_note;

enum class NoteCategory {
	GENERAL = 0,
	QUEST,
	JOURNEY,
	CLUE,
	LOCATION,
	NPC
};

inline const char* note_category_to_string(NoteCategory cat) {
	switch (cat) {
		case NoteCategory::QUEST: return "quest";
		case NoteCategory::JOURNEY: return "journey";
		case NoteCategory::CLUE: return "clue";
		case NoteCategory::LOCATION: return "location";
		case NoteCategory::NPC: return "npc";
		default: return "general";
	}
}

inline NoteCategory string_to_note_category(const std::string& str) {
	if (str == "quest") return NoteCategory::QUEST;
	if (str == "journey") return NoteCategory::JOURNEY;
	if (str == "clue") return NoteCategory::CLUE;
	if (str == "location") return NoteCategory::LOCATION;
	if (str == "npc") return NoteCategory::NPC;
	return NoteCategory::GENERAL;
}

/*
 *  A quest's location for the world-map overlay.
 */
struct Quest_marker {
	int tx, ty;        // Destination tile.
	int note_index;    // Index into Notebook_gump's notes list.
	Quest_marker() : tx(0), ty(0), note_index(-1) {}
};


/*
 *  Info. for top of a page.
 */
class Notebook_top {
	int notenum;
	int offset;

public:
	friend class Notebook_gump;

	Notebook_top(int n = 0, int o = 0) : notenum(n), offset(o) {}
};

/*
 *  A notebook gump represents the in-game journal.
 */
class Notebook_gump : public Gump {
	friend class Notebook_chip_button;
	friend class Notebook_null_button;
	friend class Notebook_map_button;
	static std::vector<One_note*> notes;    // The text.
	// Indexed by page#.
	static std::vector<Notebook_top> page_info;
	static Notebook_gump*            instance;
	static bool                      initialized;
	static bool                      initialized_auto_text;
	static std::vector<std::string>  auto_text;      // Auto-text for global flags.
	int                              curnote = 0;    // Current note # being edited.
	int                              curpage = 0;    // Current page # (from 0).
	Cursor_info                      cursor;         // Cursor loc. within current note.
	int                              updnx = 0;      // X-coord. for up/down arrows.
	// Page turners:
	Gump_button *leftpage, *rightpage;
	// Bottom-strip UI: 6 category tabs, search box, hide-completed toggle.
	Gump_button* tab_buttons[6] = {};
	Gump_button* search_button  = nullptr;
	Gump_button* toggle_button  = nullptr;
	Gump_button* null_button    = nullptr;    // Swallows clicks on the checkbox.
	Gump_button* map_button     = nullptr;    // [Map] chip click handler.
	int          pending_map    = -1;         // notes[] index of the note whose
	//   [Map] chip was pressed, or -1.
	bool         search_focused = false;    // Interactive search box has focus.
	// Add new note.
	static void add_new(const std::string& text, int gflag = -1);
	bool        paint_page(const TileRect& box, One_note* note, int& offset, int pagenum);

	bool need_next_page() const {
		return curpage % 2 == 1 && curpage < static_cast<int>(page_info.size()) - 1 && page_info[curpage + 1].offset > 0
			   && cursor.offset >= page_info[curpage + 1].offset;
	}

	void prev_page();
	void next_page();
	bool on_last_page_line();
	bool on_first_page_line();
	void up_arrow();
	void down_arrow();
	void jump_to_first_entry();
	void jump_to_last_entry();

	static NoteCategory active_filter;
	static std::string  search_query;
	static bool         show_completed;
	static int          unread_count;
	static bool         dirty;    // True when notes changed and need saving.
	// Index into notes[] of the notes that pass the current filter,
	// in display order. Empty means all notes are visible.
	static std::vector<int> visible;

	static void set_filter(NoteCategory cat) { active_filter = cat; }
	static NoteCategory get_filter() { return active_filter; }
	static const std::string& get_search_query() { return search_query; }
	static void set_search_query(const std::string& q) { search_query = q; }
	static bool note_matches_filter(const One_note* note);
	// Rebuild the visible list after filter/search/status changes.
	static void rebuild_visible();
	// Number of notes currently visible (subject to filter/search/status).
	static int nb_note_count() {
		return visible.empty() ? 0 : static_cast<int>(visible.size());
	}
	// Map a visible index to the underlying note.
	static One_note* nb_note(int i) {
		return notes[visible[i]];
	}

public:
	static int get_unread_count();
	Notebook_gump();
	~Notebook_gump() override;
	static void           clear();
	static Notebook_gump* create();

	static Notebook_gump* get_instance() {
		return instance;
	}

	void change_page(int delta);    // Page forward/backward.
	// Reset paging and repaint after visibility changed.
	void reset_view();
	// Is a given point on a button?
	Gump_button* on_button(int mx, int my) override;
	void         paint() override;    // Paint it and its contents.
	bool         handle_kbd_event(void* ev) override;
	static void  add_gflag_text(int gflag, const std::string& text);

	static void add_gflag_text(int gflag) {
		if (!initialized_auto_text) {
			read_auto_text();
		}
		if (gflag < static_cast<int>(auto_text.size()) && !auto_text[gflag].empty()) {
			add_gflag_text(gflag, auto_text[gflag]);
		}
	}

	static std::vector<Quest_marker> get_quest_markers();    // Active quests, newest first.
	static void invalidate_auto_text() {
		initialized_auto_text = false;
	}

	bool is_draggable() const override {
		return false;
	}

	bool        word_exceeds_line_length(const std::string& text, int offset, int curpage);
	void        add_new_with_line_breaks(const std::string& text, int gflag);
	std::string get_next_line(const std::string& text);
	static void initialize();
	static void write();    // Write it out to gamedat.
	static void read();     // Read it in.
	static void read_auto_text();
	static void read_auto_text_file(const char* filename);
};

/*
 *  Modal paper-map display with quest markers; 'focus' is highlighted.
 *  Defined in usecode/intrinsics.cc. Closes no gumps itself.
 */
void display_quest_map(const Quest_marker& focus);

#endif
