# Voice-Prompt Sync, Batch + Multi-GPU Speedup, and Reference-Voice Regeneration

> **For agentic workers:** Implement via the tasks below (checkboxes). Tests use `unittest` and the project's TDD convention (failing test first, then implementation). The qwen3 generation steps run under the `qwen3-tts` venv.

**Goal (3 parts):**
1. Sync `voice_prompt` / add `voice_prompt_zh` in `bilingual_mapping_review.json` from each NPC's new reference-voice design (`voice_desc_en` / `voice_desc_zh`).
2. Speed up Phase C via **native model batching** (one `generate_voice_clone` call per bucket of lines) **and** multi-GPU parallelism.
3. Regenerate all EN+ZH voices from the **new ref audio** (Phase B rebuild + Phase C), with the review HTML refreshing periodically.

## Global Constraints
- Preserve all existing non-empty `zh_text` values and every runtime-identity field in `bilingual_mapping_review.json`.
- Back up `voice/refs` and `clone_prompts.pkl` before replacement (handled by `backup_legacy_voice_state`).
- `tone` / `tone_instruct` remain metadata; the Base clone model has no text instruct input, so regeneration is audio-clone from ref audio, not tone-driven.
- Two GPUs are available: RTX 5060 Ti (cuda:0, 16GB) and RTX 3060 (cuda:1, 12GB); both fit the 1.7B model.

---

### Task 1: `sync_mapping_voice_prompts.py` (+ review-HTML prompt display)
- [ ] **Files:** create `tools/voice_acting/sync_mapping_voice_prompts.py`, `tools/voice_acting/test_sync_mapping_voice_prompts.py`; modify `tools/voice_acting/generate_voice_review_html.py`.
- [ ] **Interfaces:**
  - `build_npc_to_prompt_map(designs: dict) -> dict[str, tuple[str, str]]` → `npc_name → (voice_desc_en, voice_desc_zh)`.
  - Routing: `Avatar` → `npc_avatar_male`; `''` / `UNKNOWN` → `npc_unknown`; `Avatar male`/`Avatar female` → respective designs.
  - `sync_row(row: dict, prompt_map: dict) -> dict` → returns row with `voice_prompt` / `voice_prompt_zh` set; all other keys untouched.
  - CLI: `--mapping`, `--designs`, `--dry-run`.
- [ ] Write failing tests: resolution maps NPC→design; special-NPC routing; `sync_row` changes only `voice_prompt`/`voice_prompt_zh`; `--dry-run` writes nothing.
- [ ] Implement idempotent sync (only those two fields change); unresolved NPCs left untouched and counted.
- [ ] In `rows_from_full_voice`, fill each review row's `prompt` from `voice_prompt` / `voice_prompt_zh`.
- [ ] Run tests GREEN; `--dry-run` then real run on mapping.
- [ ] Commit: `sync_mapping_voice_prompts.py`, `test_sync_mapping_voice_prompts.py`, `generate_voice_review_html.py`, `bilingual_mapping_review.json`.

### Task 2: native model batching in Phase C
- [ ] **Files:** modify `tools/voice_acting/generate_qwen3_voice.py`; extend `tools/voice_acting/test_generate_qwen3_voice_behavior.py`.
- [ ] **Interfaces:**
  - `bucket_single_part_jobs(jobs, max_lines) -> list[Bucket]` keyed by `(lang, prompt_identity, length_class)`; `length_class` = short (≤100 chars) / long.
  - Call `model.generate_voice_clone(text=list, voice_clone_prompt=list, language=list, max_new_tokens=class)` once per bucket.
  - Rename `BATCH_SIZE_PHASE_C` → `MAX_LINES_PER_CALL`; auto OOM-split (halve bucket, retry).
- [ ] Write failing test with **mocked model**: asserts one call per bucket; short/long separated; narrator vs speaker prompts bucketed separately; multi-part entries not batched.
- [ ] Implement; multi-part (delimited narrator+speaker) entries keep existing per-line `generate_delimited_voice` (fade-splice preserved).
- [ ] Tests GREEN; `--dry-run`.

### Task 3: multi-GPU orchestration
- [ ] **Files:** modify `tools/voice_acting/generate_qwen3_voice.py`; document watcher usage.
- [ ] **Interfaces:**
  - `shard_npcs(by_npc: dict, gpus: list[int]) -> dict[int, list[str]]` (round-robin; disjoint; every NPC on exactly one GPU).
  - Orchestrator: for each `(gpu, shard)` launch subprocess `python generate_qwen3_voice.py --device cuda:{gpu} --npc {','.join(shard)} --phase voice --force …` (each subprocess applies Task 2 batching; shared `voice/zh`, `voice/en` dirs, no filename collisions).
- [ ] Write failing test: disjoint sharding; every NPC assigned to exactly one GPU.
- [ ] Implement `--gpus` arg + orchestrator; single-GPU (`--device` only) unchanged.
- [ ] Tests GREEN; `--dry-run` with `--gpus 0,1`.
- [ ] **Review HTML during multi-GPU:** run watcher alongside workers — `generate_voice_review_html.py --mode full --only-new --since-mtime <t0> --out-dir tools/voice_acting/voice_review_current` on a timer (single-GPU keeps the existing in-process periodic update).

### Task 4: regenerate + periodic review (execution)
- [ ] Run Task 1 sync (`bilingual_mapping_review.json.bak` is the safety backup).
- [ ] `generate_qwen3_voice.py --phase prompts` — rebuild clone prompts from new `voice/refs`.
- [ ] `generate_qwen3_voice.py --phase voice --force [--gpus 0,1] --review-out-dir tools/voice_acting/voice_review_current --review-update-interval 120` (or watcher for multi-GPU).
- [ ] Validate: clone-prompt coverage (every design en+zh); mapping diff shows **only** `voice_prompt`/`voice_prompt_zh` changed; review HTML renders; audio present for all rows.
- [ ] Commit generated state.

---

## Verification (all must pass)
```
python3 -m unittest discover -s tools/voice_acting -p 'test_*.py' -v
python3 tools/voice_acting/install_reference_voices.py \
  --manifest tools/voice_acting/reference_import_manifest.json \
  --refs-dir voice/refs --verify-installed
# mapping invariant: diff excluding zh_text is empty; only voice_prompt/voice_prompt_zh differ
```
