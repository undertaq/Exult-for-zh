### Task 2: Candidate Generation, Diversity Selection, and Audio Audit

**Files:**
- Create: `tools/voice_acting/generate_reference_candidates.py`
- Create: `tools/voice_acting/select_reference_candidates.py`
- Create: `tools/voice_acting/test_reference_candidate_pipeline.py`
- Modify: `tools/voice_acting/generate_qwen3_voice.py`
- Modify: `tools/voice_acting/test_generate_qwen3_voice_behavior.py`

**Interfaces:**
- Produces: `build_candidate_jobs(designs: dict, output_dir: Path, candidates: int) -> list[CandidateJob]`
- Produces: `generate_jobs(model, jobs, seed_base, batch_size, skip_existing) -> list[Path]`
- Produces: `select_maximin(embeddings, candidates, restarts) -> dict[str, int]`
- Produces: `audit_candidate(path: Path) -> AudioAudit`
- Produces: `replace_invalid_selections(selection, audits, embeddings) -> dict`

- [ ] **Step 1: Write failing job and selection tests**

```python
def test_jobs_include_ten_independent_language_candidates(self):
    jobs = module.build_candidate_jobs(designs_fixture(), Path("out"), 10)
    self.assertEqual(len(jobs), 40)
    self.assertEqual(jobs[0].output.name, "candidate_Chinese_0.ogg")

def test_maximin_avoids_near_duplicate_cast_pair(self):
    picks = selector.select_maximin(synthetic_embeddings(), candidates=2, restarts=4)
    self.assertEqual(picks, {"iolo": 1, "dupre": 0, "spark": 1})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline -v`

Expected: import failures for the new modules.

- [ ] **Step 3: Port resumable candidate generation from `voice_sample`**

Use Qwen3 VoiceDesign with the exact per-language instruction and stable sample text. Write `candidate_<Language>_<index>.ogg` and adjacent JSON atomically. Metadata includes:

```python
metadata = {
    "npc": job.npc,
    "slug": job.slug,
    "index": job.index,
    "language": job.language,
    "sample_text": job.text,
    "instruct": job.instruct,
    "seed": seed,
    "model_revision": MODEL_ID,
    "sha256": sha256_file(job.output),
    "sample_rate": sample_rate,
    "duration_seconds": round(len(wav) / sample_rate, 3),
}
```

Implement `--skip-existing`, `--overwrite`, `--npcs`, `--candidates`, `--device`, `--batch-size`, and OOM batch splitting.

- [ ] **Step 4: Port ECAPA maximin selection and medoid special selection**

Select English and Chinese independently. Ordinary cast selection maximizes the minimum pairwise cosine distance, then improves total diversity without reducing that floor. Avatar and narrator candidates use the within-character medoid.

- [ ] **Step 5: Implement deterministic audio audit fallback**

Reject unreadable clips, duration outside 2-20 seconds, clipping ratio over 0.01, or silence ratio over 0.80. Choose the valid alternative with the greatest minimum distance from already selected cast voices and record `replaced_index`, `replacement_reason`, and metrics.

- [ ] **Step 6: Verify candidate tests GREEN**

Run: `python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline -v`

Expected: all tests pass without loading GPU models.

- [ ] **Step 7: Make Phase A delegate to the candidate workflow**

Add `--reference-workflow {candidates,legacy}` with default `candidates`. In candidate mode, `--phase refs` invokes the new job generator and never writes directly to approved `voice/refs`. Preserve `legacy` only as an explicit compatibility option.

- [ ] **Step 8: Add and run Phase A delegation tests**

```python
def test_phase_a_defaults_to_candidate_workflow(self):
    args = parser_args("--phase refs --dry-run")
    self.assertEqual(args.reference_workflow, "candidates")
```

Run:

`python3 -m unittest tools.voice_acting.test_reference_candidate_pipeline tools.voice_acting.test_generate_qwen3_voice_behavior -v`

Expected: all tests pass.

- [ ] **Step 9: Commit when Git becomes writable**

```bash
git add tools/voice_acting/generate_reference_candidates.py \
  tools/voice_acting/select_reference_candidates.py \
  tools/voice_acting/test_reference_candidate_pipeline.py \
  tools/voice_acting/generate_qwen3_voice.py \
  tools/voice_acting/test_generate_qwen3_voice_behavior.py
git commit -m "Integrate robust reference candidate selection"
```

---

