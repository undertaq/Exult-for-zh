# Design: Separate Book/Scroll Font Type from Dialogue Font

Date: 2026-08-23
Status: Approved

## Problem

Changing the font type in "Dialog Text Setup" (Chinese Font Options) also changes the font used by books and scrolls.

Root cause: in `shapes/font.cc`, `get_chinese_font_path()` resolves book/scroll text via `small_font_path`, and when that is empty (the "Default" state) it falls through to the shared main `font_path` — the exact key written by the Dialog page's Font Type toggle (`gumps/ChineseFontOptions_gump.cc`). Books therefore silently track the dialogue font whenever no small font is configured.

Font size, color, letter spacing, and shadow are already separated per context; only the font *type* (TTF path) is coupled.

## Decisions (from brainstorming)

1. **Fully decoupled**: book/scroll font never follows the dialogue font. While the new setting is on "Default", it means the built-in `<PATCH>/chinese.ttf` default path.
2. **New dedicated UI page**: a fourth sub-page "Book Text Setup" in the Chinese Font Options gump.
3. **Approach 1**: new `book_font_path` config key, with legacy `small_font_path` kept as a compatibility fallback.

## Behavior / Config Semantics

- New config key: `config/video/chinese/book_font_path` (string TTF path; empty = Default).
- Book/scroll resolution order in `get_chinese_font_path()` for `is_book` fonts:
  1. `book_font_path` if set and the file exists
  2. legacy `small_font_path` if set and the file exists (keeps existing configs rendering identically)
  3. built-in default `<PATCH>/chinese.ttf`
  Books must **never** fall through to the main `font_path`.
- Dialogue text continues resolving the main `font_path` (unchanged).
- Sign font resolution and the tiny-text (rendered size ≤ 12) rule for non-book fonts are unchanged.

## Changes

### shapes/font.cc

- Restructure the `is_book` branch of `get_chinese_font_path()` so books resolve entirely within that branch using the chain above; do not fall through to the generic small-by-size step or the main-font fallback.

### gumps/ChineseFontOptions_gump.h / .cc

- Add `PAGE_BOOK` to the `Page` enum.
- MAIN page: add a fourth "Book Text Setup" button on Row 3 (currently free).
- BOOK page widgets:
  - "Font Type" toggle: choices = `{"Default"}` + scanned TTF names (same pattern as Small/Sign pages), bound to new member `book_font_path_idx` (0 = Default ⇒ write `""`).
  - Move the existing Book/Scroll Font Size slider and book Letter Spacing slider here from PAGE_SMALL.
- PAGE_SMALL afterwards contains only its own small-UI Font Type toggle (plus OK/Cancel).
- New members/callbacks: `book_font_path_idx`, snapshot fields, `toggle_book_font_path()`, `open_book_setup()`.
- `load_settings()` / `save_settings()` mirror the existing small/sign pattern: read/write `config/video/chinese/book_font_path`; idx 0 writes `""`.

### README_Chinese_Config.md

- Section 4 (書本與卷軸): document `<book_font_path>`, its priority chain (`book_font_path` → legacy `small_font_path` → 內建 `chinese.ttf`), and that it is independent of the dialogue font. Add it to the example XML block.

## Edge Cases

- `book_font_path` points at a missing file → falls to next step in the chain (same behavior as existing sign/small checks via `U7exists`).
- Configured path not among the scanned `<PATCH>`/`<DATA>` TTF list → toggle shows "Default"; saving overwrites with the chosen value (same accepted behavior as small/sign today).
- Pre-existing configs that only set `small_font_path`: books keep that font via the legacy layer; dialogue unaffected.

## Testing / Verification

Build the project, then manually verify:

1. Changing Dialog Text Setup → Font Type does not change an open book's/scroll's font.
2. Picking a font in Book Text Setup affects only books/scrolls; dialogue, barks, signs unchanged.
3. Book Font Type = Default renders with built-in `<PATCH>/chinese.ttf` (or the legacy `small_font_path` if previously configured).
4. A config with only `small_font_path` set still shows that font in books after upgrade.
