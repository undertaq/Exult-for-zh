# Quest Map Marks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mark active quest destinations on the in-game paper map (opened via the map item / M key / `UI_display_map`), add a `[Map]` chip in the notebook that opens the map with that quest's marker highlighted, and deliver the journal auto-note content in BOTH English and Chinese, selected by the game's text-language menu setting (`config/audio/text/language`, via `BilingualManager`).

**Architecture:** Four coupled edits: (1) the notebook note model gains curated destination tile + related-NPC list, parsed from `[map=x,y]` / `[npc=A,B]` markers in auto-note text and persisted in notebook.xml; (2) the paper-map painter (`Paint_map` in usecode/intrinsics.cc) draws a marker for every active quest via a new static accessor `Notebook_gump::get_quest_markers()`, plus a new modal entry point `display_quest_map(focus)`; (3) the notebook paints a `[Map]` chip next to the completion checkbox (visible for active quest notes) that closes the notebook and opens the map with that note highlighted, and a per-language "相关："/"Related:" NPC line; (4) auto-note text loads bilingually — English resource `config/autonotes` (existing) plus a new Chinese resource `config/autonotes_zh` (+ patch overrides `autonotes.txt` / `autonotes_zh.txt`), chosen by `BilingualManager::get().get_text_language()`, with untranslated flags falling back to English so no note is ever dropped.

**Tech Stack:** C++ (Exult game engine fork, SDL2, VS2019 solution at `msvcstuff/vs2019/Exult.sln`), XML notebook persistence in gamedat (`notebook.xml`), bilingual text files (`data/bg/autonotes.txt` + new `data/bg/autonotes_zh.txt`), expack-packed `exult_bg.flx`/`exult_si.flx` from `data/*/flx.in`.

**Key facts verified in code (do not re-investigate):**
- Paper map display: `USECODE_INTRINSIC(display_map)` at `usecode/intrinsics.cc:1593`; `Paint_map`/`Paint_centered` at `usecode/intrinsics.cc:1533-1591`. The player-location cross is drawn only when a sextant is owned and the avatar is outdoors (usecode-side sextant count), via BG mapping `xx = lround(tx/16.05+5)`, `yy = lround(ty/15.95+4)`.
- Notebook model `One_note` is defined **inside** `gumps/Notebook_gump.cc:95` (private fields `tx,ty`, category, completed, unread; `friend class Notebook_gump`). XML write `One_note::write()` at `gumps/Notebook_gump.cc:262`; XML read in `Notebook_gump::read()` at `gumps/Notebook_gump.cc:1396`.
- Auto-note text flow: `ucinternal.cc:2875` → `Notebook_gump::add_gflag_text(gflag)` → `add_new_with_line_breaks()` at `gumps/Notebook_gump.cc:1345`. Category tag `[quest]`/`[任务]` etc. parsed by `parse_note_category()` at `gumps/Notebook_gump.cc:532`.
- Click lifecycle (drag.cc:69-110, 344-383): mouse-down → `gump->on_button(x,y)` (button pushed); mouse-up → `Dragging_info::drop` calls `button->unpush(); button->on_button(x,y); button->activate(Left)`, and **nothing dereferences the button after `activate()` returns** — safe for a button to `close_gump()` its own gump inside `activate()` (the gump dtor deletes the button mid-call, which is fine). Gump close = immediate delete (`Gump_manager::close_gump`, `gumps/Gump_manager.cc:214`).
- Checkbox precedent: quest completion checkbox painted in `paint_page()` (`gumps/Notebook_gump.cc:759-778`), hit-tested inline in `on_button()` (`gumps/Notebook_gump.cc:867-883`), click swallowed by returning the shapeless `Notebook_null_button` (`gumps/Notebook_gump.cc:365`).
- Text language: `BilingualManager::get().get_text_language()` (`bilingual_manager.h`, enum `TextLanguage { ENGLISH=0, CHINESE=1 }`), set from the AudioOptions text-language toggle (`config/audio/text/language`, `gumps/AudioOptions_gump.cc:710-713`). Used by `Spellbook_gump.cc:564`, `shapes/items.cc` for the same purpose.
- Auto-note text source: `data/bg/autonotes.txt` — `0x<hex>:<text>` lines, read via `Text_msg_file_reader::get_global_section_strings` (`files/msgfile.h:63`): entry `i` of the returned vector = global flag `i`; missing flags yield empty strings (so a Chinese file with the same flag ids gaps out cleanly). Flag-name-only lines render verbatim in the journal (the "too simple" complaint target).
- Resource wiring: `bggame.cc:159` `add_resource("config/autonotes", gameflx, EXULT_BG_FLX_AUTONOTES_TXT)`; index from `data/exult_bg_flx.h:20` (12) / `data/exult_si_flx.h:17` (9), generated positionally from `data/bg/flx.in` / `data/si/flx.in` (appending a file at the END of flx.in gets the next free index: 18 for BG, 22 for SI). `fnames.h:180-181` defines `AUTONOTES` / `PATCH_AUTONOTES` ("<PATCH>/autonotes.txt").
- Notebook reads: `read_auto_text()` (`gumps/Notebook_gump.cc:1488`) prefers `<PATCH>/autonotes.txt` when it exists, else the flx resource; `read_auto_text_file(const char*)` (`:1469`) is legacy with no callers — leave it alone.
- `Display_map` ceremony (hide touchui controls / Face_stats / ShortcutBar, paint, modal `Get_click`, restore) — replicate exactly as `display_map` does.

