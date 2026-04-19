"""
WAV file metadata utilities for voice acting files.

Reads and writes LIST INFO chunks in WAV files to store:
  - INAM (title): hash of the text for exact matching
  - IART (artist): voice source identifier (e.g., "elevenlabs:<voice_id>")
  - ICMT (comment): the full text sent to TTS

The WAV parser in Exult safely skips unknown chunks, so this metadata
does not affect playback.
"""

import hashlib
import struct


def text_hash(text):
    """Compute a stable hash of the text for matching."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def make_artist_tag(voice_id):
    """Create an artist tag from a voice ID."""
    return f"elevenlabs:{voice_id}"


def parse_artist_tag(artist):
    """Extract voice source and ID from an artist tag."""
    if ":" in artist:
        source, vid = artist.split(":", 1)
        return source, vid
    return "unknown", artist


def _pad_to_even(data):
    """WAV chunks must be word-aligned (even byte count)."""
    if len(data) % 2 != 0:
        return data + b"\x00"
    return data


def _make_info_chunk(tag, value):
    """Create a single INFO sub-chunk."""
    encoded = value.encode("utf-8") + b"\x00"  # null-terminated
    padded = _pad_to_even(encoded)
    return tag.encode("ascii") + struct.pack("<I", len(encoded)) + padded


def create_list_info(title="", artist="", comment=""):
    """Create a LIST INFO chunk with the given metadata."""
    info_data = b""
    if title:
        info_data += _make_info_chunk("INAM", title)
    if artist:
        info_data += _make_info_chunk("IART", artist)
    if comment:
        info_data += _make_info_chunk("ICMT", comment)

    if not info_data:
        return b""

    list_type = b"INFO"
    list_payload = list_type + info_data
    return b"LIST" + struct.pack("<I", len(list_payload)) + list_payload


def read_wav_metadata(filepath):
    """Read metadata from a WAV file's LIST INFO chunk.

    Returns dict with keys: title, artist, comment (empty string if not found).
    """
    result = {"title": "", "artist": "", "comment": ""}

    try:
        with open(filepath, "rb") as f:
            data = f.read()
    except (IOError, OSError):
        return result

    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return result

    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos:pos + 4]
        chunk_size = struct.unpack_from("<I", data, pos + 4)[0]
        chunk_data_start = pos + 8

        if chunk_id == b"LIST" and chunk_size >= 4:
            list_type = data[chunk_data_start:chunk_data_start + 4]
            if list_type == b"INFO":
                _parse_info_subchunks(
                    data, chunk_data_start + 4,
                    chunk_data_start + chunk_size, result)

        # Move to next chunk (word-aligned)
        pos = chunk_data_start + chunk_size
        if pos % 2 != 0:
            pos += 1

    return result


def _parse_info_subchunks(data, start, end, result):
    """Parse INFO sub-chunks within a LIST chunk."""
    tag_map = {b"INAM": "title", b"IART": "artist", b"ICMT": "comment"}
    pos = start
    while pos + 8 <= end:
        tag = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        value_start = pos + 8
        value_end = min(value_start + size, end)

        if tag in tag_map:
            value = data[value_start:value_end]
            # Strip the null terminator and any even-alignment padding nulls.
            value = value.rstrip(b"\x00")
            result[tag_map[tag]] = value.decode("utf-8", errors="replace")

        # Word-align
        pos = value_end
        if pos % 2 != 0:
            pos += 1


def add_metadata_to_wav(filepath, title="", artist="", comment=""):
    """Add LIST INFO metadata to an existing WAV file.

    Replaces any existing LIST INFO chunk. Preserves all other chunks.
    """
    with open(filepath, "rb") as f:
        data = f.read()

    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"Not a valid WAV file: {filepath}")

    # Collect all chunks except existing LIST INFO
    chunks = []
    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos:pos + 4]
        chunk_size = struct.unpack_from("<I", data, pos + 4)[0]
        chunk_end = pos + 8 + chunk_size
        if chunk_end % 2 != 0:
            chunk_end += 1  # word-align

        is_list_info = False
        if chunk_id == b"LIST" and chunk_size >= 4:
            list_type = data[pos + 8:pos + 12]
            if list_type == b"INFO":
                is_list_info = True

        if not is_list_info:
            chunks.append(data[pos:min(chunk_end, len(data))])

        pos = chunk_end

    # Build new LIST INFO chunk
    info_chunk = create_list_info(title, artist, comment)

    # Reassemble WAV
    wave_body = b"WAVE"
    for chunk in chunks:
        wave_body += chunk
    if info_chunk:
        wave_body += info_chunk

    new_data = b"RIFF" + struct.pack("<I", len(wave_body)) + wave_body

    with open(filepath, "wb") as f:
        f.write(new_data)


def write_wav_with_metadata(filepath, pcm_data, sample_rate=22050,
                            bits_per_sample=16, num_channels=1,
                            title="", artist="", comment=""):
    """Write a WAV file with PCM data and embedded metadata."""
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(pcm_data)

    # fmt chunk
    fmt_chunk = b"fmt " + struct.pack(
        "<IHHIIHH", 16, 1, num_channels,
        sample_rate, byte_rate, block_align, bits_per_sample)

    # data chunk
    data_chunk = b"data" + struct.pack("<I", data_size) + pcm_data

    # LIST INFO chunk
    info_chunk = create_list_info(title, artist, comment)

    # Assemble
    wave_body = b"WAVE" + fmt_chunk + data_chunk + info_chunk

    with open(filepath, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(wave_body)) + wave_body)
