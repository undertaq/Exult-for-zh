# Stone Guardian: Stop Generated Voice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all AI-generated voice for the Stone Guardian (NPC 277) from the voice pipeline and shipped distribution, so the game's original recorded voice plays, while keeping the mapping/design data marked for reference.

**Architecture:** A uniform `"voice_generation": "skip"` marker is added to (a) the `npc_stone_guardian` design in `npc_voice_designs.json` and (b) all 25 Stone Guardian rows in `bilingual_mapping_review.json`. The generator (`generate_qwen3_voice.py`) and dependent tools honor the marker and never generate/track those lines. The 50 synthesized `.ogg` files are deleted and the `.pak`/`.idx` archives rebuilt. A C++ guard in `VoiceActingManager::play_for_conversation()` refuses to route NPC 277 to synthesized lookup.

**Tech Stack:** Python 3.12 (pipeline tools), C++17 (Exult engine), `make` for engine build, `unittest` for Python tests.

**Spec:** `docs/superpowers/specs/2026-08-04-stone-guardian-original-voice-design.md`

---

### Task 1: Add skip marker to the Stone Guardian voice design

**Files:**
- Modify: `tools/voice_acting/npc_voice_designs.json` (`designs.npc_stone_guardian`, ~line 5087)

- [ ] **Step 1: Add `"voice_generation": "skip"` to the design entry**

Current entry:

```json
   "npc_stone_guardian": {
    "npc": "Stone Guardian",
    "type": "individual",
    "npcs": [
     "Stone Guardian"
    ],
    "voice_desc_en": "Male, elemental, deep rumbling stone voice, slow and wise",
```

Add the marker after `"npc": "Stone Guardian",` so the entry becomes:

```json
   "npc_stone_guardian": {
    "npc": "Stone Guardian",
    "type": "individual",
    "voice_generation": "skip",
    "npcs": [
     "Stone Guardian"
    ],
    "voice_desc_en": "Male, elemental, deep rumbling stone voice, slow and wise",
```

- [ ] **Step 2: Verify JSON is still valid**

Run:
```bash
python3 -c "import json; d=json.load(open('tools/voice_acting/npc_voice_designs.json')); assert d['designs']['npc_stone_guardian']['voice_generation']=='skip'; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tools/voice_acting/npc_voice_designs.json
git commit -m "feat(voice): mark Stone Guardian voice design as generation-skip"
```

---

### Task 2: Add skip marker to the 25 Stone Guardian mapping rows

**Files:**
- Modify: `tools/voice_acting/bilingual_mapping_review.json`

- [ ] **Step 1: Add the marker to every Stone Guardian row**

Run this idempotent Python script (re-runnable):

```bash
cd /home/joe/project/Exult-for-zh && python3 - <<'EOF'
import json
path = 'tools/voice_acting/bilingual_mapping_review.json'
with open(path, encoding='utf-8') as f:
    data = json.load(f)
added = 0
for e in data:
    if e.get('npc') == 'Stone Guardian':
        if e.get('voice_generation') != 'skip':
            e['voice_generation'] = 'skip'
            added += 1
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f'Marked {added} Stone Guardian rows as skip')
EOF
```
Expected: `Marked 25 Stone Guardian rows as skip`

- [ ] **Step 2: Verify**

```bash
python3 -c "
import json
d = json.load(open('tools/voice_acting/bilingual_mapping_review.json'))
sg = [e for e in d if e.get('npc') == 'Stone Guardian']
assert len(sg) == 25 and all(e.get('voice_generation') == 'skip' for e in sg)
print('OK: all 25 Stone Guardian rows marked skip')
"
```
Expected: `OK: all 25 Stone Guardian rows marked skip`

- [ ] **Step 3: Commit**

```bash
git add tools/voice_acting/bilingual_mapping_review.json
git commit -m "feat(voice): mark Stone Guardian mapping rows as generation-skip"
```

---

### Task 3: Generator honors the skip marker

**Files:**
- Modify: `tools/voice_acting/generate_qwen3_voice.py`
  - `load_mapping()` (~line 608): skip marked rows.
  - `phase_a_generate_refs` (~line 932): skip marked designs.
  - `phase_b_build_prompts` (~lines 1150, 1186): skip marked designs.
  - `phase_c_generate_voice` (~line 1333): skip NPCs whose design is marked.
