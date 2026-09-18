# Generic Placeholder Dialogue Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or superpowers:subagent-driven-development) to implement this plan task-by-task with review checkpoints.

**Goal:** Remove the finite `dynamic_templates.tsv` dependency and make placeholder dialogue translation work for arbitrary runtime-assembled sentences.

**Architecture:** The ordinary dialogue table is indexed for generic placeholder templates. The interpreter preserves static/dynamic assembly fragments and synthesizes positional templates only when boundaries are known. Exact lookup remains the fail-closed path for opaque strings; extraction and audit report those strings without guessing.

**Tech Stack:** C++17 Exult usecode/runtime, `GameplayTranslationManager`, Python 3 `tools/u6_translation`, TSV catalog, existing unittest and C++ table-test harnesses.

**Spec:** `docs/superpowers/specs/2026-09-16-generic-placeholder-dialogue-design.md`

## Global Constraints

- Do not add NPC names, sentence literals, or per-template rows to C++ code.
- Do not require, read, or generate `dynamic_templates.tsv` for runtime translation.
- Preserve exact source-hash lookup and fail closed on ambiguity or invalid placeholder contracts.
- Keep English runtime values (player/NPC names and other dynamic values) in English when substituted.
- Use `apply_patch` for source edits and run each test after its corresponding red/green cycle.

---

### Task 1: Add failing runtime matcher tests

**Files:**
- Modify: `tests/gameplay_translation_table_test.cc`
- Modify: `gameplay_translation.h` only if the test needs a public test seam

**Interfaces:**
- Consumes: existing `GameplayTranslationManager` table-loading and dialogue lookup APIs.
- Produces: regression coverage for table-native wildcard matching that later runtime work must satisfy.

- [x] **Step 1: Write the failing tests**

Add table fixtures and assertions for:

```cpp
EXPECT_EQ(translate("Hello <ANY_NAME>!", "你好，<ANY_NAME>！", "Hello Ada!"), "你好，Ada！");
EXPECT_EQ(translate("<LEFT> gave <RIGHT>.", "<RIGHT> 給了 <LEFT>。", "Iolo gave Dupre."), "Dupre 給了 Iolo。");
EXPECT_EQ(translate("<NAME> trusts <NAME>.", "<NAME> 信任 <NAME>。", "Ada trusts Ada."), "Ada 信任 Ada。");
EXPECT_FALSE(translate("Say <A>.", "說 <B>。", "Say hi.").has_value());
EXPECT_FALSE(translate("Hello <X>!", "你好，<X>！", "Hello Ada!").has_value())
  // when a second equally specific candidate is present.
```

Use placeholder names not present in the old registry so the tests prove generic behavior.

- [x] **Step 2: Run the focused test and verify RED**

Run:

```bash
make -B gameplay_translation_table_test -j2 && ./gameplay_translation_table_test
```

Expected: failure because lookup only knows exact rows and finite dynamic templates.

- [x] **Step 3: Keep the test fixture isolated**

Ensure each test loads an in-memory TSV/table fixture and does not read `tools/u6_translation/dynamic_templates.tsv` or a patch-directory file.

### Task 2: Route all generic templates through provenance-derived source hashes

**Files:**
- Modify: `gameplay_translation.h`
- Modify: `gameplay_translation.cc`
- Test: `tests/gameplay_translation_table_test.cc`

**Interfaces:**
- Consumes: parsed dialogue rows already held by `GameplayTranslationManager`.
- Produces: generic matching through the existing source-template parser and normal table hash lookup.

- [x] **Step 1: Remove runtime registry loading and calls**

Delete `load_dynamic_templates`, its member storage, initialization error path, and registry iteration. Remove the registry-only public method and route `say_string` directly to the provenance-derived template fallback.

- [x] **Step 2: Preserve generic parser validation**

Keep the existing arbitrary-name parser, literal-anchor extraction, translated-placeholder validation, repeated-placeholder handling, and marker checks. Ensure all reviewed template rows are addressed by their normal source hash.

- [x] **Step 3: Run focused tests and verify GREEN**

Run:

```bash
make -B gameplay_translation_table_test -j2 && ./gameplay_translation_table_test
```

Expected: all generic matcher assertions pass, including arbitrary names, reordered/repeated values, and malformed rows, without opening a registry file.

### Task 3: Preserve interpreter assembly provenance

**Files:**
- Modify: `usecode/ucinternal.cc`
- Modify: `gameplay_translation.h`
- Modify: `gameplay_translation.cc`
- Test: `tests/gameplay_translation_table_test.cc` (or the existing usecode test target if available)

**Interfaces:**
- Consumes: `UC_ADDSI`, `UC_ADDSV`, `voice_string_parts`, and `say_string` assembly state.
- Produces: canonical positional templates such as `Hello <VAR0>!` when fragment boundaries are known, plus exact-only handling for opaque values.

- [x] **Step 1: Add a failing provenance test**

Construct an assembly with static `Hello `, dynamic `Ada`, and static `!`; assert that the generated source template is `Hello <VAR0>!` and translates through a normal table row. Add a second case where one opaque dynamic fragment is `Hello Ada!`; assert that no fuzzy template is synthesized and only an exact row can translate it.

