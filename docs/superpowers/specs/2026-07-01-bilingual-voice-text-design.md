# Bilingual Voice & Text Design Specification

## 1. Goal

Allow independent player selection of **text language** (English/Chinese) and **voice language** (English/Chinese) in Exult-for-zh. English usecode always drives execution; Chinese text overlays at display time via a bilingual mapping registry.

### Constraints
- Always execute original English usecode — never modify or replace usecode files
- Voice and text languages are independently toggleable
- Voice files named under canonical English (func_id, offset_key, segment); voice language selects audio directory (`en/` or `zh/`)
- Custom binary mapping file (not compiled-in or external JSON) — updateable without recompile
- No cross-language voice fallback

## 2. Architecture

### Layer Diagram

```
Audio Options Gump
  ├─ voice_enabled     (On/Off)
  ├─ voice_language    (English/Chinese)
  └─ text_language     (English/Chinese)
         │
         ▼
VoiceActingManager
  ├─ get_text_language() → int
  ├─ set_text_language(int)
  ├─ set_voice_language(int)
  ├─ lookup_text(func_id, offset_key, segment) → string
  ├─ find_voice_file(func_id, key, seg, lang) → path
  └─ play_for_conversation() → calls lookup_text()
         │
         ├──── BilingualMapping (static class)
         │       ├─ load(path) → bool
         │       └─ lookup(func_id, key, seg) → string
         │
         └──── Binary .dat file
                 BLMP | version(2B) | count(4B) |
                 entries: { func_id(2B) | key_len(2B) | key_bytes | segment(2B) | text_len(4B) | text_utf8 }
```

### Data Flow: NPC Speech (say_string)

```
usecode → ADDSI string literal → voice_string_trace ←┐
                                                       │
say_string() ──────────────────────────────────────────┤
  ├─ build key from voice_string_trace                 │
  ├─ lookup_text(func_id, offset_key, segment) ────────┘
  │     └─ BilingualMapping::lookup() → Chinese text
  ├─ if text_language == Chinese && found → overlay Chinese
  ├─ play_for_conversation(key, seg) → voice file playback
  └─ clear voice_string_trace, voice_pushs_trace
```

### Data Flow: Dialogue Options (add_answer)

```
usecode → PUSHS string literal → voice_pushs_trace ←┐
                                                      │
add_answer intrinsic ─────────────────────────────────┤
  ├─ try voice_string_trace first, fallback to voice_pushs_trace
  ├─ lookup_text(func_id, key, segment) → Chinese text
  ├─ answers.push_back(English text)  ← for usecode strcmp
  ├─ set_last_answer_display(Chinese text or English fallback)
  └─ clear both traces
```

### Data Flow: Dialogue Option Display

```
gump → show_avatar_choices()
  └─ answers_display[i] → rendered to screen
```

### Data Flow: Books (show_book)

```
show_book()
  ├─ build key from remaining voice_string_trace entries
  ├─ lookup_text(func_id, key, segment)
  ├─ if found → overlay Chinese text
  ├─ log: [show_book] diagnostic
  └─ clear voice_string_trace
```

### Key Data Structures

| Structure | Location | Purpose |
|-----------|----------|---------|
| `voice_string_trace` | `ucinternal.h:92` | ADDSI string offsets (NPC speech, books) |
| `voice_pushs_trace` | `ucinternal.h:93` | PUSHS string offsets (dialogue options) |
| `answers` | `conversation.h:46` | English text for usecode `strcmp` comparisons |
| `answers_display` | `conversation.h:47` | Chinese display text for rendering |
| `answer_stack` | `conversation.h:48` | Save/restore `answers` across usecode contexts |
| `answer_display_stack` | `conversation.h:49` | Save/restore `answers_display` across usecode contexts |
| `BilingualMapping::map_` | `BilingualMapping.h` | `unordered_map<Key, string>` in-memory cache |

## 3. Components

### 3a. BilingualMapping (audio/BilingualMapping.h, audio/BilingualMapping.cc)
- Static class: `load(path)`, `lookup(func_id, key, seg)`, `is_loaded()`
- Binary .dat parser with `read_or_fail` helper and bounds validation
- Key struct: `{ uint16 func_id, uint8 key[40], uint16 segment }` with custom hash
- `BLMP` magic, version uint16, entry count uint32, then flat entries

### 3b. VoiceActingManager (audio/VoiceActingManager.h, audio/VoiceActingManager.cc)
- `text_language` member (0=English, 1=Chinese)
- `voice_language` member (0=English, 1=Chinese)
- `lookup_text(func_id, key, seg)` → returns Chinese text or empty string
- `find_voice_file(func_id, key, seg, lang)` → constructs voice file path per language
- `play_for_conversation()` → speech playback with text lookup, logging
- `set_text_language(int)` / `set_voice_language(int)` → immediate runtime update via `config->set()`