- Test: `tools/voice_acting/test_generate_qwen3_voice_behavior.py`

- [ ] **Step 1: Write the failing tests**

Append these test methods to `GenerateQwen3VoiceBehaviorTest` in `test_generate_qwen3_voice_behavior.py`:

```python
    def test_load_mapping_excludes_rows_marked_voice_generation_skip(self):
        module = load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            module.MAPPING_PATH = str(tmp / "bilingual_mapping_review.json")
            module.EN_LINES_PATH = str(tmp / "en_voice_lines.csv")
            module.ZH_LINES_PATH = str(tmp / "zh_voice_lines.csv")
            Path(module.EN_LINES_PATH).write_text(
                "func_id,npc,speaker,caller_guess,offset_key,segment,total_segments,has_var,text\n",
                encoding="utf-8",
            )
            Path(module.ZH_LINES_PATH).write_text(
                "func_id,npc,speaker,caller_guess,offset_key,segment,total_segments,has_var,text\n",
                encoding="utf-8",
            )
            Path(module.MAPPING_PATH).write_text(
                json.dumps([
                    {
                        "npc": "Stone Guardian",
                        "voice_generation": "skip",
                        "zh_func_id": "0x0614",
                        "zh_offset_key": "0",
                        "zh_segment": 0,
                        "zh_text": "「是的，休息吧，我的朋友。」",
                        "en_func_id": "0x0614",
                        "en_offset_key": "0",
                        "en_segment": 0,
                        "en_text": "Yes, rest, my friend.",
                    },
                    {
                        "npc": "Iolo",
                        "zh_func_id": "0x0401",
                        "zh_offset_key": "0",
                        "zh_segment": 0,
                        "zh_text": "「你好。」",
                        "en_func_id": "0x0401",
                        "en_offset_key": "0",
                        "en_segment": 0,
                        "en_text": "Hello.",
                    },
                ]),
                encoding="utf-8",
            )

            data, by_npc = module.load_mapping()

        npcs = {e.get("npc") for e in data}
        self.assertNotIn("Stone Guardian", npcs)
        self.assertNotIn("Stone Guardian", by_npc)
        self.assertIn("Iolo", by_npc)

    def test_phase_c_skips_npc_with_marked_design(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            module.ZH_OUTPUT = os.path.join(tmpdir, "zh")
            module.EN_OUTPUT = os.path.join(tmpdir, "en")
            writes = []
            module.write_ogg_direct = lambda *args, **kwargs: writes.append(args)

            designs = {
                "designs": {
                    "npc_stone_guardian": {
                        "npc": "Stone Guardian",
                        "npcs": ["Stone Guardian"],
                        "voice_generation": "skip",
                    },
                },
            }
            by_npc = {
                "Stone Guardian": [
                    {
                        "npc": "Stone Guardian",
                        "zh_func_id": "0x0614",
                        "zh_offset_key": "0",
                        "zh_segment": 0,
                        "zh_text": "「是的，休息吧。」",
                    },
                ],
            }
            clone_prompts = {"npc_stone_guardian": {"zh": ["prompt"]}}
            args = argparse.Namespace(
                lang="zh", dry_run=False, force=True, max_npcs=None, device="cuda:0",
                generic_fallbacks=False, review_out_dir=None, review_update_interval=0,
                review_only_new=True, review_since_mtime=0,
            )

            generated, skipped, errors = module.phase_c_generate_voice(
                designs, clone_prompts, by_npc, args
            )

            self.assertEqual((generated, skipped, errors), (0, 1, 0))
            self.assertEqual(writes, [])
```

- [ ] **Step 2: Run the new tests, confirm they fail**

Run:
```bash
cd /home/joe/project/Exult-for-zh/tools/voice_acting && .venv/bin/python -m unittest test_generate_qwen3_voice_behavior.GenerateQwen3VoiceBehaviorTest.test_load_mapping_excludes_rows_marked_voice_generation_skip test_generate_qwen3_voice_behavior.GenerateQwen3VoiceBehaviorTest.test_phase_c_skips_npc_with_marked_design -v
```
Expected: both FAIL (Stone Guardian still present / generated).

- [ ] **Step 3: Add a skip helper and apply it in `load_mapping`**

