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

