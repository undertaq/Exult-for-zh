# Robust Reference Voice Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate per-NPC candidate-based reference voice generation and selection, import the selected `voice_sample` references, provide a full HTML review page, and translate every missing `zh_text` value without changing runtime identities.

**Architecture:** New focused modules own manifest normalization, candidate generation/selection, atomic installation, review rendering, and translation. `generate_qwen3_voice.py` keeps dialogue generation and clone-prompt construction, but its reference phase delegates to the candidate pipeline so a single unscored clip cannot overwrite an approved reference. The initial migration consumes the sibling project's selection manifest and candidate metadata, then writes self-contained artifacts into this repository.

**Tech Stack:** Python 3.12, `unittest`, Qwen3-TTS VoiceDesign, Ollama HTTP API, ECAPA/SpeechBrain, NumPy, SoundFile, ffmpeg/ffprobe, static HTML/CSS/JavaScript.

## Global Constraints

- Preserve all existing non-empty `zh_text` values and every runtime identity field in `bilingual_mapping_review.json`.
- Use local Ollama model `qwen3.6:35b` for missing Chinese translations.
- Generate Traditional Chinese and preserve narration/dialogue boundaries and placeholders.
- Every ordinary NPC gets an individual `npc_<slug>` design and reference pair.
- Preserve explicit male/female Avatar and male/female narrator routing.
- Back up references and `clone_prompts.pkl` before replacement.
- Do not depend at runtime on Python modules from `../voice_sample`.
- The current environment has read-only `.git`; commit steps can run only after Git metadata becomes writable.

---

### Task 1: Reference Manifest and Individual Design Conversion

**Files:**
- Create: `tools/voice_acting/reference_voice_manifest.py`
- Create: `tools/voice_acting/test_reference_voice_manifest.py`
- Modify: `tools/voice_acting/npc_voice_designs.json`

**Interfaces:**
- Produces: `slugify_npc(name: str) -> str`
- Produces: `design_id_for_selection(slug: str) -> str`
- Produces: `load_selection(path: Path) -> dict[str, SelectedVoice]`
- Produces: `build_individual_designs(current: dict, selection: dict, voice_bibles_dir: Path, candidate_root: Path) -> dict`
- `SelectedVoice` carries NPC, slug, EN/ZH candidate paths, indices, seeds, metadata, and special routing.

- [ ] **Step 1: Write failing normalization and routing tests**

```python
class ReferenceVoiceManifestTest(unittest.TestCase):
    def test_design_ids_are_individual_and_special_ids_are_stable(self):
        self.assertEqual(module.design_id_for_selection("iolo"), "npc_iolo")
        self.assertEqual(module.design_id_for_selection("avatar_male"), "npc_avatar_male")
        self.assertEqual(module.design_id_for_selection("avatar_female"), "npc_avatar_female")
        self.assertEqual(module.design_id_for_selection("narrator_male"), "npc_narrator_male")
        self.assertEqual(module.design_id_for_selection("narrator_female"), "npc_unknown")

    def test_grouped_designs_expand_to_one_design_per_selected_npc(self):
        result = module.build_individual_designs(
            grouped_design_fixture(), selection_fixture(), self.bibles, self.refs
        )
        self.assertEqual(result["designs"]["npc_iolo"]["npcs"], ["Iolo"])
        self.assertEqual(result["designs"]["npc_dupre"]["npcs"], ["Dupre"])
        self.assertNotIn("group_companions", result["designs"])
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m unittest tools.voice_acting.test_reference_voice_manifest -v`

Expected: import failure because `reference_voice_manifest.py` does not exist.

- [ ] **Step 3: Implement manifest parsing and deterministic design conversion**

```python
SPECIAL_DESIGN_IDS = {
    "avatar_male": "npc_avatar_male",
    "avatar_female": "npc_avatar_female",
    "narrator_male": "npc_narrator_male",
    "narrator_female": "npc_unknown",
}

def design_id_for_selection(slug: str) -> str:
    return SPECIAL_DESIGN_IDS.get(slug, f"npc_{slug}")

def selected_reference_text(candidate_metadata: dict) -> str:
    text = str(candidate_metadata.get("sample_text", "")).strip()
    if not text:
        raise ManifestError("selected candidate has no sample_text")
    return text
```

