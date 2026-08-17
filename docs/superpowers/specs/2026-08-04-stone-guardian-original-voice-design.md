# Stone Guardian: Keep Original Voice, Stop Generated Voice

**Date:** 2026-08-04
**Status:** Approved

## Problem

Ultima VII: The Black Gate already ships its own recorded voice for the
Stone Guardian (NPC 277, usecode function `0x0614`, 25 dialogue lines).
The AI-generated TTS voices currently override that original audio at
runtime. We want the original game voice to play and the synthesized
voices for Stone Guardian to be removed from the pipeline entirely —
while keeping the bilingual mapping data for reference.

## Success Criteria

1. At runtime, Stone Guardian lines play the game's original recording;
   synthesized `.ogg` files are never used for those lines.
2. No synthesized voice file for Stone Guardian exists in the shipped
   `voice/` tree (loose dirs or `.pak`/`.idx` archives) for either
   `en` or `zh`.
3. Future pipeline runs do not regenerate Stone Guardian voices.
4. The mapping data (`bilingual_mapping_review.json`) and NPC voice
   design (`npc_voice_designs.json`) retain the Stone Guardian entries,
   marked so generation skips them.

## Design

### Marker convention

New, uniform marker across data files:

```
"voice_generation": "skip"
```

There is no existing skip/disable convention in these files, so this
introduces one.

### 1. Mark NPC voice design

In `tools/voice_acting/npc_voice_designs.json`, add
`"voice_generation": "skip"` to the `npc_stone_guardian` design entry.
The design data (voice descriptions, reference texts) stays for
reference; generation skips it.

### 2. Mark mapping rows

In `tools/voice_acting/bilingual_mapping_review.json`, add
`"voice_generation": "skip"` to all 25 entries whose `npc` is
`Stone Guardian`. Keep the rows as reference data.

### 3. Generator honors the marker

`tools/voice_acting/generate_qwen3_voice.py`:

- `load_mapping()`: drop entries with `voice_generation == "skip"` so
  they never become generation jobs (Phase C).
- `phase_a_generate_refs`: skip designs with the marker.
- `phase_b_build_prompts`: skip designs with the marker.
- `phase_c_generate_voice`: skip an NPC whose design carries the marker.

Dependent generators that read the mapping for new work must treat
marked rows as reference-only:

- `generate_missing_en_voices.py`: do not list Stone Guardian lines as
  missing.
- `generate_voice_review_html.py`: rows_for_full_voice counts marked
  rows as reference, not missing.

### 4. Delete synthesized files (both languages)

Remove from the loose voice tree:

- `voice/en/0614_*_npc277.ogg` (25 files)
- `voice/zh/0614_*_npc277.ogg` (25 files)

Then rebuild the packed archives:

```
python tools/voice_acting/pack_voice.py pack --lang en
python tools/voice_acting/pack_voice.py pack --lang zh
```

`deploy.ps1` needs no change; it copies the rebuilt `.pak`/`.idx`.

### 5. Engine guard

In `audio/VoiceActingManager.cc` / `audio/VoiceActingManager.h`, add a
named constant for the Stone Guardian NPC number (277) and early-return
in `VoiceActingManager::play_for_conversation()` when the resolved
speaker or caller NPC is the Stone Guardian. Log the line with status
`original` so the runtime log records that the synthesized path was
deliberately skipped.

## Files touched

- `tools/voice_acting/npc_voice_designs.json` — add marker (1 design)
- `tools/voice_acting/bilingual_mapping_review.json` — add marker (25 rows)
- `tools/voice_acting/generate_qwen3_voice.py` — honor marker
- `tools/voice_acting/generate_missing_en_voices.py` — skip marked rows
- `tools/voice_acting/generate_voice_review_html.py` — count marked as reference
- `audio/VoiceActingManager.h` — constant
- `audio/VoiceActingManager.cc` — guard + log
- `voice/en/*.ogg`, `voice/zh/*.ogg` — delete 50 files
- `voice/en_voices.pak/.idx`, `voice/zh_voices.pak/.idx` — rebuild

## Testing

- Unit test: `load_mapping()` excludes Stone Guardian entries.
- Dry-run `pack_voice.py verify` for en/zh confirms no `npc277` entries.
- Runtime check: start a Stone Guardian conversation; the original voice
  plays and the runtime log records `original` (manual).
