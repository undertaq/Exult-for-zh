# Task 1 Report: Reference Manifest and Individual Design Conversion

## Status

BLOCKED. The implementation and focused tests are complete, but the authoritative
read-only `../voice_sample` inputs fail the required SHA-256 integrity validation.
The converter therefore did not replace `tools/voice_acting/npc_voice_designs.json`.

## Implementation

- Added `tools/voice_acting/reference_voice_manifest.py`.
  - Provides `slugify_npc`, `design_id_for_selection`, `load_selection`,
    `load_selection_data`, `SelectedVoice`, and `build_individual_designs`.
  - Validates one selected English and Chinese candidate per slug, adjacent JSON
    metadata, language/index/slug agreement, selected seed agreement, non-empty
    `sample_text`, voice-bible availability, unique NPC names, and audio SHA-256.
  - Uses `voice_prompt_enriched` and `voice_prompt_enriched_zh` from the voice
    bibles plus the exact candidate `sample_text` values for reference text.
  - Converts selected records to a single `npcs` entry each, with stable special
    routing: `npc_avatar_male`, `npc_avatar_female`, `npc_narrator_male`, and
    `npc_unknown` for the female narrator.
  - Recomputes individual-design metadata, including zero group counts.
- Added `tools/voice_acting/test_reference_voice_manifest.py` with six focused
  unit tests for IDs/routing, grouped conversion, incomplete language pairs,
  duplicate NPCs, missing metadata, and hash mismatches.
- `tools/voice_acting/npc_voice_designs.json` was intentionally not written.
  It was already modified in the working tree before this task; the converter's
  real-data preflight stopped before producing `/tmp/npc_voice_designs.individual.json`.

## Files Changed

- Created: `tools/voice_acting/reference_voice_manifest.py`
- Created: `tools/voice_acting/test_reference_voice_manifest.py`
- Created: `.superpowers/sdd/task-1-report.md`
- Not changed by this task: `tools/voice_acting/npc_voice_designs.json`

## TDD Evidence

### RED

Command:

```bash
python3 -m unittest tools.voice_acting.test_reference_voice_manifest -v
```

Result: exit 1. `ImportError: cannot import name 'reference_voice_manifest'`
because the required production module did not yet exist.

### GREEN

Command:

```bash
python3 -m unittest tools.voice_acting.test_reference_voice_manifest -v
```

Result: exit 0. All 6 tests passed in 0.064 seconds.

An intermediate GREEN attempt exposed that legacy `group_count` was not reset;
the test failed at `test_grouped_designs_expand_to_one_design_per_selected_npc`.
The root cause was the metadata update omitting that legacy key. The converter
now explicitly sets both `group_designs` and `group_count` to zero, and the
fresh GREEN run passed.

## Exact Verification Commands and Results

```bash
python3 -m unittest tools.voice_acting.test_reference_voice_manifest -v
```

Exit 0: 6 tests passed.

```bash
python3 -m py_compile \
  tools/voice_acting/reference_voice_manifest.py \
  tools/voice_acting/test_reference_voice_manifest.py
```

Exit 0.

```bash
python3 tools/voice_acting/reference_voice_manifest.py build-designs \
  --selection ../voice_sample/artifacts/reports/signature_selection.json \
  --voice-bibles ../voice_sample/artifacts/voice_bibles \
  --candidate-root ../voice_sample/artifacts \
  --current-designs tools/voice_acting/npc_voice_designs.json \
  --output /tmp/npc_voice_designs.individual.json
```

Exit 2: `aimi: English candidate sha256 mismatch`. No output design file was
written and no source artifact was modified.

```bash
../qwen3-tts/.venv/bin/python \
  tools/voice_acting/audit_narrator_gender.py --fail-on-issues
```

Exit 0 against the pre-existing design JSON: 274 NPC voices audited, 0 issues.
The system-Python invocation could not import `torch`; the installed Qwen
interpreter supplied that dependency. This is a baseline only, not the required
post-conversion audit, because conversion was correctly blocked.

```bash
git diff --check -- \
  tools/voice_acting/reference_voice_manifest.py \
  tools/voice_acting/test_reference_voice_manifest.py \
  tools/voice_acting/npc_voice_designs.json
```

Exit 0.

## Input Integrity Audit

The selection has 268 records and 536 selected language candidates. A read-only
SHA-256 audit found 22 candidate-file mismatches; 514 candidate files match
their adjacent metadata. The mismatches are both English and Chinese candidates
for: `aimi`, `batlin`, `caine`, `chuckles`, `draxinusom`, `dupre`, `erethian`,
`hydra`, `iolo`, `lord_british`, and `spark`.

The candidate audio mtimes are later than their metadata mtimes for the sampled
mismatches. This is consistent with artifacts being changed after metadata was
written; it is not safe to overwrite the recorded hashes or bypass validation.

## Self-Review

- The manifest module uses only standard-library dependencies and does not
  import sibling-project Python modules.
- The CLI writes only its requested output after complete selection validation,
  so malformed or stale input cannot partially replace the design JSON.
- Candidate paths are read-only inputs and no voice-generation process was
  stopped or restarted.
- `git diff --check` is clean for the owned implementation paths.
- The actual design replacement and its required post-conversion narrator audit
  remain unperformed because the source integrity guard stopped conversion.

## Concerns and Required External Resolution

1. Regenerate or correct the adjacent candidate JSON SHA-256 values in
   `../voice_sample/artifacts/references` for the 22 listed selected files, or
   restore the exact audio files for which those hashes were recorded. This must
   be done by the owner of the read-only sibling artifacts.
2. Re-run the exact `build-designs` command after the artifact hashes agree.
   Expected result: 268 designs, 268 unique NPCs, one English and one Chinese
   non-empty reference text per design, and zero ordinary group designs.
3. Then run the same Qwen-interpreter narrator-gender audit against the newly
   generated `tools/voice_acting/npc_voice_designs.json`.

## Commits

None. Git metadata is read-only in this environment, so no commit was attempted.
