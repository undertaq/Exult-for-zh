# Reference Voice File Generation

This document describes how reference voice clips are generated for NPC voice designs. Reference clips define the voice identity for each NPC — they are short `.ogg` audio samples (~3–8 seconds) that the TTS pipeline uses as the basis for voice cloning.

## Overview

Each NPC is assigned a **voice design** (stored in `npc_voice_designs.json`) that contains:

- `voice_desc_en` / `voice_desc_zh` — text descriptions of the voice (e.g., "A warm, inviting, and slightly adventurous male voice in his early 30s")
- `ref_en_text` / `ref_zh_text` — sample dialogue text used to generate the reference clip

The reference clip is the audio that results from reading the reference text in the described voice. These clips are consumed in Phase B to build voice clone prompt vectors.

## Voice Design Generation

**Script:** `tools/voice_acting/create_voice_designs.py`

Before reference clips can be generated, NPC voice designs must be created. The design file `npc_voice_designs.json` is generated from `bilingual_mapping_review.json`.

### Run

```bash
cd tools/voice_acting
python create_voice_designs.py
```

### Source of Tone and Personality

The tone and personality of an NPC's voice originates from `bilingual_mapping_review.json`. Each mapping entry carries raw fields inherited from the disassembly and curation pipeline:

| Source Field | Origin | Example |
|--------------|--------|---------|
| `voice_gender` | Assigned during initial JSON creation from NPC profile data | `"male"`, `"female"` |
| `voice_age` | Assigned from NPC profile data | `"young"`, `"middle"`, `"elderly"`, `"20s-30s"` |
| `voice_prompt` | English voice description (textual prompt for TTS) | `"A warm, inviting, and slightly adventurous male voice in his early 30s, with a friendly merchant's charm"` |
| `voice_prompt_zh` | Chinese translation of the voice description | `"男性，20-30歲，年輕開朗，溫暖友善，充滿活力"` |

These fields are set once per NPC (all entries for the same NPC share the same values via `bilingual_mapping_review.json`). They are the **sole source of voice identity** — the design system has no separate NPC profile database.

### Design Generation Logic

#### Step 1: Load and Aggregate Mapping Data

The script loads `bilingual_mapping_review.json` and groups all ~10,245 entries by NPC name. For each NPC, it reads:

- `voice_gender`, `voice_age` from the first entry (all entries for an NPC are consistent)
- `voice_prompt` (EN description) directly as-is
- `voice_prompt_zh` by looking up the EN prompt string as key in `voice_prompt_zh.json` (with fuzzy fallback: if the EN prompt is a substring of a key or vice versa, the match succeeds)

If `voice_prompt_zh` lookup fails entirely, a fallback translation is generated: `"男性" / "女性" / "中性"` plus `"用標準的普通話朗讀"`.

#### Step 2: Classification — Unique vs Group

NPCs are classified by three criteria:

**a) Dialogue volume** — NPCs with ≥28 lines get a unique design on the theory that major characters need distinct voices.

**b) Narrative importance** — hardcoded sets:
- Main companions: Iolo, Shamino, Dupre, Jaana, Spark, Sentri, Trellek, Julia, Katrina, Petre, Tseramed, Battles, Mariah
- Notable NPCs: Lord British, Batlin, Nystul, Chuckles, Nicodemus, Rudyom, Lord Heather, Mariah, Margareta, Avatar, Dell, Geoffrey, Hook, Time Lord, Stone Guardian, Dracothraxus, Adjhar, Dark Core, Erethian, Ferryman

**c) Keyword detection** — NPCs whose `voice_prompt` contains special keywords (gargoyle, ghost, dragon, hydra, troll, cyclops, ape, rat, horse, fox, unicorn, elemental, will-o-wisp, shrine, fairy) get unique designs regardless of line count.

The UNKNOWN (narrator) always gets a unique design.

**Remaining NPCs** are assigned to group designs by personality bucket. The bucket classifier works by matching `(gender, age, prompt_keyword)` against 15 pre-defined buckets:

