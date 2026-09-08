"""Torch-independent inference contracts shared by all remaster backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeAlias

from PIL import Image

from ..controls.prepare import ControlBundle
from ..models import GenerationJob


PrecisionProfile: TypeAlias = str


class BackendUnavailable(RuntimeError):
    """Raised when an optional or requested inference runtime cannot be used."""


@dataclass(frozen=True)
class InferenceRequest:
    """The backend-neutral inputs for one persisted generation job."""

    job: GenerationJob
    source: Image.Image
    controls: ControlBundle
    reference: Image.Image | None = None


@dataclass(frozen=True)
class GeneratedImage:
    """One in-memory candidate and the metadata needed to persist it later."""

    image: Image.Image
    job_id: str
    seed: int
    metadata: dict[str, Any] = field(default_factory=dict)


class InferenceBackend(Protocol):
    """A runtime backend; implementations keep heavyweight imports lazy."""

    def load(self, device: str, precision: PrecisionProfile) -> None:
        """Prepare the backend on one device using the scheduler's precision profile."""

    def generate(self, request: InferenceRequest) -> GeneratedImage:
        """Generate one batch-one candidate from a deterministic job request."""

    def unload(self) -> None:
        """Release runtime-owned resources after the scheduler has drained work."""
