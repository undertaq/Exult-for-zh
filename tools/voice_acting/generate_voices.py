#!/usr/bin/env python3
"""
Generate voice audio files for Exult AI voice dialog using ElevenLabs TTS.

Voice files are keyed by usecode function ID and addsi offset sequence.
Reads voice_lines.csv (produced by disassemble_usecode.py) and generates
WAV files for the lines used in the opening demo sequence.

Usage:
    python generate_voices.py --csv tools/voice_acting/voice_lines.csv --player-name Avatar --player-gender male --dry-run
    python generate_voices.py --csv tools/voice_acting/voice_lines.csv --player-name Avatar --player-gender male -o path/to/voice_acting

Set ELEVENLABS_API_KEY in environment or in a .env file.
"""

import argparse
import csv
import os
import re
import struct
import sys
import time

try:
    import requests
except ImportError:
    print("Error: 'requests' package required. Install with: pip install requests")
    sys.exit(1)

# ElevenLabs API
API_BASE = "https://api.elevenlabs.io/v1"

# Voice assignments: speaker name -> (voice_id, description)
VOICE_MAP = {
    "Iolo":        ("aV8DLAt0Q9peDuTGGPx5", "Custom Iolo voice"),
    "Finnigan":    ("l1d1DlQ9BVMMQMoVx1oe", "Custom Finnigan voice"),
    "Petre":       ("bIHbv24MWmeRgasZH58o", "Will - young, conversational"),
    "Dupre":       ("JBFqnCBsd6RMkjVDRZzb", "George - warm, authoritative"),
    "Shamino":     ("iP95p4xoKVk53GoZ742B", "Chris - down-to-earth"),
    "Townsperson": ("iP95p4xoKVk53GoZ742B", "Chris - down-to-earth"),
    "Guard":       ("JBFqnCBsd6RMkjVDRZzb", "George - authoritative"),
}

# Fallback: map func_id to a voice when speaker column is empty
# (e.g., for functions not in the NPC lookup table)
FUNC_VOICE_FALLBACK = {
    "0x0885": ("Finnigan", "l1d1DlQ9BVMMQMoVx1oe", "Custom Finnigan voice"),
}

# Default voice for unknown speakers
DEFAULT_VOICE = ("iP95p4xoKVk53GoZ742B", "Chris - default")

# Voice settings tuned for medieval fantasy dialog
VOICE_SETTINGS = {
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.4,
    "use_speaker_boost": True,
}