Build each design from the selected NPC's voice bible, set `npcs` to exactly one name, map enriched EN/ZH prompts into `voice_desc_en` and `voice_desc_zh`, and set `ref_en_text`/`ref_zh_text` from the corresponding candidate JSON. Recompute `_meta` counts with zero ordinary group designs.

- [ ] **Step 4: Add failure tests for duplicate NPCs, missing metadata, hash mismatches, and incomplete language pairs**

```python
def test_selection_requires_complete_language_pair(self):
    selection = selection_fixture()
    del selection["selected"]["iolo"]["chinese_wav"]
    with self.assertRaisesRegex(module.ManifestError, "Chinese"):
        module.load_selection_data(selection, self.refs, self.bibles)
```

- [ ] **Step 5: Run tests and verify GREEN**

Run: `python3 -m unittest tools.voice_acting.test_reference_voice_manifest -v`

Expected: all manifest tests pass.

- [ ] **Step 6: Generate and validate the individual design JSON**

Run:

```bash
python3 tools/voice_acting/reference_voice_manifest.py build-designs \
  --selection ../voice_sample/artifacts/reports/signature_selection.json \
  --voice-bibles ../voice_sample/artifacts/voice_bibles \
  --candidate-root ../voice_sample/artifacts \
  --current-designs tools/voice_acting/npc_voice_designs.json \
  --output /tmp/npc_voice_designs.individual.json
```

Expected: 268 selected records resolve; each NPC appears once; both reference texts are non-empty; no source file is modified.

- [ ] **Step 7: Replace `npc_voice_designs.json` through the validated command**

Run the same command with `--output tools/voice_acting/npc_voice_designs.json`, then run:

`python3 tools/voice_acting/audit_narrator_gender.py --fail-on-issues`

Expected: zero narrator gender issues.

- [ ] **Step 8: Commit when Git becomes writable**

```bash
git add tools/voice_acting/reference_voice_manifest.py \
  tools/voice_acting/test_reference_voice_manifest.py \
  tools/voice_acting/npc_voice_designs.json
git commit -m "Add individual reference voice manifests"
```

---

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

### Task 3: Atomic Reference Installation and Backup

**Files:**
- Create: `tools/voice_acting/install_reference_voices.py`
- Create: `tools/voice_acting/test_install_reference_voices.py`
- Generate: `tools/voice_acting/reference_import_manifest.json`
- Replace: `voice/refs/*_{en,zh}_ref.ogg`
- Back up: `voice_backup/refs_<timestamp>/`

**Interfaces:**
- Produces: `preflight(selection, source_root, designs) -> list[InstallItem]`
- Produces: `install(items, refs_dir, backup_root, clone_prompts_path) -> dict`
- Installer supports `--dry-run` and `--verify-only`.

- [ ] **Step 1: Write failing preflight and transaction tests**

```python
def test_preflight_fails_before_backup_when_one_candidate_is_missing(self):
    missing = self.source / "references/iolo/candidate_English_8.ogg"
    missing.unlink()
    with self.assertRaises(module.InstallError):
        module.preflight(self.selection, self.source, self.designs)
    self.assertFalse(any(self.backups.iterdir()))

def test_install_backs_up_then_copies_exact_selected_files(self):
    manifest = module.install(self.items, self.refs, self.backups, self.prompts)
    self.assertTrue((self.backups / manifest["backup_id"] / "refs").is_dir())
    self.assertEqual(sha256(self.refs / "npc_iolo_en_ref.ogg"), self.en_hash)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m unittest tools.voice_acting.test_install_reference_voices -v`

Expected: import failure for `install_reference_voices.py`.

- [ ] **Step 3: Implement complete preflight and atomic installation**

