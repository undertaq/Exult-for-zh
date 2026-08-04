# Bilingual Mapping Generation Pipeline

This document describes how `bilingual_mapping_review.json` is produced from raw game data. The mapping pairs English (EN) and Chinese (ZH) dialogue lines from Ultima VII's compiled usecode binaries into a unified source-of-truth file consumed by the TTS pipeline and game engine.

## Data Flow Overview

```
usecode.en (compiled EN binary)         usecode.zh (compiled ZH binary)
         │                                        │
         ▼                                        ▼
  disassemble_usecode.py                  disassemble_usecode.py
         │                                        │
         ▼                                        ▼
  en_voice_lines.csv                      zh_voice_lines.csv
         │                                        │
         └────────────────┬───────────────────────┘
                          ▼
             generate_bilingual_mapping.py
                          │
                          ▼
               bilingual_mapping.csv
                          │
                          ▼
          [initial bilingual_mapping_review.json
           created as a one-time data artifact
           with NPC voice designs and tone labels
           added by non-repo tools]
                          │
                          ▼
              fix_alignment_and_tags.py    (re-align + replace game tags)
                          │
                          ▼
              sync_zh_text_from_usecode.py (updated ZH text from usecode.zh)
                          │
                          ▼
              prepare_tts_fields.py        (raw text, archaic fixes, resolution)
                          │
                          ▼
              sync_mapping_voice_prompts.py (voice descriptions from designs)
                          │
                          ▼
              [in-place transforms, in this order]:
              fix_dialogue_quote_balance.py
              translate_missing_zh_text.py       (--direction en2zh, then zh2en)
              fix_voice_acting_issues.py
              split_tilde_segments.py            (LAST — re-indexes all rows)
                          │
                          ▼
              generate_bilingual_map.py    →  voice/bilingual_map.dat
              generate_qwen3_voice.py      →  voice/en/*.ogg, voice/zh/*.ogg
```

## Step-by-Step

### 1. Disassemble Game Binaries

**Script:** `tools/voice_acting/disassemble_usecode.py`

