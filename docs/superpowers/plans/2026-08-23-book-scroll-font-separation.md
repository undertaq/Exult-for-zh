# Separate Book/Scroll Font Type from Dialogue Font Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make the book/scroll font *type* (TTF file) fully independent of the dialogue font by adding a dedicated `config/video/chinese/book_font_path` key and a new "Book Text Setup" page in the Chinese Font Options gump.

**Architecture:** `get_chinese_font_path()` in `shapes/font.cc` gains an isolated resolution chain for book/scroll fonts: `book_font_path` → legacy `small_font_path` (compat) → built-in `<PATCH>/chinese.ttf`; books never reach the dialogue's main `font_path`. The gump gets a `PAGE_BOOK` holding the Font Type toggle (moved from implicit inheritance to an explicit choice) plus the existing book size/spacing sliders relocated off `PAGE_SMALL`.

**Tech Stack:** C++ (Exult fork, `msvcstuff/vs2019/Exult.sln`, MSVC x64), Markdown docs.

**Spec:** `docs/superpowers/specs/2026-08-23-book-scroll-font-separation-design.md`

**Testing note:** This repo has **no unit-test harness for the C++ engine**. Verification per task = clean MSBuild compile. End-to-end behavior is verified manually in Task 5. Do not invent a test framework.

---

## File Map

| File | Responsibility |
|---|---|
| `shapes/font.cc` | Book/scroll TTF resolution chain (`book_font_path` → legacy small → built-in default) |
| `gumps/ChineseFontOptions_gump.h` | `PAGE_BOOK` enum, `book_font_path_idx` member + snapshot field, callbacks |
| `gumps/ChineseFontOptions_gump.cc` | Load/save/snapshot plumbing; MAIN-page button; BOOK page widgets/paint; slim down SMALL page |
| `README_Chinese_Config.md` | Document `<book_font_path>` + updated example XML |

**Build command (all C++ tasks):**
```powershell
msbuild msvcstuff/vs2019/Exult.sln -p:Configuration=Release -p:Platform=x64 -m
```
Expected: `Build succeeded` with no new warnings/errors.

---

### Task 1: Engine-side separation in `shapes/font.cc`

**Files:**
- Modify: `shapes/font.cc:105-132` (the numbered path-resolution steps inside `get_chinese_font_path`)

- [x] **Step 1: Rework the book/scroll resolution branch**

In `shapes/font.cc`, locate `get_chinese_font_path()` steps 2–4 (lines ~105–132). Replace this exact block:

```cpp
			// 2. Book / Scroll / UI small font path (applies to all book/scroll/UI fonts regardless of font size)
			if (path.empty() && is_book) {
				std::string small_path;
				config->value("config/video/chinese/small_font_path", small_path, "");
				if (!small_path.empty()) {
					std::string sys_small_path = get_system_path(small_path);
					if (U7exists(sys_small_path)) {
						path = sys_small_path;
					}
				}
			}

			// 3. Also check small_font_path if configured and font_size <= 12
			if (path.empty() && font_size >= 0 && font_size <= 12) {
				std::string small_path;
				config->value("config/video/chinese/small_font_path", small_path, "");
				if (!small_path.empty()) {
					std::string sys_small_path = get_system_path(small_path);
					if (U7exists(sys_small_path)) {
						path = sys_small_path;
					}
				}
			}

			// 4. Main default font_path
			if (path.empty()) {
				config->value("config/video/chinese/font_path", path, "<PATCH>/chinese.ttf");
			}
```

with:

```cpp
			// 2. Book / Scroll: dedicated book_font_path, then legacy small_font_path
			//    (compat with old configs), then the built-in default. Books must
			//    NEVER fall through to the dialogue's font_path (fully decoupled).
			if (is_book) {
				std::string book_path;
				config->value("config/video/chinese/book_font_path", book_path, "");
				if (!book_path.empty()) {
					std::string sys_book_path = get_system_path(book_path);
					if (U7exists(sys_book_path)) {
						path = sys_book_path;
					}
				}
				if (path.empty()) {
					std::string small_path;
					config->value("config/video/chinese/small_font_path", small_path, "");
					if (!small_path.empty()) {
						std::string sys_small_path = get_system_path(small_path);
						if (U7exists(sys_small_path)) {
							path = sys_small_path;
						}
					}
				}
				if (path.empty()) {
					path = "<PATCH>/chinese.ttf";
				}
			} else if (path.empty() && font_size >= 0 && font_size <= 12) {
				// 3. Non-book tiny text keeps the legacy small_font_path behavior
				std::string small_path;
				config->value("config/video/chinese/small_font_path", small_path, "");
				if (!small_path.empty()) {
					std::string sys_small_path = get_system_path(small_path);
					if (U7exists(sys_small_path)) {
						path = sys_small_path;
					}
				}
			}

			// 4. Main default font_path (dialogue and everything else; books never reach this)
			if (path.empty()) {
				config->value("config/video/chinese/font_path", path, "<PATCH>/chinese.ttf");
			}
```

