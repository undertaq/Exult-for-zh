"""Typed records persisted by the graph remaster state store."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FrameKey:
    archive_sha256: str
    archive_index: int
    shape_id: int
    frame_id: int


@dataclass(frozen=True)
class SourceArchive:
    archive_sha256: str
    path: str
    size_bytes: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ShapeRecord:
    archive_sha256: str
    archive_index: int
    shape_id: int
    width: int
    height: int
    frame_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, int, int]:
        return (self.archive_sha256, self.archive_index, self.shape_id)


@dataclass(frozen=True)
class FrameRecord:
    key: FrameKey
    width: int
    height: int
    has_alpha: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationJob:
    frame: FrameKey
    state: str = "DISCOVERED"
    profile: str = ""
    backend: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    job_id: str | None = None

    @property
    def frame_key(self) -> FrameKey:
        return self.frame


@dataclass(frozen=True)
class Candidate:
    job_id: str
    artifact_path: str
    artifact_sha256: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    candidate_id: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    candidate_id: str
    passed: bool
    checks: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewDecision:
    candidate_id: str
    decision: str
    reviewer: str = ""
    notes: str = ""