Validate source hashes against candidate JSON, exact reference text against the generated design, one EN and one ZH source per design, and unique destinations. Copy to a staging directory, verify staged hashes, back up current refs/prompts, then use `Path.replace()` per destination. Write the import manifest atomically.

- [ ] **Step 4: Run installation tests GREEN**

Run: `python3 -m unittest tools.voice_acting.test_install_reference_voices -v`

Expected: all tests pass.

- [ ] **Step 5: Preflight the real sibling selection**

Run:

```bash
python3 tools/voice_acting/install_reference_voices.py \
  --selection ../voice_sample/artifacts/reports/signature_selection.json \
  --source-root ../voice_sample/artifacts \
  --designs tools/voice_acting/npc_voice_designs.json \
  --refs-dir voice/refs --backup-root voice_backup --verify-only
```

Expected: 536 files validated for 268 voices, no duplicates, no hash failures.

- [ ] **Step 6: Install the selected references**

Run the same command without `--verify-only` and with
`--manifest tools/voice_acting/reference_import_manifest.json`.

Expected: timestamped backup exists; 536 destination references match the selection manifest.

- [ ] **Step 7: Commit code and lightweight provenance when Git becomes writable**

```bash
git add tools/voice_acting/install_reference_voices.py \
  tools/voice_acting/test_install_reference_voices.py \
  tools/voice_acting/reference_import_manifest.json
git commit -m "Install selected per-character reference voices"
```

Do not add timestamped backups or generated OGG files unless repository policy already tracks `voice/refs`.

---

### Task 4: Full Reference Voice Review HTML

**Files:**
- Create: `tools/voice_acting/generate_reference_voice_review.py`
- Create: `tools/voice_acting/test_generate_reference_voice_review.py`
- Generate: `tools/voice_acting/reference_voice_review/index.html`

**Interfaces:**
- Produces: `build_report(selection, bibles, candidate_root, output_path, audit) -> str`
- Produces: `selection_fingerprint(selection: dict) -> str`
- CLI accepts selection, source root, portrait root, audit report, and output path.

- [ ] **Step 1: Write failing report behavior tests**

```python
def test_report_renders_selected_and_all_candidates_inline(self):
    page = module.build_report(self.selection, self.bibles, self.root, self.out, {})
    self.assertIn("candidate_English_8.ogg", page)
    self.assertIn("candidate_Chinese_9.ogg", page)
    self.assertIn("<audio", page)
    self.assertNotIn("target=\"_blank\"", page)

def test_review_storage_key_changes_with_selection(self):
    first = module.selection_fingerprint(self.selection)
    self.selection["selected"]["iolo"]["english_index"] = 2
    self.assertNotEqual(first, module.selection_fingerprint(self.selection))
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m unittest tools.voice_acting.test_generate_reference_voice_review -v`

Expected: import failure for the report module.

- [ ] **Step 3: Implement static report generation**

Render a searchable section per character with lazy portrait, bilingual prompts, selected EN/ZH players, seed/index/audit details, collapsed ten-candidate comparison, and selected-cell highlighting. Use `preload="none"` on audio.

- [ ] **Step 4: Implement persistent review controls and filters**

Store values under `ultima-ref-review:<selection fingerprint>` with keys `<slug>:English` and `<slug>:Chinese`. Pass and Failed are mutually exclusive. Implement filters for unreviewed, passed, failed, missing portrait, missing audio, and audit warnings, with live counters.

- [ ] **Step 5: Run tests GREEN and generate the real report**

Run:

```bash
python3 -m unittest tools.voice_acting.test_generate_reference_voice_review -v
python3 tools/voice_acting/generate_reference_voice_review.py \
  --selection ../voice_sample/artifacts/reports/signature_selection.json \
  --source-root ../voice_sample/artifacts \
  --output tools/voice_acting/reference_voice_review/index.html
```

Expected: report contains 268 character sections and 536 selected players.

- [ ] **Step 6: Browser verification**

