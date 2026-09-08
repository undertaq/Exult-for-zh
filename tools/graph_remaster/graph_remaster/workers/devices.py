"""Lazy CUDA discovery records; importing this module never imports PyTorch."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib import import_module
from typing import Any


@dataclass(frozen=True)
class CudaDeviceInfo:
    """Stable device facts captured when a worker process starts."""

    index: int
    name: str
    total_vram_bytes: int
    free_vram_bytes: int
    compute_capability: tuple[int, int]
    cuda_version: str | None
    process_started_at: str

    @property
    def device(self) -> str:
        return f"cuda:{self.index}"

    def as_metadata(self) -> dict[str, object]:
        payload = asdict(self)
        payload["device"] = self.device
        payload["compute_capability"] = list(self.compute_capability)
        return payload


def probe_devices(torch_runtime: Any | None = None) -> list[CudaDeviceInfo]:
    """Return CUDA devices without failing lightweight or CPU-only installations.

    Callers that need real CUDA facts invoke this from a spawned worker.  Tests
    can supply a fake runtime, which keeps probing independent of model loading.
    """

    torch = torch_runtime
    if torch is None:
        try:
            torch = import_module("torch")
        except ImportError:
            return []
    cuda = getattr(torch, "cuda", None)
    if cuda is None or not cuda.is_available():
        return []

    started = datetime.now(timezone.utc).isoformat()
    version = getattr(getattr(torch, "version", None), "cuda", None)
    devices: list[CudaDeviceInfo] = []
    for index in range(int(cuda.device_count())):
        properties = cuda.get_device_properties(index)
        try:
            free, total = cuda.mem_get_info(index)
        except (AttributeError, RuntimeError):
            total = int(getattr(properties, "total_memory", 0))
            free = total
        capability = tuple(int(part) for part in cuda.get_device_capability(index))
        devices.append(CudaDeviceInfo(
            index=index,
            name=str(getattr(properties, "name", f"CUDA {index}")),
            total_vram_bytes=int(total),
            free_vram_bytes=int(free),
            compute_capability=(capability[0], capability[1]),
            cuda_version=None if version is None else str(version),
            process_started_at=started,
        ))
    return devices
