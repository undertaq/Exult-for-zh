#!/usr/bin/env python3
"""
Convert a directory of WAV voice files to Ogg Vorbis, preserving the
LIST-INFO metadata chunks (INAM/IART/ICMT) as Vorbis comments
(TITLE/ARTIST/COMMENT).

Runs ffmpeg once per file. Idempotent: skips a file if the destination .ogg
already exists and is newer than the source WAV, unless --force is passed.

Usage:
    python convert_wavs_to_ogg.py \\
        --source "C:/Users/markg/Software/Temp/local_tts/output2" \\
        --dest   "C:/Program Files (x86)/GOG Galaxy/Games/Ultima 7/patch/voice_acting/second_source" \\
        --quality 2

Quality is the Vorbis -q:a value, 0-10. Rough bitrates for voice:
    0  ~48 kbps
    1  ~64 kbps
    2  ~96 kbps  (good default for speech)
    3  ~112 kbps
    5  ~160 kbps

ffmpeg is located by PATH, then falling back to a hardcoded Windows location
if the user has one of the essentials builds extracted.
"""

import argparse
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

from audio_metadata import read_audio_metadata

FFMPEG_FALLBACK = Path(
    r"C:\Users\markg\Downloads"
    r"\ffmpeg-2026-04-16-git-5abc240a27-essentials_build"
    r"\ffmpeg-2026-04-16-git-5abc240a27-essentials_build\bin\ffmpeg.exe")


def find_ffmpeg() -> Path:
    on_path = shutil.which("ffmpeg")
    if on_path:
        return Path(on_path)
    if FFMPEG_FALLBACK.exists():
        return FFMPEG_FALLBACK
    print("error: ffmpeg not found on PATH and the hardcoded fallback\n"
          f"       {FFMPEG_FALLBACK}\n"
          "       does not exist. Install ffmpeg or edit the fallback path.",
          file=sys.stderr)
    sys.exit(1)


def convert_one(ffmpeg: Path, src: Path, dst: Path, quality: int) -> bool:
    """Run ffmpeg to transcode src -> dst with Vorbis comments from the WAV's
    LIST-INFO metadata. Returns True on success."""
    meta = read_audio_metadata(str(src))
    cmd = [
        str(ffmpeg),
        "-y",                     # overwrite destination (we already handle
                                  # skip logic ourselves)
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(src),
        "-c:a", "libvorbis",
        "-q:a", str(quality),
    ]
    # Vorbis comment tags use capital keys. Mapping from LIST-INFO:
    #   INAM (title)    -> TITLE        (sha256 prefix hash of text)
    #   IART (artist)   -> ARTIST       ("elevenlabs:<voice_id>")
    #   ICMT (comment)  -> DESCRIPTION  (full text)
    # DESCRIPTION is the Vorbis standard long-form-text field. ffmpeg also
    # maps its internal COMMENT tag to DESCRIPTION on Vorbis output, so we
    # use DESCRIPTION directly.
    if meta["title"]:
        cmd += ["-metadata", f"TITLE={meta['title']}"]
    if meta["artist"]:
        cmd += ["-metadata", f"ARTIST={meta['artist']}"]
    if meta["comment"]:
        cmd += ["-metadata", f"DESCRIPTION={meta['comment']}"]
    cmd.append(str(dst))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  FAILED: {src.name}")
        if result.stderr:
            print(f"    ffmpeg stderr: {result.stderr.strip()[:300]}")
        # Clean up partial output so we can retry cleanly.
        if dst.exists():
            try: dst.unlink()
            except OSError: pass
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", "-s", required=True,
                    help="Directory of input WAV files")
    ap.add_argument("--dest", "-d", required=True,
                    help="Directory for output OGG files (created if needed)")
    ap.add_argument("--quality", "-q", type=int, default=2,
                    help="Vorbis -q:a value, 0-10 (default 2 ~= 96 kbps)")
    ap.add_argument("--limit", type=int, default=0,
                    help="Max number of files to convert (0 = unlimited)")
    ap.add_argument("--force", action="store_true",
                    help="Re-encode even if destination .ogg is up to date")
    ap.add_argument("--dry-run", "-n", action="store_true",
                    help="List what would be converted without running ffmpeg")
    ap.add_argument("--log", default=None,
                    help="Optional CSV log of conversion results "
                         "(appends if it exists)")
    args = ap.parse_args()

    if not 0 <= args.quality <= 10:
        print(f"error: --quality must be 0..10, got {args.quality}",
              file=sys.stderr)
        return 2

    src_dir = Path(args.source)
    dst_dir = Path(args.dest)
    if not src_dir.is_dir():
        print(f"error: source dir not found: {src_dir}", file=sys.stderr)
        return 1

    ffmpeg = find_ffmpeg()
    print(f"ffmpeg: {ffmpeg}")
    dst_dir.mkdir(parents=True, exist_ok=True)

    wavs = sorted(p for p in src_dir.iterdir()
                  if p.is_file() and p.suffix.lower() == ".wav")
    print(f"Found {len(wavs)} WAV files in {src_dir}")
    print(f"Quality: -q:a {args.quality}")

    log_file = None
    log_writer = None
    if args.log and not args.dry_run:
        log_path = Path(args.log)
        log_new = not log_path.exists()
        log_file = open(log_path, "a", newline="", encoding="utf-8")
        log_writer = csv.writer(log_file)
        if log_new:
            log_writer.writerow([
                "source", "dest", "quality", "src_bytes",
                "dst_bytes", "ratio", "status"])

    converted = skipped = failed = 0
    total_src_bytes = 0
    total_dst_bytes = 0

    for i, src in enumerate(wavs, 1):
        if args.limit and converted >= args.limit:
            break
        dst = dst_dir / (src.stem + ".ogg")
        if (not args.force and dst.exists()
                and dst.stat().st_mtime >= src.stat().st_mtime):
            skipped += 1
            continue

        if args.dry_run:
            print(f"  [{i}/{len(wavs)}] would convert {src.name}")
            converted += 1
            continue

        print(f"[{i}/{len(wavs)}] {src.name} -> {dst.name}", end="", flush=True)
        ok = convert_one(ffmpeg, src, dst, args.quality)
        if not ok:
            failed += 1
            if log_writer:
                log_writer.writerow([str(src), str(dst), args.quality,
                                     src.stat().st_size, 0, "", "failed"])
            continue

        src_bytes = src.stat().st_size
        dst_bytes = dst.stat().st_size
        total_src_bytes += src_bytes
        total_dst_bytes += dst_bytes
        ratio = src_bytes / dst_bytes if dst_bytes else 0
        print(f"  ({src_bytes // 1024} KB -> {dst_bytes // 1024} KB, "
              f"{ratio:.1f}x)")
        if log_writer:
            log_writer.writerow([str(src), str(dst), args.quality,
                                 src_bytes, dst_bytes, f"{ratio:.2f}",
                                 "ok"])
        converted += 1

    if log_file:
        log_file.close()

    print()
    print(f"Converted: {converted}")
    print(f"Skipped:   {skipped}")
    print(f"Failed:    {failed}")
    if total_src_bytes > 0:
        overall = total_src_bytes / total_dst_bytes if total_dst_bytes else 0
        print(f"Size:      {total_src_bytes / 1024 / 1024:.1f} MB WAV -> "
              f"{total_dst_bytes / 1024 / 1024:.1f} MB OGG "
              f"({overall:.1f}x smaller)")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
