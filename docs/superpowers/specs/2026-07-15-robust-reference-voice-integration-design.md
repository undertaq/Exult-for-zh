# Robust Reference Voice Integration Design

## Goal

Integrate the candidate-based reference voice workflow from
`../voice_sample` into this repository, install its already selected English
and Chinese references, give every NPC an individual voice design, and fill
all missing Chinese mapping text from the existing English text.

## Source Data

The initial reference import uses these authoritative files from the sibling
project:

- `../voice_sample/artifacts/reports/signature_selection.json` selects one
  English and one Chinese candidate for each character.
- `../voice_sample/artifacts/references/<slug>/candidate_<Language>_<n>.ogg`
  contains the selected audio.
- The adjacent candidate JSON contains the exact sample text, generation
  instruction, model revision, seed, and audio hash.
- `../voice_sample/artifacts/voice_bibles/<slug>.json` contains the enriched
  per-character voice design.

The current project's `bilingual_mapping_review.json` remains authoritative
for dialogue rows and runtime identity. The import must not modify function
IDs, offsets, segments, NPC identities, speakers, or existing non-empty
translations.

## Architecture

### Candidate Pipeline

Add a self-contained candidate pipeline under `tools/voice_acting` based on
the working `voice_sample` process. It will:

1. Build one voice bible per NPC from current mapping and design data.
2. Generate ten English and ten Chinese Qwen3 VoiceDesign candidates using a
   stable, resumable output layout.
3. Record the exact spoken text, instruction, seed, model revision, duration,
   sample rate, and SHA-256 beside every candidate.
4. Embed candidates with ECAPA speaker embeddings.
5. Select English and Chinese independently using the maximin cast-diversity
   objective.
6. Select Avatar and narrator voices independently by medoid because those
   voices are not ordinary cast members.
7. Audit duration, silence, clipping, and file validity, replacing a bad
   selected candidate with the best valid alternative.
8. Produce a machine-readable selection manifest and human-readable review
   report.

The implementation will reuse focused logic from `voice_sample`, adapted to
this repository's paths and data schema. It will not import Python modules at
runtime from `../voice_sample`.

### Individual Voice Designs

Replace shared group assignments with individual designs for every NPC in the
selection manifest. Normal character design IDs use `npc_<slug>`. Existing
individual design IDs that already follow that convention remain stable.

Special routing remains explicit:

- Male Avatar: `npc_avatar_male`
- Female Avatar: `npc_avatar_female`
- Male narrator: `npc_narrator_male`
- Female narrator: the existing female narrator design ID used by generation

Each individual design contains only its own NPC in `npcs`. The imported voice
bible supplies the per-language voice descriptions, and candidate metadata
supplies the exact `ref_en_text` and `ref_zh_text`. This is necessary because
Qwen3 clone prompt construction must receive the actual reference
transcription, not an older line from the grouped design.

### Reference Installation

Add an installer that reads a selection manifest and performs a complete
preflight before changing files. It validates that every selected candidate,
metadata file, voice bible, language, and NPC mapping exists and that recorded
hashes match the audio.

Before replacement, existing reference clips and `clone_prompts.pkl` are
copied to a timestamped directory under `voice_backup/refs_<timestamp>/`.
Selected files are then copied to:

- `voice/refs/npc_<slug>_en_ref.ogg`
- `voice/refs/npc_<slug>_zh_ref.ogg`

The installed OGG metadata records the source candidate, source hash,
selection method, reference text, and import timestamp. The installer writes
an import manifest so every installed file can be traced back to its candidate.

After installation, Phase B of `generate_qwen3_voice.py` rebuilds
`clone_prompts.pkl` from the new references and exact transcriptions. Phase A
will expose the candidate workflow for future reference regeneration rather
than overwriting selected references with a single unscored generation.

### Reference Voice Review

Generate `tools/voice_acting/reference_voice_review/index.html` from the voice
bibles, candidate metadata, selection manifest, and portrait cache. The report
follows the proven `voice_sample` review layout while remaining usable for the
full cast:

