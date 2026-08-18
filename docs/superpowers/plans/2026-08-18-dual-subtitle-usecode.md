# Dual Subtitle (usecode.dual) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third text-language mode, Dual, that renders dialogue subtitles stacked Chinese-over-English, backed by a generated `<PATCH>/usecode.dual` binary whose dialogue strings are `ZH\nEN` pairs.

**Architecture:** `BilingualManager` (bilingual_manager.h/cc) gains `TextLanguage::DUAL` and a `usecode_dual` machine, config `config/audio/text/language = "dual"`, with a 3-way AudioOptions toggle. The font stack already renders `\n` as a line break, so dialogue/choices/barks need only dual-aware sizing. `usecode.dual` is produced by a new Python generator that appends merged strings to each function's data segment and rewrites only the mapped `addsi` operands, preserving all other offsets. Because merged strings shift the active-usecode data offsets, voice key lookups get a second BLM2 map (`dual_map.dat`, dual?h and dual?n rows) loaded by `BilingualManager` and used by `VoiceActingManager`.

**Tech Stack:** C++ (Exult fork, msvcstuff/vs2019/Exult.sln), Python 3 + pytest (tools/voice_acting).

**Spec:** `docs/superpowers/specs/2026-08-18-dual-subtitle-usecode-design.md`

---

## File Map

| File | Responsibility |
|---|---|
| `fnames.h` | Add `DUAL_USECODE` define |
| `bilingual_manager.h` | `TextLanguage::DUAL`, `usecode_dual`, `dual_map`, `is_dual_available`, `is_zh_text`, `script_language` |
| `bilingual_manager.cc` | Load dual usecode + dual_map.dat, config parse, DUAL fallback chain, map_offset DUAL case |
| `gumps/AudioOptions_gump.cc` | 3-way text-language toggle (English/Chinese/Dual) |
| `usecode/conversation.cc` | Dual NPC text box sizing + dual avatar choice layout |
| `effects.cc` | Dual bark bubble size + position |
| `audio/VoiceActingManager.cc` | Dual-text voice cross-map via `map_offset(DUAL)` |
| `gumps/Spellbook_gump.cc` | Clamp DUAL?HINESE for spell names |
| `gumps/Notebook_gump.cc` | DUAL counts as Chinese layout |
| `tools/voice_acting/gen_dual_usecode.py` | **Create** — generate `usecode.dual` + `dual_map.dat` |
| `tools/voice_acting/test_gen_dual_usecode.py` | **Create** — pytest for the generator |
| `deploy.ps1` | Copy `usecode.dual` + `dual_map.dat` into the dist patch dir |
| `tools/voice_acting/doc/bilingual_mapping_generation.md` | Document dual generation steps |

**Build command (all C++ tasks):**
```powershell
msbuild msvcstuff/vs2019/Exult.sln -p:Configuration=Release -p:Platform=x64 -m
```
Expected: `Build succeeded` with no new warnings/errors.

---

### Task 1: `fnames.h` + `BilingualManager` DUAL plumbing

**Files:**
- Modify: `fnames.h:99-100`
- Modify: `bilingual_manager.h`
- Modify: `bilingual_manager.cc`

- [ ] **Step 1: Add the DUAL_USECODE define**

In `fnames.h`, after line 100 (`#define ZH_USECODE ...`):

```cpp
#define DUAL_USECODE         "<PATCH>/usecode.dual"
```

- [ ] **Step 2: Extend the enum and the manager header**

In `bilingual_manager.h:11`:

```cpp
enum class TextLanguage { ENGLISH = 0, CHINESE = 1, DUAL = 2 };
```

Add public methods (after `is_bilingual_available`, line 40):

```cpp
    bool is_dual_available() const { return usecode_dual != nullptr; }
    // True when the current text mode renders Chinese (ZH or DUAL).
    bool is_zh_text() const {
        return current_lang == TextLanguage::CHINESE
               || current_lang == TextLanguage::DUAL;
    }
    // Language used for non-dialogue UI lookups (spell names etc.):
    // DUAL behaves as CHINESE.
    TextLanguage script_language() const {
        return (current_lang == TextLanguage::DUAL) ? TextLanguage::CHINESE
                                                    : current_lang;
    }
```

Add members (after `usecode_zh`, line 49):

```cpp
    Usecode_machine* usecode_dual = nullptr;
    std::vector<VoiceMapping> dual_map;    // dual?h / dual?n rows (BLM2)
```

- [ ] **Step 3: Parse the "dual" config value in init()**

In `bilingual_manager.cc:24` replace:

```cpp
    current_lang = (text_lang_str == "zh") ? TextLanguage::CHINESE : TextLanguage::ENGLISH;
```

with:

```cpp
    current_lang = (text_lang_str == "zh")   ? TextLanguage::CHINESE
                   : (text_lang_str == "dual") ? TextLanguage::DUAL
                                               : TextLanguage::ENGLISH;
```

- [ ] **Step 4: Load usecode.dual in load_usecode_files()**

After the `usecode_zh` load block in `load_usecode_files()` (ends line 65):

```cpp
    if (is_system_path_defined("<PATCH>")) {
        if (U7exists(DUAL_USECODE)) {
            try {
                auto pFile = U7open_in(DUAL_USECODE);
                if (pFile) {
                    usecode_dual = Usecode_machine::create();
                    usecode_dual->read_usecode(*pFile);
                }
            } catch (const std::exception& e) {
                std::cerr << "[Bilingual] Failed to load dual usecode: "
                          << e.what() << std::endl;
                usecode_dual = nullptr;
            }
        } else {
            std::cout << "[Bilingual] usecode.dual not found; "
                         "dual mode will fall back to Chinese" << std::endl;
        }
    }
```

- [ ] **Step 5: DUAL fallback chain in get_usecode()/get_active_usecode()**

Replace `get_active_usecode()` (lines 148-151):

```cpp
Usecode_machine* BilingualManager::get_active_usecode() {
    return (current_lang == TextLanguage::DUAL) ? get_usecode(TextLanguage::DUAL)
           : (current_lang == TextLanguage::CHINESE && usecode_zh)
                   ? usecode_zh
                   : usecode_en;
}
```

