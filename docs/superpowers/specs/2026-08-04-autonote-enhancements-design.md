# Auto-Note & Quest Journal Enhancements Design Document

**Date**: 2026-08-04  
**Status**: Approved  
**Target Component**: Exult Notebook Gump & Auto-Note System (`gumps/Notebook_gump.h`, `gumps/Notebook_gump.cc`)

---

## 1. Overview

This document specifies the design for the full suite of Auto-Note & Quest Journal enhancements in Exult (`Exult-for-zh`). The goal is to modernize the in-game journal with categorized auto-notes, real-time search and filter capabilities, quest completion tracking, on-screen toast notifications, and HUD unread badges—all while preserving full backward compatibility with existing Ultima VII save files and visual styling.

---

## 2. Architecture & Data Model

### 2.1 Note Structure (`One_note`)

The `One_note` class in `gumps/Notebook_gump.h` is extended with structured metadata fields:

```cpp
enum class NoteCategory {
    GENERAL = 0,
    QUEST,
    CLUE,
    LOCATION,
    NPC
};

class One_note {
public:
    std::string title;
    std::string text;
    int time_hour;
    int time_minute;
    int time_second;
    int pos_x;
    int pos_y;
    int gflag;
    
    // New Metadata Fields
    NoteCategory category = NoteCategory::GENERAL;
    bool is_completed = false;
    bool is_unread = false;
};
```

### 2.2 Category Parsing

Auto-notes loaded from `autonotes` text configurations or added programmatically via `Notebook_gump::add_gflag_text()` parse category tags at the beginning of the text string:
- `[Quest] ...` -> `NoteCategory::QUEST`
- `[Clue] ...` -> `NoteCategory::CLUE`
- `[Location] ...` -> `NoteCategory::LOCATION`
- `[NPC] ...` -> `NoteCategory::NPC`
- Default (no tag or manual player note) -> `NoteCategory::GENERAL`

---

## 3. Data & Persistence (XML Serialization)

`One_note::write()` and `Notebook_gump::read()` are updated to serialize and deserialize the new fields as optional attributes on the `<note>` XML element:

```xml
<notebook>
  <page num="1">
    <note category="quest" status="completed" unread="false">
      <time>5:14:30</time>
      <place>832:1024</place>
      <gflag>128</gflag>
      <text>[Quest] Lord British requested assistance with the gargoyle embassy.</text>
    </note>
  </page>
</notebook>
```

### Compatibility Rules
- When loading legacy save files lacking XML attributes on `<note>`, fields default to:
  - `category = GENERAL`
  - `is_completed = false`
  - `is_unread = false`
- Forward compatibility: Standard XML parsers ignore unrecognised attributes if loaded in older versions.

---

## 4. User Interface & Controls

### 4.1 Category Bookmark Tabs
- **Tabs**: `[All]`, `[Quests]`, `[NPCs]`, `[Locations]`, `[Clues]`
- Mounted along the top border of the `Notebook_gump` window.
- Selecting a tab filters active page rendering and page-cycling indices so scrolling only navigates notes in the selected category.

### 4.2 Real-time Search & Filter
- An interactive search input box added to the right-page header.
- Typing performs case-insensitive substring matching against note titles, text content, and location coordinates (supporting both UTF-8 Chinese and ASCII English).

### 4.3 Quest Status Management (`[ ]` / `[✓]`)
- Notes categorized as `QUEST` feature an interactive checkmark toggle icon next to their entry.
- Clicking the checkbox toggles `is_completed` (`Active` ↔ `Completed`).
- Completed entries are visually styled with dimmed text.
- A toggle switch in the UI allows hiding/showing completed quests.

### 4.4 Unread Entry Highlighting
- Automatically added notes set `is_unread = true`.
- Unread notes display a `"NEW"` badge tag or marker. Viewing the page resets `is_unread = false`.

---

## 5. Notifications & HUD Feedback

### 5.1 On-Screen Toast Notification
- Triggered when `Notebook_gump::add_gflag_text()` or `add_note()` adds an auto-note during gameplay.
- Displays a top-center sliding parchment banner on the game canvas:
  `📖 Journal Updated: [Quest] Lord British's Request`
- Automatically slides out after 3 seconds. Clicking the toast opens the Notebook to that note.

### 5.2 HUD Icon Badge
- A badge showing the unread count (`🔴 N`) overlays the Notebook icon in the HUD shortcut bar when `unread_count > 0`.

### 5.3 Audio Cue
- Triggers `SFX_PAGE_FLIP` sound effect when an auto-note is added.

---

## 6. Verification & Testing Plan

1. **XML Persistence**:
   - Save and reload game with active, completed, and unread notes across different categories. Ensure attributes persist correctly.
2. **Filter & Search Logic**:
   - Filter by category tab and verify page count updates correctly.
   - Search for specific keywords in both English and Chinese text; verify filtered results match.
3. **Gameplay Toast & Badge Triggers**:
   - Trigger a gflag event in game; verify toast notification appears, SFX plays, and HUD unread count increments.
4. **Legacy Compatibility**:
   - Load a legacy save file without category attributes; verify no crashes occur and default values populate cleanly.
