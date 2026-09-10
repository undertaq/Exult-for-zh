# Ultima 6 Runtime Traditional Chinese Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reviewed, runtime Traditional Chinese translation mode for the Ultima6v1.3 mod, including translated conversation choices, an offline Ollama/Qwen pipeline, and coverage/correctness audits without creating alternate usecode.

**Architecture:** Keep the English usecode machine and English gameplay data authoritative. Add a C++ GameplayTranslationManager backed by a dependency-free UTF-8 TSV table; translate only explicit gameplay display copies, while the existing BilingualManager continues to handle mods that ship alternate usecode. Add a Python 3 offline pipeline that extracts stable catalog entries, translates them through local Ollama, audits them, and emits the runtime table.

**Tech Stack:** C++17, existing Autotools build, existing Exult font/layout and language setting, Python 3 standard library, ucxt -ftt, local Ollama HTTP API, configurable Qwen model, JSONL intermediate files, UTF-8 TSV runtime table.

**Spec:** docs/superpowers/specs/2026-09-10-u6-runtime-zh-translation-design.md

## Global Constraints

- English usecode remains authoritative; do not generate, install, load, or switch to usecode.zh for the U6 table-only mode.
- Load the runtime table from the active mod path at zh_translation.tsv.
- Use the exact u6-translation-v1 four-field TSV contract: kind, key, source_sha256, zh.
- Hash the normalized raw English source with lowercase SHA-256 and fall back to English on a key or hash mismatch.
- Translate choice display copies only; preserve the original English answers for usecode comparisons and branching.
- Keep Exult menus, configuration screens, editor views, and engine-wide lookups outside the gameplay translation scope.
- Never call Ollama from the game process; all model work is offline tooling.
- Use Python standard-library networking and JSON handling; do not add a runtime C++ JSON dependency.
- Preserve existing alternate-usecode behavior for mods that already provide valid Chinese or dual usecode.
- Runtime failures fail open to English; release emission fails closed on structural audit errors.
- Preserve all protected markers, placeholders, control sequences, and configured protected terms.

---

## File Map

Runtime C++ files:

- Create gameplay_translation_table.h and gameplay_translation_table.cc for the TSV parser, field escaping, source normalization, SHA-256, and lookup status.
- Create gameplay_translation.h and gameplay_translation.cc for active-mod loading, language state, runtime lookup, diagnostics, and catalog capture.
- Modify bilingual_manager.h and bilingual_manager.cc to keep a valid English execution machine when an alternate machine is absent.
- Modify gamewin.cc to initialize the manager and make reload behavior table-mode safe.
- Modify usecode/conversation.h, usecode/conversation.cc, usecode/ucinternal.h, and usecode/ucinternal.cc for dialogue and choice display copies.
- Modify shapes/items.h, shapes/items.cc, objs/objs.h, objs/objnames.cc, objs/objs.cc, gumps/ItemMenu_gump.cc, gamewin.cc, usecode/intrinsics.cc, and schedule.cc for gameplay-only names and indexed text-message display.
- Modify Makefile.am to compile the runtime files and a parser test.
- Create tests/gameplay_translation_table_test.cc for the dependency-free C++ table core.

Offline Python files:

- Create tools/u6_translation/__init__.py, __main__.py, catalog.py, runtime_table.py, extract.py, ollama_backend.py, translate.py, audit.py, emit.py, prompts.py, u6_glossary.tsv, and README.md.
- Create tools/u6_translation/tests/test_catalog.py, test_runtime_table.py, test_extract.py, test_runtime_keys.py, test_display_scope.py, test_ollama_backend.py, test_translate.py, test_audit.py, test_emit.py, and test_cli.py.
- Create deterministic fixtures under tools/u6_translation/tests/fixtures/ containing dialogue, choice, text-message, item, and stale-row cases.

## Task 1: Define and test the runtime table core

Files:
- Create gameplay_translation_table.h
- Create gameplay_translation_table.cc
- Create tests/gameplay_translation_table_test.cc
- Modify Makefile.am