| Bucket | Gender | Age | Personality Keywords |
|--------|--------|-----|---------------------|
| `young_male_energetic` | male | young/teen/child/20s/20s-30s/teen-20s | (age-based, any keyword) |
| `middle_male_friendly` | male | middle/30s/30s-40s/40s/40s-50s | friendly, warm, cheerful, kind, nice, gentle, happy, calm, peaceful, polite, wandering monk |
| `middle_male_serious` | male | middle/30s-50s | serious, stern, firm, gruff, strict, tough, focused, professional, dignified, broad-shouldered, confident, strong proud, authoritative |
| `middle_male_rough` | male | middle/30s-50s | rough, gruff, angry, bitter, hostile, mean, suspicious, annoyed, booming, thunderous, loud, sullen, gloomy, resentful, displeased, disapproving |
| `middle_male_worried` | male | middle/30s-50s | worried, anxious, concerned, distracted, nervous, fearful, grumpy, irritated, tired, weary |
| `middle_male_mischievous` | male | middle/30s-50s | prankster, mischievous, con artist, sly, playful, smiling, lively, theatrical |
| `elderly_male` | male | elderly/old/aged | (age-based, any keyword) |
| `young_female_bright` | female | young/20s/20s-30s/adult | cheerful, bright, sweet, warm, friendly, polite, happy, lively, welcoming, nice, kind |
| `young_female_serious` | female | young/20s-30s/adult | serious, stern, cold, tough, fierce, sly, husky, hushed, focused, wry, sneaky, wicked, confident, capable, firm, strong, muscular |
| `young_female_sad` | female | young/20s-30s | sad, shy, soft, quiet, gentle, melancholy, delicate, worried, concerned, anxious, nervous, distracted, preoccupied, thoughtful |
| `young_female_exotic` | female | young/20s-30s | exotic, mysterious, gypsy, deep, formal, dreamy, confused, sleepy |
| `middle_female_warm` | female | middle/30s-50s | warm, kind, friendly, gentle, sweet, caring, motherly, musical, noblewoman, refined, curtsy |
| `middle_female_firm` | female | middle/30s-50s | stern, cold, tough, efficient, icy, strong, proud, flat, worried, anxious, concerned, nervous, warm apologetic |
| `middle_female_troubled` | female | middle/30s-50s | sad, grief, pleading, desperate, tearful, tired, annoyed, overworked |
| `elderly_female` | female | elderly/old/aged | (age-based, any keyword) |
| `actor_entertainer` | any | any | actor, actress, performer, musician, theatrical, bard, juggler |
| `child` | any | child/toddler/baby | (age-based, any keyword) |

Unmatched NPCs fall into `group_other` with a neutral catch-all description.

**Current state:** All NPCs qualified for unique designs (the grouping logic was consolidated, producing 268 unique / 0 group designs), so the bucket system is inactive but structurally preserved.

#### Step 3: Design Output Structure

Each design contains:

```json
{
  "npc_iolo": {
    "npc": "Iolo",
    "type": "unique",
    "npcs": ["Iolo"],
    "voice_desc_en": "A warm friendly male voice, middle-aged, with a cheerful and slightly mischievous tone",
    "voice_desc_zh": "男性，中年，溫暖友善的聲音，帶有愉快且略帶頑皮的語氣",
    "ref_zh_text": "聖者，好久不見。",
    "ref_en_text": "Avatar, it's good to see you."
  }
}
```

The key fields for TTS are:
- **`voice_desc_en` / `voice_desc_zh`** — free-form text descriptions that the VoiceDesign model uses as its `instruct` parameter. These encode the entire tone/personality: gender, age, personality traits, speaking style, emotional quality.
- **`ref_zh_text` / `ref_en_text`** — sample dialogue lines used as the text content of the reference clip. These are extracted from the NPC's actual dialogue in the mapping (first suitable line, 5–100 chars, with delimiters stripped).

### Input files

| File | Purpose |
|------|---------|
| `bilingual_mapping_review.json` | Source mapping: NPC names, `voice_gender`, `voice_age`, `voice_prompt`, `voice_prompt_zh`, dialogue text |
| `voice_prompt_zh.json` | Chinese translations of English voice prompt strings (used for fuzzy matching) |

### Re-generation note

Running `create_voice_designs.py` overwrites `npc_voice_designs.json`. The current output has 268 unique designs (0 group designs), meaning all NPCs qualified for unique designs after the grouping logic was consolidated.

## How Tone/Personality Flows Through the Reference Generation Pipeline

The complete chain from game data to reference audio:

```
bilingual_mapping_review.json
  │  voice_gender: "male"
  │  voice_age: "middle"
  │  voice_prompt: "A warm friendly male voice, middle-aged, with a cheerful and slightly mischievous tone"
  │  voice_prompt_zh: "男性，中年，溫暖友善的聲音，帶有愉快且略帶頑皮的語氣"
  │  zh_text: "聖者，好久不見。"
  │  en_text: "Avatar, it's good to see you."
  ▼
create_voice_designs.py
  │  Groups by NPC, classifies as unique vs group,
  │  extracts reference texts, matches ZH prompts
  ▼
npc_voice_designs.json
  │  voice_desc_en ← voice_prompt (the tone/personality description)
  │  voice_desc_zh ← voice_prompt_zh (matched or fallback)
  │  ref_zh_text ← first suitable zh_text
  │  ref_en_text ← first suitable en_text
  ▼
generate_qwen3_voice.py --phase refs
  │  OR generate_reference_candidates.py
  │
  │  For each design × language:
  │    model.generate_voice_design(
  │      text=ref_text,          ← the sample dialogue line
  │      language='Chinese'|'English',
  │      instruct=voice_desc,    ← the tone/personality description!
  │    )
  │
  ▼
refs/{design_id}_{lang}_ref.ogg
  │  Audio clip where the VoiceDesign model interpreted
  │  "A warm friendly male voice, middle-aged, with a
  │   cheerful and slightly mischievous tone" into actual
  │  prosody, pitch, and timbre.
  ▼
generate_qwen3_voice.py --phase prompts
  │  model.create_voice_clone_prompt(ref_audio, ref_text)
  │  → Extracts voice characteristics into a prompt vector
  ▼
clone_prompts.pkl
  ▼
generate_qwen3_voice.py --phase voice
  │  For each dialogue line in bilingual_mapping_review.json:
  │    model.generate_voice_clone(
  │      text=dialogue_text,
  │      voice_clone_prompt=prompt_vector,  ← cloned from reference
  │    )
  ▼
voice/en/*.ogg, voice/zh/*.ogg
  │  Final generated dialogue, spoken in the NPC's voice
```

### Key points

1. **The `instruct` parameter is where tone lives.** The VoiceDesign model (`Qwen3-TTS-12Hz-1.7B-VoiceDesign`) takes a text description (`instruct`) and synthesizes a voice that matches it. The description is the only control over tone — there is no separate "tone slider" or "emotion parameter." The model interprets free-form text like `"A warm friendly male voice, middle-aged, with a cheerful and slightly mischievous tone"` and produces corresponding prosody.

2. **Reference text matters for naturalness.** The `ref_zh_text` / `ref_en_text` sample dialogue provides the lexical content. The model has no prior on what the NPC should sound like beyond what the `instruct` says. If the reference text is too short (<5 chars) or too long (>100 chars) it is rejected by `find_reference_texts()`.

3. **Voice cloning preserves tone.** Phase B extracts a voice clone prompt vector from the reference audio. This vector captures the acoustic characteristics produced by VoiceDesign. Phase C then uses this vector to generate new dialogue lines. The tone/personality from the `instruct` parameter is encoded into the prompt vector and persists through cloning.

4. **The `tone` field in `bilingual_mapping_review.json` is separate.** Each mapping entry has a `tone` field (`"neutral"`, `"angry"`, `"sad"`, etc.) and `tone_instruct`. These are per-line emotional annotations for the dialogue, not per-NPC voice identity. They are **not** used in reference generation. They were intended for per-line emotional variation in the TTS output but are not currently consumed by the pipeline.

5. **Acoustic audit is available.** The `audit_reference_tone_variation.py` script performs post-generation analysis of reference clips, extracting acoustic features (RMS energy, zero-crossing rate, spectral centroid/bandwidth, fundamental frequency mean/std) and flagging pairs that are too similar (Euclidean distance < 0.08). This detects cases where the VoiceDesign model produced insufficiently differentiated voices for different NPCs.

## Reference Clip Storage

Reference audio lives in two locations:

| Location | Purpose |
|----------|---------|
| `tools/voice_acting/refs/` | Current working set (350 files: 175 designs × 2 languages) |
| `voice/refs/` | Shadow copy used by the Base model in Phase B |

**Naming convention:** `{design_id}_{lang}_ref.ogg` (e.g. `npc_addom_zh_ref.ogg`, `npc_addom_en_ref.ogg`).

Each file includes Vorbis metadata with a `REFERENCE_HASH` key — a fingerprint of the text+instruction used to generate it. This hash is checked before regeneration to avoid redundant work.

## Option 1: Direct Generation (Legacy Phase A)

**Script:** `tools/voice_acting/generate_qwen3_voice.py` — Phase A

This is the simplest workflow. It generates exactly one reference clip per design per language directly to `tools/voice_acting/refs/`.

### Prerequisites

```bash
pip install -U qwen-tts torch soundfile numpy zhconv
```

