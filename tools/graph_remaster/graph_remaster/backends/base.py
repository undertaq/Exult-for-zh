"""Torch-independent inference contracts shared by all remaster backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeAlias

from PIL import Image

from ..controls.prepare import ControlBundle
from ..models import GenerationJob


PrecisionProfile: TypeAlias = str
PRECISION_FALLBACK_LADDER = (
    "fp16",
    "fp16_offload_attention_slicing_vae_tiling",
    "fp8",
    "int8",
    "int4",
)


@dataclass(frozen=True)
class PrecisionAttempt:
    """One considered runtime mode, suitable for candidate and failure metadata."""

    mode: str
    outcome: str
    reason: str

    def as_metadata(self) -> dict[str, str]:
        return {"mode": self.mode, "outcome": self.outcome, "reason": self.reason}


def precision_fallback_ladder(requested_precision: PrecisionProfile) -> tuple[str, ...]:
    """Return the safe ordered suffix beginning with the requested precision mode."""

    aliases = {"float16": "fp16", "float8": "fp8", "8bit": "int8", "4bit": "int4"}
    normalized = aliases.get(requested_precision.lower(), requested_precision.lower())
    try:
        return PRECISION_FALLBACK_LADDER[PRECISION_FALLBACK_LADDER.index(normalized) :]
    except ValueError as exc:
        supported = ", ".join(PRECISION_FALLBACK_LADDER)
        raise ValueError(f"unsupported precision {requested_precision!r}; choose one of {supported}") from exc


def precision_metadata(
    requested_precision: PrecisionProfile,
    attempts: list[PrecisionAttempt],
    applied_mode: str | None,
) -> dict[str, object]:
    """Serialize the common scheduler-facing precision/fallback metadata contract."""

    return {
        "requested_precision": requested_precision,
        "attempts": [attempt.as_metadata() for attempt in attempts],
        "applied_mode": applied_mode,
        "reasons": [attempt.reason for attempt in attempts],
    }


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