Serve the repository locally, inspect desktop and mobile widths with Playwright, verify the first/middle/last portraits and audio URLs return successfully, then click Pass, reload, and confirm persistence.

- [ ] **Step 7: Commit when Git becomes writable**

```bash
git add tools/voice_acting/generate_reference_voice_review.py \
  tools/voice_acting/test_generate_reference_voice_review.py
git commit -m "Add reference voice review report"
```

Keep generated HTML out of Git unless existing report policy tracks generated pages.

---

### Task 5: Resumable Missing Chinese Translation

**Files:**
- Create: `tools/voice_acting/translate_missing_zh_text.py`
- Create: `tools/voice_acting/test_translate_missing_zh_text.py`
- Modify: `tools/voice_acting/bilingual_mapping_review.json`
- Generate: `tools/voice_acting/missing_zh_translation_audit.json`
- Generate: `tools/voice_acting/missing_zh_translation_cache.jsonl`

**Interfaces:**
- Produces: `select_missing_rows(rows: list[dict]) -> list[dict]`
- Produces: `build_translation_prompt(rows: list[dict]) -> dict`
- Produces: `validate_translation(source: str, translated: str) -> list[str]`
- Produces: `apply_translations(rows, accepted_by_index) -> list[dict]`
- Ollama endpoint defaults to `http://127.0.0.1:11434/api/chat` and model `qwen3.6:35b`.

- [ ] **Step 1: Write failing row-selection and non-mutation tests**

```python
def test_only_nonempty_english_with_empty_chinese_is_selected(self):
    selected = module.select_missing_rows(self.rows)
    self.assertEqual([row["index"] for row in selected], [83])

def test_apply_changes_only_zh_text(self):
    before = copy.deepcopy(self.rows[0])
    after = module.apply_translations(self.rows, {83: "「譯文。」"})[0]
    self.assertEqual(after["zh_text"], "「譯文。」")
    self.assertEqual({k: v for k, v in after.items() if k != "zh_text"},
                     {k: v for k, v in before.items() if k != "zh_text"})
```

- [ ] **Step 2: Write failing delimiter, placeholder, and Traditional Chinese validation tests**

```python
def test_validator_preserves_two_dialogue_spans(self):
    source = 'He says, "First." Then she says, "Second."'
    self.assertEqual(module.validate_translation(source, "他說：「第一句。」接著她說：「第二句。」"), [])
    self.assertIn("dialogue span count", module.validate_translation(source, "他說第一句。"))

def test_validator_rejects_lost_placeholder(self):
    errors = module.validate_translation("Welcome, <PLAYER_NAME>.", "歡迎你。")
    self.assertIn("placeholder", " ".join(errors))
```

- [ ] **Step 3: Run tests and verify RED**

Run: `python3 -m unittest tools.voice_acting.test_translate_missing_zh_text -v`

Expected: import failure for the translation module.

- [ ] **Step 4: Implement deterministic Ollama translation and cache**

Send JSON-only batches with source indices and text. Set temperature to 0 and request Traditional Chinese, Ultima terminology, narration preservation, and `「」` dialogue. Cache each accepted/rejected response by SHA-256 of model name, prompt version, and source text.

- [ ] **Step 5: Implement validators and row-atomic application**

Check non-empty output, no model commentary, placeholder multiset equality, dialogue-span count, balanced `「」`, and absence of common Simplified-only characters where a Traditional equivalent exists. Never alter a rejected row.

- [ ] **Step 6: Run translation tests GREEN**

Run: `python3 -m unittest tools.voice_acting.test_translate_missing_zh_text -v`

Expected: all tests pass without contacting Ollama.

- [ ] **Step 7: Dry-run the real mapping and confirm target count**

Run:

```bash
python3 tools/voice_acting/translate_missing_zh_text.py \
  --mapping tools/voice_acting/bilingual_mapping_review.json \
  --model qwen3.6:35b --dry-run
```

Expected: exactly 85 rows selected, zero existing translations selected.

