# Plan: Fix wrong-voice-line bug (stale usecode offsets) + reapply patching

## Root cause (PROVEN)
The game names each voice file from the **current runtime usecode `addsi` offset**
(`usecode/ucinternal.cc:633-649`). The mapping / `bilingual_map.dat` / generated
filenames were built (Jun 26) by disassembling an **older `usecode.zh`**.
The live ZH usecode was **recompiled after Jun 26**, shifting `addsi` offsets.

Proof (user console + file content):
- "職業" -> ZH text "喔，當然是和傳說中…" now lives at runtime offset **`86d`**
  (console: `Checking: ...\zh\0401_86d_0_npc1.ogg - FOUND`).
- `bilingual_mapping_review.json` still records that line at stale offset **`71c`**.
- `zh/0401_71c_0_npc1.ogg` = correct "喔，當然是…" (never requested).
- `zh/0401_86d_0_npc1.ogg` = idx258 "Ugly, is it not?…" (what actually plays).
- `generate_offset_mapping.py:22` pairs EN<->ZH **positionally**, so any
  insertion/deletion in the recompiled usecode shifts ALL subsequent pairings.

Breaks in BOTH zh/zh and zh/en modes (the offset is wrong regardless of
`voice_language`). `.dat` structure is fine; its **offset keys are stale**.

## Correct existing scripts (found via git history)
- `tools/voice_acting/generate_offset_mapping.py` — rebuilds authoritative
  `offset_mapping.csv` from fresh EN+ZH disassemblies (positional pairing).
- `tools/fix_func_ids.py` — canonical **sync-JSON-from-CSV + rename `.ogg`
  files** script. Loads `offset_mapping.csv` as authoritative, corrects each
  JSON entry's `en_func_id`/`zh_func_id` from the CSV, **renames the actual
  `.ogg` files** to match, writes corrected JSON. (Commit `5336fd03d`.)
- `tools/fix_alignment_and_tags.py` — the `'Twould`->`It would`,
  `'Tis`->`It is`, tag-replacement normalization (user's patching requirement).
- `tools/voice_acting/generate_bilingual_map.py` — rebuilds `bilingual_map.dat`
  from corrected JSON.
- `tools/voice_acting/disassemble_usecode.py` — disassembles a usecode binary
  to EN/ZH CSV.

## User decisions
- Q1: EN usecode = `../Ultima_7/STATIC/usecode`
- Q2: run disassembly **in this repo**
- Q3: **rename** existing files (offset realignment)
- Patching to reapply on JSON rebuild: `npc` non-empty; `zh_text`/`en_text`
  non-empty; `'Twould`->`It would`, `'Tis`->`It is`, … (so TTS speaks
  correctly).

## Steps (verify each)

### Step 1 — Copy live binaries into repo
Copy `../Ultima_7/patch/usecode.zh` -> `tools/voice_acting/_live/usecode.zh`
and `../Ultima_7/STATIC/usecode` -> `tools/voice_acting/_live/usecode.en`.
VERIFY: both files exist and are non-empty.

### Step 2 — Re-disassemble both (current binaries)
`python tools/voice_acting/disassemble_usecode.py _live/usecode.en --all --format csv -o _live/en.csv`
`python tools/voice_acting/disassemble_usecode.py _live/usecode.zh --all --format csv -o _live/zh.csv`
VERIFY: both CSVs generated; func 0x401 present in zh.csv;
offset `86d` present for the "喔，當然是" string in zh.csv.

### Step 3 — Rebuild authoritative offset_mapping.csv
`python tools/voice_acting/generate_offset_mapping.py --en _live/en.csv --zh _live/zh.csv -o tools/voice_acting/offset_mapping.csv`
Add a DRIFT GUARD: if `len(en_groups) != len(zh_groups)` for a func,
or a func's offset set changed vs the old CSV, flag for review (don't blind-pair).
VERIFY: diff old vs new offset_mapping.csv for func 0x401 —
confirm "喔，當然是" now at `86d` (was `71c`).

### Step 4 — Sync JSON + rename .ogg files (extend fix_func_ids.py)
Extend `tools/fix_func_ids.py` pattern to ALSO correct
`en_offset_key`/`zh_offset_key` (not just func_id), and rename `.ogg` files
for offset_key changes too (existing rename logic at lines 111-148 already
handles func_id; mirror for offset_key). Dry-run first.
VERIFY: `zh/0401_86d_0_npc1.ogg` now contains "喔，當然是…"
(renamed from `zh/0401_71c_0_npc1.ogg`); `zh/0401_71c` gone or
reassigned correctly.

### Step 5 — Reapply patching to JSON
- `npc` non-empty: fill from `func_id` via `npc_data.get_npc_name_by_func`.
- `zh_text`/`en_text` non-empty: enforce.
- Archaic normalization `'Twould`->`It would`, `'Tis`->`It is`, …
  via `tools/fix_alignment_and_tags.py` on `en_text`.
VERIFY: spot-check NPCs non-empty; `'Twould`/`'Tis` absent from `en_text`.

### Step 6 — Regenerate normalized subset (Track B)
For entries whose `en_text` STILL contains `'Twould`/`'Tis`/etc. (or
other normalization triggers), regenerate audio with the per-line fix
(commit `7d9ea24de`) from normalized text. (Small subset; rename alone
leaves un-normalized audio.)
VERIFY: regenerated files' DESCRIPTION matches normalized text.

### Step 7 — Rebuild bilingual_map.dat
`python tools/voice_acting/generate_bilingual_map.py`
VERIFY: `voice/bilingual_map.dat` regenerated; `0401/86d`<->`0401/9a6`
pair present.

### Step 8 — Verify in-game
"職業" -> ZH text "喔，當然是…" now plays `zh/0401_86d` = correct line
(currently plays "Ugly…"). Check `voice_acting_log.csv`:
`offset_key` matches displayed line's func/offset, `status=played`.

## Notes
- No `.dat` format change — only offset re-derivation + realignment.
- Only new code is the offset_key extension in Step 4; everything else reuses
  proven scripts.
- Run disassembly/rename in this repo (Q2); dry-run rename first.