Reads the compiled usecode binary (Ultima VII's bytecode) and extracts every dialogue line:

- Parses the function table from the binary
- For each function, traces `addsi` (push string) + `addsv` (push variable) → `say` sequences
- Detects `show_npc_face`/`remove_npc_face` calls to assign speakers
- Infers speakers for non-NPC functions via call-graph traversal
- Splits `~~`-delimited multi-page lines into separate segments
- Tracks `<PLAYER_NAME>`, `<PRONOUN>`, `<HONORIFIC>`, `<GENDER_FLAG>` placeholders

Input: compiled `usecode` binary (EN or ZH)\
Output: `voice_lines.csv` with columns `func_id`, `npc`, `speaker`, `caller_guess`, `offset_key`, `segment`, `total_segments`, `has_var`, `text`

```bash
python disassemble_usecode.py usecode.en --all --format csv > en_voice_lines.csv
python disassemble_usecode.py usecode.zh --all --format csv > zh_voice_lines.csv
```

### 2. Generate Initial Bilingual CSV

**Script:** `tools/voice_acting/generate_bilingual_mapping.py`

Pairs EN and ZH voice lines by matching order within each function:

- Groups entries by `func_id` then by `offset_key`
- Pairs EN and ZH groups **by sequential order** (1st group ↔ 1st group, etc.)
- For functions with matching group counts: marks all pairs `order_based`
- For mismatched functions: computes a similarity score using:
  - Length ratio heuristic (EN:ZH ~ 1:2.8)
  - Shared Latin words (proper nouns like "Avatar", "Iolo")
  - `<VAR>` presence match
  - Quote-style match (`"` vs `「」`)
- Labels pairs `high`/`medium`/`low` based on score thresholds
- Extra unpaired segments → `unpaired_en` / `unpaired_zh`

```bash
python generate_bilingual_mapping.py \
    --en en_voice_lines.csv --zh zh_voice_lines.csv \
    -o bilingual_mapping.csv
```

Output columns: `func_id`, `npc`, `en_offset_key`, `en_segment`, `en_text`, `zh_offset_key`, `zh_segment`, `zh_text`, `confidence`

### 3. One-Time Data Import → JSON

The initial `bilingual_mapping_review.json` was created as a **one-time data artifact** (not via a preserved script). The CSV rows were enriched with:

| Field | Source |
|-------|--------|
| `index` | Sequential row number |
| `zh_func_id`, `en_func_id` | Copied from `func_id` (initially same for EN and ZH) |
| `voice_gender`, `voice_age` | NPC voice profiles (from `npc_voice_designs.json`, 275 designs, assigned manually/per-NPC logic) |
| `voice_prompt`, `voice_prompt_zh` | English/Chinese voice description per NPC |
| `voice_lang` | Default `"en"` |
| `tone`, `tone_instruct` | Per-entry tone classification (neutral, angry, sad, etc.) |
| `zh_raw`, `en_raw` | Raw text pre-tag-replacement |

These enrichments were done with external scripts/tools not preserved in the repo. The JSON format became the canonical source of truth going forward; all subsequent pipeline steps operate on it in-place.

### 4. Re-alignment and Tag Replacement

**Script:** `tools/voice_acting/fix_alignment_and_tags.py`

The most critical transformation. Re-reads the original EN/ZH CSVs and:

- **Rebuilds alignment from scratch** using Needleman-Wunsch global sequence alignment for functions with mismatched group counts — more accurate than the simple sequential pairing in step 2
- **Replaces game tags** in `en_text` and `zh_text` with TTS-friendly text:
  - `<PLAYER_NAME>` → `"Avatar"` / `"聖者"`
  - `<HONORIFIC>` → `"milord"` / `"大人"`
  - `<PRONOUN>` → `"he"`/`"him"` / `"他"` (context-dependent)
  - `<GENDER_FLAG>` → `"man's"` / `"男性"` (gender-dependent)
  - `<VAR>` → classifier: `player_name`, `npc_name`, `number`, `title`
  - Stores pre-replacement text in `en_text_raw`, `zh_text_raw` and the `<VAR>` class in `var_class`
- **Preserves review fields** by matching entries on `(npc, zh_offset_key, zh_segment, en_offset_key, en_segment, zh_func_id, en_func_id)` from the existing JSON
- **Emits overflow segments** instead of dropping them: when EN/ZH group sizes differ, the surplus rows that previously fell outside the `min()` truncation window are now emitted as `unpaired_en` / `unpaired_zh` entries (26 EN + 5 ZH segments were silently lost before this fix)
- **Deduplicates duplicate source rows**: the ZH CSV can contain the same `(func_id, offset_key, segment)` multiple times with identical text (e.g. `0x04AC/74f` appears 3×). The overflow loop tracks already-emitted keys (`emitted_en` / `emitted_zh`) and skips re-emission. Verified safe: 0 of 1,347 duplicate `(func, offset)` groups share a segment with differing texts
- Writes output as `bilingual_mapping_fixed.json` (manually re-copied to replace the original); this is the cleanest pipeline checkpoint (`fixed.json`)

```bash
python fix_alignment_and_tags.py \
    --en en_voice_lines.csv --zh zh_voice_lines.csv \
    -i bilingual_mapping_review.json \
    -o bilingual_mapping_fixed.json
```

### 5. ZH Text Sync from Modified usecode.zh

**Script:** `tools/voice_acting/sync_zh_text_from_usecode.py`

Extracts updated ZH text from the modified `usecode.zh` binary (the ZH localization was iterated on after the initial disassembly) and overwrites `zh_text`/`zh_text_raw` for the matched rows.

- Runs against the compiled `usecode.zh` and the existing JSON mapping
- Must run **before** `prepare_tts_fields.py` — running it afterward would re-inject raw `<VAR>`/`<PLAYER_NAME>`/`<HONORIFIC>` tags into `zh_text` after they have been replaced (leftover-tag count would jump from 0 to ~918)

```bash
python sync_zh_text_from_usecode.py \
    --usecode-zh usecode.zh \
    --mapping bilingual_mapping_review.json \
    --apply
```

### 6. TTS Field Preparation

**Script:** `tools/voice_acting/prepare_tts_fields.py`

In-place update to the JSON that prepares text for TTS consumption. **Must run AFTER `sync_zh_text_from_usecode.py`** — running the sync afterward would re-inject raw `<VAR>`/`<PLAYER_NAME>`/`<HONORIFIC>` tags into `zh_text` after they have been replaced.

- Populates `en_raw` from the authoritative EN CSV (pre-tag-replacement source)
- Copies `zh_text` → `zh_raw` as fallback
- Re-resolves all `<VAR>` tags by re-disassembling the EN usecode binary to trace what each variable resolves to at runtime
- Fixes archaic English: `'Tis` → `"It is"`, `'em` → `"them"`, `ma'am` → `"madam"`, plus archaic verb/pronoun normalization
- Normalizes whitespace (CJK spacing, punctuation spacing)
- Fixes counter-word collisions in ZH: `一些枚` → `一些`
- Balances `「」` (ZH) and `"` (EN) delimiters
- Collapses duplicate replacement words: `"the Avatar, Avatar!"` → `"the Avatar"`

### 7. Voice Prompt Sync

**Script:** `tools/voice_acting/sync_mapping_voice_prompts.py`

Syncs voice descriptions from NPC voice designs into the mapping:

- Reads `npc_voice_designs.json` (275 voice designs with `voice_desc_en`/`voice_desc_zh`)
- Copies per-NPC descriptions into `voice_prompt` and `voice_prompt_zh` for every row
- Handles special cases: Avatar, UNKNOWN, narrator gender

### 8. In-Place Transformations

Various scripts modify the JSON directly for targeted fixes. **Run in this order** (`split_tilde_segments.py` last — it re-indexes all rows):

| Script | Purpose |
|--------|---------|
| `fix_dialogue_quote_balance.py` | Fixes unbalanced `"` / `「」` in all entries |
| `translate_missing_zh_text.py` | Uses LLM to translate entries with missing `zh_text` or `en_text` (`--direction en2zh` / `zh2en`). **Cache-only by default**: the translation cache is keyed by prompt version; the on-disk cache was built with an older `PROMPT_VERSION`, so cache entries are matched by `source` text rather than `cache_key`. The cache was built with model `qwen3.6:27b` — pass `--model qwen3.6:27b` or cache hits are missed. Known caveats: 4 stale zh→en cache records contain `<PLACEHOLDER>` garbage and are rejected; entries absent from the cache remain untranslated (live-LLM runs in the original data filled them non-deterministically). Verified run: 128 en2zh selected / 104 accepted / 24 rejected; 43 zh2en selected / 41 accepted / 2 rejected. Ollama requests can take >600s; the `--timeout` default is 900s, and the opencode tool default of 120s is too short — always run with a larger timeout |
| `fix_voice_acting_issues.py` | Manual patches for specific problem entries (Anmanivas, Dracothraxus, Zorn). Targets are matched by content (`npc` + `en_offset_key` + old `zh_text`), NOT hardcoded index — the index layout shifts whenever alignment changes |
| `split_tilde_segments.py` | Splits `~`-delimited lines into separate segment rows (**LAST** — re-indexes all rows). Merges instead of duplicating: when a split target segment (>0) already exists as an `unpaired_en` overflow row (identified by empty `zh_func_id`), the ZH part is merged into that row rather than creating a duplicate key. 37 splits produced 17 new rows with zero duplicate keys |

### 9. Downstream Consumers

The final `bilingual_mapping_review.json` feeds two main pipelines:

**Runtime binary** (`generate_bilingual_map.py`):
- Reads the JSON, filters to entries with valid text + runtime keys
- Writes `voice/bilingual_map.dat` (binary `BLM2` format)
- Deployed to game patch directory by `tools/generate_all.sh`

**Voice generation** (`generate_qwen3_voice.py`):
- Reads the JSON for dialogue entries grouped by NPC
- Generates `.ogg` audio files via Qwen3-TTS
- Orchestrated by `run_phase_c.sh`, `run_fast.sh`, etc.

## Historical Steps (do NOT run)

### Function ID Correction — REMOVED (obsolete)

**Historical scripts:** `tools/fix_func_ids.py`, `tools/fix_func_ids_part2.py` (do NOT run)

This step no longer exists in the pipeline. It was removed because:

- The current reference (`bilingual_mapping_review.json`) has **zero** rows with `en_func_id != zh_func_id`, and `offset_mapping.csv` likewise has zero differing EN/ZH func_ids — the alignment from step 4 already carries the correct func_ids. There is nothing to correct.
- Running the scripts today **destroys data**: `fix_func_ids.py` collapses ~164 rows onto `0x06FA/0/0` via its last-row-wins `lookup_exact[(0,0,0,0)]` match (creates 452 duplicate rows), and `fix_func_ids_part2.py`'s first-occurrence text lookup collapses all 37 "Done!" rows onto `0x0475/6c0` (creates 634 duplicate rows). The reference has only 3 duplicate keys total (`0x0450/1fe` en, `0x0401/b4_139_1f3` seg 0+1 zh).
- The scripts also hardcode real repo paths and rename `.ogg` files on disk.

The historical `offset_mapping.csv` func_id table (from `tools/voice_acting/generate_offset_mapping.py`) is retained as a reference artifact only.

### Egg Dialog Patching — SUPERSEDED

`patch_missing_egg_dialog.py` was a one-time manual injection of egg-triggered dialog (func `0x06FA`). The disassembler now emits egg dialog natively under func `0x0903` with compound offset keys (e.g. `0_7`, `38_7`). Do NOT re-run it — it also rewrites `offset_mapping.csv` (it wrote through the sandbox symlink into the live repo file). Legacy `0x06FA` rows and redundant `0x0903` segment-9 variants must be deduped, keeping only the two canonical egg rows (`0x0903/0_7/0_9` and `0x0903/38_7/38_9`).

## JSON Entry Format

The final file contains ~8900–9000 entries, each with these fields:

```json
{
  "index": 1,
  "npc": "Erethian",
  "zh_offset_key": "88",
  "zh_segment": 0,
  "zh_text": "「我不會再跟你說話了，聖者！」他無視了你。",
  "en_offset_key": "81",
  "en_segment": 0,
  "en_text": "\"I'll speak to you no more, Avatar!\" He ignores you.",
  "confidence": "high",
  "zh_func_id": "0x009A",
  "en_func_id": "0x009A",
  "voice_gender": "male",
  "voice_age": "elderly",
  "voice_prompt": "Gender: male. Age: fifties. Role: blind mage scholar. ...",
  "voice_lang": "en",
  "tone": "neutral",
  "tone_instruct": "",
  "voice_prompt_zh": "性别：男性。年龄：五十多岁。...",
  "en_raw": "\"I'll speak to thee no more, Avatar!\" He ignores you.",
  "zh_raw": "「我不會再跟你說話了，聖者！」他無視了你。",
  "en_text_raw": "\"I'll speak to <VAR> no more, Avatar!\" He ignores you.",
  "zh_text_raw": "「我不會再跟<VAR>說話了，聖者！」他無視了你。",
  "var_class": "player_name"
}
```

## Key Design Properties

- **The JSON is the source of truth.** All pipeline scripts read and modify it in-place; none regenerate it from scratch.
- **Identity is by runtime keys**, not text: `(func_id, offset_key, segment)` uniquely identifies a dialogue line.
- **EN and ZH usecode use the same func_ids** for equivalent conversations in the current data — no func_id correction step is needed (the historical `fix_func_ids*.py` step was removed; see "Historical Steps").
- **Tag replacement is lossy** — raw pre-replacement text is preserved in `en_raw`/`zh_raw` and `en_text_raw`/`zh_text_raw`.