Replace `get_usecode()` (lines 153-155):

```cpp
Usecode_machine* BilingualManager::get_usecode(TextLanguage lang) {
    if (lang == TextLanguage::DUAL) {
        if (usecode_dual) {
            return usecode_dual;
        }
        if (usecode_zh) {    // File fallback: Chinese.
            return usecode_zh;
        }
        return usecode_en;
    }
    return (lang == TextLanguage::CHINESE) ? usecode_zh : usecode_en;
}
```

- [ ] **Step 6: shutdown() also frees usecode_dual**

In `BilingualManager::shutdown()` (lines 42-45):

```cpp
    delete usecode_dual;
    usecode_dual = nullptr;
```

- [ ] **Step 7: Build**

Run: `msbuild msvcstuff/vs2019/Exult.sln -p:Configuration=Release -p:Platform=x64 -m`
Expected: `Build succeeded`.

- [ ] **Step 8: Commit**

```bash
git add fnames.h bilingual_manager.h bilingual_manager.cc
git commit -m "feat(dual): add TextLanguage::DUAL and usecode.dual loading in BilingualManager"
```

---

### Task 2: 3-way text-language toggle in AudioOptions

**Files:**
- Modify: `gumps/AudioOptions_gump.cc:348-352, 488-492, 711-714`

- [ ] **Step 1: Three toggle options**

In `AudioOptions_gump.cc:348` replace:

```cpp
	std::vector<std::string> lang_options = {"English", "Chinese"};
```

with:

```cpp
	std::vector<std::string> lang_options = {"English", "Chinese", "Dual"};
```

- [ ] **Step 2: Parse "dual" in load_settings()**

In `AudioOptions_gump.cc:491` replace:

```cpp
	text_language   = (text_lang_str == "zh") ? 1 : 0;
```

with:

```cpp
	text_language   = (text_lang_str == "zh")   ? 1
	                  : (text_lang_str == "dual") ? 2
	                                              : 0;
```

- [ ] **Step 3: Commit "dual" and switch usecode in ok()**

In `AudioOptions_gump.cc:711-714` replace:

```cpp
	config->set("config/audio/text/language", text_language == 1 ? "zh" : "en", false);
	config->set("config/audio/speech/voice/language", voice_language == 1 ? "zh" : "en", false);
	BilingualManager::get().set_text_language(
			text_language == 1 ? TextLanguage::CHINESE : TextLanguage::ENGLISH);
```

with:

```cpp
	config->set("config/audio/text/language",
	            text_language == 2 ? "dual" : (text_language == 1 ? "zh" : "en"), false);
	config->set("config/audio/speech/voice/language", voice_language == 1 ? "zh" : "en", false);
	BilingualManager::get().set_text_language(
			text_language == 2 ? TextLanguage::DUAL
			: (text_language == 1 ? TextLanguage::CHINESE : TextLanguage::ENGLISH));
```

- [ ] **Step 4: Build**

Run: `msbuild msvcstuff/vs2019/Exult.sln -p:Configuration=Release -p:Platform=x64 -m`
Expected: `Build succeeded`.

- [ ] **Step 5: Commit**

```bash
git add gumps/AudioOptions_gump.cc
git commit -m "feat(dual): add Dual option to AudioOptions text-language toggle"
```

---

### Task 3: Dual NPC dialogue text in the conversation box

**Files:**
- Modify: `usecode/conversation.cc:409-465` (`show_npc_message`)

- [ ] **Step 1: Count dual pairs in show_npc_message()**

After the `has_chinese` scan (after line 417), insert:

```cpp
	int pairs = 1;    // # of "ZH\nEN" pairs (1 if no embedded newline).
	if (display) {
		for (const char* p = display; *p; p++) {
			if (*p == '\n') {
				pairs++;
			}
		}
	}
```

- [ ] **Step 2: Grow the large-face text box for pairs**

Replace the `info->large_face && has_chinese` block (lines 424-433):

```cpp
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
```

- [ ] **Step 3: Allocate enough render box height**

Replace lines 441-444:

```cpp
	int render_box_h = 4 * line_height;
	if (pairs > 1) {
		render_box_h = std::max(render_box_h, std::min(pairs * 2, 6) * line_height);
	}
	if (render_box_h > box.h) {
		render_box_h = box.h;
	}
```

(The `paint_text_box` loop below is unchanged — it already treats `\n` as a line break and pages at line boundaries.)

- [ ] **Step 4: Build**

Run: `msbuild msvcstuff/vs2019/Exult.sln -p:Configuration=Release -p:Platform=x64 -m`
Expected: `Build succeeded`.

- [ ] **Step 5: Commit**

```bash
git add usecode/conversation.cc
git commit -m "feat(dual): render ZH\\nEN NPC dialogue pairs in the conversation box"
```

---

### Task 4: Dual avatar choices

**Files:**
- Modify: `usecode/conversation.cc` (`show_avatar_choices`, lines 497-720)

- [ ] **Step 1: Add choice helpers (anonymous namespace)**

Insert before `show_avatar_choices` (line 497):

```cpp
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
			maxw = std::max(maxw, sman->get_text_width(0, piece.c_str(), has_chinese));
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
```

- [ ] **Step 2: calc_height() accounts for dual rows**

Replace the `calc_height` lambda (lines 613-630):

```cpp
		auto calc_height = [&]() {
			int test_tbox_w = sbox.w - fx - face->get_width() - tbox_w_offset;
			int temp_x = 0;
			int temp_y = 0;
			int temp_line_step = has_chinese ? line_height : line_height - 1;
			for (int i = 0; i < num_choices; i++) {
				const bool  multiline = strchr(choices[i], '\n') != nullptr;
				const int   lines     = choice_line_count(choices[i]);
				const int   width     = multiline ? choice_max_line_width(choices[i], has_chinese)
				                                  : sman->get_text_width(0, text_with_circle(choices[i]), has_chinese);
				if (multiline || (temp_x > 0 && temp_x + width >= test_tbox_w)) {
					temp_x = 0;
					temp_y += temp_line_step * (multiline ? lines : 1);
				}
				temp_x += width + space_width;
			}
			return temp_y + line_height;
		};
```

