# Sync Chinese Text from Updated usecode.zh — Design Spec

## Problem

The game's live `usecode.zh` (at `../Ultima_7/patch/usecode.zh`) has been updated with revised Chinese dialog text. The voice audio files in `voice/zh/*.ogg` were generated from the `zh_text` field in `tools/voice_acting/bilingual_mapping_review.json`, which now contains stale text that no longer matches what appears on screen. This causes a mismatch: the player sees one Chinese translation while hearing a different one spoken.

## Solution

A Python script (`tools/voice_acting/sync_zh_text_from_usecode.py`) that:

1. **Extracts** all Chinese dialog text from the compiled usecode binary by parsing function data segments and reconstructing `addsi → say` sequences
2. **Compares** extracted text against the `zh_text` fields in `bilingual_mapping_review.json`, keyed by `(zh_func_id, zh_offset_key, zh_segment)`
3. **Reports** all mismatches (old text vs new text) in a readable diff
4. **Updates** the JSON `zh_text` fields (optional, `--apply` flag)

## Key Design Decisions

- **Reuse `disassemble_usecode.py`**: The existing disassembler already handles the complex usecode binary format (extended/non-extended functions, symbol table skipping, opcode parsing, string extraction). Import its `parse_function()`, `disassemble_function()`, and `extract_say_lines()` rather than duplicating.
- **`--dry-run` default**: Read-only by default; `--apply` flag explicitly enables writes.
- **Reversible**: The script does not regenerate voice files — it only updates the mapping. Voice regeneration is a separate step.

## Data Flow

```
usecode.zh (binary)
       │
       ▼
  parse_function() + disassemble_function()
  extract_say_lines() → list of {func_id, offset_key, segment, text}
       │
       ▼
  Build ground-truth map: (func_id, offset_key, segment) → text
       │
       ▼
  For each entry in bilingual_mapping_review.json:
    ── look up (zh_func_id, zh_offset_key, zh_segment) in map
    ── compare map.text vs zh_text
    ── report mismatch or update zh_text (if --apply)
```

## Interface

```
python tools/voice_acting/sync_zh_text_from_usecode.py \
    --usecode-zh ../Ultima_7/patch/usecode.zh \
    --mapping tools/voice_acting/bilingual_mapping_review.json \
    [--apply] [--dry-run]
```

## Output

- **Diff report** (stdout): For each changed entry, shows the JSON key, old `zh_text`, and new `zh_text`
- **Summary counts**: total entries, matching, mismatched, missing in binary, missing in JSON
- **Updated JSON** (with `--apply`): `bilingual_mapping_review.json` with corrected `zh_text` fields