Add near the top of `generate_qwen3_voice.py` (after the constants block, e.g. after `def text_hash(text)`):

```python
def is_voice_generation_skipped(entry):
    """Return True when an entry/design is marked reference-only for voice."""
    return (entry.get('voice_generation') or '') == 'skip'
```

In `load_mapping()` (inside `for entry in raw_data:`), insert as the first statement:

```python
        if is_voice_generation_skipped(entry):
            continue
```

- [ ] **Step 4: Apply the helper in `phase_a_generate_refs`**

In `phase_a_generate_refs`, inside `for did, design in sorted(designs['designs'].items()):`, insert after the `npc_label` line:

```python
            if is_voice_generation_skipped(design):
                print(f'  [{npc_label}] Voice generation skipped (original game voice)')
                skipped += 2
                continue
```

- [ ] **Step 5: Apply the helper in `phase_b_build_prompts`**

In `phase_b_build_prompts`, in the dry-run loop (`for did, design in sorted(designs['designs'].items()):`) after `npc_label = ...`:

```python
            if is_voice_generation_skipped(design):
                continue
```

And in the real loop (also after `npc_label = ...`):

```python
            if is_voice_generation_skipped(design):
                print(f'  [{npc_label}] Voice generation skipped (original game voice)')
                continue
```

- [ ] **Step 6: Apply the helper in `phase_c_generate_voice`**

In `phase_c_generate_voice`, inside the per-NPC loop, after the `design = get_design_for_npc(...)` block (after the `if not design:` error branch and `continue`), insert:

```python
                if is_voice_generation_skipped(design):
                    print(f'  [{npc_name}] Voice generation skipped (original game voice)')
                    total_skip += len(entries)
                    continue
```

- [ ] **Step 7: Run the new tests, confirm they pass**

```bash
cd /home/joe/project/Exult-for-zh/tools/voice_acting && .venv/bin/python -m unittest test_generate_qwen3_voice_behavior.GenerateQwen3VoiceBehaviorTest.test_load_mapping_excludes_rows_marked_voice_generation_skip test_generate_qwen3_voice_behavior.GenerateQwen3VoiceBehaviorTest.test_phase_c_skips_npc_with_marked_design -v
```
Expected: both PASS.

- [ ] **Step 8: Run the full generator test suite**

```bash
cd /home/joe/project/Exult-for-zh/tools/voice_acting && .venv/bin/python -m unittest test_generate_qwen3_voice_behavior -v
```
Expected: all existing tests still PASS.

- [ ] **Step 9: Commit**

```bash
git add tools/voice_acting/generate_qwen3_voice.py tools/voice_acting/test_generate_qwen3_voice_behavior.py
git commit -m "feat(voice): generator honors voice_generation skip marker"
```

---

### Task 4: Skip marked rows in the missing-EN generator

**Files:**
- Modify: `tools/voice_acting/generate_missing_en_voices.py` (inside `main()`, loop at ~line 43)

- [ ] **Step 1: Skip marked entries**

In `main()`, at the top of the `for entry in data:` loop, add:

```python
        if (entry.get("voice_generation") or "").strip() == "skip":
            continue
```

- [ ] **Step 2: Sanity-check the audit logic is unchanged for other NPCs**

Run:
```bash
cd /home/joe/project/Exult-for-zh && python3 -c "
import json
from pathlib import Path
data = json.load(open('tools/voice_acting/bilingual_mapping_review.json'))
marked = [e for e in data if (e.get('voice_generation') or '').strip() == 'skip']
print('marked rows:', len(marked))
assert all(e.get('npc') == 'Stone Guardian' for e in marked)
print('OK: only Stone Guardian rows are marked')
"
```
Expected: `marked rows: 25` then `OK: only Stone Guardian rows are marked`

- [ ] **Step 3: Commit**

```bash
git add tools/voice_acting/generate_missing_en_voices.py
git commit -m "feat(voice): skip reference-only rows in missing-EN generator"
```

---

### Task 5: Review HTML counts marked rows as reference, not missing

**Files:**
- Modify: `tools/voice_acting/generate_voice_review_html.py` (`build_mapping_index()`, ~line 101)
- Test: `tools/voice_acting/test_generate_voice_review_html.py`

