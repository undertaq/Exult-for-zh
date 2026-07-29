# Task 2 Report: Candidate Generation, Diversity Selection, and Audio Audit

## Status

Implemented candidate planning/generation, per-language maximin selection, Avatar/Narrator medoid selection, deterministic audio audit fallback, and Phase A candidate-workflow delegation. No audio was generated and no approved `voice/refs` clip was written.

## Files Changed

- Added `tools/voice_acting/generate_reference_candidates.py`
  - `CandidateJob`, `build_candidate_jobs`, bible normalization at the CLI boundary, Qwen3 VoiceDesign batching with OOM splitting, resumable generation, atomic OGG/JSON publishing, and SHA-256 provenance metadata.
  - CLI supports `--voice-bibles`, `--npcs`, `--candidates`, `--device`, `--batch-size`, `--skip-existing`, and `--overwrite`.
- Added `tools/voice_acting/select_reference_candidates.py`
  - deterministic per-language maximin selection with total-diversity tie improvement, medoid selection for special voices, ECAPA lazy loading, audio audit, and invalid-selection replacement.
- Added `tools/voice_acting/test_reference_candidate_pipeline.py`
  - CPU-only generation planning, bible normalization, OOM splitting, maximin, medoid, and audit replacement tests.
- Updated `tools/voice_acting/generate_qwen3_voice.py`
  - added `--reference-workflow {candidates,legacy}` defaulting to `candidates`, candidate-only Phase A output, and candidate CLI forwarding. Candidate `--phase all` stops before prompts/voice pending selection and approval.
- Updated `tools/voice_acting/test_generate_qwen3_voice_behavior.py`
  - validates the default candidate workflow parser behavior.

## TDD Evidence

RED:

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline -v
```

Result: expected import failure because `generate_reference_candidates` did not exist.

```bash
python3 -m unittest tools.voice_acting.test_generate_qwen3_voice_behavior.GenerateQwen3VoiceBehaviorTest.test_phase_a_defaults_to_candidate_workflow -v
```

Result: expected `AttributeError` because `build_parser` did not exist.

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline.CandidateSelectionTest.test_special_candidates_use_the_within_character_medoid -v
```

Result: expected `AttributeError` because `select_medoids` did not exist.

GREEN:

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline -v
```

Result: `Ran 6 tests ... OK`.

## Verification

```bash
python3 -m py_compile tools/voice_acting/generate_reference_candidates.py tools/voice_acting/select_reference_candidates.py tools/voice_acting/generate_qwen3_voice.py tools/voice_acting/test_reference_candidate_pipeline.py tools/voice_acting/test_generate_qwen3_voice_behavior.py
```

Result: exit 0.

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline tools.voice_acting.test_generate_qwen3_voice_behavior -v
```

Result: `Ran 47 tests in 0.660s`, `OK`. Tests use fake Qwen modules and no GPU model/network access.

```bash
python3 tools/voice_acting/generate_reference_candidates.py --help
python3 tools/voice_acting/select_reference_candidates.py --help
```

Result: both CLIs expose their expected candidate-generation and selection arguments.

```bash
/home/joe/project/qwen3-tts/.venv/bin/python tools/voice_acting/generate_qwen3_voice.py --phase refs --dry-run --npc Iolo --candidate-output-dir /tmp/task2-reference-candidates
```

Result: reported exactly ten Chinese and ten English Iolo review candidates. It loaded no model, generated no audio, created no candidate output directory, and wrote no fresh `voice/refs` files. The command completed successfully; the environment emitted only an existing `zhconv`/`pkg_resources` deprecation warning.

```bash
git diff --check
```

Result: exit 0.

## Self-Review

- Candidate output is separate from `voice/refs`; candidate Phase A never calls the legacy reference writer.
- Candidate sidecars contain the required input provenance, model ID, content hash, sample rate, and duration fields.
- Existing reference fingerprint/hash validation was not changed or weakened.
- Model, speech encoder, and audio decoding dependencies are lazy-loaded so focused tests neither load GPU models nor access the network.
- Existing unrelated changes in the two modified Task 1 files were retained. The large existing diffs in those files were not reverted or reformatted.

## Concerns

