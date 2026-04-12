# Voice Acting Tools

> **Work in progress.** This system is still in early development and is not yet
> capable of providing complete voice acting for the game. Currently it is limited
> to the initial two conversations in Trinsic (Iolo's greeting and Finnigan's
> murder investigation). The tooling, file format, and engine integration are all
> subject to change.

Tools for adding AI-generated voice acting to Exult dialog using text-to-speech.
Currently targeting the GOG version of Ultima VII: The Black Gate.

## Overview

The voice acting system works by:

1. **Extracting dialog lines** from the compiled usecode binary using static analysis
2. **Generating voice audio** via the ElevenLabs TTS API
3. **Playing audio at runtime** matched to dialog by usecode function ID and data segment offsets

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

## Tools

### disassemble_usecode.py

Parses the compiled `usecode` binary from a U7 installation and extracts dialog lines
with metadata (speaker, function ID, offset key, variable placeholders).

```bash
# Extract dialog lines for the opening sequence as CSV
python disassemble_usecode.py "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\static\usecode" \
    --func 0x401 --func 0x40c --func 0x885 --format csv > voice_lines.csv

# Disassemble in usecode.dis format (for diffing against docs/usecode.dis)
python disassemble_usecode.py "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\static\usecode" \
    --func 0x401 --format dis

# List all functions
python disassemble_usecode.py "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\static\usecode" --list
```

The CSV output includes:
- `func_id` - usecode function number
- `npc` - NPC who owns the conversation
- `speaker` - who is actually speaking (detected via show_npc_face intrinsic tracking)
- `offset_key` - stable voice file key from addsi offsets
- `segment` - segment index within `~~` text splits
- `has_var` - whether line contains dynamic text
- `text` - dialog template with `<PLAYER_NAME>`, `<PRONOUN>`, `<HONORIFIC>` placeholders

### generate_voices.py

Generates WAV voice files using the ElevenLabs TTS API, reading from the CSV
produced by the disassembler.

```bash
# Preview what would be generated (no API calls)
python generate_voices.py --csv voice_lines.csv --player-name Avatar --player-gender female --dry-run

# Generate voice files to the GOG game directory
python generate_voices.py --csv voice_lines.csv --player-name Avatar --player-gender female \
    -o "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\patch\voice_acting"

# Generate just one file to test
python generate_voices.py --csv voice_lines.csv --player-name Avatar --player-gender female \
    -o "C:\Program Files (x86)\GOG Galaxy\Games\Ultima 7\patch\voice_acting" --limit 1
```

Options:
- `--player-name` / `--player-gender` - resolves `<PLAYER_NAME>`, `<PRONOUN>`, `<HONORIFIC>` placeholders
- `--dry-run` - shows filenames, speakers, voices, text, and character count without calling the API
- `--limit N` - cap the number of files generated in a single run
- `--regenerate` - overwrite existing files (default: skip existing)
- `--all` - generate all lines, not just the demo whitelist

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
```

For example, `0401_af_151_254_0.wav` means:
- Function `0x0401` (Iolo's conversation)
- Data segment offsets `0xAF`, `0x151`, `0x254` (the addsi instructions that built this string)
- Segment `0` (first segment after splitting at `~~` boundaries)

This naming is deterministic and independent of player name, gender, or dialog choices.
