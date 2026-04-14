#!/usr/bin/env python3
"""
Generate voice audio files from a prepared manifest CSV.

Reads the manifest produced by prepare_voice_lines.py and calls
the ElevenLabs TTS API to generate WAV files.

Usage:
    python generate_voices.py --manifest manifest.csv \
        -o "path/to/patch/voice_acting"

Set ELEVENLABS_API_KEY in environment or in a .env file.
"""

import argparse
import csv
import datetime
import os
import shutil
import struct
import sys
import time

try:
    import requests
except ImportError:
    print("Error: 'requests' package required. Install with: pip install requests")
    sys.exit(1)

from wav_metadata import (text_hash, make_artist_tag,
                           write_wav_with_metadata)

# ElevenLabs API
API_BASE = "https://api.elevenlabs.io/v1"

# Voice settings
VOICE_SETTINGS = {
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.4,
    "use_speaker_boost": True,
}


def generate_speech(api_key, voice_id, text, output_path,
                    previous_text=None, next_text=None):
    """Call ElevenLabs TTS API and save as WAV with embedded metadata."""
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

    response = requests.post(url, json=payload, headers=headers, timeout=60)

    if response.status_code == 200:
        write_wav_with_metadata(
            output_path, response.content,
            title=text_hash(text),
            artist=make_artist_tag(voice_id),
            comment=text)
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
        description="Generate voice audio from a manifest CSV"
    )
    parser.add_argument("--manifest", "-m", required=True,
                        help="Path to manifest CSV (from prepare_voice_lines.py)")
    parser.add_argument("--output-dir", "-o", required=True,
                        help="Output directory for WAV files")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Show what would be generated without calling API")
    parser.add_argument("--regenerate", action="store_true",
                        help="Regenerate files even if they already exist")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max number of files to generate (0 = unlimited)")
    parser.add_argument("--ledger", default=None,
                        help="Path to generation ledger CSV (default: <output_dir>/generation_ledger.csv)")
    args = parser.parse_args()

    # Load manifest
    with open(args.manifest, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        manifest = list(reader)

    print(f"Loaded {len(manifest)} lines from {args.manifest}")

    if args.dry_run:
        would_generate = 0
        would_copy = 0
        would_skip = 0
        total_chars = 0
        seen_pairs = {}  # (voice_id, text) -> filename
        for item in manifest:
            filepath = os.path.join(args.output_dir, item["filename"])
            exists = os.path.exists(filepath)
            pair_key = (item["voice_id"], item["text"])

            if not args.regenerate and exists:
                status = "SKIP (exists)"
                would_skip += 1
            elif args.limit and would_generate >= args.limit:
                status = "SKIP (limit)"
                would_skip += 1
            elif pair_key in seen_pairs:
                status = f"COPY <- {seen_pairs[pair_key][:25]}"
                would_copy += 1
            else:
                status = "GENERATE"
                seen_pairs[pair_key] = item["filename"]
                would_generate += 1
                total_chars += len(item["text"])

            text_preview = item["text"][:40] + (".." if len(item["text"]) > 40 else "")
            print(f"  {status:<40} {item['filename']:<40} {item['speaker']:<12} "
                  f"{item['voice_desc']:<20} {text_preview}")

        print(f"\nWould generate: {would_generate} (API calls)")
        print(f"Would copy:     {would_copy} (duplicates)")
        print(f"Would skip:     {would_skip} (existing)")
        print(f"Total characters (API): {total_chars:,}")
        return

    api_key = load_api_key()
    if not api_key:
        print("Error: ELEVENLABS_API_KEY not set.")
        print("Set it in environment or in tools/voice_acting/.env")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    # Open generation ledger (append mode)
    ledger_path = args.ledger or os.path.join(args.output_dir, "generation_ledger.csv")
    ledger_is_new = not os.path.exists(ledger_path)
    ledger_file = open(ledger_path, "a", newline="", encoding="utf-8")
    ledger_writer = csv.writer(ledger_file)
    if ledger_is_new:
        ledger_writer.writerow([
            "timestamp", "filename", "voice_id", "voice_desc",
            "speaker", "text_hash", "action", "text"])

    total = len(manifest)
    generated = 0
    copied = 0
    skipped = 0
    failed = 0
    seen_pairs = {}  # (voice_id, text) -> output_path of first generation

    for i, item in enumerate(manifest, 1):
        output_path = os.path.join(args.output_dir, item["filename"])
        pair_key = (item["voice_id"], item["text"])

        print(f"[{i}/{total}] {item['speaker']}: {item['filename']}")
        print(f"  Voice: {item['voice_desc']}")
        print(f"  Text: \"{item['text'][:70]}{'...' if len(item['text']) > 70 else ''}\"")

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        thash = text_hash(item["text"])

        if not args.regenerate and os.path.exists(output_path):
            print("  -> Skipped (already exists)")
            if pair_key not in seen_pairs:
                seen_pairs[pair_key] = output_path
            skipped += 1
            continue

        if args.limit and generated >= args.limit:
            print("  -> Skipped (limit reached)")
            skipped += 1
            continue

        # Check if we already generated this exact voice+text pair
        if pair_key in seen_pairs:
            source_path = seen_pairs[pair_key]
            shutil.copy2(source_path, output_path)
            size_kb = os.path.getsize(output_path) / 1024
            print(f"  -> Copied from {os.path.basename(source_path)} ({size_kb:.1f} KB)")
            ledger_writer.writerow([
                now, item["filename"], item["voice_id"], item["voice_desc"],
                item["speaker"], thash, "copied", item["text"]])
            ledger_file.flush()
            copied += 1
            continue

        prev_text = item.get("prev_text", "") or None
        next_text = item.get("next_text", "") or None

        if generate_speech(api_key, item["voice_id"], item["text"],
                           output_path, previous_text=prev_text,
                           next_text=next_text):
            size_kb = os.path.getsize(output_path) / 1024
            print(f"  -> Generated ({size_kb:.1f} KB)")
            seen_pairs[pair_key] = output_path
            ledger_writer.writerow([
                now, item["filename"], item["voice_id"], item["voice_desc"],
                item["speaker"], thash, "generated", item["text"]])
            ledger_file.flush()
            generated += 1
        else:
            print("  -> FAILED")
            ledger_writer.writerow([
                now, item["filename"], item["voice_id"], item["voice_desc"],
                item["speaker"], thash, "failed", item["text"]])
            ledger_file.flush()
            failed += 1

        if i < total and generated < (args.limit or total):
            time.sleep(1)

    ledger_file.close()
    print(f"\nDone: {generated} generated, {copied} copied, "
          f"{skipped} skipped, {failed} failed")
    print(f"Ledger: {ledger_path}")
    if generated > 0:
        print(f"Voice files saved to: {args.output_dir}")


if __name__ == "__main__":
    main()
