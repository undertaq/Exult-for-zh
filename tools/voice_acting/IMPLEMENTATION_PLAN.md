# Voice Generation Pipeline: Implementation Plan

## Status: Code complete, pending GPU execution

All code is committed on branch `voice_acting3`.
Repo: `https://github.com/undertaq/Exult-for-zh`

---

## Overview

Generate Chinese (ZH) + English (EN) voice files for all NPC dialogue in Ultima VII:
The Black Gate using Qwen3-TTS. The 3-stage pipeline uses VoiceDesign to create
unique NPC voice identities, then VoiceClone to generate every line with perfect
voice consistency.

### Key Design Decisions

1. **CustomVoice + VoiceClone hybrid** — VoiceDesign creates one reference clip
   per NPC voice identity, then VoiceClone reproduces it consistently across all
   lines. No per-line `tone_instruct` (VoiceClone doesn't support it), but the
   voice character is perfectly stable across every line and both languages.

2. **Simplified Chinese for TTS input** — All Chinese text is converted via
   `zhconv` (Traditional→Simplified) before feeding to the TTS model, producing
   better Mandarin output.

3. **175 voice designs for 266 NPCs** — 159 unique NPCs (major characters,
   companions, special entities) each get their own voice; 109 minor NPCs share
   15 group voices by gender/age/role; UNKNOWN narrator gets 1 neutral voice.

---

## Pipeline Stages

### Stage 0: Environment Setup (One-time)

**Requirements:**
- Python 3.12+
- GPU with 8GB+ VRAM (CUDA)
- ~15GB disk space for model weights (two models: VoiceDesign + Base)
- ffmpeg installed and in PATH

**Install dependencies:**
```bash
pip install -U qwen-tts torch soundfile numpy zhconv
```

Optional (faster): `pip install -U flash-attn --no-build-isolation`

**Model weights** (auto-downloaded on first run via Hugging Face):
- `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` (~4.5GB) — Phase A
- `Qwen/Qwen3-TTS-12Hz-1.7B-Base` (~4.5GB) — Phase B + C

Or pre-download:
```bash
huggingface-cli download Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign --local-dir ./models/VoiceDesign
huggingface-cli download Qwen/Qwen3-TTS-12Hz-1.7B-Base --local-dir ./models/Base
```

### Stage 1: Phase A — Generate Reference Clips (VoiceDesign)

**Command:**
```bash
cd Exult-for-zh/tools/voice_acting
python generate_qwen3_voice.py --phase refs --device cuda:0
```

**What it does:**
- Loads VoiceDesign model
- For each of 175 voice designs, generates:
  - 1 ZH reference clip using `voice_desc_zh` instruct + `ref_zh_text` text
  - 1 EN reference clip using `voice_desc_en` instruct + `ref_en_text` text
- Saves to `refs/{design_id}_{lang}_ref.ogg`
- ~350 small .ogg files total (3-8 seconds each)
- Pre-downloads model weights (first run only)
- Takes ~10-30 minutes depending on GPU

**Output:** `tools/voice_acting/refs/` directory

**Validation:**
```bash
# Count ref files
ls refs/*.ogg | wc -l
# Expected: 350 (175 designs × 2 languages)
```

**If voices sound wrong:**
Edit `npc_voice_designs.json` — adjust `voice_desc_zh` / `voice_desc_en` fields.
Then re-run with `--force-refs`:
```bash
python generate_qwen3_voice.py --phase refs --force-refs
```

### Stage 2: Phase B — Build Clone Prompts

**Command:**
```bash
python generate_qwen3_voice.py --phase prompts --device cuda:0
```

**What it does:**
- Loads Base model (unloads VoiceDesign first)
- For each design, loads ref audio and calls `model.create_voice_clone_prompt()`
- Stores prompts in `clone_prompts.pkl` (pickled dict)
- Takes ~5-10 minutes (mostly model load time)

**Output:** `tools/voice_acting/clone_prompts.pkl`

**If Phase A was re-run:** Delete `clone_prompts.pkl` and re-run Phase B.

### Stage 3: Phase C — Bulk Generate All Voice Files (VoiceClone)

**Command:**
```bash
# Full generation (all NPCs, both languages)
python generate_qwen3_voice.py --phase voice --device cuda:0

# Test with a single NPC first
python generate_qwen3_voice.py --phase voice --npc Iolo --device cuda:0
```

**What it does:**
- Loads Base model (same as Phase B, stays loaded for duration)
- For each NPC:
  - Looks up their voice design ID
  - Retrieves the clone prompt for target language
  - Batches all lines (batch size 8) and calls `generate_voice_clone()`
- ZH output goes to `voice/zh/{func_id}_{offset_key}_{segment}.ogg`
- EN output goes to `voice/en/{func_id}_{offset_key}_{segment}.ogg`

**Estimated time:**
- ~10,245 entries × 2 languages = ~20,490 files
- Batch size 8 → ~2,560 batches
- Each batch ~3-15 seconds → ~2-10 hours total

**Flags:**
- `--npc NAME` — process a single NPC (for testing)
- `--max-npcs N` — process only first N NPCs (incremental)
- `--force` — regenerate existing files; default skips existing

---

## File Reference

| File | Purpose |
|---|---|
| `generate_qwen3_voice.py` **→ RUN THIS** | 3-stage pipeline entry point |
| `npc_voice_designs.json` | 175 voice designs with descriptions + ref texts |
| `bilingual_mapping_review.json` | Source-of-truth: 10,245 mapped dialogue entries |
| `voice_prompt_zh.json` | Chinese voice descriptions (used as reference) |
| `clone_prompts.pkl` | Generated in Phase B, consumed in Phase C |
| `refs/` | Reference clips generated in Phase A |
| `voice/zh/` | Output: ZH .ogg files |
| `voice/en/` | Output: EN .ogg files |

### Helper Scripts

| Script | Purpose |
|---|---|
| `create_voice_designs.py` | Regenerates `npc_voice_designs.json` from `bilingual_mapping_review.json` |
| `audit_npcs.py` | Lists all 266 NPCs with metadata |

---

## NPC Voice Design Architecture

### Unique NPCs (159)
Main companions, 30+ line NPCs, special characters (gargoyles, ghosts, dragons,
elementals, etc.) and notable characters. Each gets their own VoiceDesign
reference clip and clone prompt.

### Group Designs (15)
| Group | NPCs | Type |
|---|---|---|
| `young_male_energetic` | 28 | Young friendly males |
| `middle_male_friendly` | 10 | Warm middle-aged males |
| `middle_male_rough` | 12 | Gruff/angry middle-aged males |
| `middle_male_serious` | 4 | Stern/authoritative males |
| `middle_male_worried` | 5 | Anxious/distracted males |
| `young_female_bright` | 9 | Cheerful young females |
| `young_female_serious` | 6 | Capable/tough young females |
| `young_female_sad` | 4 | Gentle/shy young females |
| `middle_female_firm` | 5 | Capable middle-aged females |
| `middle_female_warm` | 4 | Maternal/nurturing females |
| `middle_female_troubled` | 1 | Weary/distressed females |
| `elderly_male` | 4 | Wise old men |
| `elderly_female` | 2 | Grandmotherly |
| `child` | 4 | Young children |
| `actor_entertainer` | 8 | Performers, musicians |

### Narrator (1)
All UNKNOWN entries (2,590 lines of system/narrator text) use a single neutral
narrator voice.

---

## How to Add/Change a Voice Design

1. Edit `npc_voice_designs.json`:
   - Change `voice_desc_zh` / `voice_desc_en` for the design
   - Or add a new design entry (copy an existing one)
   - Or move an NPC between groups

2. Re-run Phase A with `--force-refs` for that design:
   ```bash
   # All refs
   python generate_qwen3_voice.py --phase refs --force-refs
   # Or just delete the specific ref .ogg files and re-run
   ```

3. Delete `clone_prompts.pkl` and re-run Phase B + C

---

## Voice Design Descriptions

### English voice_desc_en format
Natural language description like:
```
"Male, 40s, friendly shopkeeper, warm and welcoming voice, cheerful,
speaks in standard Mandarin"
```

The instruct describes **voice character** (gender, age, personality, tone
quality). The model generates a unique voice matching this description.

### Chinese voice_desc_zh format
Equivalent in Simplified Chinese, e.g.:
```
"男性，40多歲，熱情好客，個性開朗，用標準的普通話朗讀"
```

This ensures the model produces natural Mandarin prosody.

### Reference Text Selection
Each design has a `ref_zh_text` and `ref_en_text` — a representative line from
one of the NPCs in the group. The reference text should:
- Be 10-80 characters long
- Be typical of the NPC's dialogue style
- Contain natural speech patterns
