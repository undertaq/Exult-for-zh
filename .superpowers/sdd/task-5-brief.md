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

