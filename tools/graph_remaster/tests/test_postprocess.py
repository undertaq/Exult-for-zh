from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from PIL import Image
import pytest

from graph_remaster.models import FrameKey, FrameRecord
from graph_remaster.postprocess.hd_master import Palette, scale_offset, write_hd_master, write_indexed_preview
from graph_remaster.postprocess.masks import restore_source_alpha


def _frame(source: Path) -> FrameRecord:
    return FrameRecord(
        FrameKey("a" * 64, 2, 17, 3),
        32,
        48,
        metadata={
            "rgba_preview_path": str(source),
            "offset": [-3, 8],
            # Pixel-space crop rectangle recorded when the source was placed on
            # the generation canvas: left, top, width, height.
            "source_to_canvas": {"crop": [6, 12, 192, 288]},
        },
    )


def test_restore_source_alpha_replaces_alpha_without_destroying_hidden_rgb() -> None:
    candidate = Image.new("RGBA", (2, 1), (20, 40, 60, 255))
    candidate.putpixel((0, 0), (1, 2, 3, 99))
    source_alpha = Image.frombytes("L", (2, 1), bytes([0, 127]))

    restored = restore_source_alpha(candidate, source_alpha)

    assert restored.mode == "RGBA"
    assert restored.getpixel((0, 0)) == (1, 2, 3, 0)
    assert restored.getpixel((1, 0)) == (20, 40, 60, 127)


def test_hd_master_crops_canvas_restores_sixfold_alpha_and_writes_hash_metadata(tmp_path: Path) -> None:
    source = Image.new("RGBA", (32, 48), (0, 0, 0, 0))
    source.putpixel((1, 1), (10, 20, 30, 255))
    source.save(tmp_path / "source.png")
    candidate = Image.new("RGBA", (210, 312), (9, 8, 7, 222))
    candidate.paste(Image.new("RGBA", (192, 288), (1, 2, 3, 99)), (6, 12))

    master = write_hd_master(candidate, _frame(tmp_path / "source.png"), tmp_path / "masters" / "frame.png")

    assert master.path.is_file()
    assert master.path.with_suffix(".json").is_file()
    assert len({master.path, master.metadata_path, master.path.with_suffix(".html")}) == 3
    with Image.open(master.path) as image:
        assert image.mode == "RGBA"
        assert image.size == (192, 288)
        assert image.getpixel((0, 0)) == (1, 2, 3, 0)
        assert image.getpixel((6, 6)) == (1, 2, 3, 255)
    assert master.offset == (-18, 48)
    assert master.sha256 == sha256(master.path.read_bytes()).hexdigest()
    sidecar = json.loads(master.path.with_suffix(".json").read_text(encoding="utf-8"))
    assert sidecar["source_key"] == {"archive_sha256": "a" * 64, "archive_index": 2, "shape_id": 17, "frame_id": 3}
    assert sidecar["dimensions"] == {"logical": [32, 48], "hd": [192, 288], "scale": 6}
    assert sidecar["offset"] == {"logical": [-3, 8], "hd": [-18, 48]}
    assert sidecar["hashes"]["master_png_sha256"] == master.sha256
    assert len(sidecar["hashes"]["source_alpha_sha256"]) == 64


def test_indexed_preview_is_derived_and_leaves_rgba_master_untouched(tmp_path: Path) -> None:
    source = Image.new("RGBA", (32, 48), (0, 0, 0, 0))
    source.putpixel((0, 0), (255, 0, 0, 255))
    source.save(tmp_path / "source.png")
    master = write_hd_master(Image.new("RGBA", (192, 288), (220, 20, 20, 255)), _frame(tmp_path / "source.png"), tmp_path / "master.png")
    master_bytes = master.path.read_bytes()

    preview = write_indexed_preview(
        master,
        Palette(((0, 0, 0), (255, 0, 0)), transparent_index=0),
        tmp_path / "preview.png",
    )

    assert preview != master.path
    assert master.path.read_bytes() == master_bytes
    with Image.open(preview) as image:
        assert image.mode == "P"
        assert image.info["transparency"] == 0
        assert image.getpixel((0, 0)) == 1
        assert image.getpixel((6, 0)) == 0
    preview_metadata = json.loads(preview.with_suffix(".json").read_text(encoding="utf-8"))
    assert preview_metadata["master_path"] == str(master.path)
    assert preview_metadata["quantization"]["pixels"] == 192 * 288
    assert preview_metadata["quantization"]["mean_squared_error"] >= 0


def test_scale_offset_defaults_to_sixfold() -> None:
    assert scale_offset(-3, 8) == (-18, 48)


def test_indexed_preview_rejects_master_artifact_and_json_destinations(tmp_path: Path) -> None:
    source = Image.new("RGBA", (32, 48), (0, 0, 0, 0))
    source.save(tmp_path / "source.png")
    master = write_hd_master(Image.new("RGBA", (192, 288), (220, 20, 20, 255)), _frame(tmp_path / "source.png"), tmp_path / "master.png")
    master_png = master.path.read_bytes()
    master_json = master.metadata_path.read_bytes()
    palette = Palette(((0, 0, 0), (255, 0, 0)), transparent_index=0)

    for destination in (master.path, master.metadata_path, tmp_path / "preview.json"):
        with pytest.raises(ValueError):
            write_indexed_preview(master, palette, destination)

    assert master.path.read_bytes() == master_png
    assert master.metadata_path.read_bytes() == master_json


@pytest.mark.parametrize("scale", [3, 6.0, True])
def test_hd_master_rejects_noncanonical_scale_and_writes_offline_failure_report(tmp_path: Path, scale: object) -> None:
    source = Image.new("RGBA", (32, 48), (0, 0, 0, 0))
    source.save(tmp_path / "source.png")
    frame = _frame(tmp_path / "source.png")
    frame = FrameRecord(frame.key, frame.width, frame.height, metadata={**frame.metadata, "scale": scale})
    output = tmp_path / "rejected.png"

    with pytest.raises(ValueError, match="scale 6"):
        write_hd_master(Image.new("RGBA", (192, 288)), frame, output)

    report = output.with_suffix(".html")
    assert report.is_file()
    assert "Postprocess failed" in report.read_text(encoding="utf-8")
    assert "http" not in report.read_text(encoding="utf-8")


def test_hd_master_writes_offline_success_report(tmp_path: Path) -> None:
    source = Image.new("RGBA", (32, 48), (0, 0, 0, 0))
    source.save(tmp_path / "source.png")

    master = write_hd_master(Image.new("RGBA", (192, 288), (220, 20, 20, 255)), _frame(tmp_path / "source.png"), tmp_path / "master.png")

    report = master.path.with_suffix(".html")
    assert report.is_file()
    html = report.read_text(encoding="utf-8")
    assert "Postprocess succeeded" in html
    assert master.sha256 in html
    assert "http" not in html


@pytest.mark.parametrize("suffix", [".json", ".html", ".webp"])
def test_hd_master_rejects_non_png_destinations_before_writing_artifacts(tmp_path: Path, suffix: str) -> None:
    source = Image.new("RGBA", (32, 48), (0, 0, 0, 0))
    source.save(tmp_path / "source.png")
    output = tmp_path / "invalid-output" / f"master{suffix}"

    with pytest.raises(ValueError, match=r"\.png"):
        write_hd_master(Image.new("RGBA", (192, 288), (220, 20, 20, 255)), _frame(tmp_path / "source.png"), output)

    assert not output.exists()
    assert not output.with_suffix(".json").exists()
    assert not output.with_suffix(".html").exists()
    assert not output.parent.exists()