Key points: the `is_book` branch always ends with a non-empty `path` (explicit built-in default), so books can never reach step 4; the ≤12px rule now applies only to non-book fonts (`else if`); the sign branch above is untouched.

- [x] **Step 2: Build**

Run: `msbuild msvcstuff/vs2019/Exult.sln -p:Configuration=Release -p:Platform=x64 -m`
Expected: `Build succeeded`, no new warnings.

- [x] **Step 3: Commit**

```powershell
git add shapes/font.cc
git commit -m "feat(font): resolve book/scroll TTF via dedicated book_font_path chain"
```

---

### Task 2: Gump plumbing — enum, state, load/save/snapshot

**Files:**
- Modify: `gumps/ChineseFontOptions_gump.h:34-39,50-51,69-86,125-136`
- Modify: `gumps/ChineseFontOptions_gump.cc` (`load_settings`, `save_settings`, `take_snapshot`, `restore_snapshot`, navigation methods)

- [x] **Step 1: Add `PAGE_BOOK` to the enum**

In `gumps/ChineseFontOptions_gump.h:34-39`:

```cpp
	enum Page {
		PAGE_MAIN,
		PAGE_DIALOG,
		PAGE_SMALL,
		PAGE_BOOK,
		PAGE_SIGN
	};
```

- [x] **Step 2: Add the state member**

In the "Current values" section, next to the other path indices (~line 51):

```cpp
	int small_font_path_idx;    // small font selection index (0 = default, index+1 in ttf_paths)
	int book_font_path_idx;     // book/scroll font selection index (0 = default, index+1 in ttf_paths)
	int sign_font_path_idx;     // sign font selection index (0 = default, index+1 in ttf_paths)
```

- [x] **Step 3: Add snapshot field**

In `SettingsSnapshot` (~line 71):

```cpp
	struct SettingsSnapshot {
		int font_path_idx;
		int small_font_path_idx;
		int book_font_path_idx;
		int sign_font_path_idx;
```

- [x] **Step 4: Add navigation + toggle callback declarations**

In the public "Navigation & toggle callbacks" section (~line 130):

```cpp
	void open_dialog_setup();
	void open_small_setup();
	void open_book_setup();
	void open_sign_setup();
	void go_back();

	void toggle_font_path(int state)          { font_path_idx = state; }
	void toggle_small_font_path(int state)    { small_font_path_idx = state; }
	void toggle_book_font_path(int state)     { book_font_path_idx = state; }
	void toggle_sign_font_path(int state)     { sign_font_path_idx = state; }
```

- [x] **Step 5: Load the new key in `load_settings()`**

In `gumps/ChineseFontOptions_gump.cc`, right after the sign-font-path block (after line 187) and before the `// 4. Other numeric and toggle settings` comment, insert:

```cpp
	// 4. Load book font path index
	string book_font_path;
	config->value("config/video/chinese/book_font_path", book_font_path, "");
	book_font_path_idx = 0; // Default
	if (!book_font_path.empty()) {
		for (size_t i = 0; i < ttf_paths.size(); i++) {
			if (ttf_paths[i] == book_font_path) {
				book_font_path_idx = i + 1;
				break;
			}
		}
	}
```

and renumber the following comment from `// 4.` to `// 5.`:

```cpp
	// 5. Other numeric and toggle settings
```

- [x] **Step 6: Save the new key in `save_settings()`**

Right after the sign-path write block (after line 272), insert:

```cpp
	if (book_font_path_idx == 0) {
		config->set("config/video/chinese/book_font_path", "", false);
	} else {
		int idx = book_font_path_idx - 1;
		if (idx >= 0 && idx < static_cast<int>(ttf_paths.size())) {
			config->set("config/video/chinese/book_font_path", ttf_paths[idx], false);
		}
	}
```

- [x] **Step 7: Snapshot/restore the new index**

In `take_snapshot()` add after `snapshot.small_font_path_idx = small_font_path_idx;`:

```cpp
	snapshot.book_font_path_idx = book_font_path_idx;
```

In `restore_snapshot()` add after `small_font_path_idx = snapshot.small_font_path_idx;`:

```cpp
	book_font_path_idx = snapshot.book_font_path_idx;
```