- [ ] **Step 1: Write the failing test**

Append to `GenerateVoiceReviewHtmlTest` in `test_generate_voice_review_html.py`:

```python
    def test_build_mapping_index_excludes_voice_generation_skip_rows(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            mapping_path = Path(tmpdir) / "mapping.json"
            mapping_path.write_text(
                json.dumps([
                    {
                        "npc": "Stone Guardian",
                        "voice_generation": "skip",
                        "zh_func_id": "0x0614",
                        "zh_offset_key": "0",
                        "zh_segment": 0,
                        "zh_text": "「是的，休息吧。」",
                        "en_func_id": "0x0614",
                        "en_offset_key": "0",
                        "en_segment": 0,
                        "en_text": "Yes, rest.",
                    },
                    {
                        "npc": "Iolo",
                        "zh_func_id": "0x0401",
                        "zh_offset_key": "0",
                        "zh_segment": 0,
                        "zh_text": "「你好。」",
                        "en_func_id": "0x0401",
                        "en_offset_key": "0",
                        "en_segment": 0,
                        "en_text": "Hello.",
                    },
                ]),
                encoding="utf-8",
            )

            index = module.build_mapping_index(mapping_path)

        keys = list(index.keys())
        self.assertTrue(all("npc277" not in k[1] for k in keys))
        self.assertTrue(any("npc1" in k[1] for k in keys))
```

- [ ] **Step 2: Run it, confirm it fails**

```bash
cd /home/joe/project/Exult-for-zh/tools/voice_acting && .venv/bin/python -m unittest test_generate_voice_review_html.GenerateVoiceReviewHtmlTest.test_build_mapping_index_excludes_voice_generation_skip_rows -v
```
Expected: FAIL (npc277 key present).

- [ ] **Step 3: Skip marked rows in `build_mapping_index`**

In `build_mapping_index()`, inside `for entry in rows:`, insert as the first statement:

```python
        if (entry.get("voice_generation") or "") == "skip":
            continue
```

- [ ] **Step 4: Run it, confirm it passes**

```bash
cd /home/joe/project/Exult-for-zh/tools/voice_acting && .venv/bin/python -m unittest test_generate_voice_review_html.GenerateVoiceReviewHtmlTest.test_build_mapping_index_excludes_voice_generation_skip_rows -v
```
Expected: PASS.

- [ ] **Step 5: Run the full review-html test suite**

```bash
cd /home/joe/project/Exult-for-zh/tools/voice_acting && .venv/bin/python -m unittest test_generate_voice_review_html -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/voice_acting/generate_voice_review_html.py tools/voice_acting/test_generate_voice_review_html.py
git commit -m "feat(voice): review HTML treats voice_generation skip rows as reference"
```

---

### Task 6: Engine guard refuses synthesized voice for the Stone Guardian

**Files:**
- Modify: `audio/VoiceActingManager.h` (add constant, ~line 39 class)
- Modify: `audio/VoiceActingManager.cc` (`play_for_conversation`, ~line 445)

- [ ] **Step 1: Add the NPC constant to the header**

In `VoiceActingManager.h`, inside the class `public:` section (after the `init()` declaration), add:

```cpp
	// Stone Guardian (NPC 277) has an original in-game recording; the
	// synthesized voice is never substituted for it.
	static constexpr int stone_guardian_npc = 277;
```

- [ ] **Step 2: Add the early-return guard in `play_for_conversation`**

In `audio/VoiceActingManager.cc`, in `VoiceActingManager::play_for_conversation()`, insert immediately after the `if (!voice_enabled)` block (before `ensure_packed_loaded()`):

```cpp
	// The Stone Guardian keeps its original in-game recording. Never route
	// its lines to the synthesized lookup, even if a stray file reappears.
	const int abs_speaker = speaker_npc < 0 ? -speaker_npc : speaker_npc;
	const int abs_caller  = caller_npc < 0 ? -caller_npc : caller_npc;
	if (abs_speaker == stone_guardian_npc || abs_caller == stone_guardian_npc) {
		ensure_log_open();
		log_entry("", "", function_id, offset_key, segment, text,
		          "original", speaker_npc, caller_npc);
		return false;
	}
```

