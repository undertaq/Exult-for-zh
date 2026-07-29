# Task 2 Review

## Critical

1. Reject `voice/refs` and descendants as `--candidate-output-dir`; candidate mode must never overwrite approved references.
2. Audit candidates before embedding. Unreadable files must not abort embedding before fallback; fail clearly if a character/language has no valid candidate.
3. Emit jobs once per member of `design["npcs"]`, not once per grouped design, so every ordinary NPC receives individual candidates.

## Important

1. Route the canonical female narrator (`npc_unknown`) to standalone medoid selection rather than cast maximin.
2. Make OGG/JSON publication interruption-safe: `--skip-existing` must validate both sidecar and audio hash and regenerate an incomplete/orphaned pair.
3. OOM splitting must not reuse the same random stream for both halves; candidates remain independent and metadata records the effective seed.
4. Raise instead of writing an invalid selection when no valid replacement exists.
5. The explicit legacy mode must back up references and `clone_prompts.pkl` before replacement.

## Required Tests

Add focused tests for protected output paths, unreadable candidate handling, grouped-NPC expansion, female narrator medoid routing, orphan-sidecar resume, independent split seeds, no-valid-candidate rejection, and legacy backup behavior.

## Re-review Findings

1. Normalize `npc_unknown` / `UNKNOWN` to the `narrator_female` candidate slug so it always uses standalone medoid selection.
2. Resume validation must include `sample_text`, `instruct`, and `model_revision`, not only identity fields and audio hash.
3. Seed metadata must describe the RNG seed actually applied to model generation. Preserve stable batch identity across resumable runs; never record fabricated per-candidate seeds.
4. Write backups under project-root `voice_backup`, not `voice/voice_backup`.
5. When per-NPC voice bibles overlay grouped designs, remove those NPCs from the groups so one destination job is emitted exactly once.

The re-review claim that candidate mode cannot run `--phase prompts` is not applicable: Phase B consumes approved refs and writes clone prompts after backing them up; it does not write reference audio. The post-install prompt rebuild requires this path.

## Final Review Findings

1. Preserve fixed RNG batches during resume. If any member of a scheduled batch is stale or missing, regenerate the entire batch with its original seed, size, and positions; do not compress pending jobs.
2. Resume validation must require positive `sample_rate` and `duration_seconds` plus exact scheduled `batch_seed`, `batch_position`, and `batch_size`.
3. `--npcs` must trim grouped designs to only explicitly requested NPC members.

## Embedding Review Finding

Resample decoded candidate PCM to ECAPA's expected 16 kHz before `encode_batch`; preserve native-rate loading for audit metrics and add a focused nonmatching-rate test.
