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

from audio_metadata import (text_hash, make_artist_tag,
                            read_audio_metadata, parse_artist_tag)


def select_per_npc_lines(manifest, output_dir, n_per_npc):
    """Pick up to N lines per speaker for a sampling run.

    Selection rules:
    - Skip any speaker that already has at least one WAV matching one of
      their manifest rows on disk. This lets the user re-run the sampling
      command to pick up newly-added NPCs without regenerating existing
      samples.
    - For the remaining speakers, keep the longest N lines (by text length).
      Longest lines tend to be the most vocally distinctive and give the
      listener more character to judge the voice on.
    - Multi-NPC variants of the same say() count separately: each NPC gets
      their own N.

    Returns the filtered manifest list in the original order, for stable
    prev_text/next_text continuity where possible.
    """
    # Index by speaker
    by_speaker = {}
    for item in manifest:
        by_speaker.setdefault(item.get("speaker", ""), []).append(item)

    # Decide which speakers to include
    chosen_keys = set()  # set of (speaker, filename) entries to keep
    skipped_existing = []
    newly_sampled = []
    for speaker, items in by_speaker.items():
        if not speaker:
            continue
        has_existing = any(
            os.path.exists(os.path.join(output_dir,
                                        normalize_output_filename(it["filename"])))
            for it in items
        )
        if has_existing:
            skipped_existing.append(speaker)
            continue
        # Pick longest N lines for this speaker
        ranked = sorted(items, key=lambda x: -len(x.get("text", "")))
        picks = ranked[:n_per_npc]
        for p in picks:
            chosen_keys.add((speaker, p["filename"]))
        newly_sampled.append((speaker, len(picks)))

    print(f"  Speakers skipped (already have WAVs): {len(skipped_existing)}")
    print(f"  Speakers newly sampled: {len(newly_sampled)}")
    if newly_sampled:
        preview = ", ".join(f"{s}({n})" for s, n in newly_sampled[:10])
        print(f"    e.g. {preview}"
              f"{'...' if len(newly_sampled) > 10 else ''}")

    return [it for it in manifest
            if (it.get("speaker", ""), it["filename"]) in chosen_keys]


def normalize_output_filename(filename):
    """Force the manifest's filename to .ogg. Old manifests produced before
    the OGG switch have .wav entries; the generator always writes .ogg now
    so callers only need to see .ogg names."""
    if filename.lower().endswith(".wav"):
        return filename[:-4] + ".ogg"
    if filename.lower().endswith(".ogg"):
        return filename
    return filename + ".ogg"


def existing_file_state(output_path, voice_id, text):
    """Classify an existing audio file against the current manifest entry.

    Returns one of:
      - "missing"      - file does not exist
      - "fresh"        - file matches current voice_id and text
      - "stale_voice"  - file exists but was generated with a different voice
      - "stale_text"   - file exists but was generated for different text
      - "no_metadata"  - file exists but has no readable metadata
                         (pre-metadata generation)
    """
    if not os.path.exists(output_path):
        return "missing"
    meta = read_audio_metadata(output_path)
    if not meta.get("artist") and not meta.get("title"):
        return "no_metadata"
    if meta.get("artist"):
        _, existing_vid = parse_artist_tag(meta["artist"])
        if existing_vid and existing_vid != voice_id:
            return "stale_voice"
    if meta.get("title"):
        if meta["title"] != text_hash(text):
            return "stale_text"
    return "fresh"

# ElevenLabs API
API_BASE = "https://api.elevenlabs.io/v1"

# Voice settings
VOICE_SETTINGS = {
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.4,
    "use_speaker_boost": True,
}


import shutil
import subprocess

FFMPEG_FALLBACK = (
    r"C:\Users\markg\Downloads"
    r"\ffmpeg-2026-04-16-git-5abc240a27-essentials_build"
    r"\ffmpeg-2026-04-16-git-5abc240a27-essentials_build\bin\ffmpeg.exe")

_ffmpeg_path = None


def _find_ffmpeg():
    global _ffmpeg_path
    if _ffmpeg_path is not None:
        return _ffmpeg_path
    on_path = shutil.which("ffmpeg")
    if on_path:
        _ffmpeg_path = on_path
    elif os.path.exists(FFMPEG_FALLBACK):
        _ffmpeg_path = FFMPEG_FALLBACK
    else:
        print("Error: ffmpeg not found on PATH and fallback path is missing.",
              file=sys.stderr)
        sys.exit(1)
    return _ffmpeg_path


