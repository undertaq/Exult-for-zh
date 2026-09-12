# U6 Runtime Speaker Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Capture U6 dialogue speakers from the active runtime and use that attribution in the translation review HTML, eliminating the incorrect U7 static speaker-map dependency.

**Architecture:** `GameplayTranslationManager` writes a separate runtime speaker TSV while it captures dialogue sources. `Usecode_internal::say_string()` resolves the active U6 actor from the face/caller context and records it by the existing dialogue key. `tools/u6_translation` parses the capture, merges it over the optional static map, and marks conflicting observations as ambiguous.

**Tech Stack:** C++17, existing Autotools build, Python 3 standard library, UTF-8 escaped TSV, existing review HTML generator.

**Spec:** `docs/superpowers/specs/2026-09-12-u6-runtime-speaker-attribution-design.md`

## Global Constraints

- Do not use the Ultima 7 NPC function table to infer U6 runtime speakers.
- Do not change usecode control markers or conversation branching.
- Speaker capture must be independent of voice playback being enabled.
- Keep the existing static `--speaker-map` option as a fallback.
- Preserve unrelated worktree changes and generated artifacts.
- Run focused tests before claiming completion, then run the full relevant Python suite.

## Task 1: Add failing C++ coverage for runtime speaker capture

Files:

- `tests/gameplay_translation_table_test.cc`

- [x] Add source-level assertions for `record_runtime_speaker`, the speaker capture header/default path, `speaker_path` configuration, and the `say_string()` call site.
- [x] Add assertions that U6 actor resolution uses `get_npc()` and `get_npc_name()` rather than the U7 voice-acting table.
- [x] Run the focused test path before implementation; the recursive check was blocked by the environment's missing SDL3 headers, while the direct test target was used for verification.

## Task 2: Implement C++ speaker capture and U6 attribution

Files:

- `gameplay_translation.h`
- `gameplay_translation.cc`
- `usecode/ucinternal.cc`
- `tools/u6_translation/README.md`

- [x] Add `GameplayTranslationManager::record_runtime_speaker(key, speaker_id, speaker_name)` and a deduplicated speaker stream.
- [x] Open `config/debug/translation/speaker_path` under `GAMEDAT`, defaulting to `u6_runtime_speakers.tsv`, with the same safe-path checks as catalog capture.
- [x] Close the speaker stream and clear its deduplication state in `shutdown()`.
- [x] Resolve the active U6 actor name from `voice_current_face_npc`, the conversation caller, or the main actor fallback, preserving the numeric id.
- [x] Record speaker attribution beside each dialogue segment after its stable key is constructed, regardless of translation or voice enablement.
- [x] Document the file format and capture configuration.
- [ ] Build the affected full C++ target; focused translation test passes, but compilation of `usecode/ucinternal.cc` is blocked by missing `SDL3/SDL.h`.

## Task 3: Add Python capture parser with tests first

Files:

- `tools/u6_translation/speaker_map.py`
- `tools/u6_translation/tests/test_speaker_map.py`

- [x] Write failing tests for escaped TSV fields, dialogue filtering, same-name deduplication, conflicting names, numeric-only rows, and malformed ids/field counts.
- [x] Run the focused Python tests and confirm failure.
- [x] Implement `load_speaker_capture()` and `speaker_map_from_capture()` using the existing runtime-table TSV decoder.
- [x] Represent conflicting names as `Ambiguous · name1 / name2`, while preserving an explicit unresolved label for numeric-only observations.
- [x] Run the new tests and the existing `tools/u6_translation/tests` suite.

## Task 4: Integrate review HTML CLI precedence

Files:

- `tools/u6_translation/__main__.py`
- `tools/u6_translation/tests/test_cli.py`
- `tools/u6_translation/review_html.py` if display handling needs adjustment
- `tools/u6_translation/README.md`

- [x] Add `review-html --speaker-capture PATH`.
- [x] Merge runtime capture over `--speaker-map`; preserve static-map values for keys not observed at runtime.
- [x] Add a CLI fixture proving runtime attribution wins; parser tests cover ambiguous labels.
- [x] Run the focused CLI tests and the complete Python suite.

## Task 5: Verify and hand off

- [x] Run the focused translation test target and the complete `tools/u6_translation` test suite.
- [ ] Run a source/build smoke check for the modified full C++ files once SDL3 headers are available.
- [x] Inspect `git diff --check` and `git status --short`; unrelated generated or untracked files remain unstaged.
- [x] Explain that the new map resolves dialogue visited while capture is enabled; unvisited dialogue remains explicitly unresolved until runtime coverage is collected.
