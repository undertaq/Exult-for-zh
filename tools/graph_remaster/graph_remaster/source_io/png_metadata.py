"""Minimal PNG reader for indexed source fixtures and canonical RGBA previews."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PNGMetadataError(ValueError):
    """Raised when a source PNG cannot be inspected or normalized."""


@dataclass(frozen=True)
class PNGMetadata:
    width: int
    height: int
    indexed: bool
    has_alpha: bool
    offset: tuple[int, int]
    offset_implicit: bool
    palette: tuple[tuple[int, int, int], ...]
    indices: bytes


def read_png_offset(path: Path) -> tuple[int, int]:
    """Return the pixel offset from an oFFs chunk, or the implicit origin."""

    return read_png_metadata(path).offset


def read_png_metadata(path: Path) -> PNGMetadata:
    data = Path(path).read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise PNGMetadataError(f"not a PNG file: {path}")
    position = len(PNG_SIGNATURE)
    width = height = bit_depth = color_type = None
    palette: tuple[tuple[int, int, int], ...] = ()
    transparency = b""
    offset = (0, 0)
    offset_implicit = True
    image_data = bytearray()
    saw_ihdr = saw_plte = saw_idat = saw_iend = False
    while position < len(data):
        if position + 12 > len(data):
            raise PNGMetadataError(f"truncated PNG chunk: {path}")
        length = struct.unpack(">I", data[position:position + 4])[0]
        chunk_type = data[position + 4:position + 8]
        end = position + 12 + length
        if end > len(data):
            raise PNGMetadataError(f"truncated PNG chunk data: {path}")
        payload = data[position + 8:position + 8 + length]
        expected_crc = struct.unpack(">I", data[end - 4:end])[0]
        actual_crc = zlib.crc32(chunk_type + payload) & 0xffffffff
        if actual_crc != expected_crc:
            raise PNGMetadataError(f"invalid {chunk_type.decode('ascii', 'replace')} chunk CRC: {path}")
        if chunk_type == b"IHDR":
            if saw_ihdr or position != len(PNG_SIGNATURE) or length != 13:
                raise PNGMetadataError(f"invalid IHDR chunk: {path}")
            saw_ihdr = True
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(">IIBBBBB", payload)
            if not width or not height or compression or filter_method or interlace:
                raise PNGMetadataError(f"unsupported PNG encoding: {path}")
        elif chunk_type == b"PLTE":
            if not saw_ihdr or saw_plte or saw_idat or len(payload) % 3 or not payload:
                raise PNGMetadataError(f"invalid indexed palette: {path}")
            saw_plte = True
            palette = tuple(tuple(payload[index:index + 3]) for index in range(0, len(payload), 3))
        elif chunk_type == b"tRNS":
            if not saw_plte or saw_idat:
                raise PNGMetadataError(f"invalid tRNS chunk order: {path}")
            transparency = payload
        elif chunk_type == b"oFFs":
            if length != 9:
                raise PNGMetadataError(f"invalid oFFs chunk: {path}")
            x, y, unit = struct.unpack(">iiB", payload)
            if unit != 0:
                raise PNGMetadataError(f"unsupported oFFs unit: {path}")
            offset = (x, y)
            offset_implicit = False
        elif chunk_type == b"IDAT":
            if not saw_ihdr or not saw_plte:
                raise PNGMetadataError(f"invalid IDAT chunk order: {path}")
            saw_idat = True
            image_data.extend(payload)
        elif chunk_type == b"IEND":
            if length != 0 or not saw_idat:
                raise PNGMetadataError(f"invalid IEND chunk: {path}")
            saw_iend = True
            position = end
            if position != len(data):
                raise PNGMetadataError(f"trailing data after IEND: {path}")
            break
        position = end
    if not saw_iend or width is None or height is None or bit_depth is None or color_type is None:
        raise PNGMetadataError(f"missing IHDR chunk: {path}")
    if color_type != 3 or bit_depth != 8 or not palette:
        raise PNGMetadataError(f"expected 8-bit indexed PNG with palette: {path}")
    try:
        decoded = zlib.decompress(image_data)
    except zlib.error as exc:
        raise PNGMetadataError(f"invalid PNG image data: {path}") from exc
    indices = _unfilter(decoded, width, height)
    if any(index >= len(palette) for index in indices):
        raise PNGMetadataError(f"palette index outside PLTE: {path}")
    return PNGMetadata(
        width=width,
        height=height,
        indexed=True,
        has_alpha=bool(transparency),
        offset=offset,
        offset_implicit=offset_implicit,
        palette=palette,
        indices=indices,
    )


def write_rgba_preview(source: Path, target: Path) -> PNGMetadata:
    """Decode one indexed source PNG into a separate standards-compliant RGBA PNG."""

    metadata = read_png_metadata(source)
    rgba = bytearray()
    alpha = _transparency(source)
    for index in metadata.indices:
        rgba.extend(metadata.palette[index])
        rgba.append(alpha[index] if index < len(alpha) else 255)
    raw = b"".join(b"\0" + rgba[row * metadata.width * 4:(row + 1) * metadata.width * 4] for row in range(metadata.height))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        PNG_SIGNATURE
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", metadata.width, metadata.height, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )
    return metadata


def _transparency(source: Path) -> bytes:
    data = Path(source).read_bytes()
    position = len(PNG_SIGNATURE)
    while position + 12 <= len(data):
        length = struct.unpack(">I", data[position:position + 4])[0]
        chunk_type = data[position + 4:position + 8]
        if chunk_type == b"tRNS":
            return data[position + 8:position + 8 + length]
        position += 12 + length
    return b""


def _unfilter(data: bytes, width: int, height: int) -> bytes:
    expected = height * (width + 1)
    if len(data) != expected:
        raise PNGMetadataError("indexed PNG has unexpected scanline length")
    rows: list[bytearray] = []
    position = 0
    for _ in range(height):
        filter_type = data[position]
        row = bytearray(data[position + 1:position + 1 + width])
        prior = rows[-1] if rows else bytearray(width)
        for index in range(width):
            left = row[index - 1] if index else 0
            up = prior[index]
            up_left = prior[index - 1] if index else 0
            if filter_type == 1:
                row[index] = (row[index] + left) & 0xff
            elif filter_type == 2:
                row[index] = (row[index] + up) & 0xff
            elif filter_type == 3:
                row[index] = (row[index] + ((left + up) // 2)) & 0xff
            elif filter_type == 4:
                row[index] = (row[index] + _paeth(left, up, up_left)) & 0xff
            elif filter_type != 0:
                raise PNGMetadataError("unsupported PNG scanline filter")
        rows.append(row)
        position += width + 1
    return bytes().join(rows)


def _paeth(left: int, up: int, up_left: int) -> int:
    prediction = left + up - up_left
    distances = (abs(prediction - left), abs(prediction - up), abs(prediction - up_left))
    return (left, up, up_left)[distances.index(min(distances))]


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