A CUDA GPU with 8 GB+ VRAM is required. The VoiceDesign model (`Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign`, ~4.5 GB) auto-downloads on first use.

### Run

```bash
cd tools/voice_acting
python generate_qwen3_voice.py --phase refs --device cuda:0
```

### What it does

1. Loads the VoiceDesign model
2. Iterates over every design in `npc_voice_designs.json`
3. For each design, generates two reference clips:
   - **ZH:** model takes `ref_zh_text` as text + `voice_desc_zh` as instruction, language `Chinese`
   - **EN:** model takes `ref_en_text` as text + `voice_desc_en` as instruction, language `English`
4. Saves to `tools/voice_acting/refs/{design_id}_{lang}_ref.ogg`
5. Skips if the file already exists and its embedded `REFERENCE_HASH` matches (pass `--force-refs` to regenerate all)

### Key parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--device` | `cuda:0` | GPU device |
| `--force-refs` | off | Regenerate all references even if hashes match |
| `--design-json` | `npc_voice_designs.json` | Path to voice designs |
| `--refs-dir` | `refs/` | Output directory for reference clips |

## Option 2: Candidate Approval Workflow (Review-First)

This workflow generates multiple reference candidates per design, lets you review them, and then installs the selected ones. Use this when you want to audition different voice interpretations before committing.

### Phase 1: Generate Candidates

**Script:** `tools/voice_acting/generate_reference_candidates.py`

```bash
python generate_reference_candidates.py \
    --designs npc_voice_designs.json \
    --output-dir reference_candidates \
    --candidates 10 \
    --device cuda:0
```

#### What it does

1. For each design in `npc_voice_designs.json`, generates N candidate clips per language (default: 10)
2. Each candidate uses a different random seed for varied output
3. Output per design:
   ```
   reference_candidates/{slug}/
     candidate_zh_00.ogg + candidate_zh_00.json
     candidate_zh_01.ogg + candidate_zh_01.json
     ...
     candidate_en_00.ogg + candidate_en_00.json
     ...
   ```
4. Each `.json` sidecar contains metadata: `sha256`, `seed`, `instruct`, `sample_text`, `model_revision`, `duration`
5. Fully resumable — skips designs that already have all N candidates with matching metadata
6. Auto-splits batches on CUDA OOM

#### Key parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--designs` | `npc_voice_designs.json` | Voice designs input |
| `--output-dir` | `reference_candidates` | Output directory for candidates |
| `--candidates` | `10` | Number of candidates per design per language |
| `--device` | `cuda:0` | GPU device |
| `--skip-existing` | true | Skip designs that already have all candidates |

### Phase 2: Review and Select

Review the candidates by listening to them. Create a selection JSON file listing which candidates to install:

```json
{
  "npc_addom": {
    "zh": "reference_candidates/npc_addom/candidate_zh_03.ogg",
    "en": "reference_candidates/npc_addom/candidate_en_07.ogg"
  },
  "npc_iolo": {
    "zh": "reference_candidates/npc_iolo/candidate_zh_01.ogg",
    "en": "reference_candidates/npc_iolo/candidate_en_02.ogg"
  }
}
```

### Phase 3: Install Approved Candidates

**Script:** `tools/voice_acting/install_reference_voices.py`

```bash
python install_reference_voices.py \
    --selection selected.json \
    --source-dir reference_candidates \
    --designs npc_voice_designs.json \
    --output-dir voice/refs
```

#### What it does

1. **Preflight validation:** verifies each candidate exists, its SHA-256 matches the sidecar, the design exists
2. **Backup:** moves existing `voice/refs/` to `voice_backup/refs_YYYYMMDDTHHMMSSZ/`
3. **Atomic install:** copies approved candidates to `voice/refs/{design_id}_{lang}_ref.ogg` using atomic rename
4. **Provenance:** writes an install manifest to `voice/refs/.install_manifest.json`

#### Key parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--selection` | (required) | JSON file mapping designs to candidate paths |
| `--source-dir` | `reference_candidates` | Where candidates live |
| `--designs` | `npc_voice_designs.json` | Voice designs for validation |
| `--output-dir` | `voice/refs` | Destination for reference clips |

## Output

Either workflow produces the same output: reference `.ogg` files in `tools/voice_acting/refs/` (and/or `voice/refs/`) with naming `{design_id}_{lang}_ref.ogg`.

These are consumed by the next step: [Voice File Generation](voice_file_generation.md) Phase B (build clone prompts).
