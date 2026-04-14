# Voice Acting Tools

> **Work in progress.** This system is still in early development and is not yet
> capable of providing complete voice acting for the game. Currently it is limited
> to the initial conversations in Trinsic (Iolo's greeting, Finnigan's murder
> investigation, and other NPCs in the area). The tooling, file format, and engine
> integration are all subject to change.

Tools for adding AI-generated voice acting to Exult dialog using text-to-speech.
Currently targeting the GOG version of Ultima VII: The Black Gate.

## Overview

The voice acting system works by:

1. **Extracting dialog lines** from the compiled usecode binary using static analysis
2. **Preparing a generation manifest** that resolves placeholders, assigns voices, and expands multi-NPC shared lines
3. **Generating voice audio** via the ElevenLabs TTS API
4. **Playing audio at runtime** matched to dialog by usecode function ID and data segment offsets

Voice files are WAV files placed in `<game>/patch/voice_acting/`. The engine looks up
files based on the usecode instruction trace, making the system immune to player name
and gender variation in dialog text.

## Paths

For the GOG version of Ultima VII: The Black Gate on Windows:

| Path | Description |
|------|-------------|
| `C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\static\usecode` | Compiled usecode binary (input for disassembler) |
| `C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\patch\voice_acting\` | Voice acting WAV files (output directory) |

The `patch` directory may need to be created if it doesn't already exist.

## Pipeline

```
disassemble_usecode.py ──► scope_voice_lines.csv (extracted dialog)
                                    │
prepare_voice_lines.py ◄── overrides.csv (manual corrections)
         │
         ▼
    manifest.csv (generation-ready, all details resolved)
         │
  generate_voices.py ──► WAV files in patch/voice_acting/
```

## Tools

### disassemble_usecode.py

Parses the compiled `usecode` binary and extracts dialog lines with metadata
(speaker, function ID, offset key, variable placeholders).

```bash
# Extract dialog lines for specific functions as CSV
python disassemble_usecode.py \
    "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\static\usecode" \
    --func 0x401 --func 0x40c --format csv > scope_voice_lines.csv

# Extract all functions
python disassemble_usecode.py \
    "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\static\usecode" \
    --all --format csv > all_voice_lines.csv

# Disassemble in usecode.dis format (for diffing against docs/usecode.dis)
python disassemble_usecode.py \
    "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\static\usecode" \
    --func 0x401 --format dis

# List all functions
python disassemble_usecode.py \
    "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\static\usecode" --list
```

The CSV output includes:
- `func_id` - usecode function number
- `npc` - NPC who owns the conversation
- `speaker` - who is actually speaking (detected via show_npc_face intrinsic tracking)
- `caller_guess` - inferred speaker from call graph analysis (pipe-delimited if multiple)
- `offset_key` - stable voice file key from addsi offsets
- `segment` - segment index within `~~` text splits
- `has_var` - whether line contains dynamic text
- `text` - dialog template with `<PLAYER_NAME>`, `<PRONOUN>`, `<HONORIFIC>` placeholders

### prepare_voice_lines.py

Prepares a generation manifest from the extracted CSV. Resolves placeholders,
applies manual overrides, assigns voices, and expands shared lines into per-NPC
variants. Reports any issues (unresolved variables, missing speakers, missing
voice assignments).

```bash
python prepare_voice_lines.py \
    --csv scope_voice_lines.csv \
    --overrides overrides.csv \
    --player-name Avatar --player-gender female \
    -o manifest.csv
```

Outputs:
- `manifest.csv` - generation-ready manifest with all details resolved
- `manifest_issues.csv` - any lines that need attention

### generate_voices.py

Generates WAV voice files using the ElevenLabs TTS API, reading from the
manifest produced by `prepare_voice_lines.py`.

```bash
# Preview what would be generated (no API calls)
python generate_voices.py --manifest manifest.csv \
    -o "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\patch\voice_acting" \
    --dry-run

# Generate first 5 files to test
python generate_voices.py --manifest manifest.csv \
    -o "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\patch\voice_acting" \
    --limit 5

