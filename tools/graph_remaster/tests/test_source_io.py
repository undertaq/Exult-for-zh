import base64
import os
from pathlib import Path
import struct
import sys
import zlib

import pytest

from graph_remaster.hashing import sha256_file
from graph_remaster.cli import main
from graph_remaster.source_io.ipack_adapter import IpackAdapter, write_ipack_script
from graph_remaster.source_io.png_metadata import read_png_offset


def indexed_png(offset: tuple[int, int] | None = None) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 3, 0, 0, 0))
        + chunk(b"PLTE", b"\xff\x00\x00\x00\x80\x00")
        + chunk(b"tRNS", b"\x00\xff")
        + (chunk(b"oFFs", struct.pack(">iiB", *offset, 0)) if offset is not None else b"")
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x01"))
        + chunk(b"IEND", b"")
    )


def write_fake_ipack(path: Path) -> None:
    encoded_png = base64.b64encode(indexed_png()).decode("ascii")
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import base64\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"PNG = {encoded_png!r}\n"
        "if sys.argv[1:2] != ['-x']:\n"
        "    raise SystemExit(2)\n"
        "script = Path(sys.argv[2]).read_text(encoding='utf-8').splitlines()\n"
        "archive = next(line[8:] for line in script if line.startswith('archive '))\n"
        "if not Path(archive).is_file():\n"
        "    print('missing archive', file=sys.stderr)\n"
        "    raise SystemExit(9)\n"
        "prefix = next(line[5:] for line in script if line.startswith('all: '))\n"
        "target = Path(prefix).parent\n"
        "target.mkdir(parents=True, exist_ok=True)\n"
        "for frame in range(2):\n"
        "    Path(f'{prefix}-0007-{frame:04d}.png').write_bytes(base64.b64decode(PNG))\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | 0o100)


def test_ipack_adapter_inventories_and_extracts_indexed_frames(tmp_path: Path) -> None:
    archive = tmp_path / "shapes.vga"
    archive.write_bytes(b"fixture archive")
    ipack = tmp_path / "fake-ipack"
    write_fake_ipack(ipack)
    adapter = IpackAdapter(ipack)

    shapes = adapter.inventory(archive, tmp_path / "inventory")

    assert len(shapes) == 1
    shape = shapes[0]
    assert shape.archive_sha256 == sha256_file(archive)
    assert (shape.archive_index, shape.shape_id, shape.width, shape.height, shape.frame_count) == (0, 7, 2, 1, 2)

    frames = adapter.extract(shape, tmp_path / "extract")

    assert [(frame.key.shape_id, frame.key.frame_id) for frame in frames] == [(7, 0), (7, 1)]
    assert all((frame.width, frame.height, frame.has_alpha) == (2, 1, True) for frame in frames)
    assert all(frame.metadata["offset"] == [0, 0] for frame in frames)
    assert all(frame.metadata["offset_implicit"] is True for frame in frames)
    assert all(Path(frame.metadata["indexed_path"]).read_bytes() == indexed_png() for frame in frames)
    assert all(Path(frame.metadata["rgba_preview_path"]).is_file() for frame in frames)


def test_ipack_adapter_reports_missing_archive_output(tmp_path: Path) -> None:
    ipack = tmp_path / "fake-ipack"
    write_fake_ipack(ipack)

    with pytest.raises(Exception, match="missing archive") as error:
        IpackAdapter(ipack).inventory(tmp_path / "missing.vga", tmp_path / "work")

    assert error.value.stderr == "missing archive\n"
    assert error.value.returncode == 9


def test_ipack_script_includes_optional_palette_and_uses_prefix(tmp_path: Path) -> None:
    script = write_ipack_script(tmp_path / "shapes.vga", tmp_path / "palette.flx", tmp_path / "out/frame")

    assert script.splitlines() == [
        f"archive {tmp_path / 'shapes.vga'}",
        f"palette {tmp_path / 'palette.flx'}",
        f"all: {tmp_path / 'out/frame'}",
    ]


def test_read_png_offset_defaults_when_offsets_chunk_is_absent(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    image.write_bytes(indexed_png())

    assert read_png_offset(image) == (0, 0)


def test_read_png_offset_reads_pixel_offsets_chunk(tmp_path: Path) -> None:
    image = tmp_path / "offset-frame.png"
    image.write_bytes(indexed_png((-3, 8)))

    assert read_png_offset(image) == (-3, 8)


def test_inventory_and_extract_cli_persist_idempotent_stage_records(tmp_path: Path) -> None:
    archive = tmp_path / "shapes.vga"
    archive.write_bytes(b"fixture archive")
    ipack = tmp_path / "fake-ipack"
    write_fake_ipack(ipack)
    config = tmp_path / "pipeline.toml"
    config.write_text(
        "[project]\nname = 'black-gate'\n[paths]\ndata = 'data'\nwork = 'work'\n[render]\nscale = 6\nlogical_width = 320\nlogical_height = 200\n",
        encoding="utf-8",
    )

    inventory_args = ["inventory", "--config", str(config), "--ipack", str(ipack), "--archive", str(archive), "--run-id", "fixture"]
    assert main(inventory_args) == 0
    assert main(inventory_args) == 0
    assert main(["extract", "--config", str(config), "--ipack", str(ipack), "--archive", str(archive), "--run-id", "fixture"]) == 0

    import sqlite3
    connection = sqlite3.connect(tmp_path / "work" / "graph.sqlite3")
    assert connection.execute("SELECT COUNT(*) FROM source_archives").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM shapes").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == 2
    assert (tmp_path / "work" / "inventory" / "fixture" / "stage.json").is_file()
    assert (tmp_path / "work" / "extract" / "fixture" / "stage.json").is_file()
    assert "torch" not in sys.modules