- Live candidate minting and ECAPA embedding were intentionally not run because the full dialogue process remains allocated to the GPU; real selection requires the local SpeechBrain model/dependencies.
- System `python3` lacks `torch`; the existing Qwen virtualenv is required for `generate_qwen3_voice.py` execution. The focused tests remain runnable with system `python3` through their fake modules.
- Git metadata is read-only in this workspace, so no commit was created.

## Fix Review

### Finding Resolutions

- Critical 1: `build_candidate_jobs` now rejects `voice/refs` and every descendant after resolving paths, so candidate mode cannot target approved references.
- Critical 2: selection audits every candidate before embedding, embeds only valid clips, and raises a language/character-specific error when no valid clip exists.
- Critical 3: grouped designs now emit the full Chinese/English candidate set for every member of `design["npcs"]`.
- Important 1: `npc_unknown`, the canonical female narrator, is explicitly classified as a standalone medoid selection rather than part of cast maximin.
- Important 2: resumable generation validates both the OGG and JSON sidecar, including job identity and SHA-256. Orphaned or hash-mismatched pairs regenerate.
- Important 3: OOM child batches receive non-overlapping seeds; metadata records each candidate's effective seed. Normal batches also use unique effective seeds across the run.
- Important 4: `replace_invalid_selections` now raises when no valid alternative exists instead of emitting an invalid choice.
- Important 5: `backup_legacy_voice_state` creates one unique timestamped `voice/voice_backup/<timestamp>` directory per non-dry-run invocation, copies existing refs and `clone_prompts.pkl`, and is called before legacy reference or prompt mutation. The helper is reusable by Task 3.

### Focused Regression Tests

Added coverage for protected output paths, grouped-NPC expansion, orphan/hash-mismatched resume, split and cross-batch seed independence, unreadable candidates excluded from embedding, `npc_unknown` medoid routing, no-valid-candidate rejection, and one-time/dry-run legacy backups.

### RED/Green Evidence

RED before implementing the review fixes:

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline tools.voice_acting.test_generate_qwen3_voice_behavior -v
```

Result: `Ran 55 tests`; 4 failures and 5 errors, covering protected refs, grouped-NPC expansion, orphan resume, repeated OOM seed, unreadable-audit embedding, narrator routing, invalid fallback, and missing legacy backup API.

Additional RED found during self-review:

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline.CandidateGenerationTest.test_generate_jobs_records_unique_effective_seeds_across_batches -v
```

Result: failed with recorded seeds `[1000, 1001, 1001, 1002]` instead of `[1000, 1001, 1002, 1003]`.

GREEN after each implementation:

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline.CandidateGenerationTest.test_generate_jobs_records_unique_effective_seeds_across_batches -v
```

Result: `Ran 1 test ... OK`.

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline tools.voice_acting.test_generate_qwen3_voice_behavior -v
```

Result: `Ran 56 tests in 0.846s`, `OK`.

Additional verification:

```bash
python3 -m py_compile tools/voice_acting/generate_reference_candidates.py tools/voice_acting/select_reference_candidates.py tools/voice_acting/generate_qwen3_voice.py tools/voice_acting/test_reference_candidate_pipeline.py tools/voice_acting/test_generate_qwen3_voice_behavior.py
git diff --check
```

Result: both commands exited 0.

### Files Changed

- `tools/voice_acting/generate_reference_candidates.py`
- `tools/voice_acting/select_reference_candidates.py`
- `tools/voice_acting/test_reference_candidate_pipeline.py`
- `tools/voice_acting/generate_qwen3_voice.py`
- `tools/voice_acting/test_generate_qwen3_voice_behavior.py`
- `.superpowers/sdd/task-2-report.md`

### Self-Review

- Reviewed the candidate-output boundary, seed propagation, sidecar validation, audit-to-embedding flow, original candidate-index preservation, and legacy mutation entry points.
- No live GPU generation was run and the full dialogue generation process was not stopped or restarted.
- Existing unrelated edits remain intact. No commit was attempted because Git metadata is read-only.

## Re-review Fix Pass 2

### Finding Resolutions

- `UNKNOWN` and `npc_unknown` now normalize to the `narrator_female` candidate slug. Selection retains the legacy aliases as standalone medoid voices.
- Resume validation now compares `sample_text`, `instruct`, and `model_revision` as well as the identity fields and audio hash.
- Generation schedules against the complete job list, so resuming does not renumber batches. Sidecars record the applied `seed`/`batch_seed` and `batch_position`; a batch shares the model seed actually applied to it, and OOM child batches receive distinct seeds.
- Legacy reference/prompt backups now publish below project-root `voice_backup`.
- Per-NPC bible overlays remove the overridden NPC from existing groups before adding the bible design, yielding one destination job per NPC/language.
- Candidate-mode `--phase prompts` behavior was not changed: it still consumes approved refs and backs up mutable legacy state before rebuilding prompts.