- [x] **Step 8: Add `open_book_setup()`**

Directly below `open_small_setup()` (~line 403):

```cpp
void ChineseFontOptions_gump::open_book_setup() {
	take_snapshot();
	current_page = PAGE_BOOK;
	build_buttons();
	gwin->set_all_dirty();
}
```

- [x] **Step 9: Build**

Run: `msbuild msvcstuff/vs2019/Exult.sln -p:Configuration=Release -p:Platform=x64 -m`
Expected: `Build succeeded` (member/method may warn as unused only if Task 3 hasn't run yet — MSVC does not emit such warnings here, so expect none).

- [x] **Step 10: Commit**

```powershell
git add gumps/ChineseFontOptions_gump.h gumps/ChineseFontOptions_gump.cc
git commit -m "feat(gumps): plumb book_font_path setting through ChineseFontOptions_gump"
```

---

### Task 3: Gump UI — Book Text Setup page, relocate book widgets

> **Execution note (deviation):** code review found `book_spacing_slider` missing from the `build_buttons()` reset list and from the `run()` pump at base; both fixes were folded into Task 3's commit (`238d6cb49`) since the slider relocated to PAGE_BOOK.

**Files:**
- Modify: `gumps/ChineseFontOptions_gump.cc` (`build_buttons` MAIN/SMALL blocks, new BOOK block, `paint()`)

- [x] **Step 1: Add the MAIN-page button**

In `build_buttons()`, after the "Row 2: Sign Text Setup" button push (~line 460):

```cpp
		// Row 3: Book Text Setup
		buttons.push_back(std::make_unique<ChineseFontOptions_button>(
				this, &ChineseFontOptions_gump::open_book_setup, "Book Text Setup", 0, yForRow(3), 120));
```

(Row 3 was previously free; Shadow Type starts at Row 4, so nothing shifts.)

- [x] **Step 2: Update the MAIN-page arrange loop**

Later in `build_buttons()` (~line 579), extend the loop from 3 to 4 sub-buttons:

```cpp
	if (current_page == PAGE_MAIN && num_btns >= 5) {
		for (int i = 0; i < 4; i++) {
			Gump_button* sub_btn[] = { buttons[i].get() };
			HorizontalArrangeWidgets(tcb::span(sub_btn, 1));
		}
	}
```

- [x] **Step 3: Slim down PAGE_SMALL**

Replace the whole `current_page == PAGE_SMALL` block (~lines 513-528) with:

```cpp
	} else if (current_page == PAGE_SMALL) {
		// Row 0: Font Type (small UI text only; books have their own page)
		auto choices = get_choices_helper(ttf_names, true);
		buttons.push_back(std::make_unique<ChineseFontTextToggle>(
				this, &ChineseFontOptions_gump::toggle_small_font_path, choices, small_font_path_idx, get_button_pos_for_label("Font Type:"), yForRow(0), large_size));
		setting_widgets.push_back(buttons.back().get());

	} else if (current_page == PAGE_BOOK) {
		// Row 0: Font Type
		auto choices = get_choices_helper(ttf_names, true);
		buttons.push_back(std::make_unique<ChineseFontTextToggle>(
				this, &ChineseFontOptions_gump::toggle_book_font_path, choices, book_font_path_idx, get_button_pos_for_label("Font Type:"), yForRow(0), large_size));
		setting_widgets.push_back(buttons.back().get());

		// Row 2: Book/Scroll Font Size
		book_size_slider = std::make_shared<Slider_widget>(
				this, get_button_pos_for_label("Book/Scroll Font Size:"), yForRow(2) - 13, shidleft, shidright, shiddiamond, 9, 72, 1, book_font_size, 60);
		setting_widgets.push_back(book_size_slider.get());

		// Row 4: Letter Spacing
		book_spacing_slider = std::make_shared<Slider_widget>(
				this, get_button_pos_for_label("Letter Spacing:"), yForRow(4) - 13, shidleft, shidright, shiddiamond, -5, 5, 1, letter_spacing_book, 60);
		setting_widgets.push_back(book_spacing_slider.get());

	} else if (current_page == PAGE_SIGN) {
```

(The `PAGE_SIGN` line shown last is pre-existing context — it stays.)

The `book_size_slider` / `book_spacing_slider` members, their entries in `GetSlider()`, `run()`, the widget-collection lists, and `OnSliderValueChanged()` all keep working unchanged — they simply now live on PAGE_BOOK instead of PAGE_SMALL.

- [x] **Step 4: Update `paint()` labels**

In `paint()`, replace the `current_page == PAGE_SMALL` branch (~lines 627-634) with:

```cpp
	} else if (current_page == PAGE_SMALL) {
		font->paint_text(iwin->get_ib8(), "Font Type:", x + label_margin, y + yForRow(0) + 1);

	} else if (current_page == PAGE_BOOK) {
		font->paint_text(iwin->get_ib8(), "Font Type:", x + label_margin, y + yForRow(0) + 1);
		if (book_size_slider) {
			PaintSlider(iwin, book_size_slider.get(), "Book/Scroll Font Size:");
		}
		if (book_spacing_slider) {
			PaintSlider(iwin, book_spacing_slider.get(), "Letter Spacing:");
		}

	} else if (current_page == PAGE_SIGN) {
```

(Again, the trailing `PAGE_SIGN` line is pre-existing context.)

- [x] **Step 5: Build**

Run: `msbuild msvcstuff/vs2019/Exult.sln -p:Configuration=Release -p:Platform=x64 -m`
Expected: `Build succeeded`, no new warnings.

- [x] **Step 6: Commit**

```powershell
git add gumps/ChineseFontOptions_gump.cc
git commit -m "feat(gumps): add Book Text Setup page; move book controls off Small page"
```

---

### Task 4: Document `book_font_path` in README_Chinese_Config.md

**Files:**
- Modify: `README_Chinese_Config.md` (section 4, ~line 105; example XML, ~line 240)

- [x] **Step 1: Add the parameter doc to section 4 (Book / Scroll)**

In `README_Chinese_Config.md`, immediately under the `### 4. 書本與卷軸字型設定 (Book / Scroll)` intro sentence (~line 107), insert:

```markdown
*   `<book_font_path>`：**書本/卷軸專屬字型檔 (預設值: 空白 = 內建 `<PATCH>/chinese.ttf`)**
    *   說明：書本與卷軸的字型「類型」完全獨立於對話主字型 (`font_path`)——變更對話字型不會影響書本/卷軸。解析優先順序：`book_font_path` → 舊版 `small_font_path`（相容既有設定）→ 內建 `chinese.ttf`。
```

- [x] **Step 2: Add the example XML entry**

In the example config block, directly after the `<small_font_path>` line (~line 240), insert:

```xml
      <!-- 書本/卷軸專屬字型 (選填；未設定則使用內建 chinese.ttf，與對話字型完全獨立) -->
      <book_font_path> C:\YourGame\static\patch\book.ttf </book_font_path>
```

- [x] **Step 3: Commit**

```powershell
git add README_Chinese_Config.md
git commit -m "docs: document book_font_path in README_Chinese_Config"
```

---

### Task 5: Manual end-to-end verification

**Files:** none (runtime verification only)

- [x] **Step 1: Launch the freshly built Exult**

Run the Release x64 build produced by `msvcstuff/vs2019/Exult.sln` against the normally-installed game (same way previous manual verifications were run). Open the menu chain: in-game menu → Display Options → the Chinese font settings entry (`GameDisplayOptions_gump.cc:538` opens `ChineseFontOptions_gump`).

- [x] **Step 2: Verify decoupling from the dialogue font**

Dialog Text Setup → cycle "Font Type" to a different TTF → OK. Open any readable book/scroll in-game.
Expected: the book's glyph style is **unchanged** by the dialogue font switch (was the bug: books followed `font_path` while Small font sat at Default).

- [x] **Step 3: Verify the new Book Text Setup page**

Main Chinese-font page → "Book Text Setup" (new fourth button). Pick a distinct TTF under "Font Type" → OK. Open a book/scroll again.
Expected: books/scrolls render with the chosen font; dialogue, overhead barks, signs, menus unchanged. Re-open the dialog: the chosen name is still selected (persisted via `exult.cfg`).

- [x] **Step 4: Verify Default state**

Book Text Setup → set "Font Type" back to "Default" → OK.
Expected: books render with the built-in `<PATCH>/chinese.ttf`; `exult.cfg` contains an empty `<book_font_path>`.

- [x] **Step 5: Verify legacy compat**

Temporarily edit `exult.cfg`: clear `<book_font_path>` and set `<small_font_path>` to one of the scanned TTFs → relaunch → open a book.
Expected: book uses that `small_font_path` font (legacy layer), dialogue unaffected. Restore your config afterward.

- [x] **Step 6: Final clean build + working-tree check**

Run: `msbuild msvcstuff/vs2019/Exult.sln -p:Configuration=Release -p:Platform=x64 -m`
Expected: `Build succeeded`. Then `git status --porcelain` shows only pre-existing unrelated changes (none of the four touched files should remain modified).