Note: `text_with_circle` does not exist — use the existing inline pattern from the original code:

```cpp
			char text[512];
			text[0] = 127;
			strcpy(&text[1], choices[i]);
			const int width = multiline ? choice_max_line_width(choices[i], has_chinese)
			                            : sman->get_text_width(0, text, has_chinese);
```

So the full replacement is:

```cpp
		auto calc_height = [&]() {
			int test_tbox_w = sbox.w - fx - face->get_width() - tbox_w_offset;
			int temp_x = 0;
			int temp_y = 0;
			int temp_line_step = has_chinese ? line_height : line_height - 1;
			for (int i = 0; i < num_choices; i++) {
				const bool multiline = strchr(choices[i], '\n') != nullptr;
				const int  lines     = choice_line_count(choices[i]);
				char       text[512];
				text[0] = 127;    // A circle.
				strcpy(&text[1], choices[i]);
				const int width = multiline ? choice_max_line_width(choices[i], has_chinese)
				                            : sman->get_text_width(0, text, has_chinese);
				if (multiline || (temp_x > 0 && temp_x + width >= test_tbox_w)) {
					temp_x = 0;
					temp_y += temp_line_step * (multiline ? lines : 1);
				}
				temp_x += width + space_width;
			}
			return temp_y + line_height;
		};
```

- [ ] **Step 3: First pass (positions + backgrounds) handles dual rows**

Replace the first pass loop (lines 677-706):

```cpp
	for (int i = 0; i < num_choices; i++) {
		const bool multiline = strchr(choices[i], '\n') != nullptr;
		const int  nlines    = choice_line_count(choices[i]);
		char       text[512];
		text[0] = 127;    // A circle.
		strcpy(&text[1], choices[i]);
		const int width = multiline ? choice_max_line_width(choices[i], has_chinese)
		                            : sman->get_text_width(0, text, has_chinese);
		if (multiline || (x > 0 && x + width >= tbox.w)) {
			// Dual rows always start on a fresh line.
			x = 0;
			y += nlines * (has_chinese ? line_height : line_height - 1);
		}
		// Store info.
		int hit_h = line_height;
		std::shared_ptr<Font> font0 = sman->get_font(0);
		if (has_chinese && font0 && !multiline) {
			// Dynamically expand hit box to cover TTF ascender offsets and descenders
			int baseline = font0->get_text_baseline_for("\x80");
			int text_h = font0->get_text_height_for("\x80");
			int text_bottom = baseline + text_h / 4 + 2;
			hit_h = std::max(line_height, text_bottom);
		} else if (multiline) {
			hit_h = nlines * line_height;
		}
		conv_choices[i] = TileRect(tbox.x + x, tbox.y + y, width, hit_h);
		conv_choices[i] = conv_choices[i].intersect(sbox);
		avatar_face     = avatar_face.add(conv_choices[i]);
		// Draw shading with line_height, shifted down to align with text.
		if (text_bg >= 0) {
			gwin->get_win()->fill_translucent8(
					0, width + space_width, hit_h, tbox.x + x, tbox.y + y + bg_offset, sman->get_xform(text_bg));
		}
		x += width + space_width;
	}
```

- [ ] **Step 4: Second pass (text paint) uses the enlarged buffer**

Replace the second pass loop (lines 708-713):

```cpp
	for (int i = 0; i < num_choices; i++) {
		char text[512];
		text[0] = 127;    // A circle.
		strcpy(&text[1], choices[i]);
		sman->paint_text(0, text, conv_choices[i].x, conv_choices[i].y, has_chinese);
	}
```

(Only the buffer size changed from 256 to 512; `paint_text` renders the `\n` as a line break natively.)

- [ ] **Step 5: Build**

Run: `msbuild msvcstuff/vs2019/Exult.sln -p:Configuration=Release -p:Platform=x64 -m`
Expected: `Build succeeded`.

- [ ] **Step 6: Commit**

```bash
git add usecode/conversation.cc
git commit -m "feat(dual): layout dual avatar choices as stacked rows"
```

---

### Task 5: Dual barks (overhead speech bubbles)

**Files:**
- Modify: `effects.cc` (`Text_effect::init` ~1067-1074, `Figure_text_pos` ~1015-1051)

- [ ] **Step 1: Dual sizing in Text_effect::init()**

Replace lines 1067-1074:

```cpp
void Text_effect::init() {
	set_always(true);    // Always execute in time queue, even
	//   when paused.
	Font::is_painting_bark = true;
	width  = 8 + sman->get_text_width(0, msg.c_str());
	height = 8 + sman->get_text_height(0);
	const size_t nl = msg.find('\n');
	if (nl != std::string::npos) {
		int maxw   = 0;
		int lines  = 1;
		size_t start = 0;
		for (;;) {
			const size_t end = msg.find('\n', start);
			const std::string piece
					= msg.substr(start, end == std::string::npos ? std::string::npos : end - start);
			maxw = std::max(maxw, sman->get_text_width(0, piece.c_str()));
			if (end == std::string::npos) {
				break;
			}
			lines++;
			start = end + 1;
		}
		width  = 8 + maxw;
		height = 8 + lines * sman->get_text_height(0);
	}
	Font::is_painting_bark = false;
```

- [ ] **Step 2: Nudge the bubble up for dual text**

At the top of `Text_effect::Figure_text_pos()` (before the `if (item_obj)` branch, after the function opening brace at line 1015), insert:

```cpp
	int th = sman->get_text_height(0);
	if (msg.find('\n') != std::string::npos) {
		int lines = 1;
		for (char c : msg) {
			if (c == '\n') {
				lines++;
			}
		}
		th *= lines;
	}
```

Then replace each of the three `Font::is_painting_bark = true; int th = sman->get_text_height(0); Font::is_painting_bark = false;` sequences (lines 1023-1025, 1036-1038, 1046-1048) with nothing (the variable is now computed once at the top); the surrounding `r.y -= th;` / `return TileRect(x, y - th, ...)` lines stay as they are.

- [ ] **Step 3: Build**

