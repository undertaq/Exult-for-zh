"""Write canonical six-times RGBA masters and separate indexed previews."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from PIL import Image

from ..models import FrameKey, FrameRecord
from ..reporting import write_stage_html_report
from .masks import restore_source_alpha


DEFAULT_SCALE = 6


@dataclass(frozen=True)
class Palette:
    """An indexed compatibility palette and its transparent index, if any."""

    colors: tuple[tuple[int, int, int], ...]
    transparent_index: int | None = None

    def __post_init__(self) -> None:
        if not 1 <= len(self.colors) <= 256:
            raise ValueError("palette must contain between 1 and 256 RGB colours")
        if self.transparent_index is not None and not 0 <= self.transparent_index < len(self.colors):
            raise ValueError("transparent palette index is outside the palette")
        if any(len(color) != 3 or any(not 0 <= channel <= 255 for channel in color) for color in self.colors):
            raise ValueError("palette colours must be RGB byte triples")


@dataclass(frozen=True)
class HDMaster:
    """The persisted canonical image and enough provenance to derive previews."""

    path: Path
    metadata_path: Path
    sha256: str
    offset: tuple[int, int]
    dimensions: tuple[int, int]
    frame: FrameKey


def scale_offset(xoff: int, yoff: int, scale: int = DEFAULT_SCALE) -> tuple[int, int]:
    """Scale logical PNG offsets into the canonical HD coordinate system."""

    if not isinstance(scale, int) or isinstance(scale, bool) or scale < 1:
        raise ValueError("scale must be a positive integer")
    return xoff * scale, yoff * scale


def write_hd_master(candidate: Image.Image, frame: FrameRecord, output: Path) -> HDMaster:
    """Crop a generated canvas, restore authoritative alpha, and persist RGBA.

    A recorded ``source_to_canvas.crop`` is a pixel-space ``[left, top,
    width, height]`` rectangle in the generated candidate.  If omitted, the
    candidate itself must already be the exact six-times target rectangle.
    """

    output, metadata_path, report_path = _master_artifact_paths(Path(output))
    try:
        scale = _frame_scale(frame)
        target_size = (frame.width * scale, frame.height * scale)
        cropped = _crop_candidate(candidate, frame.metadata.get("source_to_canvas"), target_size)
        source_alpha = _source_alpha(frame).resize(target_size, Image.Resampling.NEAREST)
        master_image = restore_source_alpha(cropped, source_alpha)

        output.parent.mkdir(parents=True, exist_ok=True)
        master_image.save(output, format="PNG", optimize=False, compress_level=9)
        digest = _sha256_file(output)
        offset = scale_offset(*_logical_offset(frame), scale)
        metadata = {
            "format": "graph-remaster-hd-master/v1",
            "source_key": _frame_key(frame.key),
            "dimensions": {"logical": [frame.width, frame.height], "hd": list(target_size), "scale": scale},
            "offset": {"logical": list(_logical_offset(frame)), "hd": list(offset)},
            "source_to_canvas": frame.metadata.get("source_to_canvas"),
            "hashes": {
                "candidate_rgba_sha256": _image_hash(cropped.convert("RGBA")),
                "source_alpha_sha256": sha256(source_alpha.tobytes()).hexdigest(),
                "master_png_sha256": digest,
                "master_rgba_sha256": _image_hash(master_image),
            },
        }
        _write_json(metadata_path, metadata)
        master = HDMaster(output, metadata_path, digest, offset, target_size, frame.key)
        write_stage_html_report(report_path, "Postprocess succeeded", {
            "stage": "postprocess", "status": "succeeded", "master_path": str(master.path),
            "metadata_path": str(master.metadata_path), "master_png_sha256": master.sha256,
        })
        return master
    except Exception as exc:
        write_stage_html_report(report_path, "Postprocess failed", {
            "stage": "postprocess", "status": "failed", "output_path": str(output), "error": str(exc),
        })
        raise


def _master_artifact_paths(output: Path) -> tuple[Path, Path, Path]:
    """Validate the canonical master name before any artifact can be written."""

    if output.suffix != ".png":
        raise ValueError("canonical HD master output must have a .png suffix")
    metadata_path = output.with_suffix(".json")
    report_path = output.with_suffix(".html")
    if len({path.resolve() for path in (output, metadata_path, report_path)}) != 3:
        raise ValueError("master PNG, metadata, and report paths must be distinct")
    return output, metadata_path, report_path


def write_indexed_preview(master: HDMaster, palette: Palette, output: Path) -> Path:
    """Write an indexed compatibility derivative without changing the master."""

    output = Path(output)
    if output.suffix.lower() != ".png":
        raise ValueError("indexed preview output must be a .png path")
    metadata_path = output.with_suffix(".json")
    master_artifacts = {master.path.resolve(), master.metadata_path.resolve()}
    if output.resolve() in master_artifacts or metadata_path.resolve() in master_artifacts:
        raise ValueError("indexed preview PNG/JSON pair must not overwrite master artifacts")
    with Image.open(master.path) as loaded:
        rgba = loaded.convert("RGBA")
    paletted = _quantize_to_palette(rgba, palette)
    output.parent.mkdir(parents=True, exist_ok=True)
    save_args: dict[str, Any] = {"format": "PNG", "optimize": False, "compress_level": 9}
    if palette.transparent_index is not None:
        save_args["transparency"] = palette.transparent_index
    paletted.save(output, **save_args)
    _write_json(metadata_path, {
        "format": "graph-remaster-indexed-preview/v1",
        "master_path": str(master.path),
        "master_png_sha256": master.sha256,
        "preview_path": str(output),
        "preview_png_sha256": _sha256_file(output),
        "palette_sha256": sha256(bytes(channel for color in palette.colors for channel in color)).hexdigest(),
        "transparent_index": palette.transparent_index,
        "quantization": _quantization_metrics(rgba, paletted, palette),
    })
    return output


def _frame_scale(frame: FrameRecord) -> int:
    value = frame.metadata.get("scale", DEFAULT_SCALE)
    if not isinstance(value, int) or isinstance(value, bool) or value != DEFAULT_SCALE:
        raise ValueError("canonical HD masters require frame metadata scale 6")
    return value


def _crop_candidate(candidate: Image.Image, transform: object, target_size: tuple[int, int]) -> Image.Image:
    image = candidate.convert("RGBA")
    # Backends may return either the original generation canvas or an already
    # extracted target.  The latter is unambiguous and must not be cropped a
    # second time merely because the frame retains its recorded transform.
    if image.size == target_size:
        return image
    if transform is None:
        raise ValueError("candidate dimensions must match the HD target when source_to_canvas is absent")
    if not isinstance(transform, dict) or set(transform) != {"crop"}:
        raise ValueError("source_to_canvas must contain only a pixel-space crop rectangle")
    crop = transform["crop"]
    if not isinstance(crop, (list, tuple)) or len(crop) != 4 or any(not isinstance(value, int) or isinstance(value, bool) for value in crop):
        raise ValueError("source_to_canvas crop must be [left, top, width, height] integers")
    left, top, width, height = crop
    if (width, height) != target_size or left < 0 or top < 0 or left + width > image.width or top + height > image.height:
        raise ValueError("source_to_canvas crop must be an in-bounds exact HD target")
    return image.crop((left, top, left + width, top + height))


def _source_alpha(frame: FrameRecord) -> Image.Image:
    source = frame.metadata.get("rgba_preview_path")
    if not isinstance(source, str) or not source:
        raise ValueError("frame metadata must include rgba_preview_path")
    with Image.open(source) as image:
        rgba = image.convert("RGBA")
    if rgba.size != (frame.width, frame.height):
        raise ValueError("source RGBA preview dimensions must match the frame")
    return rgba.getchannel("A")


def _logical_offset(frame: FrameRecord) -> tuple[int, int]:
    offset = frame.metadata.get("offset", [0, 0])
    if not isinstance(offset, (list, tuple)) or len(offset) != 2 or any(not isinstance(value, int) or isinstance(value, bool) for value in offset):
        raise ValueError("frame metadata offset must be a pair of integers")
    return offset[0], offset[1]


def _quantize_to_palette(image: Image.Image, palette: Palette) -> Image.Image:
    palette_image = Image.new("P", (1, 1))
    raw_palette = [channel for color in palette.colors for channel in color]
    palette_image.putpalette(raw_palette + [0] * (768 - len(raw_palette)))
    indexed = image.convert("RGB").quantize(palette=palette_image, dither=Image.Dither.NONE)
    if palette.transparent_index is not None:
        alpha = image.getchannel("A")
        pixels = indexed.load()
        for y in range(indexed.height):
            for x in range(indexed.width):
                if alpha.getpixel((x, y)) == 0:
                    pixels[x, y] = palette.transparent_index
    return indexed


def _quantization_metrics(source: Image.Image, indexed: Image.Image, palette: Palette) -> dict[str, float | int]:
    rgb = source.convert("RGB")
    alpha = source.getchannel("A")
    error = 0
    opaque = 0
    for y in range(source.height):
        for x in range(source.width):
            if alpha.getpixel((x, y)) == 0:
                continue
            colour = palette.colors[indexed.getpixel((x, y))]
            original = rgb.getpixel((x, y))
            error += sum((original[channel] - colour[channel]) ** 2 for channel in range(3))
            opaque += 1
    return {"pixels": source.width * source.height, "opaque_pixels": opaque, "mean_squared_error": error / (opaque * 3) if opaque else 0.0}


def _frame_key(key: FrameKey) -> dict[str, int | str]:
    return {"archive_sha256": key.archive_sha256, "archive_index": key.archive_index, "shape_id": key.shape_id, "frame_id": key.frame_id}


def _image_hash(image: Image.Image) -> str:
    return sha256(image.tobytes()).hexdigest()


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
