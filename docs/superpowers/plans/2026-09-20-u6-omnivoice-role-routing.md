# U6 OmniVoice Role Routing and Avatar Voices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Make U6 OmniVoice generation use the correct reference voice for every rendered part: NPC speech uses the NPC reference, narration uses the gender-matched U7 narrator reference, mixed lines splice both, and Avatar lines generate male/female variants selected by the existing runtime.

**Architecture:** Keep the U6 shared runtime identity (`function_id/offset_key/segment`) and add routing metadata at generation time. A compact U6 role manifest provides authoritative English `@...@` speaker markers and their aligned Chinese text. The generator stages only the four U7 special reference families into `u6_voice/refs`, builds either a single effective reference or an ordered list of per-part references, and retains batch generation for single-reference jobs while rendering mixed jobs part-by-part before fade-splicing them. Avatar variants use the existing `_avatar_male`/`_avatar_female` runtime suffix contract; no C++ lookup redesign is required.

**Tech Stack:** Python 3, pytest, OmniVoice model adapter, JSONL routing manifest, OGG sidecar metadata, existing U6 `VoiceActingManager` runtime and review HTML tooling.

**Spec:**

- Add `u6_voice/manifests/u6_voice_roles.jsonl` as the reproducible role source. Each valid row contains `key`, `source_en`, and `text_zh`, keyed by `function_id`, `offset_key`, and `segment`.
- Treat English `@...@` markers as the role authority for both languages. Marked spans are speaker text and unmarked spans are narrator text. If a row has no English markers, the complete line is narrator text even when the Chinese translation contains quotation marks. For Chinese rows with English markers, use Chinese `@...@` markers when present; otherwise use explicit source-derived/aligned role metadata when available, and fall back to the full translated text as speaker text when alignment is unavailable. Never assign a Chinese role solely from quotation punctuation.
- Remove U6 trailing `*` control markers from spoken parts and never send them to OmniVoice.
- Preserve existing exact-NPC U7 references for NPCs with matching names. Stage U7 `Avatar male`, `Avatar female`, `Narrator male`, and `UNKNOWN` narrator references from `voice/refs` into `u6_voice/refs` with manifest-verified destination names.
- For ordinary NPC jobs, use the NPC reference for speaker-only lines, the gender-matched narrator reference for narrator-only lines, and an ordered `VoicePart` list for mixed lines. The narrator gender follows the NPC/design gender casting already used by U7; female is the default when no reliable gender is available.
- For mapping rows whose NPC is `Avatar`, expand each language into male and female output jobs. Speaker parts use the corresponding Avatar reference, narration uses the corresponding narrator gender reference, and output names insert `_avatar_male` or `_avatar_female` before `.ogg`. Existing runtime selection by the main actor’s sex already checks these suffixes.
- Add stable routing/reference revision metadata to routed jobs, include it in deterministic seeds and completion checks, and serialize `reference_role`, `reference_revision`, and ordered reference-part metadata in clone sidecars and the OmniVoice manifest.
- Keep legacy `CloneJob` construction and completion metadata compatible for existing tests and un-routed jobs. Single-reference narrator/Avatar jobs remain batchable; only mixed jobs require per-part rendering.
- Keep review generation compatible with the existing mapping and add route metadata for generated variant/mixed files so reviewers can see which reference role was used.

## Global Constraints

- Use `@...@` source markers as the role signal; do not infer speaker ownership solely from Chinese quotation punctuation.
- Do not add U6 `usecode.zh`, `usecode.dual`, `bilingual_map.dat`, or U7 alternate-usecode mappings. U6 continues to use display-time translation with one shared runtime identity.
- Do not modify unrelated generated audio, reviews, manifests, or dirty worktree files. Stage only files belonging to this feature and explicitly selected special-reference artifacts.
- Follow test-driven development for each production behavior: add a focused failing test, run it red, implement the smallest change, then run it green.
- Preserve batch generation for single-reference jobs; do not turn the approximately twenty-thousand-job clone phase into one model call per line.
- Verify generated route counts, Avatar variant filenames, reference hashes, sidecar metadata, review HTML, and the existing C++ Avatar lookup contract before committing.

---

## Task 1: Add role-manifest loading and role-part parsing

**Files:** `tools/voice_acting/generate_omnivoice_u6.py`, `tools/voice_acting/test_generate_omnivoice_u6.py`, `u6_voice/manifests/u6_voice_roles.jsonl`

1. Add failing tests for `load_role_manifest()` using a temporary JSONL fixture, including malformed-line tolerance, key normalization, and a row with English `@...@` markers.
2. Add failing tests for the role parser: speaker-only English, narrator-only English, mixed English, mixed Chinese with aligned `@...@`, Chinese quote fallback, trailing `*` removal, and the rule that Chinese quotes do not create a speaker part when English has no speaker markers.
3. Add `RoleSource`/`VoicePart`-level helpers with explicit signatures:

   ```python
   load_role_manifest(path: Path) -> dict[tuple[str, str, str], dict[str, str]]
   parse_role_parts(source_en: str, translated_text: str, lang: str) -> list[tuple[str, str]]
   role_key(function_id: str, offset_key: str, segment: str) -> tuple[str, str, str]
   ```

   Normalize whitespace and control markers without changing meaningful punctuation or translation text.