Run: `msbuild msvcstuff/vs2019/Exult.sln -p:Configuration=Release -p:Platform=x64 -m`
Expected: `Build succeeded`.

- [ ] **Step 4: Commit**

```bash
git add effects.cc
git commit -m "feat(dual): size and position bark bubbles for dual subtitle lines"
```

---

### Task 6: Voice cross-map for dual text

**Files:**
- Modify: `bilingual_manager.h`, `bilingual_manager.cc`
- Modify: `audio/VoiceActingManager.cc:471-502`

- [ ] **Step 1: Factor the BLM2 reader and load dual_map.dat**

In `bilingual_manager.cc`, extract the body of `load_bilingual_map()` (lines 68-134) into a private helper and call it for both files. Add to `bilingual_manager.h` private section:

```cpp
    void load_map_file(const std::string& path, std::vector<VoiceMapping>& out);
```

Implementation (the file body is the existing BLM2/BLMP parse loop, parameterized):

```cpp
void BilingualManager::load_map_file(const std::string& map_path,
                                     std::vector<VoiceMapping>& out) {
	out.clear();
	if (!U7exists(map_path)) {
		std::cout << "[Bilingual] No voice map found at " << map_path << std::endl;
		return;
	}
	try {
		auto pFile = U7open_in(map_path.c_str());
		if (!pFile) {
			std::cerr << "[Bilingual] Failed to open voice map " << map_path << std::endl;
			return;
		}
		auto& file = *pFile;
		char header[4];
		file.read(header, 4);
		bool is_v2 = std::memcmp(header, "BLM2", 4) == 0;
		if (!is_v2 && std::memcmp(header, "BLMP", 4) != 0) {
			std::cerr << "[Bilingual] Invalid map header in " << map_path << std::endl;
			return;
		}
		uint32_t count;
		file.read(reinterpret_cast<char*>(&count), 4);
		out.reserve(count);
		for (uint32_t i = 0; i < count; i++) {
			VoiceMapping m;
			file.read(reinterpret_cast<char*>(&m.zh_func_id), 4);
			std::getline(file, m.zh_offset_key, '\0');
			uint16_t segment_raw;
			file.read(reinterpret_cast<char*>(&segment_raw), 2);
			m.zh_segment = segment_raw;
			file.read(reinterpret_cast<char*>(&m.en_func_id), 4);
			std::getline(file, m.en_offset_key, '\0');
			if (is_v2) {
				uint16_t en_segment_raw;
				file.read(reinterpret_cast<char*>(&en_segment_raw), 2);
				m.en_segment = en_segment_raw;
			} else {
				m.en_segment = segment_raw;
			}
			out.push_back(std::move(m));
		}
		std::cout << "[Bilingual] Loaded " << out.size() << " voice mappings from "
				  << map_path << std::endl;
	} catch (const std::exception& e) {
		std::cerr << "[Bilingual] Error loading voice map " << map_path << ": "
				  << e.what() << std::endl;
		out.clear();
	}
}
```

Replace the body of `load_bilingual_map()` (lines 68-134) with:

```cpp
void BilingualManager::load_bilingual_map() {
	load_map_file("<PATCH>/voice_acting/bilingual_map.dat", bilingual_map);
	load_map_file("<PATCH>/voice_acting/dual_map.dat", dual_map);
}
```

(`load_bilingual_map` is still called from `init()` unchanged. `bilingual_map` semantics are untouched; `dual_map` rows store the DUAL-side key in `zh_*` fields and the TARGET-side (zh or en) key in `en_*` fields.)

- [ ] **Step 2: map_offset() DUAL case**

In `map_offset()` (bilingual_manager.cc:157-184), add before the closing `return false;`:

```cpp
	if (from_lang == TextLanguage::DUAL) {
		for (const auto& m : dual_map) {
			if (m.zh_func_id == func_id && m.zh_offset_key == offset_key
					&& m.zh_segment == segment) {
				out_func_id = m.en_func_id;
				out_offset_key = m.en_offset_key;
				out_segment = m.en_segment;
				return true;
			}
		}
	}
```

- [ ] **Step 3: VoiceActingManager dual handling**

In `audio/VoiceActingManager.cc:474-502`, replace:

```cpp
	const std::string& cur_voice_lang = get_voice_language();
	TextLanguage	   text_lang	   = BilingualManager::get().get_text_language();
	if (BilingualManager::get().is_bilingual_available()
		&& ((cur_voice_lang == "en" && text_lang == TextLanguage::CHINESE)
			|| (cur_voice_lang == "zh" && text_lang == TextLanguage::ENGLISH))) {
		TextLanguage from_lang
				= (cur_voice_lang == "en") ? TextLanguage::CHINESE : TextLanguage::ENGLISH;
```

with:

```cpp
	const std::string& cur_voice_lang = get_voice_language();
	TextLanguage	   text_lang	   = BilingualManager::get().get_text_language();
	bool map_needed = false;
	if (text_lang == TextLanguage::DUAL) {
		map_needed = BilingualManager::get().is_dual_available();
	} else if (cur_voice_lang == "en" && text_lang == TextLanguage::CHINESE) {
		map_needed = true;
	} else if (cur_voice_lang == "zh" && text_lang == TextLanguage::ENGLISH) {
		map_needed = true;
	}
	if (BilingualManager::get().is_bilingual_available() && map_needed) {
		TextLanguage from_lang = text_lang;    // CHINESE, ENGLISH or DUAL.
```

The `map_offset(from_lang, ...)` call and the rest of the block stay unchanged.

- [ ] **Step 4: Build**

Run: `msbuild msvcstuff/vs2019/Exult.sln -p:Configuration=Release -p:Platform=x64 -m`
Expected: `Build succeeded`.

- [ ] **Step 5: Commit**

```bash
git add bilingual_manager.h bilingual_manager.cc audio/VoiceActingManager.cc
git commit -m "feat(dual): voice key cross-map via dual_map.dat for dual text mode"
```

---

### Task 7: Spellbook + Notebook integration

**Files:**
- Modify: `gumps/Spellbook_gump.cc:596`
- Modify: `gumps/Notebook_gump.cc:565, 1030, 1583, 1796`