### 3c. Audio Options Gump (gumps/AudioOptions_gump.cc)
- Three toggles: `voice_enabled`, `voice_language`, `text_language`
- Hardcoded labels: `"Voice Language:"`, `"Text Language:"`
- Toggle values: `{"English", "Chinese"}`
- `save_settings()` calls `set_voice_language()` and `set_text_language()` directly

### 3d. Conversation System (usecode/conversation.h, usecode/conversation.cc)
- `answers` vector: always stores English text (for usecode `get_answer()` comparisons)
- `answers_display` vector: stores Chinese display text (or English fallback)
- `set_last_answer_display(string)`: replaces last entry in `answers_display`
- `show_avatar_choices()`: renders from `answers_display`
- `push_answers/pop_answers/clear_answers/remove_answer`: all handle both vectors
- `show_npc_message()`: `has_chinese` detection at bytes >= 0x80, adjusts line height/rect for NPC speech

### 3e. Usecode Integration (usecode/ucinternal.cc, usecode/intrinsics.cc)
- `say_string()`: builds key from `voice_string_trace`, looks up Chinese overlay, plays voice, clears both traces
- `show_book()`: builds key from remaining trace entries, looks up text, clears trace
- `add_answer` intrinsic (intrinsics.cc:160): builds key from `voice_string_trace` first, falls back to `voice_pushs_trace`, stores English in `answers`, calls `set_last_answer_display(zh)`
- PUSHS opcode handler (ucinternal.cc:2465): pushes offset to `voice_pushs_trace`
- `strcmp(str, user_choice) == 0` at ucinternal.cc:2351 — compares against `answers` (always English)

## 4. Binary .dat Format

```
Offset  Size  Field
0       4     Magic: "BLMP"
4       2     Version (uint16 LE)
6       4     Entry count (uint32 LE)
10+     var   Entries
```

Each entry:
```
Offset  Size  Field
0       2     func_id (uint16 LE)
2       2     key_len (uint16 LE)
4       key_len  offset_key (raw bytes, not null-terminated)
4+key_len  2   segment (uint16 LE)
6+key_len  4   text_len (uint32 LE)
10+key_len  text_len  text (UTF-8, not null-terminated)
```

Generated by `tools/voice_acting/generate_bilingual_mapping_data.py`.

## 5. Static Analysis Pipeline

### Tool: `tools/voice_acting/generate_bilingual_mapping_static.py`

```
Step 1: Disassemble EN and ZH usecode → extract ADD_SI / PUSH_SI sequences
Step 2: extract_text_sequences() → (addsi_seqs, pushs_seqs, data_seg)
Step 3: build_sequence_map() → (addsi_map, pushs_map)
  Keys: (func_id, initial_seq_offset)
  Values: [{offset, text, position_index}, ...]
Step 4: pair_sequences() — content-based matching first:
  ├─ extract_ascii_tokens(text) → [ASCII word tokens]
  ├─ compute_match_score(en_tokens, zh_tokens) → score
  │   Requires >= 2 shared tokens, or 1 if EN text <= 3 tokens or token is uppercase proper noun
  ├─ Position-distance constraint: |en_pos_index - zh_pos_index| <= 3
  ├─ Greedy match: pick (ei, zi) pair with highest shared token count
  └─ Fallback to position-based pairing for sequences without ASCII tokens
Step 6: Export to bilingual_mapping_static.csv (28,217 entries)
  Columns: func_id, en_offset_key, en_segment, zh_offset_key, zh_segment, confidence
  Confidence tags: matched_pushs, static_pushs, matched_addsi, static_addsi
```

### Merge into .dat:
```
Step 7: generate_bilingual_mapping_data.py --csv static.csv --json review.json
  JSON entries overwrite CSV entries on same (func_id, en_offset_key, en_segment) key
  Output: bilingual_map.dat (24,497 entries)
```

## 6. Current Status

### Completed
- BilingualMapping class (load, lookup, binary parser)
- VoiceActingManager text_language support, say_string() Chinese overlay
- Audio Options UI (voice_enabled, voice_language, text_language toggles)
- Python mapping generation tool
- x64 Debug build succeeds (0 errors)
- Original English usecode now executes (Chinese patched usecode renamed to `usecode.zhbak`)
- `bilingual_map.dat` copied to `<PATCH>/voice_acting/`
- Fix: `set_text_language()` / `set_voice_language()` runtime update (immediate Apply)
- Fix: diagnostic logging — `[say_string]` prints func_id, offset_key, segment, ZH OK/MISS
- Fix: double-encoded UTF-8 mojibake in CSV repaired
- Fix: UI labels — replaced `get_text_msg(0x620/0x621)` with hardcoded strings
- Fix: toggle options — `"中文"` → `"Chinese"`
- Fix: SDL3.dll — debug DLL replaced with working release copy via PostBuildEvent
- Fix: Dialogue options PUSHS trace — separate `voice_pushs_trace` from `voice_string_trace`
- Fix: Book text — `show_book()` now with voice trace context, lookup, logging
- Fix: Both traces cleared after `add_answer`, `show_book`, and `say_string`
- Fix: Voice file checking debug output disabled (commented out `pout` messages)
- Fix: Static analysis — separated ADDSI and PUSHS pairing
- Fix: Static analysis — content-based matching with `extract_ascii_tokens()` and `compute_match_score()`
- Fix: Position-distance constraint (|ei-zi| <= 3) for content-based matching
- Fix: Minimum 2 shared tokens (or 1 proper noun for short texts)
- Fix: Static analysis tries content matching FIRST, falls back to position-based
- `bilingual_mapping_static.csv` regenerated: 28,217 entries with confidence tags
- `bilingual_map.dat` regenerated: 24,497 entries (merged from CSV + JSON)
- **ROOT CAUSE FOUND for unclickable dialogue options**: `strcmp(str, user_choice) == 0` at ucinternal.cc:2351 compares Chinese with hardcoded English
- **FIX: `answers_display` parallel vector** — English always in `answers`, Chinese display in `answers_display`
- Build succeeds (0 errors) with `answers_display` fix

