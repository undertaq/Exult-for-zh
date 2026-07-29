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