# Lines to generate for the demo, identified by (func_id, offset_key, segment).
# This whitelist ensures we only spend credits on lines we actually use.
# Optional 4th element: "female" or "male" to restrict to a specific gender.
DEMO_LINES = {
    # --- Iolo greeting (0x401) ---
    ("0x0401", "0xaf_0x151_0x254", 0),   # narrative intro
    ("0x0401", "0xaf_0x151_0x254", 1),   # "<NAME>! If I did not trust..."
    ("0x0401", "0xaf_0x151_0x254", 2),   # "Lo and behold!..."
    ("0x0401", "0xaf_0x151_0x254", 3),   # "Dost thou realize, <NAME>..."
    ("0x0401", "0x2b1", 0),              # Iolo whispers
    ("0x0401", "0x2b1", 1),              # "He resumes speaking aloud..."
    ("0x0401", "0x2b1", 2),              # "Oh, but Avatar!..."
    ("0x0401", "0x437_0x466", 0),        # Petre interrupts
    ("0x0401", "0x48d", 0),              # Iolo nods...
    ("0x0401", "0x48d", 1),              # "Ah, yes. Our friend Petre..."
    # Interactive Iolo dialog (skipped for demo - uncomment to generate):
    # ("0x0401", "0x6bf", 0),            # "Yes, my friend?" Iolo asks.
    # ("0x0401", "0x6e1_0x70e", 0),      # "What, art thou joking..."
    # ("0x0401", "0x748_0x765", 0),      # "Thou must see for thyself..."
    # ("0x0401", "0x847", 0),            # "<NAME>! However, thou mayest..."
    # ("0x0401", "0x847", 1),            # "Of course, thou shouldst be safe..."
    # ("0x0401", "0x9a6", 0),            # "Ugly, is it not?..."
    # ("0x0401", "0xa54", 0),            # "I wish thee luck..."
    # ("0x0401", "0xe08", 0),            # "Thou must mean Shamino and Dupre."
    # ("0x0401", "0x18d7", 0),           # "'Tis always a pleasure..."
    # --- Finnigan (0x40C) ---
    ("0x040C", "0x364", 0),              # "You see a middle-aged nobleman."
    ("0x040C", "0x384", 0),              # "Iolo! Who is this stranger?"
    ("0x040C", "0x3a3_0x433", 0),        # "Why, this is the Avatar!"
    ("0x040C", "0x441", 0, "female"),     # "I simply cannot believe she..."
    ("0x040C", "0x469", 0, "male"),      # "I simply cannot believe he..."
    ("0x040C", "0x490", 0),              # "The Mayor looks you up and down..."
    ("0x040C", "0x4f4", 0),              # "I swear to thee..."
    ("0x040C", "0x519", 0),              # "I have heard that thou art..."
    ("0x040C", "0x565", 0),              # "The mayor looks at you again..."
    ("0x040C", "0x5c6", 0),              # "Welcome, Avatar."
    ("0x040C", "0x5d9", 0),              # "But just as suddenly..."
    ("0x040C", "0x60e", 0),              # "A horrible murder has occurred..."
    ("0x040C", "0x716", 0),              # "Petre here knows something..."
    ("0x040C", "0x747", 0),              # Petre interjects
    ("0x040C", "0x7ab", 0),              # "Petre, the stables caretaker..."
    ("0x040C", "0x805", 0),              # "Hast thou searched the stables?"
    # Interactive Finnigan dialog (skipped for demo - uncomment to generate):
    # ("0x040C", "0x248", 0),            # "Well, do so, then come speak..."
    # ("0x040C", "0x2b6", 0),            # "Splendid..."
    # ("0x040C", "0x2f1", 0),            # "Then leave our people..."
    # ("0x040C", "0x329", 0),            # "Avatar! I am ashamed of thee!"
    # ("0x040C", "0x86d", 0),            # "Yes, Avatar?" Finnigan asks.
    # ("0x040C", "0x8d7", 0),            # "My name is Finnigan."
    # ("0x040C", "0x8f7", 0),            # "I am the Mayor of Trinsic..."
    # --- Finnigan follow-up (0x885) ---
    ("0x0885", "0x1f2", 0),              # "Then I suggest thou lookest inside..."
    # ("0x0885", "0x0", 0),              # "What didst thou find?"
}


def resolve_placeholders(text, player_name, player_gender):
    """Replace labeled placeholders with actual values."""
    gender_map = {
        "male": {"<PRONOUN>": "him", "<HONORIFIC>": "milord"},
        "female": {"<PRONOUN>": "her", "<HONORIFIC>": "milady"},
    }
    replacements = gender_map.get(player_gender, gender_map["male"])
    replacements["<PLAYER_NAME>"] = player_name

    result = text
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)
    return result


def check_unresolved_placeholders(text):
    """Check for any remaining unresolved <...> placeholders."""
    matches = re.findall(r'<[A-Z_]+>', text)
    return matches


def voice_filename(func_id, offset_key, segment):
    """Compute the voice filename from function ID, offset key, and segment."""
    # Normalize func_id: strip 0x prefix and lowercase
    fid = func_id.lower().replace("0x", "")
    # Replace 0x prefixes in offset key
    okey = offset_key.replace("0x", "")
    return f"{fid}_{okey}_{segment}.wav"


