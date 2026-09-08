"""Narrow, replaceable adapter around the external ``ipack`` archive tool."""

from __future__ import annotations

import shutil
from collections import defaultdict
from pathlib import Path
import re

from ..errors import SourceToolError
from ..hashing import sha256_file
from ..models import FrameKey, FrameRecord, ShapeRecord
from .base import CommandRunner, run_command
from .png_metadata import PNGMetadataError, read_png_metadata, write_rgba_preview


_FRAME_NAME = re.compile(r"^(?P<prefix>.+)-(?P<shape>\d+)-(?P<frame>\d+)\.png$")


def write_ipack_script(archive: Path, palette: Path | None, prefix: Path) -> str:
    """Build the limited extraction script accepted by the ipack adapter."""

    lines = [f"archive {Path(archive)}"]
    if palette is not None:
        lines.append(f"palette {Path(palette)}")
    lines.append(f"all: {Path(prefix)}")
    return "\n".join(lines) + "\n"


class IpackAdapter:
    def __init__(self, ipack_binary: Path, runner: CommandRunner = run_command) -> None:
        self.ipack_binary = Path(ipack_binary)
        self.runner = runner

    def inventory(
        self, source_archive: Path, work_dir: Path, palette: Path | None = None
    ) -> list[ShapeRecord]:
        archive = Path(source_archive)
        output = self._extract_all(archive, palette, Path(work_dir) / "indexed")
        grouped: dict[int, list[tuple[int, Path]]] = defaultdict(list)
        for image in output:
            shape_id, frame_id = _frame_identity(image)
            grouped[shape_id].append((frame_id, image))
        archive_sha256 = sha256_file(archive)
        records = []
        for shape_id, images in sorted(grouped.items()):
            ordered = sorted(images)
            metadata = _metadata(ordered[0][1])
            records.append(
                ShapeRecord(
                    archive_sha256, 0, shape_id, metadata.width, metadata.height, len(ordered),
                    {
                        "source_archive": str(archive.resolve()),
                        "palette": str(palette.resolve()) if palette is not None else None,
                        "indexed_directory": str(output[0].parent.resolve()),
                    },
                )
            )
        return records

    def extract(self, shape: ShapeRecord, work_dir: Path) -> list[FrameRecord]:
        source_archive = Path(str(shape.metadata.get("source_archive", "")))
        palette_value = shape.metadata.get("palette")
        palette = Path(str(palette_value)) if palette_value else None
        output = self._extract_all(source_archive, palette, Path(work_dir) / "raw")
        indexed_dir = Path(work_dir) / "indexed"
        preview_dir = Path(work_dir) / "rgba"
        frames = []
        for image in output:
            shape_id, frame_id = _frame_identity(image)
            if shape_id != shape.shape_id:
                continue
            indexed_path = indexed_dir / image.name
            indexed_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(image, indexed_path)
            preview_path = preview_dir / image.name
            metadata = _metadata(indexed_path, preview_path)
            frames.append(
                FrameRecord(
                    FrameKey(shape.archive_sha256, shape.archive_index, shape.shape_id, frame_id),
                    metadata.width, metadata.height, metadata.has_alpha,
                    {
                        "indexed_path": str(indexed_path.resolve()),
                        "rgba_preview_path": str(preview_path.resolve()),
                        "offset": list(metadata.offset),
                        "offset_implicit": metadata.offset_implicit,
                        "indexed": metadata.indexed,
                    },
                )
            )
        return sorted(frames, key=lambda record: record.key.frame_id)

    def _extract_all(self, archive: Path, palette: Path | None, output_dir: Path) -> list[Path]:
        if not self.ipack_binary.is_file():
            raise SourceToolError(f"ipack binary not found: {self.ipack_binary}")
        if palette is not None and not palette.is_file():
            raise SourceToolError(f"palette not found: {palette}")
        output_dir.mkdir(parents=True, exist_ok=True)
        prefix = output_dir / "frame"
        script = output_dir / "ipack.script"
        script.write_text(write_ipack_script(archive, palette, prefix), encoding="utf-8")
        command = (str(self.ipack_binary), "-x", str(script))
        result = self.runner(command)
        if result.returncode:
            raise SourceToolError(
                f"ipack exited with status {result.returncode}: {result.stderr.strip()}", command=command,
                returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
            )
        images = sorted(output_dir.glob("frame-*.png"))
        if not images:
            raise SourceToolError("ipack produced no PNG frames", command=command, stdout=result.stdout, stderr=result.stderr)
        return images


def _frame_identity(path: Path) -> tuple[int, int]:
    match = _FRAME_NAME.match(path.name)
    if match is None:
        raise SourceToolError(f"unexpected ipack frame name: {path.name}")
    return int(match.group("shape")), int(match.group("frame"))


def _metadata(path: Path, preview: Path | None = None):
    try:
        metadata = read_png_metadata(path)
        if preview is not None:
            write_rgba_preview(path, preview)
        return metadata
    except (OSError, PNGMetadataError) as exc:
        raise SourceToolError(f"malformed source PNG {path}: {exc}") from exc