- [ ] **Step 8: Translate, validate, and inspect rejected rows**

Run without `--dry-run`, writing cache and audit paths. Retry only rejected rows after correcting prompt or terminology rules. Do not manually force validator failures into the mapping.

- [ ] **Step 9: Run quote and canonical mapping audits**

Run:

```bash
python3 tools/voice_acting/fix_dialogue_quote_balance.py --dry-run
python3 -m unittest tools.voice_acting.test_fix_alignment_and_tags \
  tools.voice_acting.test_fix_dialogue_quote_balance -v
```

Expected: balanced dialogue delimiters and no canonical identity regressions.

- [ ] **Step 10: Commit when Git becomes writable**

```bash
git add tools/voice_acting/translate_missing_zh_text.py \
  tools/voice_acting/test_translate_missing_zh_text.py \
  tools/voice_acting/bilingual_mapping_review.json \
  tools/voice_acting/missing_zh_translation_audit.json
git commit -m "Translate missing Chinese voice mapping text"
```

Do not add the resumable cache unless repository policy explicitly tracks model caches.

---

### Task 6: Prompt Rebuild and End-to-End Verification

**Files:**
- Modify: `tools/voice_acting/clone_prompts.pkl`
- Modify: `tools/voice_acting/generate_qwen3_voice.py` only if verification exposes a compatibility defect
- Modify: tests only for defects proven during verification

**Interfaces:**
- Consumes installed `voice/refs`, individual `npc_voice_designs.json`, and Phase B.
- Produces clone prompts for both languages for every complete design.

- [ ] **Step 1: Run the complete lightweight test suite before GPU work**

Run:

```bash
python3 -m unittest \
  tools.voice_acting.test_reference_voice_manifest \
  tools.voice_acting.test_reference_candidate_pipeline \
  tools.voice_acting.test_install_reference_voices \
  tools.voice_acting.test_generate_reference_voice_review \
  tools.voice_acting.test_translate_missing_zh_text \
  tools.voice_acting.test_generate_qwen3_voice_behavior -v
```

Expected: all tests pass.

- [ ] **Step 2: Rebuild clone prompts from imported references**

Run:

```bash
/home/joe/project/qwen3-tts/.venv/bin/python \
  tools/voice_acting/generate_qwen3_voice.py --phase prompts --device cuda:0
```

Expected: EN and ZH prompts build for every complete individual design; zero missing-reference errors.

- [ ] **Step 3: Audit prompt/reference coverage**

Load `clone_prompts.pkl` and assert every design has non-null `en` and `zh` prompts. Compare each installed OGG hash and transcription with `reference_import_manifest.json`.

- [ ] **Step 4: Run all voice-acting unit tests and data audits**

Run:

```bash
python3 -m unittest discover -s tools/voice_acting -p 'test_*.py' -v
python3 tools/voice_acting/audit_narrator_gender.py --fail-on-issues
python3 tools/voice_acting/install_reference_voices.py \
  --manifest tools/voice_acting/reference_import_manifest.json \
  --refs-dir voice/refs --verify-installed
```

Expected: all tests pass, narrator issues are zero, installed references verify.

- [ ] **Step 5: Verify mapping invariants against the pre-change snapshot**

Compare every row excluding `zh_text`; assert byte-equivalent values for all other keys. Confirm missing target count is zero or every remaining row appears as rejected in the audit report with a concrete reason.

- [ ] **Step 6: Refresh the review report against installed references**

Generate the HTML using the repository import manifest and installed refs. Confirm all selected sources are playable and review state uses the same selection fingerprint as the candidate report.

- [ ] **Step 7: Commit final generated state when Git becomes writable**

```bash
git add tools/voice_acting/clone_prompts.pkl
git commit -m "Rebuild clone prompts from robust references"
```

- [ ] **Step 8: Record final operational commands**

Update `tools/voice_acting/README.md` if present; otherwise add a concise workflow section to the nearest voice-acting documentation covering candidate generation, selection, installation, review, translation, and Phase B prompt rebuild.