---

### Task 1: Note model — destination tile + related NPCs (data + persistence)

**Files:**
- Modify: `gumps/Notebook_gump.h`
- Modify: `gumps/Notebook_gump.cc`

- [ ] **Step 1: Add `Quest_marker` + declarations to `gumps/Notebook_gump.h`**

After the `string_to_note_category` inline function (line ~54), add:

```cpp
/*
 *  A quest's location for the world-map overlay.
 */
struct Quest_marker {
	int tx, ty;        // Destination tile.
	int note_index;    // Index into Notebook_gump's notes list.
	Quest_marker() : tx(0), ty(0), note_index(-1) {}
};
```

In the `private:` section of `Notebook_gump` (next to `null_button`, line ~93), add:

```cpp
	Gump_button* map_button     = nullptr;    // [Map] chip click handler.
	int          pending_map    = -1;         // notes[] index of the note whose
	//   [Map] chip was pressed, or -1.
```

Add `friend class Notebook_map_button;` next to the existing friend declarations (line 74-75).

In the `public:` section (after `add_gflag_text(gflag)` overload, line ~165), add:

```cpp
	static std::vector<Quest_marker> get_quest_markers();    // Active quests, newest first.
	static void invalidate_auto_text() {
		initialized_auto_text = false;
	}
```

After the class closing brace (line ~180), add:

```cpp
/*
 *  Modal paper-map display with quest markers; 'focus' is highlighted.
 *  Defined in usecode/intrinsics.cc. Closes no gumps itself.
 */
void display_quest_map(const Quest_marker& focus);
```

- [ ] **Step 2: Add `dest_x/dest_y/npcs` fields + accessors to `One_note`**

In `gumps/Notebook_gump.cc`, inside `One_note` (line ~95), after the `bool is_unread` member (line 104) add:

```cpp
	int          dest_x = -1, dest_y = -1;    // Curated map destination; <0 = none.
	string       npcs;                        // Related NPC names, comma separated.
```

After `set_unread()` (line ~138) add:

```cpp
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
```

- [ ] **Step 3: Persist the new fields — `One_note::write()`**

In `One_note::write()` (`gumps/Notebook_gump.cc:262`), after the `<place>` line (line 272) add:

```cpp
	if (dest_x >= 0 && dest_y >= 0) {
		out << "<dest> " << dest_x << ':' << dest_y << " </dest>" << endl;
	}
	if (!npcs.empty()) {
		out << "<npcs> " << npcs << " </npcs>" << endl;
	}
```

- [ ] **Step 4: Load the new fields — `Notebook_gump::read()`**

In `Notebook_gump::read()` (`gumps/Notebook_gump.cc:1396`), after the `note/place` handler (line 1448) add:

```cpp
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
		}
```

Old saves without `note/dest` / `note/npcs` load identically (fields default `-1` / empty).

- [ ] **Step 5: Marker parser — `[map=x,y]` and `[npc=a,b]`**

In `gumps/Notebook_gump.cc`, directly after `parse_note_category()` (line ~575), add:

```cpp
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
```

