"""A deterministic, visibly marked backend for lightweight pipeline tests."""

from __future__ import annotations

from hashlib import sha256

from PIL import Image

from .base import GeneratedImage, InferenceRequest, PrecisionProfile


class MockBackend:
    """Produce repeatable non-AI candidates without importing torch or diffusers."""

    def __init__(self) -> None:
        self._device: str | None = None
        self._precision: PrecisionProfile | None = None

    def load(self, device: str, precision: PrecisionProfile) -> None:
        self._device = device
        self._precision = precision

    def generate(self, request: InferenceRequest) -> GeneratedImage:
        job_id = request.job.job_id or _derived_job_id(request)
        seed = _seed(request)
        width, height = _dimensions(request)
        source = request.source.convert("RGBA").resize((width, height), Image.Resampling.NEAREST)
        image = source.copy()
        accent, shadow = _marker_colours(request, seed)
        pixels = image.load()
        for y in range(height):
            for x in range(width):
                if x < 2 or y < 2 or x >= width - 2 or y >= height - 2:
                    pixels[x, y] = accent if (x + y + seed) % 2 else shadow
        metadata = {
            "backend": "mock",
            "candidate_kind": "deterministic_mock",
            "control_kinds": list(request.controls.profile.controls),
            "height": height,
            "is_real_ai_candidate": False,
            "job_id": job_id,
            "profile": request.job.profile or request.controls.profile.name,
            "seed": seed,
            "source_size": list(request.source.size),
            "width": width,
        }
        return GeneratedImage(image=image, job_id=job_id, seed=seed, metadata=metadata)

    def unload(self) -> None:
        self._device = None
        self._precision = None


def _seed(request: InferenceRequest) -> int:
    value = request.job.parameters.get("seed", 0)
    if isinstance(value, bool):
        raise ValueError("generation seed must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("generation seed must be an integer") from exc


def _dimensions(request: InferenceRequest) -> tuple[int, int]:
    width = _dimension(request.job.parameters.get("width", request.source.width), "width")
    height = _dimension(request.job.parameters.get("height", request.source.height), "height")
    return width, height


def _dimension(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"generation {name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"generation {name} must be a positive integer") from exc
    if parsed < 1:
        raise ValueError(f"generation {name} must be a positive integer")
    return parsed


def _derived_job_id(request: InferenceRequest) -> str:
    frame = request.job.frame
    return f"mock-{frame.archive_sha256[:12]}-{frame.archive_index}-{frame.shape_id}-{frame.frame_id}"


def _marker_colours(request: InferenceRequest, seed: int) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    digest = sha256()
    digest.update(request.source.convert("RGBA").tobytes())
    digest.update(str(seed).encode("ascii"))
    digest.update((request.job.job_id or "").encode("utf-8"))
    value = digest.digest()
    return (255, value[0], 0, 255), (value[1], 0, 255, 255)
