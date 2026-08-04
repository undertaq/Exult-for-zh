# Auto-Note & Quest Journal Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full suite of auto-note and quest journal enhancements including category tags, live search/filter, quest status management, toast notifications, and HUD unread badges.

**Architecture:** Extend `One_note` data model with XML attributes for persistence; build filtering, bookmark tabs, search, and checkbox controls into `Notebook_gump`; trigger floating canvas toasts and SFX on auto-note creation.

**Tech Stack:** C++, Exult Gump UI framework, XML parser (`gamedat/notebook.xml`), SDL / Exult Audio system.

## Global Constraints
- XML schema changes must be backward-compatible with legacy save files (`gamedat/notebook.xml`).
- Visual styling must fit original Ultima VII notebook Gump boundaries.
- Support UTF-8 Chinese text parsing and searching (`Exult-for-zh`).

---

### Task 1: Data Model & XML Persistence (`One_note` Class)

**Files:**
- Modify: `gumps/Notebook_gump.h:28-40`
- Modify: `gumps/Notebook_gump.cc:87-165`

**Interfaces:**
- Consumes: Standard C++ STL `std::string`, `std::ostream`, `XML_Stack`
- Produces: Extended `One_note` fields (`category`, `is_completed`, `is_unread`) and backward-compatible XML reading/writing.

- [ ] **Step 1: Add NoteCategory enum and metadata members to One_note header**

Define `NoteCategory` enum (`GENERAL`, `QUEST`, `CLUE`, `LOCATION`, `NPC`) and add `category`, `is_completed`, `is_unread` fields to `One_note` in `gumps/Notebook_gump.h`.

- [ ] **Step 2: Update One_note constructor and initializer**

In `gumps/Notebook_gump.cc`, update `One_note` constructors and `set()` method to initialize `category` to `GENERAL`, `is_completed` to `false`, and `is_unread` to `false`.

- [ ] **Step 3: Update One_note::write() for XML serialization**

Modify `One_note::write(ostream& out)` in `gumps/Notebook_gump.cc:152-164` to write attributes on `<note>` tag:
```cpp
out << "<note category=\"" << category_to_string(category) 
    << "\" status=\"" << (is_completed ? "completed" : "active") 
    << "\" unread=\"" << (is_unread ? "true" : "false") << "\">" << endl;
```

- [ ] **Step 4: Update XML parser in Notebook_gump::read()**

In `Notebook_gump::read()` in `gumps/Notebook_gump.cc`, extract attributes from `<note>` tag if present, falling back to defaults if missing.

- [ ] **Step 5: Commit**

```bash
git add gumps/Notebook_gump.h gumps/Notebook_gump.cc
git commit -m "feat(notebook): extend One_note model and XML persistence with category and status"
```

---

### Task 2: Category Parsing & Auto-Text Processing

**Files:**
- Modify: `gumps/Notebook_gump.h:93-116`
- Modify: `gumps/Notebook_gump.cc:239-250`

**Interfaces:**
- Consumes: Task 1 `One_note` model and `NoteCategory` enum.
- Produces: Tag-aware auto-note creation function `add_gflag_text()`.

- [ ] **Step 1: Implement category tag parser helper**

Add helper function `parse_note_category(const std::string& text, NoteCategory& cat, std::string& clean_text)` in `gumps/Notebook_gump.cc` to extract prefix tags like `[Quest]`, `[Clue]`, `[Location]`, `[NPC]`.

- [ ] **Step 2: Update add_new() to set category and unread state**

Update `Notebook_gump::add_new()` to call `parse_note_category()` and mark newly auto-added notes as `is_unread = true`.

- [ ] **Step 3: Commit**

```bash
git add gumps/Notebook_gump.h gumps/Notebook_gump.cc
git commit -m "feat(notebook): implement prefix tag category parser for auto-notes"
```

---

### Task 3: Category Bookmark Tabs & Filtering Logic

**Files:**
- Modify: `gumps/Notebook_gump.h:46-78`
- Modify: `gumps/Notebook_gump.cc:300-450`

**Interfaces:**
- Consumes: Task 1 & 2 `One_note` categories.
- Produces: Tab navigation UI buttons and filtered `page_info` calculation.