# Generate all files (skips existing by default)
python generate_voices.py --manifest manifest.csv \
    -o "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\patch\voice_acting"

# Regenerate all files (overwrites existing)
python generate_voices.py --manifest manifest.csv \
    -o "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\patch\voice_acting" \
    --regenerate
```

### audit_voice_lines.py

Compares the runtime game log against the statically extracted voice lines to
verify that keys, text, and speaker assignments match.

```bash
python audit_voice_lines.py \
    --log "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\patch\voice_acting\voice_acting_log.csv" \
    --extracted voice_lines.csv \
    -o audit_report.csv
```

## Configuration Files

### overrides.csv

Manually maintained corrections and additions. Checked into the repo. Each row
can override fields in the extracted CSV by matching on `func_id` + `offset_key` +
`segment`. Blank `offset_key`/`segment` acts as a wildcard for all lines in a
function.

Uses:
- Fix unresolved `<VAR>` placeholders with actual text
- Assign speakers to lines where static analysis couldn't determine them
- Add lines that the disassembler missed (e.g., from dynamic code paths)
- Set text to `SKIP` to exclude a line from generation

### voice_assignments.py

Maps NPC speaker names to ElevenLabs voice IDs. Edit this file to change which
voice is used for each character. Supports both custom cloned voices and stock
ElevenLabs voices.

### npc_data.py

Shared NPC name/number data used by the disassembler and other tools.

## Setup

1. Get an API key from [ElevenLabs](https://elevenlabs.io)
2. Create a `.env` file in this directory:
   ```
   ELEVENLABS_API_KEY=your_key_here
   ```
3. Install the `requests` Python package:
   ```
   pip install requests
   ```

## Voice File Naming

Files are named by their usecode origin:

```
<funcID>_<offset_key>_<segment>.wav
<funcID>_<offset_key>_<segment>_npc<N>.wav   (per-NPC variant)
```

For example, `0401_af_151_254_0.wav` means:
- Function `0x0401` (Iolo's conversation)
- Data segment offsets `0xAF`, `0x151`, `0x254` (the addsi instructions that built this string)
- Segment `0` (first segment after splitting at `~~` boundaries)

For shared dialog (e.g., Fellowship description said by multiple NPCs), per-NPC
files use a `_npc<N>` suffix: `0919_0_0_npc16.wav` (Klog's version). The engine
tries the NPC-specific file first, then falls back to the generic version.

## Runtime Log

When running Exult with voice acting files installed, the engine writes a log to
`<game>/patch/voice_acting/voice_acting_log.csv`. Each conversation line encountered
is recorded with:

- `session` - timestamp identifying the play session
- `func_id` - usecode function ID
- `offset_key` - addsi offset sequence
- `segment` - segment index
- `filename` - WAV filename looked up (including NPC-specific attempts)
- `status` - `played`, `missing`, or `error`
- `speaker_npc` - NPC whose face is displayed (from show_npc_face tracking)
- `caller_npc` - NPC that initiated the conversation (from call stack)
- `text` - the actual displayed text (including player name as-is)

The log appends across multiple sessions, so you can play through the game multiple
times (with different character names/genders) and build up a complete picture of
all dialog lines encountered. Use the audit tool to compare against extracted data.

## Known Limitations / Future Work

- **Long text pagination**: When a single dialog line is too long to fit in the
  conversation text box, the game paginates it with click-to-continue. Currently
  the voice audio plays in full on the first page and subsequent pages are silent.
  A future improvement could use the ElevenLabs
  [timestamps API](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps)
  to get per-character timing data, then seek the audio to the correct position
  when the text advances to a new page.

- **Branch-dependent dialog**: The usecode disassembler uses linear scanning and
  may miss dialog lines that are only reachable through specific code branches.
  These can be added manually via the overrides CSV, or discovered through
  runtime log auditing.

- **Say-text bubbles**: Voice acting is currently limited to conversation text
  (the `say` opcode). Floating text bubbles above character sprites are not
  voiced.