### Known Issues
1. **Not yet tested with rebuilt binary** containing `answers_display` fix — user hasn't run Exult since fix was compiled
2. **Voice filenames mismatch**: English usecode generates different offset keys than Chinese usecode used to name voice files; need regeneration
3. **Review JSON func_ids mismatch**: JSON entries keyed by Chinese usecode func/offset — only ~42 func=0x0401 entries have correct English func_ids
4. **Wrong NPC speech text**: key=6bf in func=0x401 paired with wrong ZH offset (650) via position-based fallback
5. **JSON-only .dat has 8,404 entries but lacks most dialogue option keys** — only works for func=0x0401 entries that happen to match

## 7. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Approach A (text overlay) over dual-usecode | Minimal engine changes, English usecode always drives execution |
| Custom binary .dat over compiled-in or JSON | Updateable without recompile, fast to load |
| `BLMP` binary format | Simple flat structure, easy to parse in C++ and generate in Python |
| No cross-language voice fallback | Voice language strictly respected — cleaner UX |
| Two-option toggles (not scrollable list) | Matches existing UI pattern in Audio Options |
| Immediate Apply via `config->set()` | No restart required, settings take effect right away |
| Separate `voice_pushs_trace`/`voice_string_trace` | PUSHS and ADDSI are different opcodes; sharing trace causes key contamination |
| English in `answers`, Chinese in `answers_display` | Fixes `strcmp` failure — usecode always compares against English strings |
| Content-based matching for static analysis | More reliable than position-based when sequence counts differ between EN and ZH |
| Position-distance constraint `<= 3` | Prevents false positives from sequences at very different positions |

## 8. Next Steps

1. **Test rebuilt binary**: Run `exult -p`, talk to Iolo, verify options are clickable
2. **Fix wrong NPC speech**: key=6bf + func=0x401 — manual override or improved matching heuristics
3. **Improve static analysis**: reduce false positives in content matching
4. **Regenerate voice files** using English offset keys
5. **Test books**: open a book in-game, check `[show_book]` diagnostic output
6. **Build release configuration** for final deployment

## 9. Relevant Files

| File | Role |
|------|------|
| `audio/BilingualMapping.h` | BilingualMapping class declaration (static load/lookup, private Key/KeyHash) |
| `audio/BilingualMapping.cc` | Binary .dat parser with read_or_fail helper, bounds validation |
| `audio/VoiceActingManager.h` | text_language, voice_language, lookup_text(), play_for_conversation() |
| `audio/VoiceActingManager.cc` | Config init, BilingualMapping::load, runtime updaters, log_entry |
| `usecode/ucinternal.cc` | say_string() overlay, show_book() lookup, PUSHS handler, strcmp at 2351 |
| `usecode/ucinternal.h` | voice_string_trace (line 92), voice_pushs_trace (line 93) |
| `usecode/conversation.cc` | add_answer, show_npc_message, show_avatar_choices, answers/answers_display handling |
| `usecode/conversation.h` | answers (46), answers_display (47), answer_stack (48), answer_display_stack (49) |
| `usecode/intrinsics.cc` | add_answer intrinsic — key building, diagnostic logging |
| `gumps/AudioOptions_gump.cc` | UI toggles, save_settings(), hardcoded labels |
| `tools/voice_acting/generate_bilingual_mapping_data.py` | Binary .dat generation from CSV + JSON inputs |
| `tools/voice_acting/generate_bilingual_mapping_static.py` | Static analysis: disassemble, extract, content-match, pair, export |
| `tools/voice_acting/bilingual_mapping_static.csv` | 28,217 entries with confidence tags |
| `tools/voice_acting/bilingual_mapping_review.json` | 10,245 hand-validated entries (keys from Chinese usecode) |
| `tools/voice_acting/bilingual_map.dat` | 24,497 entries — final merged binary |