def generate_speech(api_key, voice_id, text, output_path,
                    previous_text=None, next_text=None, speed=1.0):
    """Call ElevenLabs TTS API and save as PCM WAV."""
    url = f"{API_BASE}/text-to-speech/{voice_id}?output_format=pcm_22050"

    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }

    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": VOICE_SETTINGS,
    }

    if previous_text:
        payload["previous_text"] = previous_text
    if next_text:
        payload["next_text"] = next_text
    if speed != 1.0:
        payload["speed"] = speed

    response = requests.post(url, json=payload, headers=headers, timeout=60)

    if response.status_code == 200:
        pcm_data = response.content
        with open(output_path, "wb") as f:
            sample_rate = 22050
            bits_per_sample = 16
            num_channels = 1
            byte_rate = sample_rate * num_channels * bits_per_sample // 8
            block_align = num_channels * bits_per_sample // 8
            data_size = len(pcm_data)
            f.write(b"RIFF")
            f.write(struct.pack("<I", 36 + data_size))
            f.write(b"WAVE")
            f.write(b"fmt ")
            f.write(struct.pack("<IHHIIHH", 16, 1, num_channels,
                                sample_rate, byte_rate, block_align,
                                bits_per_sample))
            f.write(b"data")
            f.write(struct.pack("<I", data_size))
            f.write(pcm_data)
        return True
    else:
        print(f"  API error {response.status_code}: {response.text[:200]}")
        return False


def load_api_key():
    """Load API key from environment or .env file."""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        for env_path in [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"),
        ]:
            if os.path.exists(env_path):
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#") or "=" not in line:
                            continue
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip("\"'")
                        if key == "ELEVENLABS_API_KEY":
                            api_key = value
                            break
                if api_key:
                    break
    return api_key


