# Bilingual Text & Voice Support — Design Spec

## Overview

Add Chinese/English bilingual text and voice support to Exult-for-zh with runtime switching in Audio Options. Two independent settings: **Text Language** and **Voice Language**.

## Architecture: Dual Usecode Machine (Approach A)

Two `Usecode_machine` instances loaded simultaneously. A `BilingualManager` singleton owns both and swaps the active pointer when language changes.

### Why Approach A

- Minimal changes to existing usecode internals — each machine is self-contained
- ~3MB memory cost is negligible on modern systems
- Clean separation: text vectors stored per-language, no pointer confusion
- Future dual-text mode (English+Chinese) adds a third usecode — natural extension

---

## Component 1: BilingualManager Singleton

New class `bilingual_manager.h` / `bilingual_manager.cc`.

```cpp
enum class TextLanguage { ENGLISH = 0, CHINESE = 1 };

class BilingualManager {
public:
    static BilingualManager& get();

    void init();  // Load both usecode files, text vectors, bilingual map
    void shutdown();

    TextLanguage get_text_language() const;
    void set_text_language(TextLanguage lang);  // Swaps active usecode + text

    Usecode_machine* get_active_usecode();
    Usecode_machine* get_usecode(TextLanguage lang);

    // Bilingual map for cross-language voice lookup
    bool map_offset(TextLanguage from_lang, int func_id,
                    const std::string& offset_key,
                    int& out_func_id, std::string& out_offset_key);

private:
    TextLanguage current_lang = TextLanguage::ENGLISH;
    Usecode_machine* usecode_en = nullptr;  // STATIC/usecode
    Usecode_machine* usecode_zh = nullptr;  // patch/usecode.zh

    // Bilingual mapping table
    std::vector<VoiceMapping> bilingual_map;
};
```

### Initialization Flow

1. Load English usecode from `<STATIC>/usecode` → `usecode_en`
2. Load Chinese usecode from `<PATCH>/usecode.zh` → `usecode_zh`
3. Load English text vectors from `<STATIC>/textmsg.txt`
4. Load Chinese text vectors from `<PATCH>/textmsg.txt`
5. Load Chinese spell names from `<PATCH>/spellnames.txt`
6. Load bilingual map from generated file
7. Set active usecode to `usecode_en` (default)

### Language Switch (`set_text_language`)

1. Swap `Game_window::usecode` pointer to target language's usecode
2. Swap `Game_singletons::ucmachine` pointer
3. Update `current_lang`
4. Call `gwin->set_all_dirty()` to refresh UI

---

## Component 2: Text Vector Switching

### `shapes/items.cc`

Current file-scope globals become language-indexed:

```cpp
static vector<string> item_names[2];  // [ENGLISH], [CHINESE]
static vector<string> text_msgs[2];
static vector<string> misc_names[2];
```

Existing `get_text_msg(idx)` becomes language-aware:

```cpp
const char* get_text_msg(unsigned idx) {
    int lang = static_cast<int>(BilingualManager::get().get_text_language());
    return get_text_internal(text_msgs[lang], idx);
}
```

New public function: `Reload_text(TextLanguage lang)` — loads text vectors for a specific language from the appropriate file path.

### `gumps/Spellbook_gump.cc`

Spell names become language-indexed:

```cpp
static vector<string> custom_spell_names[2];
static bool spell_names_loaded[2] = {false, false};

void Load_spell_names(TextLanguage lang);
```

Accessed via `BilingualManager::get_text_language()` to select the correct vector.

---

## Component 3: Bilingual Map Generation

### Standalone Python tool: `tools/gen_bilingual_map.py`

**Input:** English usecode (`STATIC/usecode`), Chinese usecode (`patch/usecode.zh`)

**Process:**
1. Parse both usecode binaries — extract function table, string constants
2. For each conversation function, match segments by positional alignment
3. Build mapping: Chinese offset → English offset

**Output:** `patch/voice_acting/bilingual_map.dat`

**Binary format:**
```
BLMP                    (4 bytes header)
entry_count             (4 bytes, uint32)
For each entry:
    zh_func_id          (4 bytes, int32)
    zh_offset_key       (null-terminated string)
    segment             (2 bytes, uint16)
    en_func_id          (4 bytes, int32)
    en_offset_key       (null-terminated string)
```

