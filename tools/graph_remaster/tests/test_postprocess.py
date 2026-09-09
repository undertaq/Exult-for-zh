from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from PIL import Image
import pytest

from graph_remaster.cli import main
from graph_remaster.db import AssetStore
from graph_remaster.models import FrameKey, FrameRecord
from graph_remaster.models import Candidate, GenerationJob, ShapeRecord, SourceArchive
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


def test_postprocess_cli_persists_canonical_master_and_updates_candidate(tmp_path: Path) -> None:
    source = Image.new("RGBA", (8, 8), (10, 20, 30, 0))
    source.putpixel((2, 3), (10, 20, 30, 255))
    source_path = tmp_path / "source.png"
    source.save(source_path)
    key = FrameKey("b" * 64, 0, 4, 0)
    frame = FrameRecord(
        key,
        8,
        8,
        metadata={
            "asset_type": "flat_tile",
            "offset": [1, -2],
            "rgba_preview_path": str(source_path),
            "scale": 6,
        },
    )
    database = tmp_path / "graph.sqlite3"
    store = AssetStore.open(database)
    store.migrate()
    store.upsert_source_archive(SourceArchive(key.archive_sha256, "shapes.vga"))
    store.upsert_shape(ShapeRecord(key.archive_sha256, key.archive_index, key.shape_id, 8, 8, 1))
    store.upsert_frame(frame)
    store.create_generation_job(GenerationJob(key, "GENERATED", "flat_tile", "mock", {"seed": 7}, "job-postprocess"))
    candidate_path = tmp_path / "candidate.png"
    Image.new("RGBA", (48, 48), (90, 80, 70, 255)).save(candidate_path)
    candidate_id = store.add_candidate(
        Candidate("job-postprocess", str(candidate_path), candidate_id="candidate-postprocess")
    )
    store.close()
    config = tmp_path / "pipeline.toml"
    config.write_text(
        "[project]\nname = 'black-gate'\n[paths]\ndata = 'data'\nwork = 'work'\n"
        "[render]\nscale = 6\nlogical_width = 320\nlogical_height = 200\n",
        encoding="utf-8",
    )

    assert main([
        "postprocess", "--config", str(config), "--database", str(database),
        "--run-id", "pilot", candidate_id,
    ]) == 0

    master = tmp_path / "work" / "masters" / "pilot" / f"{candidate_id}.png"
    assert master.is_file()
    with Image.open(master) as image:
        assert image.mode == "RGBA"
        assert image.size == (48, 48)
        assert image.getpixel((12, 18))[3] == 255
        assert image.getpixel((0, 0))[3] == 0
    updated = AssetStore.open(database)
    try:
        persisted = updated.get_candidate(candidate_id)
        assert persisted.artifact_path == str(master)
        assert persisted.artifact_sha256
        assert persisted.metadata["generated_artifact_path"] == str(candidate_path)
    finally:
        updated.close()
    report = tmp_path / "work" / "reports" / "pilot" / "postprocess.html"
    assert report.is_file()
    assert "Postprocess succeeded" in report.read_text(encoding="utf-8")


def test_postprocess_cli_accepts_explicit_crop_for_legacy_canvas_candidate(tmp_path: Path) -> None:
    source = Image.new("RGBA", (8, 8), (10, 20, 30, 0))
    source.putpixel((2, 3), (10, 20, 30, 255))
    source_path = tmp_path / "source.png"
    source.save(source_path)
    key = FrameKey("c" * 64, 0, 5, 0)
    frame = FrameRecord(
        key,
        8,
        8,
        metadata={"rgba_preview_path": str(source_path)},
    )
    database = tmp_path / "graph.sqlite3"
    store = AssetStore.open(database)
    store.migrate()
    store.upsert_source_archive(SourceArchive(key.archive_sha256, "shapes.vga"))
    store.upsert_shape(ShapeRecord(key.archive_sha256, key.archive_index, key.shape_id, 8, 8, 1))
    store.upsert_frame(frame)
    store.create_generation_job(
        GenerationJob(
            key,
            "GENERATED",
            "flat_tile",
            "mock",
            {"width": 512, "height": 512, "seed": 9},
            "job-legacy-crop",
        )
    )
    store.transition_job("job-legacy-crop", "GENERATED", "REJECTED")
    candidate_path = tmp_path / "candidate.png"
    Image.new("RGBA", (512, 512), (90, 80, 70, 255)).save(candidate_path)
    candidate_id = store.add_candidate(
        Candidate("job-legacy-crop", str(candidate_path), candidate_id="candidate-legacy-crop")
    )
    store.close()
    config = tmp_path / "pipeline.toml"
    config.write_text(
        "[project]\nname = 'black-gate'\n[paths]\ndata = 'data'\nwork = 'work'\n"
        "[render]\nscale = 6\nlogical_width = 320\nlogical_height = 200\n",
        encoding="utf-8",
    )

    assert main([
        "postprocess", "--config", str(config), "--database", str(database),
        "--run-id", "legacy", "--crop", "232,232,48,48", candidate_id,
    ]) == 0

    updated = AssetStore.open(database)
    try:
        parameters = updated.job_parameters("job-legacy-crop")
        persisted = updated.get_candidate(candidate_id)
        enriched_frame = updated.get_frame(key)
        state = updated.job_state("job-legacy-crop")
    finally:
        updated.close()
    assert parameters["source_to_canvas"] == {
        "crop": [232, 232, 48, 48],
    }
    assert enriched_frame.metadata["asset_type"] == "flat_tile"
    assert enriched_frame.metadata["scale"] == 6
    assert state.value == "GENERATED"
    assert persisted.artifact_path.endswith(f"work/masters/legacy/{candidate_id}.png")
    assert main([
        "postprocess", "--config", str(config), "--database", str(database),
        "--run-id", "legacy", "--crop", "232,232,48,48", candidate_id,
    ]) == 0


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