- One searchable character section per NPC with portrait, English prompt, and
  Chinese prompt.
- Inline audio controls for the selected English and Chinese references, with
  selected candidate indices, seeds, and audit status visible.
- A collapsed comparison table containing all ten English and Chinese
  candidates, with selected cells highlighted.
- Pass and Failed controls for each selected language clip, stored in browser
  local storage under a versioned manifest key.
- Filters for unreviewed, passed, failed, missing portrait, missing audio, and
  audit-warning entries, plus reviewed and total counters.
- Lazy-loaded portraits and audio so the full report does not preload thousands
  of media files.

Regenerating the page with an unchanged selection-manifest fingerprint keeps
review decisions. A changed selection gets a new review key so a decision for
an old candidate cannot silently apply to its replacement. The report is a
static local page: audio plays in place and no link opens another window.

### Missing Chinese Translation

Add a resumable translation command that selects only mapping rows where
`en_text` is non-empty and `zh_text` is empty. The current count is 85.

The command calls the local Ollama model `qwen3.6:35b` in deterministic batches
and requests Traditional Chinese suitable for Ultima VII. It must preserve:

- Dialogue versus narration boundaries.
- Balanced English `"` input semantics as Chinese `「」` dialogue delimiters.
- Character names, `Avatar`, Britannian terminology, numbers, and placeholders.
- Paragraph and sentence order.

Responses are cached by source-text hash so interrupted runs resume without
retranslation. A validator rejects empty output, Simplified-only wording,
unexpected commentary, lost placeholders, unbalanced delimiters, and a changed
dialogue-span count. Rejected rows remain unchanged and are written to an audit
report for manual review.

Accepted translations update only `zh_text`. Rows without a Chinese runtime
identity remain without one; translation does not invent `zh_func_id`,
`zh_offset_key`, or `zh_segment`.

## Interfaces

The integrated tooling will provide separate commands for:

- Preparing individual voice designs and candidate jobs.
- Generating resumable reference candidates.
- Selecting and auditing candidates.
- Importing an existing selection manifest, including the current
  `../voice_sample` output.
- Generating the static reference voice review page from candidates and the
  active selection manifest.
- Translating and validating missing `zh_text` rows.
- Rebuilding clone prompts after reference installation.

Each command supports a dry-run or validation-only mode where mutation is
possible. Paths are configurable, while defaults match this repository and
the current sibling project layout.

## Failure Handling

Reference installation is all-or-nothing after preflight. Missing files,
unknown NPCs, duplicate design assignments, hash mismatches, malformed
metadata, or incomplete language pairs stop installation before references are
replaced.

Translation is row-atomic. A failed model call or validation failure does not
alter that row. The cache and audit report retain enough information to retry
only failed rows.

Existing unrelated worktree changes and generated voice output are not
removed. Backup directories are never overwritten.

## Testing

Automated tests will cover:

- Stable conversion between voice-sample slugs and current design IDs.
- Expansion of grouped designs into unique per-NPC assignments.
- Preservation of Avatar and narrator special routing.
- Selection-manifest parsing and complete preflight failure behavior.
- Copy destinations, backups, hashes, provenance metadata, and exact reference
  transcriptions.
- Candidate selection using synthetic embeddings and audit fallback behavior.
- Review HTML rendering, selected-candidate highlighting, lazy media loading,
  stable review-state keys, filters, and inline audio paths.
- Missing-row selection without touching existing Chinese text.
- Traditional Chinese translation validation, placeholder preservation, and
  balanced dialogue delimiters.
- Idempotent reruns and resumable translation cache behavior.

Integration verification will confirm that all selected characters have both
installed references, every NPC resolves to exactly one design, Phase B builds
both clone prompts for every complete design, all 85 target rows are either
translated or explicitly reported as rejected, and no runtime identity fields
change. Browser verification will open the generated review page at desktop
and mobile widths and confirm portraits render, selected EN/ZH audio sources
load, filters work, and Pass/Failed state survives a reload.