### RED Evidence

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline.CandidateGenerationTest.test_unknown_narrator_uses_the_canonical_female_narrator_slug -v
```

Result: `FAILED (failures=2)`; `UNKNOWN` produced `unknown` and `npc_unknown` produced `npc_unknown`, not `narrator_female`.

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline.CandidateGenerationTest.test_resume_rejects_sidecars_with_stale_generation_inputs -v
```

Result: `FAILED (failures=3)`; stale `sample_text`, `instruct`, and `model_revision` sidecars were treated as complete.

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline.CandidateGenerationTest.test_resumed_batches_record_the_applied_seed_and_batch_position -v
```

Result: `FAILED (failures=1)`; resume compressed pending jobs, changing the first model batch from `[job 1]` to `[job 1, job 2]`.

```bash
python3 -m unittest tools.voice_acting.test_generate_qwen3_voice_behavior.GenerateQwen3VoiceBehaviorTest.test_legacy_backup_copies_refs_and_clone_prompts_once tools.voice_acting.test_generate_qwen3_voice_behavior.GenerateQwen3VoiceBehaviorTest.test_legacy_backup_does_not_run_during_dry_run -v
```

Result: `FAILED (failures=1)`; backup parent was `voice/voice_backup` rather than project-root `voice_backup`.

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline.CandidateGenerationTest.test_voice_bible_overlay_removes_its_npc_from_grouped_designs -v
```

Result: `FAILED (failures=1)`; the grouped Iolo jobs remained alongside the bible Iolo jobs.

### GREEN Evidence

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline.CandidateGenerationTest.test_unknown_narrator_uses_the_canonical_female_narrator_slug tools.voice_acting.test_reference_candidate_pipeline.CandidateSelectionTest.test_canonical_female_narrator_uses_medoid_selection -v
```

Result: `Ran 2 tests ... OK`.

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline.CandidateGenerationTest.test_resume_rejects_sidecars_with_stale_generation_inputs -v
```

Result: `Ran 1 test ... OK`.

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline.CandidateGenerationTest.test_resumed_batches_record_the_applied_seed_and_batch_position tools.voice_acting.test_reference_candidate_pipeline.CandidateGenerationTest.test_generate_jobs_splits_oom_batches_and_writes_metadata tools.voice_acting.test_reference_candidate_pipeline.CandidateGenerationTest.test_generate_jobs_records_shared_batch_seeds_and_positions -v
```

Result: `Ran 3 tests ... OK`.

```bash
python3 -m unittest tools.voice_acting.test_generate_qwen3_voice_behavior.GenerateQwen3VoiceBehaviorTest.test_legacy_backup_copies_refs_and_clone_prompts_once tools.voice_acting.test_generate_qwen3_voice_behavior.GenerateQwen3VoiceBehaviorTest.test_legacy_backup_does_not_run_during_dry_run -v
```

Result: `Ran 2 tests ... OK`.

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline.CandidateGenerationTest.test_voice_bible_overlay_removes_its_npc_from_grouped_designs -v
```

Result: `Ran 1 test ... OK`.

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline tools.voice_acting.test_generate_qwen3_voice_behavior -v
```

Result: `Ran 60 tests in 0.665s`, `OK`. No GPU model or network access was used.

Additional RNG provenance migration check:

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline.CandidateGenerationTest.test_resume_rejects_sidecars_without_batch_provenance -v
```

RED result: `FAILED (failures=1)` because a hash-valid legacy sidecar without `batch_seed` or `batch_position` was accepted. GREEN result: `Ran 1 test ... OK`; resume now regenerates sidecars missing required batch provenance.

Final focused-suite verification after this migration check: `Ran 61 tests in 0.621s`, `OK`. The five Task 2 Python files also passed `python3 -m py_compile`, and `git diff --check` exited 0.

## Final Review Fix Pass 3

### Finding Resolutions