4. Generate the compact `u6_voice/manifests/u6_voice_roles.jsonl` from the valid approved rows in the existing U6 source manifest, retaining only mapping keys and role-source fields. Validate its row count and key coverage against `u6_qwen3_mapping.json`; report malformed source rows rather than silently inventing role data.
5. Add `--role-manifest` with the compact manifest as the default and thread the loaded source through `main()` while keeping test callers that omit it backward-compatible.
6. Run the focused parser/loader tests and the existing U6 generator test file.

## Task 2: Stage U7 special references and build routed clone jobs

**Files:** `tools/voice_acting/generate_omnivoice_u6.py`, `tools/voice_acting/test_generate_omnivoice_u6.py`, selected files under `u6_voice/refs`

1. Add failing tests for staging the four U7 special reference families from `voice/refs` into a temporary U6 refs directory, including source/destination names, idempotent copies, and manifest transcript preservation.
2. Add failing tests for clone-job routing with a temporary role manifest:
   - NPC speaker-only uses its NPC reference.
   - Narrator-only uses gender-matched narrator reference.
   - Mixed text creates ordered NPC/narrator/NPC parts.
   - An NPC name matching U7 keeps the exact U7 reference.
   - `Avatar` expands into male/female jobs with distinct output filenames and matching speaker/narrator references.
3. Add `stage_u7_special_references()` and reference-selection helpers. Use the existing U7 import manifest and verify source files before copying into `u6_voice/refs`; return stable reference IDs, transcript text, and source hashes.
4. Extend `CloneJob` with backward-compatible defaults for `reference_role`, `reference_revision`, `voice_parts`, and Avatar gender/variant data. Add a small serializable part representation containing role, text, reference path, reference transcript, and reference ID.
5. Extend `build_clone_jobs()` with optional role-source/reference-route inputs. Resolve each mapping row into one effective reference for single-part jobs or an ordered part list for mixed jobs. Expand Avatar rows without changing the shared function/offset/segment identity.
6. Include reference revision/part identity in `_job_seed()`, require current reference revision in `_completion_expected()`/`_complete()`, and keep old metadata valid for jobs without routing metadata.
7. Add route fields to clone manifest records and sidecars without embedding non-serializable `Path` objects.
8. Run the new routing tests, all existing generator tests, and a dry-run count report showing ordinary, narrator-only, mixed, and Avatar-male/female job counts.

## Task 3: Render mixed parts and expose routing in review output

**Files:** `tools/voice_acting/generate_omnivoice_u6.py`, `tools/voice_acting/generate_voice_review_html.py`, `tools/voice_acting/test_generate_omnivoice_u6.py`, relevant review tests

1. Add failing model-fake tests proving each mixed part uses its own reference prompt and that the final audio is ordered and spliced; add a regression test that single-reference jobs still use the existing batch path.
2. Implement a per-part OmniVoice render helper that caches prompts by `(reference path, transcript)`, derives deterministic part seeds, renders each part with its selected reference, applies short boundary fades, and concatenates the parts. Route failures through the same configured fallback policy as ordinary clone jobs.
3. Update `process_voice()` to retain the existing batch path for jobs without multiple parts and use the mixed renderer only where required. Publish the complete route metadata and reference hashes for both paths.
4. Extend review data generation to associate Avatar-suffixed files and routed sidecars with their mapping rows, exposing at least `reference_role`, `reference_revision`, and ordered part roles/reference IDs while retaining existing review URLs and expected-filename behavior.
5. Run focused rendering/review tests and a local dry-run/review generation over representative speaker-only, narrator-only, mixed, and both Avatar variants.

## Task 4: Regenerate affected artifacts and verify the runtime contract

**Files:** generated outputs under `u6_voice/refs`, `u6_voice/omnivoice`, `u6_voice/omnivoice_review`, and `u6_voice/omnivoice_manifest.json`; existing runtime tests only if a targeted assertion is needed

1. Stage and hash the four U7 special reference families into `u6_voice/refs`, preserving already-correct NPC references and changing only missing/outdated routed references.
2. Run the reference phase for any newly required Avatar/narrator references, then run the clone phase for routed jobs and explicitly stale/failed jobs. Keep periodic review HTML generation enabled and record the final route counts.
3. Verify every generated Avatar base has `_avatar_male` and `_avatar_female` outputs, every narrator/mixed output sidecar names the expected narrator/NPC references, and no output embeds a trailing `*` marker.
4. Run the existing C++ gameplay translation/runtime contract test and confirm `VoiceActingManager` still selects `_avatar_female` for a female main actor and `_avatar_male` otherwise. No runtime source change is expected because this behavior already exists.
5. Run the full targeted Python test suite plus relevant runtime tests, inspect `git diff --check`, and review the generated HTML/index metadata.
6. Commit only the implementation, tests, plan, compact role manifest, special reference files, and intentionally regenerated routed artifacts. Push the scoped commit to `origin/u6_voice`; leave unrelated dirty/untracked work untouched.

## Verification Commands

```bash
python3 -m pytest tools/voice_acting/test_generate_omnivoice_u6.py -q
python3 -m pytest tools/voice_acting/test_generate_voice_review_html.py -q
make gameplay_translation_table_test && ./gameplay_translation_table_test
python3 tools/voice_acting/generate_omnivoice_u6.py --phase voice --role-manifest u6_voice/manifests/u6_voice_roles.jsonl --dry-run
git diff --check
git status --short
```

The final handoff will report the exact commit, pushed branch, routed-job counts, generated/reviewed artifact locations, and any intentionally uncommitted generated audio that was left out because it was unrelated or too large.
