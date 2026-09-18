# Structural Dialogue Fragment Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Translate structurally assembled dialogue from provenance tokens when its complete placeholder template is not yet in the table, while retaining the canonical template as an audit miss.

**Architecture:** Keep exact canonical-template lookup as the first runtime path. When it misses, consume the already recorded ordered `voice_string_parts` tokens directly: translate static source-key fragments and dynamic values independently, concatenate them, and record the canonical `<VARn>` source for audit. Remove the completed-English anchor search from the inference path so no runtime pattern matching is used.

**Tech Stack:** C++17 Exult usecode interpreter and translation manager; Python `tools.u6_translation` catalog/audit; existing C++ and pytest suites.

**Spec:** `docs/superpowers/specs/2026-09-16-generic-placeholder-dialogue-design.md`

## Global Constraints

- Runtime matching must use provenance structure and exact canonical source hashes; it must not use regex, wildcard, or `std::string::find` matching against completed English dialogue.
- Exact sentence-level translations take precedence over fragment fallback.
- Missing canonical templates remain visible to audit even when runtime fragment fallback produces translated text.
- Opaque single-value sentences remain exact-only because their placeholder boundary cannot be recovered safely.
- Preserve `@`, `~`, `*`, English names, and existing Chinese delimiter behavior.

---

### Task 1: Add the red regression test for structural fallback

**Files:**
- Modify: `tests/gameplay_translation_table_test.cc` near the existing generic template tests.

**Interfaces:**
- Consumes: `GameplayTranslationManager::translate_dialogue_template_if_available`, `GameplayTranslationManager::translate`, and provenance fragment behavior.
- Produces: A test that distinguishes structural fallback from canonical template lookup.

- [x] **Step 1: Write the failing test**

Add a test that loads a temporary table containing only the static fragments `Very well, ` → `很好，` and `, I shall wait here until thy return.@` → `我會在這裡等你回來。@`, then passes provenance parts for `Very well, `, dynamic `Avatar`, and the suffix. Assert the expected concatenated Chinese output `很好，聖者，我會在這裡等你回來。@`. Also assert that a sentence-level lookup for `Very well, <VAR0>, I shall wait here until thy return.@` remains absent so the audit contract is not replaced by the fallback.

- [x] **Step 2: Run the focused test to verify it fails**

Run: `make gameplay_translation_table_test -j2 && ./gameplay_translation_table_test`

Expected: FAIL at the new fallback assertion because the current `say_string` path returns no complete template translation when the canonical row is absent.

### Task 2: Implement provenance-only fragment fallback

**Files:**
- Modify: `usecode/ucinternal.cc` in `Usecode_internal::say_string`.
- Modify: `gameplay_translation.cc` only if a small reusable token fallback helper is needed.
- Modify: `gameplay_translation.h` only if that helper needs a public declaration.

**Interfaces:**
- Consumes: ordered `voice_string_parts`, `voice_func_id`, and existing source translation APIs.
- Produces: Runtime translation that uses exact canonical lookup first and provenance-token concatenation second.

- [x] **Step 1: Replace the anchor-inference fallback**

In the dialogue translation lambda, build the canonical source from `voice_string_parts` as it already does. Keep the exact template lookup first. If it misses, translate each part directly: use `translate` for keyed static fragments and `translate_by_source` for dynamic fragments. Concatenate the results only when all part offsets cover `String` exactly and marker counts remain unchanged.

- [x] **Step 2: Preserve audit visibility**

Before returning the fragment result, call `record_runtime_source` with the canonical function/template key. Do not mark the canonical row translated or synthesize a table row at runtime; the audit must continue to list the source template as missing.

- [x] **Step 3: Remove completed-English pattern matching from this path**

Do not call `infer_dialogue_template_candidates_from_static_fragments` from the fallback path. Keep opaque one-value strings on exact source lookup only. Add a source comment explaining that provenance tokens are authoritative and completed-English matching is intentionally unsupported.

- [x] **Step 4: Run the focused test to verify it passes**

Run: `make gameplay_translation_table_test -j2 && ./gameplay_translation_table_test`

Expected: PASS, including the new structural fallback test and all existing placeholder/name/marker tests.

### Task 3: Extend audit regression coverage

**Files:**
- Modify: `tools/u6_translation/tests/test_audit.py` or the existing catalog/audit test module that checks assembled templates.
- Modify: `tests/gameplay_translation_table_test.cc` only if the audit fixture is shared there.

**Interfaces:**
- Consumes: canonical runtime source records emitted by the existing catalog/audit pipeline.
- Produces: A regression proving fragment-translated output does not hide a missing canonical template.

- [x] **Step 1: Add the audit fixture**

Create a minimal catalog containing the three structural parts but no `fallback_<hash>` row. Run the audit against it and assert that the canonical assembled key appears in `assembled_templates.missing_keys`, while no orphan or stale error is introduced by the fragment rows.

- [x] **Step 2: Run the focused Python test**

Run: `python3 -m pytest tools/u6_translation/tests/test_audit.py -q`

Expected: PASS, with the new case failing before the audit fixture/assertion is added and passing after it is added.

### Task 4: Verify, rebuild, and document the behavior

**Files:**
- Modify: `reports/u6_shamino_wait_fix_before_after.html` or add a focused structural-fallback report if the existing report would be misleading.

- [x] **Step 1: Run the complete verification suite**

Run: `python3 -m pytest tools/u6_translation/tests -q`, `make check -j2`, `make exult -j2`, `./gameplay_translation_table_test`, and `git diff --check`.

Expected: all tests pass, the build exits 0, and the deployed binary can be refreshed with `cp exult /home/joe/.local/bin/exult`.

- [x] **Step 2: Run the audit against the live table**

Run the `audit all` command with `/home/joe/project/Ultima_7/mods/Ultima6v1.3/patch/zh_translation.tsv` and verify that the Shamino canonical key is reported according to the table state while runtime fragment rows remain valid.

- [x] **Step 3: Update the HTML before/after report**

Show that the sentence is translated by structural fragment fallback, while the canonical placeholder sentence remains an audit finding until a reviewed full-sentence row is added.