(`<cctype>`'s `tolower` is already used in this file at line 213, so no new include.)

- [ ] **Step 6: Wire the parser into both note-creation paths**

In `Notebook_gump::add_new()` (`gumps/Notebook_gump.cc:581`), replace the body between `string clean_text;` and the `One_note*` construction:

```cpp
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
```

In `Notebook_gump::add_new_with_line_breaks()` (`gumps/Notebook_gump.cc:1345`), replace the body between `string clean_text;` and `One_note* note =`:

```cpp
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
```

- [ ] **Step 7: Implement `get_quest_markers()`**

In `gumps/Notebook_gump.cc`, directly after `Notebook_gump::rebuild_visible()` (line ~237):

```cpp
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
```

(`n->tx`/`n->ty` are accessible: `Notebook_gump` is a friend of `One_note`.)

- [ ] **Step 8: Build check**

Build the `Exult` project from `msvcstuff/vs2019/Exult.sln` (Release x64) — or however you normally build this fork. Expected: compiles clean; no new warnings.

---

### Task 2: Paper-map painting — quest markers + new modal entry point

**Files:**
- Modify: `usecode/intrinsics.cc`

- [ ] **Step 1: Include the notebook header**

At the top of `usecode/intrinsics.cc`, after `#include "mouse.h"` (line 57), add:

```cpp
#include "Notebook_gump.h"
```

- [ ] **Step 2: Shared tile→pixel mapping helper + marker-aware `Paint_map`**

Replace the whole `Paint_map` class (lines 1556-1591) with:

```cpp
/*
 *  Convert world tile coords to pixel coords on the paper map.
 */
static void Map_tile_to_pixel(int tx, int ty, int& xx, int& yy) {
	if (Game::get_game_type() == BLACK_GATE) {
		xx = std::lround(tx / 16.05 + 5);
		yy = std::lround(ty / 15.95 + 4);
	} else if (Game::get_game_type() == SERPENT_ISLE) {
		xx = std::lround(tx / 16.0 + 18);
		yy = std::lround(ty / 16.0 + 9.4);
	} else {
		xx = std::lround(tx / 16.0 + 5);
		yy = std::lround(ty / 16.0 + 5);
	}
}

/*
 *  Paint map, optionally with active-quest markers. 'markers' points at
 *  a caller-owned vector; 'focus' points at one of its elements (or null)
 *  and is drawn bigger and in a different color.
 */
class Paint_map : public Paint_centered {
	bool                            show_loc;    // Draw the player-location cross.
	const std::vector<Quest_marker>* markers    = nullptr;
	const Quest_marker*              focus      = nullptr;

public:
	Paint_map(ShapeID* s, bool loc, const std::vector<Quest_marker>* marks = nullptr, const Quest_marker* foc = nullptr)
			: Paint_centered(s), show_loc(loc), markers(marks), focus(foc) {}

	void paint() override {
		Paint_centered::paint();
		const float   scale = get_ui_scale();
		Image_buffer* win   = gwin->get_win();
		Shape_frame*  s     = sid->get_shape();
		const int     xo    = x - s->get_xleft() * scale;
		const int     yo    = y - s->get_yabove() * scale;
		if (show_loc) {    // Mark player location.
			int              xx;
			int              yy;
			const Tile_coord t = gwin->get_main_actor()->get_tile();
			Map_tile_to_pixel(t.tx, t.ty, xx, yy);
			xx = xx * scale + xo;
			yy = yy * scale + yo;
			win->fill8(50, 1 * scale, 5 * scale, xx, yy - 2 * scale);
			win->fill8(50, 5 * scale, 1 * scale, xx - 2 * scale, yy);
		}
		if (markers) {    // Mark active quest destinations.
			for (const Quest_marker& m : *markers) {
				int mx;
				int my;
				Map_tile_to_pixel(m.tx, m.ty, mx, my);
				mx = mx * scale + xo;
				my = my * scale + yo;
				const bool is_focus = (&m == focus);
				const int  half     = is_focus ? 3 : 2;
				win->fill8(is_focus ? 54 : 52, half * 2 * scale, half * 2 * scale, mx - half * scale, my - half * scale);
			}
		}
	}
};
```

Color indices 52 (quest) / 54 (focus) sit in the same system-palette block as the existing cross color 50; if either is invisible on the test machine's palette, tweak only those two numbers.

- [ ] **Step 3: Wire markers into the `display_map` intrinsic**

In `USECODE_INTRINSIC(display_map)` (`usecode/intrinsics.cc:1593`), replace:

```cpp
	ShapeID   msid(game->get_shape("sprites/map"), 0, SF_SPRITES_VGA);
	Paint_map map(&msid, loc);
```

with:

```cpp
	ShapeID                    msid(game->get_shape("sprites/map"), 0, SF_SPRITES_VGA);
	std::vector<Quest_marker>  marks = Notebook_gump::get_quest_markers();
	Paint_map                  map(&msid, loc, &marks);
```

(Empty journal → empty vector → identical behavior to today. The local `marks` outlives the modal `Get_click`, during which `Paint_map::paint` runs every frame.)

- [ ] **Step 4: New modal entry point `display_quest_map`**

Directly after the `display_map` intrinsic body (after line ~1633), add:

```cpp
/*
 *  Modal paper map with active quests marked and one destination
 *  highlighted. Called from the notebook's [Map] chip; the notebook must
 *  already be closed.
 */
void display_quest_map(const Quest_marker& focus) {
	if (touchui != nullptr) {
		touchui->hideGameControls();
	}
	if (Face_stats::Visible()) {
		Face_stats::HideGump();
	}
	if (ShortcutBar_gump::Visible()) {
		ShortcutBar_gump::HideGump();
	}
	gwin->paint();
	ShapeID                    msid(game->get_shape("sprites/map"), 0, SF_SPRITES_VGA);
	std::vector<Quest_marker>  marks = Notebook_gump::get_quest_markers();
	const Quest_marker*        foc   = nullptr;
	for (const Quest_marker& m : marks) {
		if (m.note_index == focus.note_index) {
			foc = &m;
			break;
		}
	}
	Paint_map map(&msid, false, &marks, foc);
	int       xx;
	int       yy;
	Get_click(xx, yy, Mouse::hand, nullptr, false, &map);
	gwin->paint();
	if (touchui != nullptr) {
		Gump_manager* gumpman = gwin->get_gump_man();
		if (!gumpman->gump_mode()) {
			touchui->showGameControls();
		}
	}
	if (!Face_stats::Visible()) {
		Face_stats::ShowGump();
	}
	if (!ShortcutBar_gump::Visible()) {
		ShortcutBar_gump::ShowGump();
	}
	gwin->paint();
}
```

The signature must match the declaration added in Task 1 Step 1.

- [ ] **Step 5: Build check**

Build again. Expected: compiles clean.

---

### Task 3: Notebook UI — `[Map]` chip, click handling, related-NPC line

**Files:**
- Modify: `gumps/Notebook_gump.cc`

- [ ] **Step 1: Include bilingual manager**

In `gumps/Notebook_gump.cc`, after `#include "Audio.h"` (line 30), add:

```cpp
#include "bilingual_manager.h"
```

- [ ] **Step 2: `Notebook_map_button` class**

Right after `Notebook_null_button` (line ~373), add:

```cpp
/*
 *  Shapeless button returned when the [Map] chip on a quest note is
 *  pressed. The chip itself is hit-tested (and this note recorded) inside
 *  Notebook_gump::on_button; on mouse release we close the notebook and
 *  open the quest map. Self-closing inside activate() is safe: the click
 *  dispatcher (Dragging_info::drop) dereferences nothing after activate
 *  returns.
 */
class Notebook_map_button : public Gump_button {
public:
	Notebook_map_button(Gump* par) : Gump_button(par, -1, 0, 0) {}

	bool on_widget(int mx, int my) const override {
		ignore_unused_variable_warning(mx, my);
		return true;    // Release anywhere still fires activate().
	}

	bool activate(MouseButton button) override;
};

bool Notebook_map_button::activate(MouseButton button) {
	if (button != MouseButton::Left) {
		return false;
	}
	Notebook_gump* nb = static_cast<Notebook_gump*>(parent);
	if (nb->pending_map < 0) {
		return true;
	}
	const int idx = nb->pending_map;
	nb->pending_map = -1;
	std::vector<Quest_marker> marks = Notebook_gump::get_quest_markers();
	for (const Quest_marker& m : marks) {
		if (m.note_index == idx) {
			// Deletes nb (and this button); safe as argued above.
			gwin->get_gump_man()->close_gump(nb);
			display_quest_map(m);
			break;
		}
	}
	return true;
}
```

- [ ] **Step 3: Create/destroy the button in the gump ctor/dtor**

In `Notebook_gump::Notebook_gump()` (`gumps/Notebook_gump.cc:599`), after `null_button = new Notebook_null_button(this);` (line 633) add:

```cpp
	map_button = new Notebook_map_button(this);
```

In `Notebook_gump::~Notebook_gump()` (`gumps/Notebook_gump.cc:673`), after `delete null_button; null_button = nullptr;` (lines 688-689) add:

```cpp
	delete map_button;
	map_button = nullptr;
```

- [ ] **Step 4: Hit-test the chip in `on_button()`**

In `Notebook_gump::on_button()` (`gumps/Notebook_gump.cc:847`), replace the quest-checkbox block (lines 867-883) with:

```cpp
	// Quest completion checkbox + [Map] chip on the note-info row of the
	// left page.
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
			if (n->get_category() == NoteCategory::QUEST && !n->get_completed()
				&& TileRect(box.x + box.w - 43, box.y - 12, 18, 9).has_point(mx, my)) {
				pending_map = visible[notenum];    // notes[] index for later lookup.
				return map_button;                // Opens the map on release.
			}
		}
	}
```

`visible[notenum]` is safe: this block only runs while `visible` is the live filter result (both are rebuilt together in `reset_view()`).

- [ ] **Step 5: Paint the chip and the related-NPC line in `paint_page()`**

In `Notebook_gump::paint_page()` (`gumps/Notebook_gump.cc:716`), after the quest-checkbox painting block (after line 778, still inside `if (offset == 0)`), add:

```cpp
		// "[Map]" chip: opens the world map with this quest's destination
		// marked (active quests only, mirroring the checkbox's row).
		if (note->get_category() == NoteCategory::QUEST && !note->get_completed()) {
			const int mpx = x + box.x + box.w - 43;
			const int mpy = y + pagey;
			const int blk = sman->get_special_pixel(BLACK_PIXEL);
			const int pap = sman->get_special_pixel(PROTECT_PIXEL);
			gwin->get_win()->fill8(pap, 18, 9, mpx, mpy);
			gwin->get_win()->fill8(blk, 18, 1, mpx, mpy);
			gwin->get_win()->fill8(blk, 18, 1, mpx, mpy + 8);
			gwin->get_win()->fill8(blk, 1, 9, mpx, mpy);
			gwin->get_win()->fill8(blk, 1, 9, mpx + 17, mpy);
			sman->paint_text(4, "Map", mpx + (18 - sman->get_text_width(4, "Map")) / 2, mpy + 1);
		}
```

Then, after the text-painting block, right after the line `offset = str - note->text.c_str();    // Return offset past end.` (line ~805) and before `// Watch for exactly filling page.`, add:

```cpp
	// Related-NPC line under the text (paint_text_box reported the text
	// height in endoff when the note finished on this page). Label follows
	// the game's text-language setting.
	if (endoff > 0 && endoff < box.h && !note->get_npcs().empty()) {
		const bool      zh = BilingualManager::get().get_text_language() == TextLanguage::CHINESE;
		const string    rel = (zh ? "相关：" : "Related: ") + note->get_npcs();
		if (dim_trans) {
			sman->get_font(4)->paint_text(
					gwin->get_win()->get_ib8(), rel.c_str(), x + box.x, y + box.y + endoff, const_cast<unsigned char*>(dim_trans));
		} else {
			sman->paint_text(4, rel.c_str(), x + box.x, y + box.y + endoff);
		}
	}
```

- [ ] **Step 6: Build check**

Build again. Expected: compiles clean.

---

### Task 4: Bilingual auto-note loading (code)

**Files:**
- Modify: `fnames.h`
- Modify: `data/bg/flx.in`
- Modify: `data/si/flx.in`
- Modify: `data/exult_bg_flx.h`
- Modify: `data/exult_si_flx.h`
- Modify: `gamemgr/bggame.cc`
- Modify: `gamemgr/sigame.cc`
- Modify: `data/Makefile.am`
- Modify: `gumps/Notebook_gump.cc`
- Modify: `gumps/AudioOptions_gump.cc`

- [ ] **Step 1: New file-name macros**

In `fnames.h` (after line 181), add:

```cpp
#define AUTONOTES_ZH     "autonotes_zh.txt"
#define PATCH_AUTONOTES_ZH "<PATCH>/autonotes_zh.txt"
```

- [ ] **Step 2: Pack the new files into the flx archives**

Append this line at the END of `data/bg/flx.in` (after `global_flags.txt`, line 19):

```text
autonotes_zh.txt
```

Append the same at the END of `data/si/flx.in`.

Append to the END of `data/exult_bg_flx.h` (before the CRC32 define, line 27):

```cpp
#define	EXULT_BG_FLX_AUTONOTES_ZH_TXT		18
```

Append to the END of `data/exult_si_flx.h` (before the CRC32 define, line 30):

```cpp
#define	EXULT_SI_FLX_AUTONOTES_ZH_TXT		22
```

(The headers are positionally generated by expack at data-build time from flx.in order; appending at the end keeps every existing index stable and the regenerated header matches what was written manually.)

- [ ] **Step 3: Register the new resources**

In `gamemgr/bggame.cc` (after line 159), add:

```cpp
		add_resource("config/autonotes_zh", gameflx, EXULT_BG_FLX_AUTONOTES_ZH_TXT);
```

In `gamemgr/sigame.cc` (after line 139), add:

```cpp
		add_resource("config/autonotes_zh", gameflx, EXULT_SI_FLX_AUTONOTES_ZH_TXT);
```

- [ ] **Step 4: Dist-list the new files for autotools**

In `data/Makefile.am`, next to the existing `autonotes.txt` references, add the `autonotes_zh.txt` entries for both BG and SI file lists (match the surrounding file-list style).

- [ ] **Step 5: Language-aware loading — `Notebook_gump::read_auto_text()`**

In `gumps/Notebook_gump.cc`, replace the whole `read_auto_text()` function (lines 1488-1508) with:

```cpp
/*
 *  Load an autonote file, preferring the <PATCH> override, else the
 *  bundled flx resource. Returns false if neither exists.
 */
static bool Load_autonotes(const char* patch_path, const char* resource_key, std::vector<string>& out) {
	if (is_system_path_defined("<PATCH>") && U7exists(patch_path)) {
		cout << "Loading patch autonotes: " << patch_path << endl;
		IFileDataSource notesfile(patch_path, true);
		if (notesfile.good()) {
			Text_msg_file_reader reader(notesfile);
			reader.get_global_section_strings(out);
			return true;
		}
	}
	const str_int_pair& resource = game->get_resource(resource_key);
	IExultDataSource    notesfile(resource.str, resource.num);
	if (notesfile.good()) {
		cout << "Loading autonotes resource: " << resource_key << endl;
		Text_msg_file_reader reader(notesfile);
		reader.get_global_section_strings(out);
		return true;
	}
	return false;
}

// read in from flx bundled file (or <PATCH> overrides)
void Notebook_gump::read_auto_text() {
	if (gwin->get_allow_autonotes()) {
		initialized_auto_text = true;
		std::vector<string> en;
		std::vector<string> zh;
		const bool have_en = Load_autonotes(PATCH_AUTONOTES, "config/autonotes", en);
		const bool have_zh = Load_autonotes(PATCH_AUTONOTES_ZH, "config/autonotes_zh", zh);
		auto_text.clear();
		if (BilingualManager::get().get_text_language() == TextLanguage::CHINESE && have_zh) {
			// Chinese wins; untranslated flags fall back to English so no
			// note is ever dropped (missing entries arrive as "").
			if (have_en) {
				const size_t n = std::max(en.size(), zh.size());
				auto_text.reserve(n);
				for (size_t i = 0; i < n; ++i) {
					const bool zh_empty = i >= zh.size() || zh[i].empty();
					auto_text.push_back(zh_empty && i < en.size() ? en[i] : (i < zh.size() ? zh[i] : std::string()));
				}
			} else {
				auto_text = std::move(zh);
			}
		} else if (have_en) {
			auto_text = std::move(en);
		} else if (have_zh) {
			auto_text = std::move(zh);
		}
	}
}
```

Leave `read_auto_text_file(const char*)` (line 1469) untouched — it has no callers; its purpose is fully covered by `read_auto_text()` + `Load_autonotes`.

- [ ] **Step 6: Refresh the language cache when the option changes**

In `gumps/AudioOptions_gump.cc`, in the text-language toggle (lines 710-713, where `BilingualManager::get().set_text_language(...)` is called), add after the `set_text_language` call:

```cpp
		// New auto-notes (journal flags set from now on) use the new
		// language; already-written notes keep their text.
		Notebook_gump::invalidate_auto_text();
```

Add `#include "Notebook_gump.h"` to `gumps/AudioOptions_gump.cc` if not already present (check the include block first).

- [ ] **Step 7: Build check**

Build the `Exult` project AND the data project (the data build regenerates `exult_bg.flx`/`exult_si.flx` via expack from flx.in — make sure the regenerated flx headers still contain the `_ZH_TXT` defines you added manually; they will, per Step 2's ordering argument). Verify with `expack -p <path>/exult_bg.flx` (or the data project's pack output) that `autonotes_zh.txt` is listed. Expected: compiles clean.

---

### Task 5: Manual verification (game run)

No unit-test harness exists for gump/notebook code in this fork (notebook reads `gamedat/notebook.xml` live); verification is a scripted game run. Play as usual (BG savegame under `blackgate/`, run `Exult.exe`, with the built `exult_bg.flx` in the game's data dir or `autonotes_zh.txt` dropped into `<PATCH>/`).

- [ ] **Step 1: Baseline — map + notebook unchanged**

Start a new BG game, open the journal with quest entries (`[Map]` chip absent for completed/non-quest notes; present for active quest notes). Press M (or use the paper map item): map opens, player cross only appears with a sextant — unchanged.

- [ ] **Step 2: Quest markers on the M-key map**

Carry a sextant, be outdoors, open the map (M key). Expected: one small marker (color 52) at Trinsic/current quest location in addition to the magenta cross. Complete the quest (checkbox), reopen the map: marker is gone.

- [ ] **Step 3: `[Map]` chip from the notebook**

With an active quest displayed at the top of the left page, click its `[Map]` chip. Expected: notebook closes, map opens centered, highlighted focus marker (color 54, larger) at that quest's location, other active quests marked smaller. Any click closes the map and restores the game view.

- [ ] **Step 4: Related-NPC line — English**

With text language = English (options > audio > text language = en): journal shows `Related: Finnigan,Christopher` in English beneath the text.

- [ ] **Step 5: Related-NPC line — Chinese**

In the options menu switch text language to zh (restart not required; this is the menu setting from `config/audio/text/language`). Start a NEW game so journal flags fire after the switch, or toggle the language before the relevant flags are set. Expected: `相关：Finnigan,Christopher` (Chinese label) under Chinese notes; untranslated flags (entries missing from `autonotes_zh.txt`) still show their English text instead of disappearing.

- [ ] **Step 6: `[map=x,y]` destination override**

With the cheat menu, note the avatar's tile coords. Temporarily edit the BG source or `<PATCH>/autonotes_zh.txt` test entry to `[map=<tx>,<ty>]` where `<tx>,<ty>` are the avatar's own coords, start a new game, stand still, open the map via M: the quest marker must overlap the player cross exactly (same point). Then remove the temp entry.

- [ ] **Step 7: Save/load round-trip**

Add + complete a quest, close the journal, quit, relaunch: note state (dest/npcs/completed) survives; `notebook.xml` contains `<dest>`/`<npcs>` for tagged notes.

Fix any failures (marker color visibility, chip layout) at this point; color tweaks are single-number edits in Task 2's `Paint_map`.

---

### Task 6: English content pass — restore flag-name lines in `data/bg/autonotes.txt`

**Files:**
- Modify: `data/bg/autonotes.txt`

Only flag-name-only lines are rewritten (full-sentence lines stay). Format stays `0x<hex>:<text>`; one line per flag; `[npc=...]` markers go at the very end of the line (the parser strips them; keep tags at line ends so removal doesn't glue words together). NPC names are the game's English names — they double as a search key.

- [ ] **Step 1: Replace these flag-name lines with the exact text below**

The target lines currently read exactly `0x14:MET_IOLO`, `0x15:MET_SPARK`, etc. (verify each before editing):

```text
0x14: I met my old friend Iolo. [npc=Iolo]
0x15: I met a boy named Spark in Trinsic. [npc=Spark]
0x16: I met Shamino. [npc=Shamino]
0x17: I met Dupre. [npc=Dupre]
0x19: I met a man called Trellek. [npc=Trellek]
0x1A: I met a quiet man named Sentri, who has joined me. [npc=Sentri]
0x1C: I met Katrina. [npc=Katrina]
0x1D: I met Tseramed. [npc=Tseramed]
0x3B: I woke up in Trinsic; a murder investigation begins here. [npc=Finnigan,Spark]
0x41: Klog told me the Avatar should travel with companions. [npc=Klog]
0x46: I told Spark my name. [npc=Spark]
0x47: I told Spark that I am the Avatar. [npc=Spark]
0x49: Spark asked to join my party. [npc=Spark]
0x4A: Captain Gargan said he once sailed the seas. [npc=Gargan]
0x4B: I met Petre. [npc=Petre]
0x4D: I met Gilberto. [npc=Gilberto]
0x4E: I met Johnson. [npc=Johnson]
0x4F: I met Klog. [npc=Klog]
0x50: I met Ellen. [npc=Ellen]
0x51: I met Apollonia. [npc=Apollonia]
0x53: I met Dell. [npc=Dell]
```

Leave all other lines untouched in this pass. (Sections beyond the Trinsic block keep their flag names — a later content pass can widen coverage; the mechanism is identical.)

- [ ] **Step 2: Verify**

Start a new game with text language = English; each `MET_*`/Trinsic flag now appears as a full sentence with a `Related:` NPC line (Task 5 Step 4 covers the check).

---

### Task 7: Chinese content — create `data/bg/autonotes_zh.txt` and `data/si/autonotes_zh.txt`

**Files:**
- Create: `data/bg/autonotes_zh.txt`
- Create: `data/si/autonotes_zh.txt`

English keeps the "source of truth" text; the zh files carry the SAME flag ids with Chinese text. Missing ids → English fallback (Task 4 Step 5), so partial coverage is safe.

- [ ] **Step 1: Create `data/bg/autonotes_zh.txt`**

Start with a header comment explaining the file (same style as `autonotes.txt`, e.g. `# Chinese translations of the journal auto-notes.` + one line about the fallback). Then add the 22 entries from Task 6 Step 1 with Chinese text, `[npc=]` markers kept identical:

```text
0x14: 我遇见了老友伊欧洛（Iolo）。[npc=Iolo]
0x15: 我在特林蒂克遇到了男孩火花（Spark）。[npc=Spark]
0x16: 我遇见了沙米诺（Shamino）。[npc=Shamino]
0x17: 我遇见了杜普雷（Dupre）。[npc=Dupre]
0x19: 我遇见了一个叫特雷莱克（Trellek）的人。[npc=Trellek]
0x1A: 我遇见了一位沉默的伙伴哨兵（Sentri），他已加入我的队伍。[npc=Sentri]
0x1C: 我遇见了卡特里娜（Katrina）。[npc=Katrina]
0x1D: 我遇见了茨塞拉梅德（Tseramed）。[npc=Tseramed]
0x3B: 我在特林蒂克醒来，一场谋杀案的调查由此展开。[npc=Finnigan,Spark]
0x41: 克洛格（Klog）告诉我，圣者应当与同伴一同行动。[npc=Klog]
0x46: 我告诉了火花我的名字。[npc=Spark]
0x47: 我告诉火花我是圣者。[npc=Spark]
0x49: 火花请求加入我的队伍。[npc=Spark]
0x4A: 船长加尔甘（Gargan）说他曾扬帆远航。[npc=Gargan]
0x4B: 我遇见了彼得（Petre）。[npc=Petre]
0x4D: 我遇见了吉尔伯托（Gilberto）。[npc=Gilberto]
0x4E: 我遇见了约翰逊（Johnson）。[npc=Johnson]
0x4F: 我遇见了克洛格（Klog）。[npc=Klog]
0x50: 我遇见了艾琳（Ellen）。[npc=Ellen]
0x51: 我遇见了阿波罗妮亚（Apollonia）。[npc=Apollonia]
0x53: 我遇见了戴尔（Dell）。[npc=Dell]
```

Then translate the existing English sentence lines whose meaning is clear and stable, keeping their flag ids — at least these (verify the English text still matches the current file before translating): `0x29`, `0x32`, `0x35`, `0x39`, `0x3C`, `0x3E`, `0x40`, `0x42`, `0x43`, `0x45`, `0x83` — translate each as a natural Chinese sentence, no `[npc=]` unless already present in the English line.

- [ ] **Step 2: Create `data/si/autonotes_zh.txt`**

Open `data/si/autonotes.txt` first. Translate its `MET_*`/`MEET_*` and other flag-name-only lines using the same `0xNN: <Chinese>. [npc=X]` scheme (flag ids come from the SI file itself). If an SI flag's meaning is unclear, skip it — English fallback covers it.

- [ ] **Step 3: Verify (both languages)**

With text language = zh: journal shows Chinese sentences + `相关：` labels; flags absent from the zh file still appear (English fallback). With text language = en: English file is used unchanged. (Task 5 Steps 4-5 cover the checks.)

---

## Self-review

- **Spec coverage:** design items 1 (data: dest + npcs, XML, parser) = Task 1; item 2 (markers in `display_map` + focus highlight + modal entry) = Task 2; item 3 (notebook `[Map]` chip + per-language related line) = Task 3; item 4 (bilingual loading: resources, flx packing, patch overrides, fallback, language-switch cache refresh) = Task 4; verification = Task 5; English content = Task 6; Chinese content = Task 7. Sextant gating of the player cross is untouched (only the M-key path's `loc` flag drives it); quest markers always show. English fallback guarantees no note is dropped in Chinese mode even for untranslated flags (empty-string entries from `get_global_section_strings`).
- **Placeholder scan:** every step contains complete code or exact text; no TBDs. The only runtime judgment calls (marker colors 52/54; which SI flags to translate) have explicit test steps and single-number fix paths.
- **Type consistency:** `Quest_marker` (Task 1) is used by `get_quest_markers` (Task 1), `Paint_map`/`display_quest_map` (Task 2), and `Notebook_map_button` (Task 3) — same struct, same fields (`tx,ty,note_index`). `note_index` is a `notes[]` index everywhere: written as `i` in `get_quest_markers`, written as `visible[notenum]` in `on_button`, read as `nb->pending_map` in `activate`. `display_quest_map(const Quest_marker&)` declared in the header (Task 1) and defined with the same signature (Task 2). `map_button`/`pending_map` members added in Task 1 Step 1, used in Tasks 1-3. `invalidate_auto_text()` declared in Task 1, called in Task 4. `TextLanguage::CHINESE`/`ENGLISH` used in Tasks 3 and 4 from `bilingual_manager.h`; includes added where used. `AUTONOTES_ZH`/`PATCH_AUTONOTES_ZH` defined in Task 4 and consumed in the same task; `EXULT_BG_FLX_AUTONOTES_ZH_TXT` (18) / `EXULT_SI_FLX_AUTONOTES_ZH_TXT` (22) match the append positions in flx.in.

**Plan complete and saved to `docs/superpowers/plans/2026-08-10-quest-map-marks.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**