- [ ] **Step 1: Spellbook clamps DUAL**

In `gumps/Spellbook_gump.cc:596` replace:

```cpp
		int lang = static_cast<int>(BilingualManager::get().get_text_language());
```

with:

```cpp
		int lang = static_cast<int>(BilingualManager::get().script_language());
```

- [ ] **Step 2: Notebook treats DUAL as Chinese**

Replace all four `BilingualManager::get().get_text_language() == TextLanguage::CHINESE` checks (lines 565, 1030, 1583, 1796) with `BilingualManager::get().is_zh_text()`. Use `replaceAll`-style edits per site; keep surrounding logic identical. Example (line 565):

```cpp
	const bool     chinese = BilingualManager::get().is_zh_text();
```

and line 1796 becomes:

```cpp
		if (BilingualManager::get().is_zh_text() && have_zh) {
```

- [ ] **Step 3: Build**

Run: `msbuild msvcstuff/vs2019/Exult.sln -p:Configuration=Release -p:Platform=x64 -m`
Expected: `Build succeeded`.

- [ ] **Step 4: Commit**

```bash
git add gumps/Spellbook_gump.cc gumps/Notebook_gump.cc
git commit -m "fix(dual): treat DUAL as Chinese for spell names and journal layout"
```

---

### Task 8: Generator `gen_dual_usecode.py` + tests

**Files:**
- Create: `tools/voice_acting/gen_dual_usecode.py`
- Create: `tools/voice_acting/test_gen_dual_usecode.py`

Background: `tools/voice_acting/disassemble_usecode.py` is importable (has a `__main__` guard, line 1124) and already provides everything the generator needs:
- `parse_function(data, offset)` -> `(func_id, func_data, extended, next_offset)` (line 173)
- `disassemble_function(func_id, func_data, extended)` -> structured func dict (line 192)
- `extract_say_lines(func)` -> per-segment say lines with `offset_key`, `segment`, `text`, `addsi_offsets`, `code_addr` (line 776)
- `skip_symbol_table(data, offset)` -> offset after the Exult symbol table (line 1017)

`extract_say_lines` computes the offset key like the runtime (`ucinternal.cc:637-654`): the ordered `addsi` data offsets of one trace. It uses Python `hex()` internally, so the generator re-derives keys with `"%x"` to match the review JSON format (e.g. `"88"`, not `"0x88"`).

The review JSON (`bilingual_mapping_review.json`) rows: `zh_func_id` (`"0x009A"` hex str), `zh_offset_key` (`"88"`, lowercase-hex offsets joined by `_`), `zh_segment` (int, 0-based segment index within the trace), `zh_raw`/`zh_text`, `en_raw`/`en_text`, `en_func_id`, `en_offset_key`, `en_segment`. Raw texts contain no `~` — rows are already per segment.

Generation rules (from the spec):
- Base: `usecode.zh`, function table copied verbatim; all unmerged bytes byte-identical.
- For every zh trace (grouped by `(zh_func_id, zh_offset_key)`) present in the review JSON: merged segment text = `zh_segment + "\n" + en_segment`; segments joined with `~` (segment count and numbering match the original — `extract_say_lines` splits with the same rules used to generate the voice files).
- Segment with no usable EN counterpart -> ZH alone (pair-fallback ZH).
- Append the merged string to that function's data segment; redirect the trace's FIRST `addsi` operand to it, the rest to one shared empty string. All other bytes unchanged -> all other offsets valid.
- First-offset collision between two traces (e.g. keys `"88"` and `"88_1a0"`): skip the later trace (zh-only), count in `skipped`.
- Output `usecode.dual` (+ symbol table, if present) and `dual_map.dat` (BLM2): per merged segment, one dual->zh row and one dual->en row, keyed `(dual_func, new_offset_key, segment)`.

- [ ] **Step 1: Write the failing tests**

Create `tools/voice_acting/test_gen_dual_usecode.py`:

