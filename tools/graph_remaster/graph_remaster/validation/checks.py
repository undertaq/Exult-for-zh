"""Small, named, deterministic checks for canonical remaster artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from PIL import Image, ImageChops

from ..controls.prepare import AtlasBundle
from ..models import FrameRecord


CANONICAL_SCALE = 6
CANONICAL_FLAT_TILE_SIZE = (8, 8)


@dataclass(frozen=True)
class CheckResult:
    """One inspectable validation outcome; failures are never collapsed away."""

    name: str
    passed: bool
    metrics: Mapping[str, int | float | str]
    threshold: int | float | str | None
    explanation: str
    blocking: bool = True

    @property
    def status(self) -> str:
        return "passed" if self.passed else "failed"

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "passed": self.passed,
            "blocking": self.blocking,
            "metrics": dict(self.metrics),
            "threshold": self.threshold,
            "explanation": self.explanation,
        }


def validate_dimensions(frame: FrameRecord, master: Image.Image) -> CheckResult:
    """Require exact six-times dimensions, including the canonical 48x48 tile."""

    scale = _scale(frame)
    expected = (frame.width * scale, frame.height * scale)
    passed = master.size == expected
    if _asset_type(frame) == "flat_tile":
        passed = passed and (frame.width, frame.height) == CANONICAL_FLAT_TILE_SIZE and expected == (48, 48)
    return CheckResult(
        "dimensions", passed,
        {"actual_width": master.width, "actual_height": master.height, "expected_width": expected[0], "expected_height": expected[1], "scale": scale},
        f"{expected[0]}x{expected[1]}",
        "master dimensions match the source frame at the canonical six-times scale" if passed else "master dimensions violate the source-derived six-times target",
    )


def validate_alpha(frame: FrameRecord, master: Image.Image) -> CheckResult:
    """Compare every master alpha pixel to nearest-neighbour source alpha."""

    expected_size = (frame.width * _scale(frame), frame.height * _scale(frame))
    try:
        expected = _source_rgba(frame).getchannel("A").resize(expected_size, Image.Resampling.NEAREST)
    except (OSError, ValueError) as exc:
        return CheckResult("alpha", False, {"mismatched_pixels": -1}, 0, f"source alpha is unavailable: {exc}")
    if master.size != expected.size:
        return CheckResult("alpha", False, {"mismatched_pixels": master.width * master.height}, 0, "master dimensions prevent alpha comparison")
    difference = ImageChops.difference(master.convert("RGBA").getchannel("A"), expected)
    mismatched = sum(value != 0 for value in difference.get_flattened_data())
    return CheckResult("alpha", mismatched == 0, {"mismatched_pixels": mismatched, "pixels": expected.width * expected.height}, 0, "master alpha exactly preserves the source silhouette" if mismatched == 0 else "master alpha differs from the source silhouette")


def validate_tile_grid(atlas: AtlasBundle, frame_set: Sequence[FrameRecord]) -> CheckResult:
    """Check flat-tile atlas dimensions, fixed 48px cells, and capacity."""

    cell_width = atlas.canvas.tile_width * atlas.scale
    cell_height = atlas.canvas.tile_height * atlas.scale
    expected = (atlas.canvas.columns * cell_width, atlas.canvas.rows * cell_height)
    frames_are_tiles = all((frame.width, frame.height) == CANONICAL_FLAT_TILE_SIZE for frame in frame_set)
    passed = (
        atlas.scale == CANONICAL_SCALE
        and (cell_width, cell_height) == (48, 48)
        and atlas.image.size == expected
        and len(frame_set) <= atlas.canvas.columns * atlas.canvas.rows
        and frames_are_tiles
    )
    return CheckResult(
        "tile_grid", passed,
        {"atlas_width": atlas.image.width, "atlas_height": atlas.image.height, "expected_width": expected[0], "expected_height": expected[1], "cell_width": cell_width, "cell_height": cell_height, "frame_count": len(frame_set), "capacity": atlas.canvas.columns * atlas.canvas.rows},
        "48x48 cells at scale 6",
        "flat tiles occupy an aligned canonical 48x48 grid" if passed else "flat tile atlas is not a canonical 6x/48x48 grid",
    )


def validate_animation_boxes(frames: Sequence[FrameRecord], masters: Sequence[Image.Image], tolerance: int) -> CheckResult:
    """Require one master per NPC frame and bounded foreground-box displacement."""

    if tolerance < 0:
        raise ValueError("animation box tolerance must be non-negative")
    count_matches = len(frames) == len(masters)
    drifts: list[int] = []
    if count_matches:
        for frame, master in zip(frames, masters, strict=True):
            source_box = _source_rgba(frame).getchannel("A").getbbox()
            expected_box = _scale_box(source_box, _scale(frame))
            actual_box = master.convert("RGBA").getchannel("A").getbbox()
            drifts.append(_box_drift(expected_box, actual_box))
    max_drift = max(drifts, default=0)
    passed = count_matches and max_drift <= tolerance
    return CheckResult(
        "animation_boxes", passed,
        {"expected_frame_count": len(frames), "actual_frame_count": len(masters), "max_drift": max_drift},
        tolerance,
        "NPC frame count and foreground boxes remain within tolerance" if passed else "NPC frame count or foreground-box drift exceeds tolerance",
    )


def validate_seams(atlas: Image.Image | AtlasBundle, threshold: float) -> CheckResult:
    """Measure average RGBA discontinuity on horizontal and vertical tile seams."""

    if threshold < 0:
        raise ValueError("seam threshold must be non-negative")
    image = atlas.image if isinstance(atlas, AtlasBundle) else atlas
    rgba = image.convert("RGBA")
    vertical = _seam_delta(rgba, vertical=True)
    horizontal = _seam_delta(rgba, vertical=False)
    maximum = max(vertical, horizontal)
    return CheckResult(
        "seams", maximum <= threshold,
        {"vertical_mean_delta": vertical, "horizontal_mean_delta": horizontal, "max_mean_delta": maximum},
        threshold,
        "border seams are within the permitted RGBA delta" if maximum <= threshold else "border seam delta exceeds the permitted threshold",
    )


def validate_rgba(master: Image.Image) -> CheckResult:
    return CheckResult("rgba", master.mode == "RGBA", {"mode": master.mode, "bands": len(master.getbands())}, "RGBA", "artifact is canonical RGBA" if master.mode == "RGBA" else "artifact must be RGBA")


def validate_offset(frame: FrameRecord) -> CheckResult:
    offset = frame.metadata.get("offset", [0, 0])
    valid = isinstance(offset, (list, tuple)) and len(offset) == 2 and all(isinstance(value, int) and not isinstance(value, bool) for value in offset)
    metrics: dict[str, int | str] = {"components": len(offset) if isinstance(offset, (list, tuple)) else 0}
    if valid:
        metrics.update({"x": offset[0], "y": offset[1], "scale": _scale(frame)})
    return CheckResult("offset", valid, metrics, "two logical integer components", "offset metadata is well-formed" if valid else "offset metadata must be a pair of logical integers")


def validate_metadata(frame: FrameRecord) -> CheckResult:
    source = frame.metadata.get("rgba_preview_path")
    required = {"asset_type", "rgba_preview_path", "scale"}
    missing = sorted(key for key in required if key not in frame.metadata)
    valid_type = _asset_type(frame) in {"flat_tile", "npc_rle", "building_combo"}
    source_exists = isinstance(source, str) and Path(source).is_file()
    passed = not missing and valid_type and source_exists and _scale(frame) == CANONICAL_SCALE
    return CheckResult("metadata", passed, {"missing_count": len(missing), "source_exists": int(source_exists), "asset_type": _asset_type(frame)}, "asset_type, rgba_preview_path, scale", "required canonical metadata is present" if passed else "required canonical metadata is missing or invalid")


def _source_rgba(frame: FrameRecord) -> Image.Image:
    path = frame.metadata.get("rgba_preview_path")
    if not isinstance(path, str) or not path:
        raise ValueError("frame metadata must include rgba_preview_path")
    with Image.open(path) as image:
        return image.convert("RGBA")


def _scale(frame: FrameRecord) -> int:
    value = frame.metadata.get("scale", CANONICAL_SCALE)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _asset_type(frame: FrameRecord) -> str:
    value = frame.metadata.get("asset_type", "flat_tile")
    return value if isinstance(value, str) else ""


def _scale_box(box: tuple[int, int, int, int] | None, scale: int) -> tuple[int, int, int, int] | None:
    return None if box is None else tuple(value * scale for value in box)


def _box_drift(expected: tuple[int, int, int, int] | None, actual: tuple[int, int, int, int] | None) -> int:
    if expected is None and actual is None:
        return 0
    if expected is None or actual is None:
        return max(*(expected or actual))
    return max(abs(left - right) for left, right in zip(expected, actual, strict=True))


def _seam_delta(image: Image.Image, *, vertical: bool) -> float:
    if vertical:
        if image.width < 2:
            return 0.0
        boundary = image.width // 2
        pairs = ((image.getpixel((boundary - 1, y)), image.getpixel((boundary, y))) for y in range(image.height))
    else:
        if image.height < 2:
            return 0.0
        boundary = image.height // 2
        pairs = ((image.getpixel((x, boundary - 1)), image.getpixel((x, boundary))) for x in range(image.width))
    values = [sum(abs(left[channel] - right[channel]) for channel in range(4)) / 4 for left, right in pairs]
    return float(sum(values) / len(values)) if values else 0.0