Note: `speaker_npc`/`caller_npc` follow the negative-NPC usecode convention (`-1` = Iolo), and the existing code at line ~533 already computes `speaker_abs` the same way — this guard matches that convention.

- [ ] **Step 3: Compile the engine**

```bash
cd /home/joe/project/Exult-for-zh && make audio/VoiceActingManager.o
```
Expected: compiles with no errors (exit 0).

- [ ] **Step 4: Full link check (optional but recommended)**

```bash
cd /home/joe/project/Exult-for-zh && make 2>&1 | tail -5
```
Expected: links successfully.

- [ ] **Step 5: Commit**

```bash
git add audio/VoiceActingManager.h audio/VoiceActingManager.cc
git commit -m "feat(voice): engine never substitutes synthesized voice for Stone Guardian"
```

---

### Task 7: Delete synthesized Stone Guardian files and rebuild packs

**Files:**
- Delete: `voice/en/0614_*_npc277.ogg` (25 files)
- Delete: `voice/zh/0614_*_npc277.ogg` (25 files)
- Rebuild: `voice/en_voices.pak/.idx`, `voice/zh_voices.pak/.idx`

- [ ] **Step 1: Confirm the file sets before deleting**

```bash
cd /home/joe/project/Exult-for-zh && echo "en: $(ls voice/en/0614_*_npc277.ogg | wc -l)" && echo "zh: $(ls voice/zh/0614_*_npc277.ogg | wc -l)"
```
Expected: `en: 25` and `zh: 25`

- [ ] **Step 2: Delete the files**

```bash
cd /home/joe/project/Exult-for-zh && rm voice/en/0614_*_npc277.ogg voice/zh/0614_*_npc277.ogg
```

- [ ] **Step 3: Rebuild the packed archives**

```bash
cd /home/joe/project/Exult-for-zh && python3 tools/voice_acting/pack_voice.py pack --lang en && python3 tools/voice_acting/pack_voice.py pack --lang zh
```
Expected: each prints `Packed N files ...` with a pak size.

- [ ] **Step 4: Verify no npc277 entries remain in the archives**

```bash
cd /home/joe/project/Exult-for-zh && python3 tools/voice_acting/pack_voice.py verify --lang en && python3 tools/voice_acting/pack_voice.py verify --lang zh
```
Expected: `Verified en: N entries, ... — all OK` and same for zh.

Then confirm no npc277 in the loose dirs or index:

```bash
cd /home/joe/project/Exult-for-zh && echo "loose npc277: $(ls voice/en/ voice/zh/ | grep -c npc277 || true)" && python3 -c "
from pathlib import Path
for lang in ('en','zh'):
    data = Path(f'voice/{lang}_voices.idx').read_bytes()
    print(lang, 'npc277 in idx:', b'npc277' in data)
"
```
Expected: `loose npc277: 0`, `en npc277 in idx: False`, `zh npc277 in idx: False`.

- [ ] **Step 5: Commit**

```bash
cd /home/joe/project/Exult-for-zh && git add -A voice/ && git commit -m "chore(voice): remove Stone Guardian synthesized voice and rebuild packs"
```

---

### Task 8: Full-suite verification

- [ ] **Step 1: Run all Python test files that touch the changed code**

```bash
cd /home/joe/project/Exult-for-zh/tools/voice_acting && .venv/bin/python -m unittest test_generate_qwen3_voice_behavior test_generate_voice_review_html -v
```
Expected: all PASS.

- [ ] **Step 2: Confirm the marker is honored end-to-end with a dry-run**

```bash
cd /home/joe/project/Exult-for-zh/tools/voice_acting && .venv/bin/python generate_qwen3_voice.py --phase voice --lang en --npc "Stone Guardian" --dry-run 2>&1 | tail -10
```
Expected: no Stone Guardian lines in the would-generate output (empty NPC set → `NPC(s) not found: Stone Guardian` or a skip message).

- [ ] **Step 3: Confirm engine still compiles**

```bash
cd /home/joe/project/Exult-for-zh && make audio/VoiceActingManager.o
```
Expected: exit 0.

- [ ] **Step 4: Manual runtime check (documented for the user)**

Start Exult, open a Stone Guardian conversation. Verify:
1. The original game recording plays (no synthesized audio).
2. `<PATCH>/voice_acting/voice_acting_log.csv` records the line with status `original`.