```python
"""Tests for gen_dual_usecode.py."""
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import gen_dual_usecode as g

ADDSI = 0x1C
SAY = 0x33


def build_func(func_id, code, data, extended=False):
    """Wrap code+data into a function blob (classic or 0xfffe header)."""
    tail = struct.pack("<HHH", 0, 0, 0) + code   # args, vars, externs
    body_len = len(data) + len(tail)
    if extended:
        blob = struct.pack("<H", 0xFFFE) + struct.pack("<i", func_id)
        blob += struct.pack("<I", body_len) + struct.pack("<i", len(data))
    else:
        blob = struct.pack("<H", func_id) + struct.pack("<H", body_len)
        blob += struct.pack("<H", len(data))
    return blob + data + tail


def test_offset_key_for():
    assert g.offset_key_for([0x88, 0x1A0]) == "88_1a0"
    assert g.offset_key_for([0]) == "0"


def test_build_merged():
    assert g.build_merged("zh", "en") == "zh\nen"


def test_generate_merges_and_preserves_unmerged():
    data = b"HELLO\0world\0"
    code1 = struct.pack("<B", ADDSI) + struct.pack("<H", 0) + struct.pack("<B", SAY)
    f1 = build_func(0x0123, code1, data)
    code2 = struct.pack("<B", ADDSI) + struct.pack("<H", 0) + struct.pack("<B", 0x05)
    f2 = build_func(0x0401, code2, b"BYE\0")
    zh = f1 + f2
    review = [{
        "zh_func_id": "0x0123", "zh_offset_key": "0", "zh_segment": 0,
        "zh_raw": "HELLO", "en_raw": "NIHAO",
        "en_func_id": "0x0402", "en_offset_key": "0", "en_segment": 0,
    }]
    dual, rows, skipped = g.generate(zh, review)
    assert skipped == []
    fid, fdata, ext, nxt = g.dis.parse_function(dual, 0)
    func = g.dis.disassemble_function(fid, fdata, ext)
    assert fid == 0x0123
    assert func["strings"][0] == "HELLO"          # original data preserved
    lines = g.dis.extract_say_lines(func)
    assert any(l["text"] == "HELLO\nNIHAO" for l in lines)
    # second function byte-identical
    assert dual[nxt:] == f2
    # dual->zh + dual->en rows
    assert len(rows) == 2
    zh_rows = [r for r in rows if r["en_func_id"] == 0x0123]
    en_rows = [r for r in rows if r["en_func_id"] == 0x0402]
    assert len(zh_rows) == 1 and len(en_rows) == 1
    assert en_rows[0]["zh_offset_key"] in ("0", "8", "10", "18")  # appended offset


def test_generate_two_traces_redirects_later_addsi_to_empty():
    data = b"AAA\0BBB\0CCC\0"
    code = (
        struct.pack("<B", ADDSI) + struct.pack("<H", 0)
        + struct.pack("<B", ADDSI) + struct.pack("<H", 6)
        + struct.pack("<B", SAY)
        + struct.pack("<B", ADDSI) + struct.pack("<H", 12)
        + struct.pack("<B", SAY)
    )
    zh = build_func(0x0200, code, data)
    review = [
        {"zh_func_id": "0x0200", "zh_offset_key": "0_6", "zh_segment": 0,
         "zh_raw": "AAABBB", "en_raw": "EN1",
         "en_func_id": "0x0200", "en_offset_key": "0_6", "en_segment": 0},
        {"zh_func_id": "0x0200", "zh_offset_key": "c", "zh_segment": 0,
         "zh_raw": "CCC", "en_raw": "EN2",
         "en_func_id": "0x0200", "en_offset_key": "c", "en_segment": 0},
    ]
    dual, rows, skipped = g.generate(zh, review)
    assert skipped == []
    fid, fdata, ext, _ = g.dis.parse_function(dual, 0)
    func = g.dis.disassemble_function(fid, fdata, ext)
    lines = g.dis.extract_say_lines(func)
    texts = sorted(l["text"] for l in lines)
    assert texts == ["AAABBB\nEN1", "CCC\nEN2"]
    assert len(rows) == 4
    # both merged strings present in the data segment
    merged = [s for s in func["strings"].values() if "\n" in s]
    assert len(merged) == 2


def test_generate_pair_fallback_zh():
    data = b"HELLO\0"
    code = struct.pack("<B", ADDSI) + struct.pack("<H", 0) + struct.pack("<B", SAY)
    zh = build_func(0x0123, code, data)
    review = [{"zh_func_id": "0x0123", "zh_offset_key": "0", "zh_segment": 0,
               "zh_raw": "HELLO", "en_raw": ""}]
    dual, rows, skipped = g.generate(zh, review)
    assert skipped == []
    fid, fdata, ext, _ = g.dis.parse_function(dual, 0)
    func = g.dis.disassemble_function(fid, fdata, ext)
    lines = g.dis.extract_say_lines(func)
    assert any(l["text"] == "HELLO" for l in lines)   # no \n appended
    assert len(rows) == 1                              # dual->zh only


def test_generate_skips_missing_review_row():
    data = b"HELLO\0"
    code = struct.pack("<B", ADDSI) + struct.pack("<H", 0) + struct.pack("<B", SAY)
    zh = build_func(0x0567, code, data)
    dual, rows, skipped = g.generate(zh, [])
    # no review rows: function copied byte-identical, no map rows
    assert dual == zh
    assert rows == []
    assert skipped == []


def test_blm2_roundtrip(tmp_path):
    rows = [{"zh_func_id": 0x123, "zh_offset_key": "aa", "zh_segment": 0,
             "en_func_id": 0x9ab, "en_offset_key": "bb", "en_segment": 1}]
    p = tmp_path / "dual_map.dat"
    g.write_blm2(p, rows)
    assert g.read_blm2(p) == rows
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tools/voice_acting/test_gen_dual_usecode.py -q`
Expected: FAILED/ERROR — `No module named gen_dual_usecode`.

- [ ] **Step 3: Implement the generator**

Create `tools/voice_acting/gen_dual_usecode.py`:

