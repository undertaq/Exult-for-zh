"""Small, runtime-light boundary for source archive readers."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol, Sequence
import subprocess

from ..models import FrameRecord, ShapeRecord


class SourceAdapter(Protocol):
    def inventory(self, source_archive: Path, work_dir: Path) -> list[ShapeRecord]: ...

    def extract(self, shape: ShapeRecord, work_dir: Path) -> list[FrameRecord]: ...


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run one source tool command without a shell or inherited output streams."""

    return subprocess.run(
        list(command), check=False, capture_output=True, text=True, shell=False
    )
