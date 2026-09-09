"""Pillow-only deterministic preparation of masks, atlases, and controls."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Mapping, Sequence, TYPE_CHECKING

from PIL import Image, ImageChops, ImageFilter

from ..config import AssetProfile
from ..models import FrameKey, FrameRecord
from .profiles import AssetType

if TYPE_CHECKING:
    from ..db import AssetStore


@dataclass(frozen=True)
class CanvasSpec:
    columns: int
    rows: int
    tile_width: int
    tile_height: int


@dataclass(frozen=True)
class MaskRecord:
    frame: FrameKey
    source: Image.Image
    protected: Image.Image
    generation: Image.Image


@dataclass(frozen=True)
class AtlasBundle:
    image: Image.Image
    canvas: CanvasSpec
    scale: int


@dataclass(frozen=True)
class ControlBundle:
    frame: FrameRecord
    profile: AssetProfile
    masks: MaskRecord
    controls: Mapping[str, Image.Image]


def prepare_mask(frame: FrameRecord) -> MaskRecord:
    """Use source alpha exactly; no segmentation or rembg fallback is involved."""

    image = _load_source_image(frame)
    alpha = image.getchannel("A").copy()
    return MaskRecord(frame.key, alpha, alpha.copy(), alpha.copy())


def build_tile_atlas(frames: Sequence[FrameRecord], scale: int, canvas: CanvasSpec) -> AtlasBundle:
    """Lay fixed-size nearest-neighbour tile cells left-to-right, top-to-bottom."""

    if scale < 1:
        raise ValueError("scale must be positive")
    capacity = canvas.columns * canvas.rows
    if len(frames) > capacity:
        raise ValueError("frame count exceeds fixed atlas capacity")
    atlas = Image.new("RGBA", (canvas.columns * canvas.tile_width * scale, canvas.rows * canvas.tile_height * scale))
    for index, frame in enumerate(frames):
        image = _load_source_image(frame)
        if image.size != (canvas.tile_width, canvas.tile_height):
            raise ValueError("frame dimensions must match the fixed atlas tile size")
        tile = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
        x = (index % canvas.columns) * tile.width
        y = (index // canvas.columns) * tile.height
        atlas.alpha_composite(tile, (x, y))
    return AtlasBundle(atlas, canvas, scale)


def make_canny(image: Image.Image, threshold_low: int, threshold_high: int) -> Image.Image:
    """Return a deterministic Pillow-only Canny edge map."""

    if not 0 <= threshold_low <= threshold_high <= 255:
        raise ValueError("Canny thresholds must satisfy 0 <= low <= high <= 255")
    pixels = image.convert("L").filter(ImageFilter.GaussianBlur(radius=1)).load()
    width, height = image.size
    magnitude = [[0.0] * width for _ in range(height)]
    direction = [[0] * width for _ in range(height)]
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            gx = (
                pixels[x + 1, y - 1] + 2 * pixels[x + 1, y] + pixels[x + 1, y + 1]
                - pixels[x - 1, y - 1] - 2 * pixels[x - 1, y] - pixels[x - 1, y + 1]
            )
            gy = (
                pixels[x - 1, y + 1] + 2 * pixels[x, y + 1] + pixels[x + 1, y + 1]
                - pixels[x - 1, y - 1] - 2 * pixels[x, y - 1] - pixels[x + 1, y - 1]
            )
            value = min(255.0, (gx * gx + gy * gy) ** 0.5)
            magnitude[y][x] = value
            slope = abs(gy / gx) if gx else float("inf")
            direction[y][x] = 0 if slope <= 0.4142 else 2 if slope >= 2.4142 else (1 if gx * gy > 0 else 3)

    strong: set[tuple[int, int]] = set()
    weak: set[tuple[int, int]] = set()
    offsets = ((1, 0), (1, 1), (0, 1), (1, -1))
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            dx, dy = offsets[direction[y][x]]
            value = magnitude[y][x]
            if value < magnitude[y - dy][x - dx] or value < magnitude[y + dy][x + dx]:
                continue
            if value >= threshold_high:
                strong.add((x, y))
            elif value >= threshold_low:
                weak.add((x, y))
    frontier = list(strong)
    while frontier:
        x, y = frontier.pop()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                neighbour = (x + dx, y + dy)
                if neighbour in weak:
                    weak.remove(neighbour)
                    strong.add(neighbour)
                    frontier.append(neighbour)
    result = Image.new("L", (width, height))
    for point in strong:
        result.putpixel(point, 255)
    return result


def make_synthetic_depth(mask: Image.Image, asset_type: AssetType | str) -> Image.Image:
    """Generate deterministic mask-derived depth, keeping transparent pixels black."""

    if AssetType(asset_type) is not AssetType.BUILDING_COMBO:
        raise ValueError("synthetic depth is only defined for building_combo assets")
    alpha = mask.convert("L")
    # A soft, repeatable depth ramp derived from the protected silhouette.
    blurred = alpha.filter(ImageFilter.GaussianBlur(radius=2)).point(
        lambda value: value if value >= 2 else 0, mode="L"
    )
    return ImageChops.multiply(blurred, alpha)


def prepare_controls(frame: FrameRecord, profile: AssetProfile) -> ControlBundle:
    """Create only controls declared by the serialized asset profile."""

    masks = prepare_mask(frame)
    image = _load_source_image(frame)
    controls: dict[str, Image.Image] = {}
    for kind in profile.controls:
        if kind == "canny":
            controls[kind] = make_canny(image, profile.threshold_low, profile.threshold_high)
        elif kind == "edge":
            controls[kind] = make_canny(masks.source, profile.threshold_low, profile.threshold_high)
        elif kind == "silhouette":
            controls[kind] = masks.generation.copy()
        elif kind == "depth":
            controls[kind] = make_synthetic_depth(masks.protected, AssetType.BUILDING_COMBO)
        else:
            raise ValueError(f"unsupported control kind {kind!r}")
    return ControlBundle(frame, profile, masks, controls)


def persist_controls(
    store: "AssetStore", root: Path, bundle: ControlBundle, *, commit: bool = True,
) -> dict[str, Path]:
    """Write PNG artifacts by content hash and idempotently link them to a frame."""

    root = Path(root)
    artifacts: dict[str, Image.Image] = {
        "source": bundle.masks.source,
        "protected": bundle.masks.protected,
        "generation": bundle.masks.generation,
        **bundle.controls,
    }
    paths: dict[str, Path] = {}
    for kind, image in artifacts.items():
        digest, payload = _png_digest(image)
        path = root / digest[:2] / f"{digest}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(payload)
        metadata = {"sha256": digest, "profile": asdict(bundle.profile)}
        if kind in {"source", "protected", "generation"}:
            store.upsert_mask(bundle.frame.key, kind, digest, path, metadata, commit=commit)
        else:
            store.upsert_control_map(bundle.frame.key, kind, digest, path, metadata, commit=commit)
        paths[kind] = path
    return paths


def persist_tile_atlas(
    store: "AssetStore", root: Path, frames: Sequence[FrameRecord], profile: AssetProfile,
    atlas: AtlasBundle, *, commit: bool = True,
) -> Path:
    """Persist one fixed-grid flat-tile atlas and link it to every member frame."""

    digest, payload = _png_digest(atlas.image)
    path = _write_content_addressed_png(Path(root), digest, payload)
    metadata = {
        "sha256": digest,
        "profile": asdict(profile),
        "atlas": {"columns": atlas.canvas.columns, "rows": atlas.canvas.rows,
                  "tile_width": atlas.canvas.tile_width, "tile_height": atlas.canvas.tile_height,
                  "scale": atlas.scale},
    }
    for frame in frames:
        store.upsert_control_map(frame.key, "atlas", digest, path, metadata, commit=commit)
    return path


def _load_source_image(frame: FrameRecord) -> Image.Image:
    source = frame.metadata.get("rgba_preview_path")
    if not isinstance(source, str) or not source:
        raise ValueError("frame metadata must include rgba_preview_path")
    with Image.open(source) as loaded:
        return loaded.convert("RGBA")


def _png_digest(image: Image.Image) -> tuple[str, bytes]:
    output = BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    payload = output.getvalue()
    return sha256(payload).hexdigest(), payload


def _write_content_addressed_png(root: Path, digest: str, payload: bytes) -> Path:
    path = root / digest[:2] / f"{digest}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(payload)
    return path