- [ ] **Step 1: Add active_filter and filter tabs to Notebook_gump**

Add `NoteCategory filter_category` member and tab button handler methods to `Notebook_gump`.

- [ ] **Step 2: Update page calculation to respect active category filter**

Modify `Notebook_gump::paint()` and page-indexing logic to filter `notes` vector based on `filter_category` before calculating page splits.

- [ ] **Step 3: Render category bookmark tabs in paint()**

Draw category bookmark tab buttons (`[All]`, `[Quests]`, `[NPCs]`, `[Locations]`) along the top notebook margin.

- [ ] **Step 4: Commit**

```bash
git add gumps/Notebook_gump.h gumps/Notebook_gump.cc
git commit -m "feat(notebook): add category bookmark tabs and filtered page rendering"
```

---

### Task 4: Real-Time Text Search & Filtering

**Files:**
- Modify: `gumps/Notebook_gump.h:50-80`
- Modify: `gumps/Notebook_gump.cc:451-600`

**Interfaces:**
- Consumes: Task 3 filtering pipeline.
- Produces: Interactive search string buffer and query matching engine.

- [ ] **Step 1: Add search query buffer and keypress interceptor**

Add `std::string search_query` to `Notebook_gump`. Update `handle_kbd_event()` to intercept typing when search field is focused.

- [ ] **Step 2: Implement search filter predicate**

Add helper method `note_matches_query(const One_note* note, const std::string& query)` supporting case-insensitive UTF-8 substring searching.

- [ ] **Step 3: Render search bar in right-page header**

Draw search box input field in `Notebook_gump::paint()`.

- [ ] **Step 4: Commit**

```bash
git add gumps/Notebook_gump.h gumps/Notebook_gump.cc
git commit -m "feat(notebook): add real-time search input box and filter engine"
```

---

### Task 5: Quest Status Toggle & Completion Checkboxes

**Files:**
- Modify: `gumps/Notebook_gump.h:70-90`
- Modify: `gumps/Notebook_gump.cc:601-750`

**Interfaces:**
- Consumes: Task 1 `is_completed` field, Task 3 page painting logic.
- Produces: Interactive checkbox hit-detection and strikethrough/dimmed rendering.

- [ ] **Step 1: Add checkbox click hit handler in Gump mouse handling**

Update `Notebook_gump::on_button()` or mouse click handling to detect clicks on quest entry checkboxes (`[ ]` / `[✓]`), toggling `is_completed`.

- [ ] **Step 2: Render quest checkbox icons and dimmed text for completed quests**

Update `Notebook_gump::paint_page()` to render checkmark icons for quest entries and apply dimmed text styling when `is_completed == true`.

- [ ] **Step 3: Commit**

```bash
git add gumps/Notebook_gump.h gumps/Notebook_gump.cc
git commit -m "feat(notebook): add interactive quest completion checkmarks and dimmed text"
```

---

### Task 6: Toast Notification & HUD Badge Feedback

**Files:**
- Modify: `gumps/Notebook_gump.cc:900-1050`
- Modify: `gumps/Gump_manager.cc`

**Interfaces:**
- Consumes: Task 1 & 2 `is_unread` flag and `add_gflag_text()` triggers.
- Produces: Canvas floating notification toast, HUD unread counter, and page-flip SFX.

- [ ] **Step 1: Implement floating toast notification renderer**

Create canvas overlay helper in `Gump_manager` or `Notebook_gump` to draw sliding parchment toast: `"📖 Journal Updated: [Quest] ..."`.

- [ ] **Step 2: Trigger toast and SFX_PAGE_FLIP in add_gflag_text()**

Update `Notebook_gump::add_gflag_text()` to trigger SFX sound effect and spawn toast overlay upon note creation.

- [ ] **Step 3: Render unread count badge on HUD icon**

Update notebook shortcut bar icon rendering to draw red badge counter `🔴 N` when `unread_count > 0`.

- [ ] **Step 4: Commit**

```bash
git add gumps/Notebook_gump.cc gumps/Gump_manager.cc
git commit -m "feat(notebook): add floating toast notifications, HUD unread badge, and SFX trigger"
```