### C++ Loading (`BilingualManager::load_bilingual_map()`)

```cpp
struct VoiceMapping {
    int zh_func_id;
    std::string zh_offset_key;
    int segment;
    int en_func_id;
    std::string en_offset_key;
};

bool map_offset(TextLanguage from_lang, int func_id,
                const std::string& offset_key,
                int& out_func_id, std::string& out_offset_key);
```

---

## Component 4: Voice Language Switching

### `audio/VoiceActingManager.cc`

Existing `voice_language` config already supports `"en"` and `"zh"`.

**Cross-language lookup in `play_for_conversation()`:**

```
if (voice_language != text_language) {
    bilingual_map->map_offset(CHINESE, func_id, offset_key,
                              en_func_id, en_offset_key);
    // Search English voice file using translated key
    find_voice_file(en_base_filename, path);
}
```

**Config keys:**
- `config/audio/text/language` → `"en"` or `"zh"`
- `config/audio/voice/language` → `"en"` or `"zh"`

---

## Component 5: GUI Changes

### `gumps/AudioOptions_gump.h`

New button IDs:

```cpp
id_text_language,    // row 14
id_voice_language,   // row 15
```

New member variables:

```cpp
TextLanguage text_language;
TextLanguage voice_language;
```

### `gumps/AudioOptions_gump.cc`

**New rows in `rebuild_buttons()`:**

```cpp
std::vector<std::string> lang_options = {"English", "Chinese"};
buttons[id_text_language] = std::make_unique<AudioTextToggle>(
    this, &AudioOptions_gump::toggle_text_language,
    std::move(lang_options), static_cast<int>(text_language),
    get_button_pos_for_label("Text Language"), yForRow(14), 80);

std::vector<std::string> vlang_options = {"English", "Chinese"};
buttons[id_voice_language] = std::make_unique<AudioTextToggle>(
    this, &AudioOptions_gump::toggle_voice_language,
    std::move(vlang_options), static_cast<int>(voice_language),
    get_button_pos_for_label("Voice Language"), yForRow(15), 80);
```

**Labels in `paint()`:**

```cpp
font->paint_text(iwin->get_ib8(), "Text Language", x + label_margin, y + yForRow(14) + 1);
font->paint_text(iwin->get_ib8(), "Voice Language", x + label_margin, y + yForRow(15) + 1);
```

**Constructor background:** Increase to `yForRow(15) + 2 * bottomrow_gap`.

---

## Component 6: Config Persistence

**Config keys:**
```
config/audio/text/language    → "en" or "zh"
config/audio/voice/language   → "en" or "zh"
```

**`load_settings()` addition:**
```cpp
string text_lang_str, voice_lang_str;
config->value("config/audio/text/language", text_lang_str, "en");
config->value("config/audio/voice/language", voice_lang_str, "zh");
text_language = (text_lang_str == "zh") ? TextLanguage::CHINESE : TextLanguage::ENGLISH;
voice_language = (voice_lang_str == "zh") ? TextLanguage::CHINESE : TextLanguage::ENGLISH;
```

**`save_settings()` addition:**
```cpp
config->set("config/audio/text/language",
    text_language == TextLanguage::CHINESE ? "zh" : "en", false);
config->set("config/audio/voice/language",
    voice_language == TextLanguage::CHINESE ? "zh" : "en", false);
BilingualManager::get().set_text_language(text_language);
VoiceActingManager::get().set_voice_language(
    voice_language == TextLanguage::CHINESE ? "zh" : "en");
```

---

## Error Handling

| Missing File | Fallback |
|---|---|
| `patch/usecode.zh` | English-only mode, text language toggle disabled |
| `patch/textmsg.txt` | English text for both languages |
| `patch/spellnames.txt` | Empty spell names for Chinese |
| `bilingual_map.dat` | No cross-language voice (voice follows text lang) |

---

## Future: Dual-Text Mode

When a third text option is needed (English + Chinese displayed together):

1. Add `TextLanguage::DUAL` enum value
2. Build `usecode.dual` by merging English + Chinese conversation text using `~` separator
3. Add third `Usecode_machine* usecode_dual` in `BilingualManager`
4. Modify `say_string()` to display both segments from the `~` split instead of clicking between them
5. Text vectors add a third slot for dual-language display
