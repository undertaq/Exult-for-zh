# U6 Runtime Speaker Attribution Design

## Goal

Make Ultima 6 dialogue speaker attribution come from the running U6 game rather than the existing Ultima 7 voice-acting NPC table. The attribution is captured alongside the runtime translation catalog and consumed by the review HTML generator.

## Root cause

The current review generator receives a static `speaker_map.json` produced by `tools/voice_acting/disassemble_usecode.py`. That tool imports U7-specific NPC function mappings, while U6 speaker identity is established dynamically by `Usecode_internal::show_npc_face()` and `say_string()`. Static disassembly also cannot reliably resolve helper calls and dynamic face changes, so most entries are shown as unresolved.

## Architecture

Add a separate UTF-8 TSV capture file, `u6_runtime_speakers.tsv`, written by `GameplayTranslationManager` when runtime catalog capture is enabled. Each row records the existing dialogue key, the numeric U6 NPC id, and the actor name known by the running game:

```text
# u6-runtime-speakers-v1
# kind\tkey\tspeaker_id\tspeaker
dialogue\tdialogue:0x0401:1a_2f:0\t17\tIolo
```

`Usecode_internal::say_string()` records this data after it has established the active face/caller and built the dialogue segment key. The capture is independent of voice playback, so it works when voice acting is disabled.

The Python review tool accepts `--speaker-capture`. Runtime attribution takes precedence over the existing optional static map. If one dialogue key is observed with multiple names, the review displays an explicit `Ambiguous · A / B` label. If no runtime row exists, the existing unresolved fallback remains visible; this means the review distinguishes unobserved dialogue from incorrectly mapped dialogue.

## Marker boundary

`@` remains usecode conversation/overhead-text markup and `*` remains the click-to-continue marker consumed by the runtime. This change does not translate or strip either marker. Translation audit and rendering continue to treat control markers separately from speaker attribution.

## Configuration

The existing `config/debug/translation/catalog_capture` flag enables both catalog and speaker capture. `config/debug/translation/speaker_path` optionally changes the relative `GAMEDAT` output path. The default is `u6_runtime_speakers.tsv`.

## Failure behavior

Speaker capture is diagnostic data only. A missing actor name, malformed capture row, or missing capture file cannot affect gameplay or translation; the review tool falls back to the static map and then to an explicit unresolved label.

## Verification

- C++ source-level regression checks verify the capture API, safe-path configuration, U6 actor-name resolution, and runtime call site.
- Python unit tests verify escaped TSV fields, stable duplicate handling, ambiguity labels, invalid-row errors, and CLI precedence.
- The full Python translation test suite and focused C++ test must pass.