```python
#!/usr/bin/env python3
"""Generate usecode.dual + dual_map.dat from usecode.zh + the review JSON.

Every dialogue trace present in bilingual_mapping_review.json gets a merged
data string: segments "<ZH>\n<EN>" joined by '~'. The trace's FIRST addsi
operand is redirected to the appended merged string; its remaining addsi
operands point to one shared empty string. All other bytes are copied
verbatim, so every other string offset stays valid.

Usage:
    python gen_dual_usecode.py [--zh PATH] [--review PATH]
                               [--out PATH] [--map-out PATH]
"""
import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import disassemble_usecode as dis


def build_merged(zh, en):
    return zh + "\n" + en


def offset_key_for(addsi_offsets):
    """hex offsets joined by '_' — matches review JSON / runtime keys."""
    return "_".join("%x" % o for o in addsi_offsets)


def load_en_by_key(review):
    """{(func_hex, offset_key): {segment: en_info_dict}}"""
    by_key = {}
    for r in review:
        fid = r.get("zh_func_id")
        key = r.get("zh_offset_key")
        seg = r.get("zh_segment")
        if not fid or not key or seg is None:
            continue
        by_key.setdefault((fid, key), {})[seg] = {
            "text": (r.get("en_raw") or r.get("en_text") or "").strip(),
            "en_func_id": r.get("en_func_id", fid),
            "en_offset_key": r.get("en_offset_key", key),
            "en_segment": r.get("en_segment", seg),
        }
    return by_key


def iter_addsi(code, extended):
    """Yield (instr_ip, data_off) for every addsi in instruction order."""
    ip = 0
    while ip < len(code):
        instr_ip = ip
        op = code[ip]
        ip += 1
        info = dis.OPCODES.get(op)
        if info is None:
            ip += 1
            continue
        fmt = info[1]
        if fmt == "si":
            val = dis.read4s(code, ip) if extended else dis.read2(code, ip)
            if op == 0x1C:      # UC_ADDSI (0x1C covers ADDSI32 too)
                yield instr_ip, val
            ip += 4 if extended else 2
        elif fmt in ("w", "s", "ji"):
            ip += 2
        elif fmt == "b":
            ip += 1
        elif fmt == "ci":
            ip += 3
        elif fmt == "cs":
            ip += 4
        elif fmt == "lt":
            ip += 10
        elif fmt == "n":
            pass
        else:
            ip += 1


def parse_parts(func_data, extended):
    """Return (old_data, nargs, nvars, externs, old_code)."""
    pos = 0
    if extended:
        data_len = dis.read4s(func_data, pos); pos += 4
    else:
        data_len = dis.read2(func_data, pos); pos += 2
    old_data = func_data[pos:pos + data_len]
    pos += data_len
    nargs = dis.read2(func_data, pos); pos += 2
    nvars = dis.read2(func_data, pos); pos += 2
    nexterns = dis.read2(func_data, pos); pos += 2
    externs = func_data[pos:pos + 2 * nexterns]
    pos += 2 * nexterns
    return old_data, nargs, nvars, externs, func_data[pos:]


def rebuild_function(func_data, extended, traces):
    """Append merged strings; redirect addsi operands.

    traces: {addsi_tuple: merged_str}
    Returns (new_func_blob, first_offsets, empty_off).
    Raises ValueError if two traces claim the same first addsi offset.
    """
    old_data, nargs, nvars, externs, old_code = parse_parts(func_data, extended)

    new_data = bytearray(old_data)
    first_offsets = {}
    redirect = {}
    empty_off = None
    for t, merged in traces.items():
        t_first = t[0]
        if t_first in redirect:
            raise ValueError("addsi %x claimed by two traces" % t_first)
        first_offsets[t] = len(new_data)
        new_data += merged.encode("utf-8") + b"\0"
        redirect[t_first] = first_offsets[t]
    for t in traces:
        for later in t[1:]:
            if later in redirect:
                continue          # already a trace start (or previously claimed)
            if empty_off is None:
                empty_off = len(new_data)
                new_data += b"\0"
            redirect[later] = empty_off

    new_code = bytearray(old_code)
    for instr_ip, data_off in iter_addsi(old_code, extended):
        if data_off in redirect:
            new_off = redirect[data_off]
            if extended:
                new_code[instr_ip + 1:instr_ip + 5] = struct.pack("<i", new_off)
            else:
                new_code[instr_ip + 1:instr_ip + 3] = struct.pack("<H", new_off)

    if extended:
        data_len_bytes = struct.pack("<i", len(new_data))
    else:
        data_len_bytes = struct.pack("<H", len(new_data))
    blob = (data_len_bytes + bytes(new_data)
            + struct.pack("<HHH", nargs, nvars, nexterns)
            + externs + bytes(new_code))
    return blob, first_offsets, empty_off


def write_blm2(path, rows):
    with open(path, "wb") as f:
        f.write(b"BLM2")
        f.write(struct.pack("<I", len(rows)))
        for r in rows:
            f.write(struct.pack("<i", r["zh_func_id"]))
            f.write(r["zh_offset_key"].encode() + b"\0")
            f.write(struct.pack("<H", r["zh_segment"]))
            f.write(struct.pack("<i", r["en_func_id"]))
            f.write(r["en_offset_key"].encode() + b"\0")
            f.write(struct.pack("<H", r["en_segment"]))


def read_blm2(path):
    rows = []
    with open(path, "rb") as f:
        assert f.read(4) == b"BLM2", "not a BLM2 file"
        (count,) = struct.unpack("<I", f.read(4))
        for _ in range(count):
            (zh_fid,) = struct.unpack("<i", f.read(4))
            zh_key = b"".join(iter(lambda: f.read(1), b"\0")).decode()
            (zh_seg,) = struct.unpack("<H", f.read(2))
            (en_fid,) = struct.unpack("<i", f.read(4))
            en_key = b"".join(iter(lambda: f.read(1), b"\0")).decode()
            (en_seg,) = struct.unpack("<H", f.read(2))
            rows.append({"zh_func_id": zh_fid, "zh_offset_key": zh_key,
                         "zh_segment": zh_seg, "en_func_id": en_fid,
                         "en_offset_key": en_key, "en_segment": en_seg})
    return rows


def generate(zh_blob, review):
    """Returns (dual_blob, dual_rows, skipped)."""
    by_key = load_en_by_key(review)
    out = bytearray()
    dual_rows = []
    skipped = []
    offset = 0
    while offset < len(zh_blob):
        if zh_blob[offset:offset + 8] == b"\xff\xff\xff\xffUSCY":
            offset = dis.skip_symbol_table(zh_blob, offset)
            continue
        try:
            fid, fdata, ext, nxt = dis.parse_function(zh_blob, offset)
        except (struct.error, IndexError):
            break
        if nxt <= offset:
            break
        fid_hex = "0x%04X" % fid
        func = dis.disassemble_function(fid, fdata, ext)
        lines = dis.extract_say_lines(func)
        groups = {}
        for line in lines:
            key = offset_key_for(line["addsi_offsets"])
            if key:
                groups.setdefault(key, []).append(line)
        traces = {}
        for key, seg_lines in groups.items():
            info_per_seg = by_key.get((fid_hex, key)) or {}
            merged_parts = []
            for line in seg_lines:
                zh = line["text"]
                en = info_per_seg.get(line["segment"], {}).get("text", "")
                merged_parts.append(build_merged(zh, en) if en else zh)
            if not merged_parts:
                continue
            t = tuple(seg_lines[0]["addsi_offsets"])
            if t in traces:
                skipped.append((fid_hex, key, "duplicate trace"))
                continue
            traces[t] = "~".join(merged_parts)
        if not traces:
            out += zh_blob[offset:nxt]
            offset = nxt
            continue
        try:
            new_blob, first_offsets, _ = rebuild_function(fdata, ext, traces)
        except ValueError as e:
            skipped.append((fid_hex, str(e)))
            out += zh_blob[offset:nxt]
            offset = nxt
            continue
        out += new_blob
        for key, seg_lines in groups.items():
            t = tuple(seg_lines[0]["addsi_offsets"])
            if t not in first_offsets:
                continue
            new_key = "%x" % first_offsets[t]
            info_per_seg = by_key.get((fid_hex, key)) or {}
            for line in seg_lines:
                seg = line["segment"]
                dual_rows.append({"zh_func_id": fid, "zh_offset_key": new_key,
                                  "zh_segment": seg,
                                  "en_func_id": fid, "en_offset_key": key,
                                  "en_segment": seg})                # dual->zh
                info = info_per_seg.get(seg)
                if info and info["text"]:
                    dual_rows.append({"zh_func_id": fid,
                                      "zh_offset_key": new_key,
                                      "zh_segment": seg,
                                      "en_func_id": int(info["en_func_id"], 16),
                                      "en_offset_key": info["en_offset_key"],
                                      "en_segment": info["en_segment"]})  # dual->en
        offset = nxt
    return bytes(out), dual_rows, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zh",
                    default=str(Path(__file__).parent / "_live" / "usecode.zh"))
    ap.add_argument("--review",
                    default=str(Path(__file__).parent / "bilingual_mapping_review.json"))
    ap.add_argument("--out",
                    default=str(Path(__file__).parent / "_live" / "usecode.dual"))
    ap.add_argument("--map-out",
                    default=str(Path(__file__).parent / "_live" / "dual_map.dat"))
    args = ap.parse_args()

    zh_blob = Path(args.zh).read_bytes()
    review = json.loads(Path(args.review).read_text(encoding="utf-8"))
    dual_blob, dual_rows, skipped = generate(zh_blob, review)
    Path(args.out).write_bytes(dual_blob)
    write_blm2(args.map_out, dual_rows)
    print(f"Wrote {args.out}: {len(dual_blob)} bytes")
    print(f"Wrote {args.map_out}: {len(dual_rows)} rows")
    for item in skipped[:10]:
        print("  skipped:", item, file=sys.stderr)
    if len(skipped) > 10:
        print(f"  ... and {len(skipped) - 10} more", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tools/voice_acting/test_gen_dual_usecode.py -q`
