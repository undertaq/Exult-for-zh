# Voice File Generation

This document describes how the actual EN and ZH voice `.ogg` files are generated from the bilingual mapping and reference voice clips. This is a 3-stage pipeline (Phases A/B/C) implemented in `generate_qwen3_voice.py`, using **Qwen3-TTS** models for voice cloning.

## Pipeline Overview

```
npc_voice_designs.json  ──┐
                          │
bilingual_mapping_review.json ──┐
                               │
                               ▼
              ┌─────────────────────────────────────┐
PHASE A       │  Generate Reference Clips           │
              │  (VoiceDesign model)                 │
              │  → refs/{id}_{lang}_ref.ogg          │
              └──────────────────┬──────────────────┘
                                 │
              ┌──────────────────▼──────────────────┐
PHASE B       │  Build Clone Prompts                │
              │  (Base model)                       │
              │  → clone_prompts.pkl                 │
              └──────────────────┬──────────────────┘
                                 │
              ┌──────────────────▼──────────────────┐
PHASE C       │  Bulk Generate Voice Files          │
              │  (Base model + clone prompts)        │
              │  → voice/zh/*.ogg (13k files)        │
              │  → voice/en/*.ogg (13k files)        │
              └─────────────────────────────────────┘
```

## Prerequisites

### Hardware

- CUDA GPU with 8 GB+ VRAM (12 GB+ recommended for Phase C bulk runs)
- ~10 GB free disk space for generated audio

### Software

```bash
pip install -U qwen-tts torch soundfile numpy zhconv
# Optional but recommended for speed:
pip install flash-attn
```

The models auto-download from Hugging Face on first use:

| Model | Size | Used In |
|-------|------|---------|
| `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` | ~4.5 GB | Phase A only |
| `Qwen/Qwen3-TTS-12Hz-1.7B-Base` | ~4.5 GB | Phases B + C |

### Input Files

| File | Required By | Description |
|------|-------------|-------------|
| `tools/voice_acting/npc_voice_designs.json` | All phases | 268 NPC voice designs with descriptions and reference texts |
| `tools/voice_acting/bilingual_mapping_review.json` | Phase C | ~10,245 dialogue entries with text, runtime keys, NPC assignments |
| `tools/voice_acting/refs/{id}_{lang}_ref.ogg` | Phase B | Reference clips (output of Phase A) |
| `tools/voice_acting/npc_data.py` | Phase C | NPC name ↔ NPC number mapping |

## Phase A: Generate Reference Clips

See [Reference Voice File Generation](reference_voice_generation.md) for the detailed reference clip workflow. Summarized:

```bash
cd tools/voice_acting
python generate_qwen3_voice.py --phase refs --device cuda:0
```

Generates `refs/{design_id}_{lang}_ref.ogg` for every design in `npc_voice_designs.json`. Uses the **VoiceDesign** model to synthesize audio from text descriptions.

Skip if references already exist — pass `--force-refs` to regenerate.

## Phase B: Build Clone Prompts

**Script:** `tools/voice_acting/generate_qwen3_voice.py` — Phase B

Converts reference clips into voice clone prompt vectors that the Base model uses for voice cloning.

### Run

```bash
cd tools/voice_acting
python generate_qwen3_voice.py --phase prompts --device cuda:0
```

### What it does

1. Loads the **Base** model (`Qwen3-TTS-12Hz-1.7B-Base`)
2. For each design in `npc_voice_designs.json`:
   a. Loads `refs/{design_id}_zh_ref.ogg` and its reference text from the design
   b. Calls `model.create_voice_clone_prompt(ref_audio, ref_text)` to produce a prompt tensor for ZH
   c. Same for EN: `refs/{design_id}_en_ref.ogg`
3. Stores all prompts as a pickled dictionary:
   ```python
   { design_id: {'zh': prompt_data, 'en': prompt_data}, ... }
   ```
4. Writes to `tools/voice_acting/clone_prompts.pkl`

### Key details

- The clone prompt is a model-internal vector representation of the voice characteristics extracted from the reference audio + text pair
- This is a fast step (seconds per design, ~5 minutes total for 268 designs)
- The Base model is shared across Phases B and C — it stays loaded between calls

### Key parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--device` | `cuda:0` | GPU device |
| `--design-json` | `npc_voice_designs.json` | Voice designs |
| `--refs-dir` | `refs/` | Directory with reference clips |
| `--prompts-output` | `clone_prompts.pkl` | Output pickle file |

### Verification

The script prints a summary of how many designs were processed and which languages:
```
Processing 268 designs for clone prompts...
  ZH prompts: 268 (all complete)
  EN prompts: 268 (all complete)
```

## Phase C: Bulk Generate Voice Files

**Script:** `tools/voice_acting/generate_qwen3_voice.py` — Phase C

This is the heavy step — it generates all ~26,000 `.ogg` voice files (ZH + EN) from the bilingual mapping.

### Run

```bash
cd tools/voice_acting

# Full generation (all NPCs, both languages):
python generate_qwen3_voice.py --phase voice --device cuda:0

# Single NPC for testing:
python generate_qwen3_voice.py --phase voice --npc Iolo --device cuda:0

# Single language:
python generate_qwen3_voice.py --phase voice --lang zh --device cuda:0
```

### What it does