- Candidate jobs are partitioned into stable scheduled batches before resume validation. A batch is skipped only when every member matches its scheduled seed, position, and size; one stale or missing member regenerates the entire original batch, including otherwise valid peers.
- Sidecar validation now requires positive `sample_rate` and `duration_seconds`, valid integer seed/provenance fields, and exact scheduled `batch_seed`, `batch_position`, and `batch_size`. `seed` continues to record the effective model seed after OOM splitting, while the batch fields preserve stable resume identity.
- `--npcs` now trims each retained grouped design's `npcs` list to explicitly requested members before candidate jobs are built.

### RED Evidence

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline.CandidateGenerationTest.test_resumed_batches_record_the_applied_seed_and_batch_position tools.voice_acting.test_reference_candidate_pipeline.CandidateGenerationTest.test_resume_rejects_invalid_audio_metrics_and_mismatched_batch_provenance tools.voice_acting.test_reference_candidate_pipeline.CandidateGenerationTest.test_npcs_filter_trims_unrequested_members_from_grouped_design -v
```

Result: `Ran 3 tests`; 7 failures. The partially complete batch was compressed to one pending job, all five invalid metric/provenance subcases were skipped, and grouped `--npcs Iolo` scheduled four jobs including Spark instead of two Iolo jobs.

### GREEN Evidence

The same three-test command after implementation reported `Ran 3 tests in 0.023s`, `OK`.

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline tools.voice_acting.test_generate_qwen3_voice_behavior -v
```

Result: `Ran 63 tests in 0.650s`, `OK`. The suites use fake models and performed no GPU generation or network access.

Final post-refactor rerun of the same two suites without `-v`: `Ran 63 tests in 0.600s`, `OK`.

```bash
python3 -m py_compile tools/voice_acting/generate_reference_candidates.py tools/voice_acting/test_reference_candidate_pipeline.py
git diff --check
```

Result: both commands exited 0.

### Files Changed

- `tools/voice_acting/generate_reference_candidates.py`
- `tools/voice_acting/test_reference_candidate_pipeline.py`
- `.superpowers/sdd/task-2-report.md`

### Concerns

- Existing candidate sidecars without positive audio metrics or the new `batch_size` field are intentionally stale. Resuming them regenerates their entire scheduled batch to restore deterministic RNG identity.
- Live Qwen generation was intentionally not run; no GPU or network work was performed.

## Embedding Fix Pass 4

### Finding Resolution

- `embed_candidates` now resamples non-16 kHz decoded PCM to ECAPA's required 16 kHz before calling `encode_batch`. The resampling dependency is imported only when a candidate needs conversion; module import and 16 kHz candidates do not load Torch or torchaudio through this path.
- `audit_candidate` remains unchanged and continues to calculate duration, clipping, and silence from native decoded PCM and its native sample rate.

### RED Evidence

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline.CandidateSelectionTest.test_embed_candidates_resamples_24khz_audio_to_16khz_before_ecapa -v
```

Result: `FAILED (failures=1)`. The fake ECAPA encoder received `(24000,)` samples from a 24 kHz candidate where the regression test required `(16000,)`.

### GREEN Evidence

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline.CandidateSelectionTest.test_embed_candidates_resamples_24khz_audio_to_16khz_before_ecapa -v
```

Result: `Ran 1 test in 0.008s`, `OK`. The test verifies that the lazy resampler is called with `24000 -> 16000` and that `encode_batch` receives 16,000 samples.

```bash
python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline tools.voice_acting.test_generate_qwen3_voice_behavior -v
```

Result: `Ran 64 tests in 1.591s`, `OK`. The suites used fakes; no live GPU model or network generation was run.

```bash
python3 -m py_compile tools/voice_acting/select_reference_candidates.py tools/voice_acting/test_reference_candidate_pipeline.py
git diff --check
```

Result: both commands exited 0.

### Self-Review

- The only production behavior change is the pre-encoder sample-rate conversion in `embed_candidates`.
- Audio audit loading and metrics remain native-rate and are not routed through the ECAPA conversion helper.
- `torch` and `torchaudio` remain lazy imports; no heavy dependency was added at module import time.
- No candidate audio or approved references were generated or modified. Unrelated workspace edits were preserved.

### Concern

- Embedding a non-16 kHz candidate now requires the existing ECAPA runtime's `torchaudio` installation. The focused tests replace it with a fake module and do not load GPU dependencies.
