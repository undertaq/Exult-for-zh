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

