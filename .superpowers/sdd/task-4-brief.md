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

