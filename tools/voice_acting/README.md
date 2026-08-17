# Voice Acting Tools

> **Work in progress.** The voice acting system is under active development. It
> has been built out for (and tested against) Ultima VII: The Black Gate on the
> GOG release. The tooling, file format, and engine integration are all still
> subject to change.

Tools for adding AI-generated voice acting to Exult dialog using text-to-speech.

## Overview

The pipeline has two halves:

1. **Static analysis and generation** (the Python tools in this directory). These
   extract dialog lines from the compiled usecode, prepare a generation manifest,
   and call the ElevenLabs TTS API to produce voice WAV files.
2. **Voice casting** (the `voice_casting_tool/` web app). A local web UI for
   browsing ElevenLabs voices, previewing samples, assigning voices to NPCs, and
   exporting the canonical NPC-to-voice map as a CSV.

At runtime, Exult looks up voice files keyed by a usecode instruction trace
(function ID + data segment offsets), making playback immune to player name and
gender variation in dialog text.

## Directory layout

```
tools/voice_acting/
├── .env                     Secrets (gitignored)
├── *.py                     Pipeline scripts (see "Tools" below)
├── overrides.csv            Hand-curated dialog corrections (committed)
├── voice_assignments.csv    NPC -> voice map, exported from the casting tool (committed)
├── csvs/                    Regenerable pipeline outputs (gitignored)
├── transcripts/             Reference transcripts used for override curation
└── voice_casting_tool/      Local web app for voice casting (see its README)
```

## Paths

Default locations for the GOG release of Ultima VII on Windows:

| Path | Description |
|------|-------------|
| `C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\static\usecode` | Compiled usecode binary (disassembler input) |
| `C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\patch\voice_acting\` | Generated voice WAV files (engine input) |

The `patch` directory may need to be created if it does not already exist.

## Setup

1. Get an API key from [ElevenLabs](https://elevenlabs.io).
2. Create `.env` in this directory:
   ```
   ELEVENLABS_API_KEY=sk_...
   # Optional overrides used by the casting tool:
   MANIFEST_CSV=/absolute/path/to/csvs/manifest.csv
   VOICE_WAV_DIR=/absolute/path/to/patch/voice_acting
   ```
3. Install Python dependencies:
   ```
   pip install requests anthropic
   ```
   (`anthropic` is only needed for `voice_casting_tool/scripts/suggest_voices.py`.)

## Pipeline at a glance

```
disassemble_usecode.py  ──►  csvs/voice_lines.csv          (extracted dialog)
                                      │
       prepare_voice_lines.py  ◄──  overrides.csv          (manual corrections)
                │            ◄──  voice_assignments.csv    (voice map from casting tool)
                ▼
          csvs/manifest.csv  (generation-ready)
                │
         generate_voices.py  ──►  *.wav in patch/voice_acting/
```

## Pipeline scripts

### `disassemble_usecode.py`

Parses the compiled `usecode` binary and extracts dialog lines with metadata
(speaker, function ID, offset key, variable placeholders).

```bash
# Extract all functions
python disassemble_usecode.py \
    "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\static\usecode" \
    --all --format csv > csvs/voice_lines.csv

# Or only specific functions
python disassemble_usecode.py \
    "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\static\usecode" \
    --func 0x401 --func 0x40c --format csv > csvs/voice_lines.csv

# Usecode.dis format (for diffing against docs/usecode.dis)
python disassemble_usecode.py \
    "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\static\usecode" \
    --func 0x401 --format dis

# List all functions
python disassemble_usecode.py \
    "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\static\usecode" --list
```

Key CSV columns: `func_id`, `npc`, `speaker`, `caller_guess`, `offset_key`,
`segment`, `has_var`, `text`.

### `prepare_voice_lines.py`

Builds the generation manifest from the extracted CSV. Resolves placeholders,
applies `overrides.csv`, looks up voices from `voice_assignments.csv`, and
expands shared lines into per-NPC variants.

```bash
python prepare_voice_lines.py \
    --csv csvs/voice_lines.csv \
    --overrides overrides.csv \
    --voice-map voice_assignments.csv \
    --player-name Helena --player-gender female \
    -o csvs/manifest.csv
```

`--voice-map` is required. Produce it by clicking **Export CSV** in the
`voice_casting_tool` web app and committing the result as
`voice_assignments.csv`.

Outputs:
- `csvs/manifest.csv` — generation-ready.
- `csvs/manifest_issues.csv` — lines needing attention (unresolved vars, missing
  speakers, missing voice assignments).

### `generate_voices.py`

Generates WAV files with the ElevenLabs TTS API, reading from the manifest.

```bash
# Preview with cost estimate, no API calls
python generate_voices.py -m csvs/manifest.csv \
    -o "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\patch\voice_acting" \
    --dry-run

