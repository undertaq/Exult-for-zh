# Dual Subtitle (usecode.dual) Design

Date: 2026-08-18
Branch: `dual_subtitle`
Status: Approved

## Goal

Add a third text-language mode, **Dual**, that displays dialogue in both
Chinese and English (Chinese on top, English below, stacked in the dialogue
box). Backed by a new compiled usecode binary, `<PATCH>/usecode.dual`, whose
dialogue strings are merged `ZH\nEN` pairs.

## Context

- The fork already ships `usecode` (EN) and `<PATCH>/usecode.zh` (ZH) managed
  by `BilingualManager` (`bilingual_manager.h/cc`), with `TextLanguage`
  enum { ENGLISH, CHINESE } and config key `config/audio/text/language`
  (`"en"`/`"zh"`).
- `bilingual_map.dat` (`<PATCH>/voice_acting/bilingual_map.dat`) already maps
  every dialogue/speech row between ZH and EN at the
  (func_id, offset_key, segment) granularity (used for voice).
- `shapes/font.cc` already breaks text natively on `\n`, so a merged
  `ZH\nEN` string renders as two stacked lines without special paint code.

## 1. `usecode.dual` content

- Sibling of `usecode.zh`, same function table and data layout.
- Every dialogue row present in `bilingual_map.dat` becomes
  `<ZH text>\n<EN text>`.
- ZH row with no EN counterpart keeps ZH text alone (pair-fallback ZH).
- Rows not present in the map keep their ZH text unchanged.
- All voice keys, function IDs, and offsets remain identical to
  `usecode.zh` — no runtime pairing, no runtime text lookup.

### Generation tool

New script `tools/voice_acting/gen_dual_usecode.py`:

- Inputs: `usecode.zh`, `bilingual_map.dat` (BLM2/BLMP format, same reader
  as `BilingualManager::load_bilingual_map`).
- Reuses the existing disassembly/pairing/text-replacement machinery from
  the documented pipeline (`docs/voice_acting_guide.md` /
  `tools/voice_acting/doc/bilingual_mapping_generation.md`).
- Output: `patch/usecode.dual`.
- Doc section added explaining how to run it.

## 2. Engine loading & language state

- `fnames.h`: add `#define DUAL_USECODE "<PATCH>/usecode.dual"`.
- `bilingual_manager.h`:
  - `TextLanguage { ENGLISH = 0, CHINESE = 1, DUAL = 2 }`.
  - Member `usecode_dual`;
    `bool is_dual_available() const { return usecode_dual != nullptr; }`.
  - `get_usecode(TextLanguage)` returns dual → zh → en fallback chain for
    `DUAL`.
- `bilingual_manager.cc`:
  - `load_usecode_files()` loads `DUAL_USECODE` if present; if absent,
    log a warning (`[Bilingual] usecode.dual not found; dual mode will
    fall back to Chinese`). Never throws.
  - `init()`: parse config `"dual"` → `TextLanguage::DUAL`.
  - `get_active_usecode()`/`set_text_language()` handle DUAL like CHINESE
    (dual binary shares zh's layout).
  - `shutdown()` deletes `usecode_dual`.
  - `map_offset()` unchanged (dual text never needs runtime
    cross-language mapping for subtitles).

## 3. Rendering

Strings containing `\n` only exist in the dual binary, so all changes below
are gated on "string contains `\n`" and are inert for EN/ZH modes.

### NPC dialogue — `usecode/conversation.cc::show_npc_message`

- Existing `has_chinese` byte scan already trips on ZH bytes → Chinese font,
  22px minimum line height, widened large-face box all apply automatically.
- Addition: when the display string contains `\n`, grow the large-face
  `text_rect` by one extra line height (room for the two stacked lines) and
  use the Chinese line height in `render_box_h`/pagination math.
- Click-to-continue pagination (`sman->paint_text_box` < 0 path) already
  works per physical line; no change needed.

### Avatar choices — `show_avatar_choices`

- For each choice, count `\n` occurrences; the choices box allocates that
  many rows per choice (2 rows for a dual choice). Box height math uses the
  Chinese line height when any choice contains `\n`.

### Barks — `effects.cc::Text_effect`

- `init()`: when `msg` contains `\n`, height = `8 + 2*line_height` and
  width = `8 + max(line widths)`.
- `Figure_text_pos()`: when dual text, nudge the bubble up one extra line
  height so it stays above the NPC head.

### Journal — `gumps/Notebook_gump.cc`

- Already renders both languages via its own bilingual path; no change.
- Binary `== CHINESE` layout checks treat DUAL as Chinese (no behavior
  change in dual mode).

## 4. UI — `gumps/AudioOptions_gump.cc/h`

- Text-language toggle becomes 3-way: `English / Chinese / Dual`
  (`lang_options = {"English", "Chinese", "Dual"}`).
- `text_language` int: 0 = EN, 1 = ZH, 2 = Dual.
- `load_settings()`: parse `"dual"` → 2.
- `ok()`: commit `"en"`/`"zh"`/`"dual"` and call
  `set_text_language`(ENGLISH/CHINESE/DUAL).
- Voice-language toggle stays 2-way (`English / Chinese`).

## 5. Voice — `audio/VoiceActingManager.cc`

- Dual text counts as ZH-side: the cross-language condition
  (`play_for_conversation`, ~line 475) gains
  `|| text_lang == TextLanguage::DUAL`.
- voice=zh → plays directly (dual layout = zh func/offset keys).
- voice=en → ZH→EN cross-map as today.
- No other voice logic changes.

## 6. Edge integration

- `gumps/Spellbook_gump.cc:596`: clamp DUAL → CHINESE when indexing
  `custom_spell_names[lang]` (spell names stay Chinese; book UI is not
  dialogue).
- `GameDisplayOptions` game-language toggle untouched — install language
  and its patch-file gating stay independent of the text-language level.
- Unknown config value still falls back to EN (current behavior).

## 7. Verification

1. Fork builds cleanly (normal build; msvcstuff for Windows).
2. Config round-trip: `"en" | "zh" | "dual"` parse and commit correctly;
   unknown → EN.
3. With `usecode.dual` present:
   - NPC dialogue shows ZH over EN, both fit; overflow paginates with
     click-to-continue.
   - Avatar choices render dual rows.
   - Barks show two lines above NPC heads.
   - Voice zh / en both play the correct files (zh direct, en cross-mapped).
4. Without `usecode.dual`: dual mode falls back to `usecode.zh` with a
   startup warning.
5. Generate a BG sample `usecode.dual`; spot-check 3–5 rows against
   `bilingual_map.dat` ZH/EN pairs.

## Out of scope

- Books/scrolls text (textmsgs pipeline) remain single-language.
- Combining dual subtitles with speech (voice) direct playback ordering.
- Notebook journal changes.
- Game-language install-level changes.