- [x] **Step 2: Run the focused test and verify RED**

Run:

```bash
make -B gameplay_translation_table_test -j2 && ./gameplay_translation_table_test
```

Expected: the static/dynamic assembly case currently misses because the old fallback depends on the registry; the opaque case must remain untranslated without an exact row.

- [x] **Step 3: Implement provenance synthesis**

Retain the original English text for each static fragment, mark each dynamic fragment, preserve fragment order across the existing `append_string` path, and synthesize positional placeholders at `SAY`. Translate captured dynamic values independently only when an exact value translation exists; otherwise preserve the English value.

- [x] **Step 4: Reset provenance safely**

Clear fragment metadata on every completed `SAY`, aborted string, and usecode reset path so a later dialogue cannot inherit earlier fragments.

- [x] **Step 5: Run focused tests and verify GREEN**

Run the C++ table test and the relevant usecode/conversation test targets. Confirm the opaque sentence is exact-only and the assembled sentence uses the generic table matcher.

### Task 4: Make extraction and audit registry-free

**Files:**
- Modify: `tools/u6_translation/extract.py`
- Modify: `tools/u6_translation/catalog.py`
- Modify: `tools/u6_translation/audit.py`
- Modify: `tools/u6_translation/templates.py`
- Modify: `tools/u6_translation/__main__.py`
- Modify: `tools/u6_translation/tests/test_extract.py`
- Modify: `tools/u6_translation/tests/test_catalog.py`
- Modify: `tools/u6_translation/tests/test_audit.py`

**Interfaces:**
- Consumes: ordinary TSV rows and runtime-observed source fragments.
- Produces: canonical placeholder rows in the main catalog and audit findings for opaque/untranslated sources; no registry file.

- [x] **Step 1: Add failing Python tests**

Cover arbitrary placeholder names, multiple/repeated placeholders, provenance-derived rows, and a run with no `dynamic_templates.tsv` present. Assert that audit counts ordinary placeholder rows and reports opaque runtime sources.

- [x] **Step 2: Run Python tests and verify RED**

Run:

```bash
python3 -m unittest discover -s tools/u6_translation/tests -p 'test_*.py'
```

Expected: failures where extraction still imports `DYNAMIC_DIALOGUE_TEMPLATES` or audit still expects dynamic-template rows.

- [x] **Step 3: Generalize extraction**

Replace the finite `_dynamic_dialogue_templates` registry walk with conversion of observed static/dynamic fragment traces into ordinary dialogue catalog rows using positional `<VARn>` placeholders. Deduplicate by source hash and preserve source provenance in metadata/context.

- [x] **Step 4: Generalize audit/catalog validation**

Use the shared placeholder parser for all rows, validate source/translation multiplicity and marker preservation, and add an explicit opaque-runtime finding. Remove registry coverage counters and file existence requirements.

- [x] **Step 5: Remove or deprecate registry CLI behavior**

Delete the finite template definitions and make `write-dynamic-templates` fail with a clear migration message or become a no-op diagnostic that points to the main catalog. Do not write a replacement registry file.

- [x] **Step 6: Run Python tests and verify GREEN**

Run the unittest command again; expected result is zero failures with no registry fixture required.

### Task 5: Update documentation and generate the requested HTML report

**Files:**
- Modify: `tools/u6_translation/README.md`
- Create: `reports/u6_generic_placeholder_before_after.html`
- Test: existing Python audit tests plus a report-generation smoke check

**Interfaces:**
- Consumes: before/after audit records and the final translation table.
- Produces: documentation describing table-native wildcard matching and an offline HTML report showing representative fixes.

- [x] **Step 1: Add a report smoke test**

Assert that the report generator writes a self-contained HTML file containing `before`, `after`, source, translated text, and the generic placeholder explanation.

- [x] **Step 2: Run the smoke test and verify RED**

Run the report test before implementing the generator; it must fail because the new report does not exist.

- [x] **Step 3: Update README and generate report**

Document that `zh_translation.tsv` is the sole template source, explain positional provenance, and show the exact/fail-closed behavior for opaque strings. Generate the report with escaped HTML and no external assets.

- [x] **Step 4: Run the complete verification suite**

Run:

```bash
python3 -m unittest discover -s tools/u6_translation/tests -p 'test_*.py'
make -B gameplay_translation_table_test -j2
./gameplay_translation_table_test
git diff --check
```

Then run the audit command used by the repository and record both the targeted placeholder/name metrics and any pre-existing unrelated findings. Open the generated report locally with a browser-capable tool or validate its HTML structure with the project’s existing report checker.

### Task 6: Final review against the spec

- [ ] Verify no production code references `dynamic_templates.tsv`, `DYNAMIC_DIALOGUE_TEMPLATES`, or a finite NPC template list.
- [ ] Verify arbitrary placeholder names are covered by tests and audit.
- [ ] Verify ambiguous/malformed matches fail closed.
- [ ] Verify opaque whole-sentence values are never fuzzy-translated.
- [ ] Verify all changed files are intentional and preserve unrelated user work.
- [ ] Re-run the complete verification suite after the final diff review.