Expected: all tests PASS.

- [ ] **Step 5: Run the existing disassembler tests**

Run: `python -m pytest tools/voice_acting/test_disassemble_usecode.py -q`
Expected: all PASS (no regression from importing `disassemble_usecode`).

- [ ] **Step 6: Commit**

```bash
git add tools/voice_acting/gen_dual_usecode.py tools/voice_acting/test_gen_dual_usecode.py
git commit -m "feat(dual): generator for usecode.dual and dual_map.dat"
```

### Task 9: Deploy + docs

**Files:**
- Modify: `deploy.ps1`
- Modify: `tools/voice_acting/doc/bilingual_mapping_generation.md`

- [ ] **Step 1: deploy.ps1 copies the dual artifacts**

After the `usecode.zh` copy block (lines ~25-30), insert:

```powershell
if (Test-Path "$workspace\tools\voice_acting\_live\usecode.dual") {
    Copy-Item -Path "$workspace\tools\voice_acting\_live\usecode.dual" -Destination "$patchDest\" -Force
    Copy-Item -Path "$workspace\tools\voice_acting\_live\dual_map.dat" -Destination "$voiceDest\" -Force
}
```

- [ ] **Step 2: Document the dual generation step**

Append to `tools/voice_acting/doc/bilingual_mapping_generation.md`:

```markdown
## 10. Dual Subtitle usecode.dual Generation

1. Ensure `_live/usecode.zh` is the current compiled ZH binary and
   `bilingual_mapping_review.json` is up to date.
2. Run:
   `python gen_dual_usecode.py`
   (paths via `--zh/--review/--out/--map-out`; defaults: `_live/usecode.zh`,
   `bilingual_mapping_review.json`, outputs into `_live/`).
3. Outputs: `_live/usecode.dual` (dialogue strings merged as `ZH\nEN`) and
   `_live/dual_map.dat` (dual?h and dual?n voice key rows, BLM2).
4. `deploy.ps1` copies both into the distribution's patch dir.

Invariant: every original data offset and every non-dialogue byte in
`usecode.dual` is byte-identical to `usecode.zh`; only mapped dialogue
traces redirect their first `addsi` to an appended merged string. Voice
lookup in dual text mode goes through `dual_map.dat` (`map_offset(DUAL)`).
```

- [ ] **Step 3: Commit**

```bash
git add deploy.ps1 tools/voice_acting/doc/bilingual_mapping_generation.md
git commit -m "chore(dual): deploy usecode.dual + dual_map.dat, document generation"
```

---

### Task 10: End-to-end verification

**Files:** none (runtime checks)

- [ ] **Step 1: Generate against the live lineage**

Run (from `tools/voice_acting`):
```powershell
python gen_dual_usecode.py
```
Expected: prints `Wrote ... usecode.dual: N bytes` and `Wrote ... dual_map.dat: M rows`; `skipped` should be small (report the number).

- [ ] **Step 2: Spot-check merged rows**

Run:
```powershell
python disassemble_usecode.py ..\..\_live\usecode.dual --func 0x009a --format voice
```
Expected: the disassembly of Erethian's dialogue shows the merged strings (e.g. `"I'll speak to you no more, Avatar!"\n<ZH>` style pairs — verify 3-5 known rows from the review JSON appear as `ZH\nEN` and that unpaired rows show ZH only.

- [ ] **Step 3: Manual engine smoke test**

1. Copy `tools/voice_acting/_live/usecode.dual` → `<Ultima_7>/patch/usecode.dual` and `dual_map.dat` → `<Ultima_7>/patch/voice_acting/dual_map.dat`.
2. Launch the built `exult.exe` with the fork's `exult.cfg`; open Audio Options; set Text Language = `Dual`.
3. In-game: start a conversation with an NPC — the dialogue box shows Chinese on top and English below; click-to-continue paginates long lines; Avatar choices render as stacked pairs; an NPC bark (top-left quote) shows two lines.
4. Toggle Voice Language zh then en — both play correct audio for the same dialogue.
5. Set Text Language back to English and Chinese — single-language rendering as before.
6. Delete `patch/usecode.dual` (keep `dual_map.dat`), restart, select Dual — engine logs `usecode.dual not found; dual mode will fall back to Chinese` and dialogue shows Chinese.

- [ ] **Step 4: Commit any fix-ups produced during verification**

```bash
git add -u
git commit -m "fix(dual): verification adjustments"
```

(Only if changes were needed.)