def main():
    parser = argparse.ArgumentParser(
        description="Generate voice audio for Exult using ElevenLabs TTS"
    )
    parser.add_argument("--csv", default="tools/voice_acting/voice_lines.csv",
                        help="Path to voice_lines.csv from disassemble_usecode.py")
    parser.add_argument("--output-dir", "-o", default=".",
                        help="Output directory for WAV files")
    parser.add_argument("--player-name", default="Avatar",
                        help="Player character name for <PLAYER_NAME> substitution")
    parser.add_argument("--player-gender", choices=["male", "female"], default="male",
                        help="Player gender for <PRONOUN> and <HONORIFIC> substitution")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Show what would be generated without calling API")
    parser.add_argument("--regenerate", action="store_true",
                        help="Regenerate files even if they already exist")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max number of files to generate (0 = unlimited)")
    parser.add_argument("--all", action="store_true",
                        help="Generate all lines, not just the demo whitelist")
    args = parser.parse_args()

    # Load CSV
    if not os.path.exists(args.csv):
        print(f"Error: CSV file not found: {args.csv}")
        sys.exit(1)

    with open(args.csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        all_lines = list(reader)

    print(f"Loaded {len(all_lines)} lines from {args.csv}")

    # Filter to demo lines unless --all
    if not args.all:
        lines = []
        for row in all_lines:
            key3 = (row['func_id'], row['offset_key'], int(row['segment']))
            # Check both gendered and ungendered whitelist entries
            key_female = key3 + ("female",)
            key_male = key3 + ("male",)
            if key3 in DEMO_LINES:
                lines.append(row)
            elif key_female in DEMO_LINES and args.player_gender == "female":
                lines.append(row)
            elif key_male in DEMO_LINES and args.player_gender == "male":
                lines.append(row)
        # Count non-gendered + matching-gender entries for display
        active_count = sum(1 for e in DEMO_LINES
                           if len(e) == 3
                           or (len(e) == 4 and e[3] == args.player_gender))
        print(f"Filtered to {len(lines)} demo lines ({active_count} active in whitelist)")
    else:
        lines = all_lines
        print(f"Generating all {len(lines)} lines")

    # Resolve placeholders and validate
    to_generate = []
    errors = []
    for row in lines:
        text = resolve_placeholders(row['text'], args.player_name, args.player_gender)

        # Check for unresolved placeholders
        unresolved = check_unresolved_placeholders(text)
        if unresolved:
            errors.append((row, unresolved))
            continue

        # Strip surrounding quotes from display text (CSV quoting artifact)
        text = text.strip('"')

        # Determine voice
        speaker = row.get('speaker', '') or row.get('npc', '')
        if speaker and speaker in VOICE_MAP:
            voice_id, voice_desc = VOICE_MAP[speaker]
        elif row['func_id'] in FUNC_VOICE_FALLBACK:
            speaker, voice_id, voice_desc = FUNC_VOICE_FALLBACK[row['func_id']]
        else:
            voice_id, voice_desc = DEFAULT_VOICE

        filename = voice_filename(row['func_id'], row['offset_key'],
                                  int(row['segment']))

        to_generate.append({
            'filename': filename,
            'speaker': speaker,
            'voice_id': voice_id,
            'voice_desc': voice_desc,
            'text': text,
            'has_var': row['has_var'] == 'True',
            'func_id': row['func_id'],
            'offset_key': row['offset_key'],
            'segment': row['segment'],
        })

    if errors:
        print(f"\nERROR: {len(errors)} lines have unresolved placeholders:")
        for row, unresolved in errors:
            print(f"  {row['func_id']} {row['offset_key']}:{row['segment']} "
                  f"- unresolved: {', '.join(unresolved)}")
            print(f"    Text: \"{row['text'][:80]}...\"")
        print("\nFix the placeholders or add --player-name/--player-gender args.")
        sys.exit(1)

    # Compute previous_text / next_text context for each line.
    # Links consecutive lines from the same speaker within the same function
    # to help ElevenLabs maintain voice continuity.
    for i, item in enumerate(to_generate):
        item['prev_text'] = None
        item['next_text'] = None
        if i > 0:
            prev = to_generate[i - 1]
            if (prev['func_id'] == item['func_id']
                    and prev['speaker'] == item['speaker']):
                item['prev_text'] = prev['text']
        if i + 1 < len(to_generate):
            nxt = to_generate[i + 1]
            if (nxt['func_id'] == item['func_id']
                    and nxt['speaker'] == item['speaker']):
                item['next_text'] = nxt['text']

    # Dry run: show what would be generated
    if args.dry_run:
        print(f"\n{'Filename':<25} {'Speaker':<10} {'Voice':<22} {'prev_text':<22} {'text':<42} {'next_text':<22}")
        print("-" * 145)
        for item in to_generate:
            text_preview = item['text'][:40] + (".." if len(item['text']) > 40 else "")
            if item['prev_text']:
                prev_preview = ".." + item['prev_text'][-18:]
            else:
                prev_preview = ""
            if item['next_text']:
                next_preview = item['next_text'][:18] + ".."
            else:
                next_preview = ""
            print(f"{item['filename']:<25} {item['speaker']:<10} "
                  f"{item['voice_desc']:<22} {prev_preview:<22} {text_preview:<42} {next_preview:<22}")
        print(f"\nTotal: {len(to_generate)} voice lines to generate")

        # Estimate character count for API credits
        total_chars = sum(len(item['text']) for item in to_generate)
        print(f"Total characters: {total_chars:,}")
        return

    # Generate
    api_key = load_api_key()
    if not api_key:
        print("Error: ELEVENLABS_API_KEY not set.")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    total = len(to_generate)
    generated = 0
    skipped = 0
    failed = 0

    for i, item in enumerate(to_generate, 1):
        output_path = os.path.join(args.output_dir, item['filename'])

        print(f"[{i}/{total}] {item['speaker']}: {item['filename']}")
        print(f"  Text: \"{item['text'][:70]}{'...' if len(item['text']) > 70 else ''}\"")

        if not args.regenerate and os.path.exists(output_path):
            print("  -> Skipped (already exists)")
            skipped += 1
            continue

        if args.limit and generated >= args.limit:
            print("  -> Skipped (limit reached)")
            skipped += 1
            continue

        if generate_speech(api_key, item['voice_id'], item['text'], output_path,
                           previous_text=item['prev_text'],
                           next_text=item['next_text']):
            size_kb = os.path.getsize(output_path) / 1024
            print(f"  -> Generated ({size_kb:.1f} KB)")
            generated += 1
        else:
            print("  -> FAILED")
            failed += 1

        if i < total:
            time.sleep(1)

    print(f"\nDone: {generated} generated, {skipped} skipped, {failed} failed")
    if generated > 0:
        print(f"Voice files saved to: {args.output_dir}")


if __name__ == "__main__":
    main()