# Sample one line per NPC (skips NPCs already having any WAVs)
python generate_voices.py -m csvs/manifest.csv \
    -o "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\patch\voice_acting" \
    --per-npc 1

# Full generation (skips fresh files, regenerates stale-metadata ones)
python generate_voices.py -m csvs/manifest.csv \
    -o "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\patch\voice_acting"
```

Each WAV embeds a LIST-INFO chunk with the `voice_id`, a text hash, and the
full text. The script uses this to detect staleness:

- `fresh`: voice_id and text match the manifest — skip.
- `stale_voice` / `stale_text`: metadata differs from the manifest. The script
  **refuses to run** until stale files are moved aside with
  `backup_stale_voices.py` (or `--regenerate` is passed to force overwrite).

### `backup_stale_voices.py`

Safety tool used before regenerating. Scans the manifest, identifies any WAVs
whose embedded metadata no longer matches, and moves them into a backup dir.

```bash
python backup_stale_voices.py \
    --manifest csvs/manifest.csv \
    --source "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\patch\voice_acting" \
    --dest "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\patch\voice_acting\backup"
```

Pass `--dry-run` to preview. If you later want to restore a voice, copy files
back from the backup dir.

### `audit_voice_lines.py`

Compares the runtime game log (see "Runtime log" below) against the statically
extracted voice lines to verify keys, text, and speaker assignments match.

```bash
python audit_voice_lines.py \
    --log "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\patch\voice_acting\voice_acting_log.csv" \
    --extracted csvs/voice_lines.csv \
    -o audit_report.csv
```

### `sync_voice_files.py`

Rename-by-metadata tool. If the manifest filename scheme ever changes, this
reads each WAV's embedded metadata, matches it back against the current
manifest, and renames the files accordingly.

## Configuration files

### `overrides.csv` (committed)

Hand-curated corrections. Each row matches on `func_id` + `offset_key` +
`segment`; blanks act as wildcards.

Uses:
- Fix unresolved `<VAR>` placeholders with actual text
- Assign speakers where static analysis could not
- Add lines the disassembler missed (e.g., dynamic code paths)
- Set text to `SKIP` to exclude a line

### `voice_assignments.csv` (committed)

The canonical NPC-to-voice map. Exported from the casting tool's **Export CSV**
button. Treat the casting tool's SQLite as the editing surface; this CSV is
the commit artifact.

### `npc_data.py`

Shared NPC name/number tables consumed by the disassembler and related tools.

## Voice file naming

```
<funcID>_<offset_key>_<segment>.wav
<funcID>_<offset_key>_<segment>_npc<N>.wav   (per-NPC variant)
```

For example, `0401_af_151_254_0.wav` means:
- Function `0x0401` (Iolo's conversation)
- Data segment offsets `0xAF`, `0x151`, `0x254` (the addsi instructions that
  built this string)
- Segment `0` (first segment after splitting at `~~` boundaries)

For shared dialog (e.g., Fellowship description said by multiple NPCs), per-NPC
files use a `_npc<N>` suffix such as `0919_0_0_npc16.wav` (Klog's version).
The engine tries the NPC-specific file first, then the generic fallback.

## Runtime log

When you run Exult with voice files installed, the engine appends to
`<game>/patch/voice_acting/voice_acting_log.csv`. Each played/missing line is
recorded with `session`, `func_id`, `offset_key`, `segment`, `filename`,
`status`, `speaker_npc`, `caller_npc`, and `text`. The log is cumulative
across sessions; use `audit_voice_lines.py` to compare against the extracted
data and find gaps.

## Voice casting UI

See [`voice_casting_tool/README.md`](voice_casting_tool/README.md) for the
local web app used to assign voices, preview the ElevenLabs library, and
export the voice map.

## Known limitations / future work

- **Long text pagination.** When a single dialog line wraps across multiple
  pages in the conversation box, the audio plays in full on the first page
  and subsequent pages are silent. A future improvement could use the
  ElevenLabs
  [timestamps API](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps)
  to seek the audio as the text advances.

- **Branch-dependent dialog.** The disassembler does linear scanning and may
  miss lines reachable only through specific branches. These can be added
  manually via `overrides.csv` or discovered through runtime-log auditing.

- **Say-text bubbles.** Voice acting currently covers conversation text (the
  `say` opcode). Floating text bubbles above sprites are not voiced.

- **Disk footprint.** WAV PCM at 22050 Hz/16-bit is ~44 KB/s, so a full pass is
  ~400 MB. The engine already supports Ogg Vorbis (via the built-in
  `OggAudioSample`); switching the distribution format to Ogg would reduce the
  patch size ~8× at no quality cost for speech.