def generate_speech(api_key, voice_id, text, output_path,
                    previous_text=None, next_text=None, ogg_quality=4):
    """Call ElevenLabs TTS API, pipe raw PCM through ffmpeg, and save as
    Ogg Vorbis with embedded Vorbis comments (TITLE/ARTIST/DESCRIPTION).

    Note: DESCRIPTION is used rather than COMMENT because ffmpeg's default
    behaviour is to store passed-in COMMENT tags as DESCRIPTION in the Vorbis
    container. We use DESCRIPTION directly for clarity.
    """
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

    if response.status_code != 200:
        print(f"  API error {response.status_code}: {response.text[:200]}")
        return False

    ffmpeg = _find_ffmpeg()
    # ElevenLabs returns raw 16-bit little-endian mono PCM at 22050 Hz.
    cmd = [
        ffmpeg,
        "-y", "-hide_banner", "-loglevel", "error",
        "-f", "s16le", "-ar", "22050", "-ac", "1",
        "-i", "pipe:0",
        "-c:a", "libvorbis",
        "-q:a", str(ogg_quality),
        "-metadata", f"TITLE={text_hash(text)}",
        "-metadata", f"ARTIST={make_artist_tag(voice_id)}",
        "-metadata", f"DESCRIPTION={text}",
        output_path,
    ]
    result = subprocess.run(cmd, input=response.content,
                            capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        print(f"  ffmpeg error: {stderr[:300]}")
        # Clean up partial output
        if os.path.exists(output_path):
            try: os.unlink(output_path)
            except OSError: pass
        return False
    return True


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
    parser.add_argument("--per-npc", type=int, default=0,
                        help="If set, generate at most N lines per speaker "
                             "(longest lines chosen first). Speakers that "
                             "already have one or more generated WAV files "
                             "in the output dir are skipped entirely.")
    parser.add_argument("--only-stale", action="store_true",
                        help="Only (re)generate files that already exist but "
                             "are stale (voice_id or text changed). Skips "
                             "lines with no file on disk - useful for "
                             "correcting a known set of out-of-date files "
                             "without adding new ones.")
    parser.add_argument("--ogg-quality", type=int, default=4,
                        help="Vorbis -q:a value, 0-10 (default 4).")
    parser.add_argument("--ledger", default=None,
                        help="Path to generation ledger CSV (default: <output_dir>/generation_ledger.csv)")
    args = parser.parse_args()

    # Load manifest
    with open(args.manifest, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        manifest = list(reader)

    print(f"Loaded {len(manifest)} lines from {args.manifest}")

    # Optional sampling: restrict to N lines per speaker, skipping speakers
    # that already have any WAV on disk. Used for the "get a sample voice
    # line from everyone" workflow.
    if args.per_npc > 0:
        manifest = select_per_npc_lines(manifest, args.output_dir, args.per_npc)
        print(f"Sampling: {len(manifest)} lines after --per-npc filter")

    # Optional: restrict to stale lines (existing files whose voice_id or
    # text no longer matches the manifest). This mode implies --regenerate
    # because the whole point is to overwrite in place.
    if args.only_stale:
        stale = []
        for item in manifest:
            p = os.path.join(args.output_dir,
                             normalize_output_filename(item["filename"]))
            state = existing_file_state(p, item["voice_id"], item["text"])
            if state in ("stale_voice", "stale_text"):
                stale.append(item)
        print(f"--only-stale: {len(stale)} files out of {len(manifest)} "
              "are stale and will be regenerated")
        manifest = stale
        # Without this, the safety check we added earlier would refuse to run.
        args.regenerate = True

    if args.dry_run:
        would_generate = 0
        would_copy = 0
        would_skip = 0
        would_refresh_voice = 0
        would_refresh_text = 0
        total_chars = 0
        seen_pairs = {}  # (voice_id, text) -> filename
        for item in manifest:
            filepath = os.path.join(args.output_dir,
                                    normalize_output_filename(item["filename"]))
            pair_key = (item["voice_id"], item["text"])

            state = existing_file_state(
                filepath, item["voice_id"], item["text"])
            is_fresh = state in ("fresh", "no_metadata")
            # Treat "no_metadata" as fresh-enough so we don't re-bill for old
            # untagged files. Use --regenerate if you want to refresh those.

            if not args.regenerate and is_fresh:
                status = "SKIP (fresh)"
                would_skip += 1
            elif args.limit and would_generate >= args.limit:
                status = "SKIP (limit)"
                would_skip += 1
            elif pair_key in seen_pairs:
                status = f"COPY <- {seen_pairs[pair_key][:25]}"
                would_copy += 1
            else:
                if state == "stale_voice":
                    status = "REGEN (voice changed)"
                    would_refresh_voice += 1
                elif state == "stale_text":
                    status = "REGEN (text changed)"
                    would_refresh_text += 1
                else:
                    status = "GENERATE"
                seen_pairs[pair_key] = item["filename"]
                would_generate += 1
                total_chars += len(item["text"])

            text_preview = item["text"][:40] + (".." if len(item["text"]) > 40 else "")
            print(f"  {status:<40} {item['filename']:<40} {item['speaker']:<12} "
                  f"{item['voice_desc']:<20} {text_preview}")

        print(f"\nWould generate: {would_generate} "
              f"(new: {would_generate - would_refresh_voice - would_refresh_text}, "
              f"voice-changed: {would_refresh_voice}, "
              f"text-changed: {would_refresh_text})")
        print(f"Would copy:     {would_copy} (duplicates)")
        print(f"Would skip:     {would_skip} (fresh)")
        print(f"Total characters (API): {total_chars:,}")
        return

    # Safety check: refuse to run if any existing files are stale (voice or
    # text changed). Forces the user to back them up first, so regeneration
    # never silently overwrites recoverable audio. Bypass with --regenerate
    # if you intentionally want to rewrite everything.
    if not args.regenerate:
        stale_voice = []
        stale_text = []
        for item in manifest:
            p = os.path.join(args.output_dir,
                             normalize_output_filename(item["filename"]))
            state = existing_file_state(p, item["voice_id"], item["text"])
            if state == "stale_voice":
                stale_voice.append(item)
            elif state == "stale_text":
                stale_text.append(item)

        total_stale = len(stale_voice) + len(stale_text)
        if total_stale > 0:
            print()
            print("=" * 70)
            print(f"REFUSING TO GENERATE: {total_stale} files on disk are stale")
            print("=" * 70)
            print(f"  voice changed: {len(stale_voice)}")
            print(f"  text changed:  {len(stale_text)}")
            print()
            preview = (stale_voice + stale_text)[:20]
            for item in preview:
                reason = ("voice" if item in stale_voice else "text")
                print(f"  [{reason:5s}] {item['filename']:<40} "
                      f"{item['speaker']:<15} {item['voice_desc']}")
            if total_stale > len(preview):
                print(f"  ...and {total_stale - len(preview)} more")
            print()
            print("These files would be overwritten without a chance to recover.")
            print("Back them up first, then re-run generation:")
            print()
            print(f"  python backup_stale_voices.py \\")
            print(f"    --manifest {args.manifest} \\")
            print(f"    --source \"{args.output_dir}\" \\")
            print(f"    --dest \"<your_backup_dir>\"")
            print()
            print("Or pass --regenerate to override this check and overwrite anyway.")
            sys.exit(2)

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
        out_filename = normalize_output_filename(item["filename"])
        output_path = os.path.join(args.output_dir, out_filename)
        pair_key = (item["voice_id"], item["text"])

        print(f"[{i}/{total}] {item['speaker']}: {out_filename}")
        print(f"  Voice: {item['voice_desc']}")
        print(f"  Text: \"{item['text'][:70]}{'...' if len(item['text']) > 70 else ''}\"")

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        thash = text_hash(item["text"])

        state = existing_file_state(
            output_path, item["voice_id"], item["text"])

        if not args.regenerate and state in ("fresh", "no_metadata"):
            if state == "no_metadata":
                print("  -> Skipped (exists, no metadata - use --regenerate "
                      "to refresh)")
            else:
                print("  -> Skipped (fresh)")
            if pair_key not in seen_pairs:
                seen_pairs[pair_key] = output_path
            skipped += 1
            continue

        if state == "stale_voice":
            print(f"  -> Regenerating: voice changed "
                  f"(existing file has a different voice_id)")
        elif state == "stale_text":
            print(f"  -> Regenerating: text changed "
                  f"(existing file has a different text hash)")

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
                           next_text=next_text,
                           ogg_quality=args.ogg_quality):
            size_kb = os.path.getsize(output_path) / 1024
            print(f"  -> Generated ({size_kb:.1f} KB)")
            seen_pairs[pair_key] = output_path
            action = {
                "stale_voice": "regenerated_voice_changed",
                "stale_text": "regenerated_text_changed",
            }.get(state, "generated")
            ledger_writer.writerow([
                now, item["filename"], item["voice_id"], item["voice_desc"],
                item["speaker"], thash, action, item["text"]])
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