1. Loads the **Base** model (the same one from Phase B; kept in memory)
2. Loads `clone_prompts.pkl` to get prompt vectors for each design
3. Reads `bilingual_mapping_review.json` to get all dialogue entries
4. Groups entries by NPC name, then for each NPC:
   a. Looks up the NPC's design ID and its ZH/EN clone prompts
   b. For **single-part** dialogue: calls once
   c. For **multi-part** dialogue (narrator + speaker mixed in one line): splits by `「」` or `""` delimiters, generates each part separately with different prompts, then fade-splices them together
5. Writes each line to `voice/{lang}/{filename}.ogg`

### Output File Naming

```
voice/zh/{func_id}_{offset_key}_{segment}.ogg
voice/en/{func_id}_{offset_key}_{segment}.ogg
```

For NPC-specific variants (shared dialogue spoken by multiple NPCs):

```
voice/zh/{func_id}_{offset_key}_{segment}_npc{N}.ogg
voice/en/{func_id}_{offset_key}_{segment}_npc{N}.ogg
```

Where `N` is the NPC number from Exult's NPC table (e.g., Iolo=1, Dupre=4).

A generic fallback copy is also created: `{base}.ogg` so the engine can fall back if NPC-specific lookup fails.

Avatar gender variants use `_avatar_male` / `_avatar_female` suffixes.

### Multi-Part Dialogue Handling

When text contains both narration and speech (detected by `「」` in ZH or `""` in EN), the line is split into parts:

```python
# Example: mixed narrator + speaker text
zh_text = "「我不會再跟你說話了！」他無視了你。"
# → narrator part: "他無視了你。" (uses narrator prompt)
# → speaker part: "我不會再跟你說話了！" (uses NPC's own prompt)
```

Each part is generated separately with the appropriate prompt, then spliced with:
- 280 ms gap between parts
- 30 ms crossfade at splice boundaries

### Deterministic Generation

All generation uses a fixed seed (`TTS_SEED = 20240718`) via `torch.Generator`:

```python
generator = torch.Generator(device=device).manual_seed(TTS_SEED)
```

This ensures consistent pronunciation for the same NPC across runs.

### Key parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--device` | `cuda:0` | GPU device |
| `--npc` | (all) | Generate for a specific NPC only |
| `--lang` | (both) | `zh` or `en` to limit to one language |
| `--mapping` | `bilingual_mapping_review.json` | Source mapping |
| `--prompts` | `clone_prompts.pkl` | Pre-built clone prompts |
| `--design-json` | `npc_voice_designs.json` | Voice designs |
| `--output-dir` | `voice/` | Output directory root |
| `--max-lines` | (unlimited) | Max lines to generate (for testing) |

### Runner Scripts (Production Stability)

Phase C is the longest step (~hours on a single GPU). CUDA stability issues with sustained runs are handled by wrapper scripts:

| Script | Strategy | Use Case |
|--------|----------|----------|
| `run_fast.sh` | Loops `--phase voice --lang X` with 900s timeout until all files exist | Fast iterative fill |
| `run_phase_c.sh` | Batches NPCs in groups of 5, ZH then EN, 600s timeout | Balanced throughput |
| `run_phase_c_batches.sh` | Batches of 3 NPCs with 600s timeout, retries individually on failure | Most robust |
| `run_phase_c_batch.sh [start] [size]` | Manual slice of sorted NPC list | Targeted re-generation |
| `generate_all_npcs.sh` | One NPC at a time, 600s timeout each | Debugging specific NPCs |
| `run_voice_regen_multigpu.py --gpus 0,1` | Shards ZH/EN across GPUs | Fastest with multiple GPUs |

Example usage:
```bash
# Fill in missing files iteratively:
cd tools/voice_acting
./run_fast.sh

# Batched for reliability:
./run_phase_c_batches.sh

# Multi-GPU:
python run_voice_regen_multigpu.py --gpus 0,1
```

### Phase C Progress

The script prints a progress summary after Phase C completes:

```
ZH: 13308 files | <50K:small 50-150K:mid >150K:large
EN: 13319 files | <50K:small 50-150K:mid >150K:large
```

## Post-Generation: Missing Voice Auditing

After Phase C, check for any missing files:

```bash
# Generate only missing EN files:
python generate_missing_en_voices.py

# Generate only missing files for both languages:
python generate_missing_voices_only.py
```

These scripts audit `bilingual_mapping_review.json` against the actual files on disk and re-generate only what's missing.

## Packaging for Runtime

### Pack into .pak/.idx

```bash
cd tools/voice_acting
python pack_voice.py pack --lang zh   # → voice/zh_voices.pak + voice/zh_voices.idx
python pack_voice.py pack --lang en   # → voice/en_voices.pak + voice/en_voices.idx
```

The `.pak` file is a simple concatenation of OGG data. The `.idx` file uses binary format (`VAIX` magic) with `(name, offset, size)` entries for random access.

### Sync to Exult Patch Directory

```bash
python sync_voice_output_to_patch.py
```

This reads `exult.cfg` to find the game's patch path and copies generated `.ogg` files there.

## Complete One-Shot Pipeline

The `tools/generate_all.sh` script ties together the bilingual map generation and voice pipeline. For voice files specifically, the manual sequence is:

```bash
cd tools/voice_acting

# 1. Phase A: References (one-time per design)
python generate_qwen3_voice.py --phase refs --device cuda:0

# 2. Phase B: Clone prompts (one-time per reference change)
python generate_qwen3_voice.py --phase prompts --device cuda:0

# 3. Phase C: Bulk generation (can be partial / resumed)
./run_phase_c_batches.sh

# 4. Fill any gaps
python generate_missing_voices_only.py

# 5. Pack for distribution
python pack_voice.py pack --lang zh
python pack_voice.py pack --lang en
```