Interfaces:
- enum class GameplayTranslationKind { Dialogue, Choice, TextMessage, Item, Location, Misc, Spell };
- enum class TranslationLookupStatus { Hit, Missing, SourceMismatch, Disabled };
- struct TranslationLookup { std::string text; TranslationLookupStatus status; };
- std::string normalize_translation_source(std::string_view source);
- std::string sha256_hex(std::string_view source);
- std::string escape_translation_field(std::string_view field);
- std::optional<std::string> unescape_translation_field(std::string_view field, std::string& error);
- class GameplayTranslationTable { bool load(std::istream& input, std::string& error); TranslationLookup lookup(GameplayTranslationKind kind, std::string_view key, std::string_view english) const; size_t size() const; };

- [ ] Step 1: Write the failing C++ tests.

Add assertions for the known SHA-256 vector, CRLF normalization, escaped tab/newline/backslash round-trips, a valid four-field row, a missing row, a source-hash mismatch, duplicate keys, unknown kinds, invalid escapes, invalid hash length, and empty Chinese text.

    assert(sha256_hex("abc") ==
           "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    assert(normalize_translation_source("a\r\nb\rc") == "a\nb\nc");

- [ ] Step 2: Run the focused test to verify it fails.

Run: make check TESTS=gameplay_translation_table_test -j2

Expected: FAIL because the table API and test target do not exist.

- [ ] Step 3: Implement the minimal table core.

Implement the SHA-256 compression routine without external libraries, normalize only CRLF/CR to LF, parse the exact header and four escaped fields, load into a temporary map before swapping on success, reject duplicate kind/key pairs, and return SourceMismatch when the stored hash differs from sha256_hex(normalize_translation_source(english)).

- [ ] Step 4: Register the test target and run it.

Add gameplay_translation_table.cc and gameplay_translation_table.h to EXULTSOURCES. Add a root Autotools check_PROGRAMS target named gameplay_translation_table_test using tests/gameplay_translation_table_test.cc and gameplay_translation_table.cc, with TESTS = $(check_PROGRAMS). Run make check TESTS=gameplay_translation_table_test -j2.

Expected: PASS for all parser, escaping, hash, and fallback cases.

- [ ] Step 5: Commit the table contract.

    git add Makefile.am gameplay_translation_table.h gameplay_translation_table.cc tests/gameplay_translation_table_test.cc
    git commit -m "feat: add runtime translation table core"

## Task 2: Add the runtime translation manager and catalog capture

Files:
- Create gameplay_translation.h
- Create gameplay_translation.cc
- Modify Makefile.am

Interfaces:
- struct TranslationDiagnostics { size_t rows; size_t hits; size_t misses; size_t source_mismatches; size_t malformed_rows; size_t fallbacks; };
- class GameplayTranslationManager { public: static GameplayTranslationManager& get(); void init(); void shutdown(); bool load_table(std::istream& input, std::string& error); void set_text_language(TextLanguage language); bool table_only_enabled() const; std::string translate(GameplayTranslationKind kind, std::string_view key, std::string_view english); void record_runtime_source(GameplayTranslationKind kind, std::string_view key, std::string_view english); TranslationDiagnostics diagnostics() const; };
- std::string make_dialogue_translation_key(int function_id, std::string_view offset_key, int segment);
- std::string make_choice_translation_key(int function_id, int callsite_offset, int ordinal);
- std::string make_item_translation_key(int shape, int frame, int quality);

- [ ] Step 1: Add manager API tests to the table test fixture.

Test key builders with function 0x0401, offset 1a_2f, segment 0, choice callsite 0x0088, ordinal 0, and item shape/frame/quality 0x01f4/2/7. Test that a table lookup increments hits, a missing row increments misses, and a stale row increments source_mismatches.

- [ ] Step 2: Run the focused test to verify the new manager behavior fails.

Run: make check TESTS=gameplay_translation_table_test -j2

Expected: FAIL on missing key-builder and manager symbols.

- [ ] Step 3: Implement manager loading and lookup.

In init(), clear old state, check the active patch for zh_translation.tsv, open it through the existing U7 path helpers, and load the table. Treat a missing table as disabled and a malformed table as disabled with a diagnostic. Enable table-only translation only when the current language is Chinese, the table is valid, and no legacy alternate Chinese/dual usecode is active. Return the original English string for every non-hit result.

- [ ] Step 4: Implement runtime catalog capture.

Read config/debug/translation/catalog_capture as a boolean and config/debug/translation/catalog_path as a path relative to GAMEDAT. When capture is enabled, write this exact header and one escaped row per unique kind/key/source_hash:

    # u6-runtime-catalog-v1
    # kind\tkey\tsource_sha256\tenglish

Flush capture output after each new row so an interrupted play session remains usable by the extractor. Do not write Chinese values from the runtime.

- [ ] Step 5: Run tests and commit.

Run: make check TESTS=gameplay_translation_table_test -j2

Expected: PASS, including stable key strings and diagnostics.

    git add Makefile.am gameplay_translation.h gameplay_translation.cc gameplay_translation_table.h gameplay_translation_table.cc tests/gameplay_translation_table_test.cc
    git commit -m "feat: add gameplay translation manager"

## Task 3: Make language switching and usecode reload safe for table-only U6 mode

Files:
- Modify bilingual_manager.h:24-65
- Modify bilingual_manager.cc:180-227
- Modify gamewin.cc:562-615
- Modify gamewin.cc:1574-1610
- Test tests/gameplay_translation_table_test.cc for the fallback policy helpers

Interfaces:
- Keep BilingualManager::get_usecode(TextLanguage) as the actual-file lookup.
- Make BilingualManager::get_active_usecode() return usecode_en when the requested Chinese or dual machine is absent.
- Add bool BilingualManager::has_execution_usecode(TextLanguage) const and use it in reload code to distinguish a real alternate file from the English fallback.

- [ ] Step 1: Add failing regression assertions.

Create a policy test covering ENGLISH, CHINESE without usecode.zh, and DUAL without usecode.dual; the expected active machine is English in both missing-alternate cases. Add a source-level smoke assertion in the test fixture that table-only mode never reports a null active machine.

- [ ] Step 2: Run the regression test before implementation.

Run: make check TESTS=gameplay_translation_table_test -j2

Expected: FAIL until the fallback policy is implemented.

- [ ] Step 3: Implement safe active-machine selection.

Update set_text_language() so newm is always the real alternate machine when available and otherwise usecode_en. Preserve the existing state transfer only when oldm and newm are distinct non-null machines. Update get_active_usecode() with the same fallback rule. Do not change is_bilingual_available() or is_dual_available(); those must continue to report actual files.

- [ ] Step 4: Initialize and reload the translation manager.

Call GameplayTranslationManager::get().init() immediately after BilingualManager::get().init() in Game_window::init_files(). On language changes, update the translation manager after current_lang changes and before repainting. In Game_window::reload_usecode(), read usecode.zh or usecode.dual only when the corresponding has_execution_usecode() result is true; otherwise reload the original English USECODE file into the already active English machine.

- [ ] Step 5: Build and commit.

Run: make -j2 and make check TESTS=gameplay_translation_table_test -j2

Expected: the executable and parser test build successfully, and no table-only path installs a null usecode pointer.

    git add bilingual_manager.h bilingual_manager.cc gamewin.cc gameplay_translation.h gameplay_translation.cc tests/gameplay_translation_table_test.cc
    git commit -m "fix: keep English usecode for table-only language mode"

## Task 4: Translate dialogue and conversation choice display copies

Files:
- Modify usecode/conversation.h:41-106
- Modify usecode/conversation.cc:435-508
- Modify usecode/conversation.cc:733-810
- Modify usecode/conversation.cc:1014-1037
- Modify usecode/ucinternal.h:70-115
- Modify usecode/ucinternal.cc:594-741
- Modify usecode/ucinternal.cc:1803-1992
- Test tests/gameplay_translation_table_test.cc and the manual U6 smoke test in Task 10

Interfaces:
- Add void Conversation::set_choice_context(int function_id, int callsite_offset).
- Add void Conversation::clear_choice_context().
- Store int choice_function_id and int choice_callsite_offset in Conversation while choices are visible.
- Use GameplayTranslationManager::translate(GameplayTranslationKind, std::string_view, std::string_view) for display copies.

- [ ] Step 1: Extend the C++ regression fixture and write the conversation behavior checklist.

Assert that the same dialogue input produces dialogue:0x0401:1a_2f:0 and that three options produce ordinals 0, 1, and 2. Record the required choice invariant in the test name: the display string may change, but get_answer(index) must remain byte-for-byte identical to the English input. The Python key tests are created and run in Task 6 after the catalog package exists.

- [ ] Step 2: Run the focused C++ regression test before implementation.

Run: make check TESTS=gameplay_translation_table_test -j2

Expected: FAIL on the new choice/dialogue regression assertions until the runtime display path is implemented.

- [ ] Step 3: Translate each dialogue segment without changing voice or game logic.

In Usecode_internal::say_string(), retain the current voice trace calculation and pass the English str to VoiceActingManager. Before conv->show_npc_message(str), build the dialogue key from the selected function id, offset key, and current segment, call the manager, and pass the returned temporary display string to the conversation. Record the English source for catalog capture before token resolution.

    const int segment_index = segment++;
    const std::string key = make_dialogue_translation_key(
            voice_func_id, voice_offset_key, segment_index);
    const std::string display = GameplayTranslationManager::get().translate(
            GameplayTranslationKind::Dialogue, key, str);
    conv->show_npc_message(display.c_str());

- [ ] Step 4: Translate choices while preserving answers.

In get_user_choice_num(), capture frame->function->id and frame->ins_ip - frame->code before conv->show_avatar_choices(). Store that context in Conversation. In the no-argument show_avatar_choices(), allocate temporary strings from answers; for each ordinal, look up choice:function:callsite:ordinal, then pass the temporary char* array to the existing renderer. Clear the context in clear_avatar_choices(). Leave get_answer(), locate_answer(), user_choice, and CMPS matching untouched.

- [ ] Step 5: Preserve Chinese token/layout behavior and commit.

Update resolve_dialogue_tokens() so a table-only Chinese string is resolved as a single Chinese part, while existing ZH\nEN dual strings retain their current split behavior. Keep BilingualManager::is_zh_text() as the CJK layout switch. Run make -j2, then commit:

    git add usecode/conversation.h usecode/conversation.cc usecode/ucinternal.h usecode/ucinternal.cc
    git commit -m "feat: translate U6 dialogue and choice displays"

## Task 5: Add gameplay-only indexed messages and object-name display helpers

Files:
- Modify shapes/items.h:35-55
- Modify shapes/items.cc:145-219
- Modify objs/objs.h:317
- Modify objs/objnames.cc:139-230
- Modify objs/objs.cc:939-949
- Modify gamewin.cc:2151-2235
- Modify gumps/ItemMenu_gump.cc:100-115
- Modify usecode/intrinsics.cc:2946
- Modify schedule.cc:1127-1179
- Create tools/u6_translation/tests/test_display_scope.py

Interfaces:
- Add std::string get_gameplay_text_msg(unsigned message_id) to shapes/items.h.
- Add std::string Game_object::get_gameplay_display_name() const to objs/objs.h.
- Keep get_text_msg(), get_item_name(), get_misc_name(), and Game_object::get_name() English/data-authoritative.

- [ ] Step 1: Add the display-scope test fixture.

Use fixture entries for textmsg:0x0123, item:0x01f4:2:7, and misc:0x0042. Assert that gameplay helper calls return Chinese while the existing raw lookup contract remains English. Add an explicit test that an Exult menu lookup does not call the gameplay helper. The test imports the catalog and manager test seams created in Task 6; implementation of the C++ call sites remains the deliverable of this task.

- [ ] Step 2: Run the C++ baseline before implementation.

Run: make check TESTS=gameplay_translation_table_test -j2

Expected: the pre-existing parser/key tests pass. The Python display-scope fixture is intentionally executed after the catalog package is created in Task 6 and is included in the complete suite in Task 10.

- [ ] Step 3: Implement non-mutating text-message display helpers.

Define get_gameplay_text_msg() as get_text_msg(message_id) followed by a TextMessage lookup. Use it in Game_object::say(int), Game_object::say(int,int), the indexed bed-occupied NPC message in usecode/intrinsics.cc, and the two scheduled indexed messages in schedule.cc. Do not route menu, screenshot, debugging, or configuration calls through this helper.

- [ ] Step 4: Implement non-mutating object-name display helpers.

Keep Game_object::get_name() unchanged and add get_gameplay_display_name() that builds the stable item key from shape, frame, and quality, then translates the final English composed name. Update Game_window::show_items() and Itemmenu_gump to use it. For the Avatar's special misc name in Get_object_name(), translate misc:0x42 for Black Gate and the existing Serpent Isle id for Serpent Isle. Leave map editor callers and internal comparisons on raw names.

- [ ] Step 5: Build and commit the gameplay display changes.

Run: make -j2

Expected: gameplay display callers compile without changing raw lookup signatures. Run test_display_scope.py with the complete Python suite in Task 10 after the package and fixtures are present.

    git add shapes/items.h shapes/items.cc objs/objs.h objs/objnames.cc objs/objs.cc gamewin.cc gumps/ItemMenu_gump.cc usecode/intrinsics.cc schedule.cc
    git commit -m "feat: translate gameplay names and indexed messages"

## Task 6: Build the Python catalog and static/runtime extraction pipeline

Files:
- Create tools/u6_translation/__init__.py
- Create tools/u6_translation/__main__.py
- Create tools/u6_translation/catalog.py
- Create tools/u6_translation/runtime_table.py
- Create tools/u6_translation/extract.py
- Create tools/u6_translation/tests/test_catalog.py
- Create tools/u6_translation/tests/test_runtime_table.py
- Create tools/u6_translation/tests/test_extract.py
- Create tools/u6_translation/tests/test_runtime_keys.py
- Create tools/u6_translation/tests/fixtures/catalog.jsonl
- Create tools/u6_translation/tests/fixtures/runtime_catalog.tsv

Interfaces:
- @dataclass(frozen=True) class CatalogEntry: kind: str; key: str; source: str; source_sha256: str; context: str; origin: str; protected_tokens: tuple[str, ...]
- @dataclass(frozen=True) class RuntimeRow: kind: str; key: str; source_sha256: str; zh: str
- def normalize_source(source: str) -> str
- def source_sha256(source: str) -> str
- def load_catalog(path: pathlib.Path) -> list[CatalogEntry]
- def write_catalog(path: pathlib.Path, entries: collections.abc.Iterable[CatalogEntry]) -> None
- def extract_catalog(mod_root: pathlib.Path, ucxt_path: pathlib.Path, runtime_catalog: pathlib.Path | None) -> list[CatalogEntry]
- def parse_runtime_catalog(path: pathlib.Path) -> list[CatalogEntry]

- [ ] Step 1: Write failing catalog and codec tests.

Cover JSONL round-trips, deterministic ordering, identical Python/C++ source hashes using abc and CRLF fixtures, protected-token extraction for @...@, ~, *, <PLAYER_NAME>, <HONORIFIC>, <PRONOUN>, <GENDER_FLAG>, and <VAR>, and runtime-catalog TSV parsing with escaped tabs and newlines.

- [ ] Step 2: Run the Python tests before implementation.

Run: python3 -m unittest discover -s tools/u6_translation/tests -v

Expected: FAIL because the package modules and fixtures do not exist.

- [ ] Step 3: Implement catalog and runtime-table codecs.

Use only json, hashlib, pathlib, re, and standard collections. Preserve the source exactly after CRLF/CR normalization. Reject duplicate keys with different source hashes, but merge identical static/runtime entries by kind,key,source_sha256 and retain both origin labels.

- [ ] Step 4: Implement static and runtime extraction.

Run ucxt -ftt with the supplied executable, parse direct usecode strings into stable dialogue candidates, split ~ segments consistently with the runtime, parse Ultima6v1.3/patch/textmsg.txt, and merge the C++ runtime capture file. Mark statically discovered choice candidates as unbound until a runtime choice callsite supplies the final function/callsite/ordinal key. Classify location names found in indexed resources with context="location" while retaining their runtime textmsg identity unless a dedicated location callsite provides a location: key.

- [ ] Step 5: Run tests and commit the extraction layer.

Run: python3 -m unittest discover -s tools/u6_translation/tests -v

Expected: PASS for codec, hash, token, static fixture, runtime merge, and stable-choice-key cases.

    git add tools/u6_translation
    git commit -m "feat: add U6 translation catalog extraction"

## Task 7: Add the local Ollama/Qwen translation and semantic-review pipeline

Files:
- Create tools/u6_translation/ollama_backend.py
- Create tools/u6_translation/prompts.py
- Create tools/u6_translation/translate.py
- Create tools/u6_translation/u6_glossary.tsv
- Create tools/u6_translation/tests/test_ollama_backend.py
- Create tools/u6_translation/tests/test_translate.py

Interfaces:
- @dataclass(frozen=True) class OllamaConfig: url: str = "http://127.0.0.1:11434/api/chat"; model: str = "qwen3:8b"; timeout_seconds: float = 120.0; retries: int = 3
- class OllamaBackend: def __init__(self, config: OllamaConfig); def translate_batch(self, entries: list[CatalogEntry]) -> list[dict[str, str]]; def review_batch(self, entries: list[CatalogEntry], translations: list[dict[str, str]]) -> list[dict[str, object]]
- def translate_catalog(catalog_path: pathlib.Path, output_path: pathlib.Path, cache_path: pathlib.Path, backend: OllamaBackend, prompt_version: str) -> None
- def review_catalog(catalog_path: pathlib.Path, table_path: pathlib.Path, output_path: pathlib.Path, backend: OllamaBackend, prompt_version: str) -> None

- [ ] Step 1: Write failing mocked-HTTP tests.

Mock urllib.request.urlopen for successful JSON responses, HTTP errors, malformed JSON, missing message.content, retries, cache hits, batch order preservation, and prompt-version cache invalidation. Assert that no test performs network I/O.

- [ ] Step 2: Run the mocked tests before implementation.

Run: python3 -m unittest tools.u6_translation.tests.test_ollama_backend tools.u6_translation.tests.test_translate -v

Expected: FAIL because the backend and cache functions are absent.

- [ ] Step 3: Implement the Ollama backend.

POST JSON to the configured /api/chat URL with stream=false, a system prompt, and a user payload containing indexed entries. Require JSON-only responses with key, source_sha256, zh, and status. Retry transient URL/HTTP/JSON failures up to retries, preserving the original exception in the final error. Never send file paths, save data, or runtime state.

- [ ] Step 4: Implement translation caching and prompts.

Use cache keys containing entry source hash, model, prompt version, glossary hash, and operation. Batch entries without changing their order. Create u6_glossary.tsv with exactly these initial protected conventions and columns en, zh, policy:

    Avatar	聖者	translated
    The Fellowship	友誼會	translated
    Fellowship Hall	友誼會館	translated
    Inner Voice	內在之聲	translated
    Passion Play	受難劇	translated

Load Traditional Chinese and protected-term rules from this file; include the existing tools/ucxt/output/Translation_Guide.md rules as prompt guidance, but keep the U6 glossary separate so U7-specific names are not silently imported.

- [ ] Step 5: Implement optional semantic review and commit.

Write review records with key, source_sha256, status, issues, suggested_zh, model, and prompt version. Semantic review is advisory by default and does not overwrite candidate or approved translations. Run the mocked tests and commit:

    python3 -m unittest tools.u6_translation.tests.test_ollama_backend tools.u6_translation.tests.test_translate -v
    git add tools/u6_translation/ollama_backend.py tools/u6_translation/prompts.py tools/u6_translation/translate.py tools/u6_translation/u6_glossary.tsv tools/u6_translation/tests/test_ollama_backend.py tools/u6_translation/tests/test_translate.py
    git commit -m "feat: add offline Ollama translation pipeline"

## Task 8: Implement coverage, correctness, review, and emission audits

Files:
- Create tools/u6_translation/audit.py
- Create tools/u6_translation/emit.py
- Modify tools/u6_translation/__main__.py
- Create tools/u6_translation/tests/test_audit.py
- Create tools/u6_translation/tests/test_emit.py
- Create tools/u6_translation/tests/test_cli.py
- Create tools/u6_translation/tests/fixtures/approved_review.jsonl
- Create tools/u6_translation/tests/fixtures/bad_translation.tsv

Interfaces:
- def coverage_report(catalog: list[CatalogEntry], rows: list[RuntimeRow]) -> dict[str, object]
- def correctness_report(catalog: list[CatalogEntry], rows: list[RuntimeRow], glossary: pathlib.Path, semantic_reviews: list[dict[str, object]] | None) -> dict[str, object]
- def format_terminal_report(report: dict[str, object]) -> str
- def report_exit_code(report: dict[str, object], strict: bool) -> int
- def emit_approved_table(catalog: list[CatalogEntry], review_path: pathlib.Path, output_path: pathlib.Path) -> None

- [ ] Step 1: Write failing audit tests.

Create fixtures containing one translated dialogue row, one translated choice row, one missing choice row, one stale hash, one duplicate, one orphan, one marker-loss translation, one placeholder-loss translation, one simplified-character warning, and one glossary mismatch. Assert per-kind counts, entry coverage, character-weighted coverage, and strict/non-strict exit codes.

- [ ] Step 2: Run audit tests before implementation.

Run: python3 -m unittest tools.u6_translation.tests.test_audit tools.u6_translation.tests.test_emit tools.u6_translation.tests.test_cli -v

Expected: FAIL because audit functions and CLI subcommands are absent.

- [ ] Step 3: Implement coverage reporting.

Compare catalog rows to runtime rows by kind,key, then validate source hashes. Report total, translated, missing, stale, duplicate, orphan, and unbound rows by dialogue, choice, textmsg, item, location, misc, and spell. Report both row coverage and len(source)-weighted coverage. Count each dialogue segment and each choice ordinal separately.

- [ ] Step 4: Implement deterministic correctness checks.

Validate UTF-8, exact field count, key syntax, lowercase 64-character hashes, non-empty Chinese output, protected-marker multisets, placeholder sets, newline structure, source duplication, protected spell terms, glossary consistency, and configured Traditional-Chinese policy. Record every issue with key, check name, severity, and source location. Keep semantic Ollama results separate from deterministic failures.

- [ ] Step 5: Implement review gating, CLI, and emission.

Add these commands and arguments:

    python3 -m tools.u6_translation extract --mod-root MOD_ROOT --ucxt UCXT --runtime-catalog RUNTIME_CATALOG --output CATALOG
    python3 -m tools.u6_translation translate --catalog CATALOG --output CANDIDATES --cache CACHE --model qwen3:8b --url http://127.0.0.1:11434/api/chat
    python3 -m tools.u6_translation audit coverage --catalog CATALOG --table TABLE --report REPORT --strict
    python3 -m tools.u6_translation audit correctness --catalog CATALOG --table TABLE --report REPORT --glossary tools/u6_translation/u6_glossary.tsv
    python3 -m tools.u6_translation audit all --catalog CATALOG --table TABLE --report REPORT --glossary tools/u6_translation/u6_glossary.tsv --strict
    python3 -m tools.u6_translation emit --catalog CATALOG --review REVIEW --output TABLE

Represent each review row as JSON with kind, key, source_sha256, zh, status (approved, needs-review, or rejected), issues, suggested_zh, model, and prompt_version. Make audit print a terminal summary and write JSON. Make strict mode return non-zero for missing/stale/structural failures; make non-strict mode return zero for reviewable missing translations. Make emit reject any non-approved row or deterministic audit failure and write sorted u6-translation-v1 TSV. Run all audit tests and commit:

    python3 -m unittest tools.u6_translation.tests.test_audit tools.u6_translation.tests.test_emit tools.u6_translation.tests.test_cli -v
    git add tools/u6_translation
    git commit -m "feat: add translation coverage and correctness audits"

## Task 9: Document the pipeline and package the reviewed U6 table

Files:
- Modify tools/u6_translation/README.md
- Create tools/u6_translation/tests/fixtures/README.md
- External output, not committed in this repository until review: ../Ultima_7/mods/Ultima6v1.3/Ultima6v1.3/patch/zh_translation.tsv

Interfaces and workflow:
- Document MOD_ROOT=../Ultima_7/mods/Ultima6v1.3 and PATCH_DIR=$MOD_ROOT/Ultima6v1.3/patch.
- Document runtime capture configuration keys config/debug/translation/catalog_capture and config/debug/translation/catalog_path.
- Document that the final table is emitted only after strict audit and human approval.

- [ ] Step 1: Write documentation tests as command examples.

Verify every command in the README uses the actual package module, the actual U6 mod root, the actual patch directory, and the configured Ollama URL/model. Include a choice row example and explicitly state that answers remains English internally.

- [ ] Step 2: Run the documented extraction command against the mod fixture.

    MOD_ROOT="$PWD/../Ultima_7/mods/Ultima6v1.3"
    PATCH_DIR="$MOD_ROOT/Ultima6v1.3/patch"
    python3 -m tools.u6_translation extract --mod-root "$MOD_ROOT" --ucxt "$PWD/tools/ucxt/ucxt" --runtime-catalog tools/u6_translation/tests/fixtures/runtime_catalog.tsv --output /tmp/u6_catalog.jsonl

Expected: a deterministic catalog containing text-message entries and fixture runtime dialogue/choice entries.

- [ ] Step 3: Run translation in cache-only mock mode.

Run: python3 -m unittest tools.u6_translation.tests.test_ollama_backend tools.u6_translation.tests.test_translate -v

Expected: the documented cache/resume behavior passes without requiring a running model.

- [ ] Step 4: Document release emission.

Show the strict audit and emit commands writing only to PATCH_DIR/zh_translation.tsv; explain that the generated table must be reviewed before copying it into the external mod directory. Do not modify the existing Ultima6v1.3.cfg or add an alternate usecode file.

- [ ] Step 5: Commit the documentation.

    git add tools/u6_translation/README.md tools/u6_translation/tests/fixtures/README.md
    git commit -m "docs: describe U6 translation pipeline"

## Task 10: Run full verification and the manual U6 smoke test

Files:
- Test tests/gameplay_translation_table_test.cc
- Test tools/u6_translation/tests/
- Verify bilingual_manager.cc, gamewin.cc, usecode/conversation.cc, usecode/ucinternal.cc, shapes/items.cc, objs/objnames.cc, gumps/ItemMenu_gump.cc, usecode/intrinsics.cc, and schedule.cc

- [ ] Step 1: Run the C++ build and parser test.

Run: make -j2 && make check TESTS=gameplay_translation_table_test -j2

Expected: build succeeds and the C++ table test passes.

- [ ] Step 2: Run the complete Python test suite.

Run: python3 -m unittest discover -s tools/u6_translation/tests -v

Expected: all catalog, extractor, Ollama mock, translation, audit, emission, CLI, and runtime-key tests pass without network access.

- [ ] Step 3: Run strict audit on the reviewed table.

    MOD_ROOT="$PWD/../Ultima_7/mods/Ultima6v1.3"
    PATCH_DIR="$MOD_ROOT/Ultima6v1.3/patch"
    python3 -m tools.u6_translation.audit all --catalog /tmp/u6_catalog.jsonl --table "$PATCH_DIR/zh_translation.tsv" --report /tmp/u6_translation_audit.json --glossary tools/u6_translation/u6_glossary.tsv --strict

Expected: zero missing/stale/structural failures and a JSON report showing separate choice-option coverage.

- [ ] Step 4: Perform the manual runtime smoke test.

Launch the configured Ultima6v1.3 mod with no usecode.zh. Test English mode, Chinese mode, an NPC conversation, a conversation with at least three choice options, keyboard and mouse choice selection, a gameplay bark, an item-name display, the Avatar name, an indexed text message, save/load, and Exult menus. Remove one table row and corrupt one source hash to verify per-entry English fallback. Confirm choice branching is identical in English and Chinese.

- [ ] Step 5: Verify repository state and record final commit.

Run:

    git diff --check
    git status --short
    git log --oneline -8

Expected: no whitespace errors; only the planned commits are tracked. Preserve unrelated pre-existing untracked files and do not stage them. Commit any final implementation-only adjustments with a focused message.

## Self-Review Checklist

- Runtime table parsing, escaping, hashing, duplicate rejection, and fallback are covered by Task 1.
- Active-mod loading, diagnostics, capture, language state, and no-null-usecode behavior are covered by Tasks 2 and 3.
- Dialogue translation, segment keys, token resolution, CJK layout, and English voice/game logic are covered by Task 4.
- Choice options are translated independently, while answers, ordinal selection, and usecode comparisons remain English; this is covered by Task 4 and the smoke test.
- Gameplay-only text-message, item, Avatar, and object-name display paths are covered by Task 5; Exult menu/editor paths remain raw.
- Static ucxt -ftt extraction, runtime key capture, catalog merge, and stable hashes are covered by Task 6.
- Local Ollama/Qwen translation, retries, cache/resume, protected prompts, and optional semantic review are covered by Task 7.
- Coverage, weighted coverage, correctness, marker checks, Traditional-Chinese checks, strict mode, JSON reports, and release emission are covered by Task 8.
- Documentation, external mod table placement, and no alternate usecode packaging are covered by Task 9.
- Build, Python tests, strict audit, manual fallback, choice branching, and repository verification are covered by Task 10.
- No step is incomplete, depends on an unspecified dependency, uses a global translation lookup, or creates a second usecode.
