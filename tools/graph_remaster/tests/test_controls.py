from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from PIL import Image
import pytest

from graph_remaster.controls.prepare import (
    CanvasSpec,
    build_tile_atlas,
    make_synthetic_depth,
    prepare_controls,
    prepare_mask,
    persist_controls,
)
from graph_remaster.controls.profiles import AssetType, get_profile
from graph_remaster.cli import main
from graph_remaster.config import PipelineConfig
from graph_remaster.db import AssetStore
from graph_remaster.errors import ConfigError
from graph_remaster.models import FrameKey, FrameRecord, ShapeRecord, SourceArchive


def make_frame(tmp_path: Path, *, frame_id: int = 2, asset_type: str | None = None) -> FrameRecord:
    image = Image.new("RGBA", (4, 3), (0, 0, 0, 0))
    for x in (1, 2):
        for y in (1, 2):
            image.putpixel((x, y), (200, 100, 50, 255))
    source = tmp_path / f"frame-{frame_id}.png"
    image.save(source)
    return FrameRecord(
        FrameKey("a" * 64, 0, 7, frame_id),
        4,
        3,
        metadata={"rgba_preview_path": str(source), **({"asset_type": asset_type} if asset_type else {})},
    )


def seed_frame(store: AssetStore, frame: FrameRecord) -> None:
    key = frame.key
    store.upsert_source_archive(SourceArchive(key.archive_sha256, "source.vga"))
    store.upsert_shape(ShapeRecord(key.archive_sha256, key.archive_index, key.shape_id, 4, 3))
    store.upsert_frame(frame)


def image_hash(image: Image.Image) -> str:
    return sha256(image.tobytes()).hexdigest()


def test_authoritative_alpha_masks_preserve_the_exact_source_silhouette(tmp_path: Path) -> None:
    frame = make_frame(tmp_path)

    masks = prepare_mask(frame)

    expected = bytes((0, 0, 0, 0, 0, 255, 255, 0, 0, 255, 255, 0))
    assert masks.source.tobytes() == expected
    assert masks.protected.tobytes() == expected
    assert masks.generation.tobytes() == expected


def test_tile_atlas_uses_nearest_neighbor_sixfold_scaling_and_fixed_grid(tmp_path: Path) -> None:
    frame = make_frame(tmp_path)

    atlas = build_tile_atlas([frame], scale=6, canvas=CanvasSpec(columns=2, rows=1, tile_width=4, tile_height=3))

    assert atlas.image.size == (48, 18)
    assert atlas.image.getpixel((6, 6)) == (200, 100, 50, 255)
    assert atlas.image.getpixel((5, 6)) == (0, 0, 0, 0)
    assert atlas.image.getpixel((12, 6)) == (200, 100, 50, 255)
    assert atlas.image.getpixel((18, 6)) == (0, 0, 0, 0)


def test_control_maps_are_deterministic_and_flat_tiles_omit_depth(tmp_path: Path) -> None:
    frame = make_frame(tmp_path)

    flat = prepare_controls(frame, get_profile(AssetType.FLAT_TILE))
    building = prepare_controls(frame, get_profile(AssetType.BUILDING_COMBO))

    assert set(flat.controls) == {"canny"}
    assert "depth" not in flat.controls
    assert image_hash(flat.controls["canny"]) == "4ded406749d672cc8bdc3a070989be0e5fcda7976ad19ee8917f8897fabc213c"
    assert image_hash(building.controls["canny"]) == "15ec7bf0b50732b49f8228e07d24365338f9e3ab994b00af08e5a3bffe55fd8b"
    assert image_hash(building.controls["depth"]) == "a1536ee4562aa44fe66d701704cd16e06ef36b84d5f5cad5efe3c55af8000209"


def test_synthetic_depth_restores_black_transparent_pixels_after_blurring() -> None:
    mask = Image.new("L", (9, 9))
    mask.paste(255, (3, 3, 6, 6))

    depth = make_synthetic_depth(mask, AssetType.BUILDING_COMBO)

    assert depth.getpixel((2, 4)) == 0
    assert depth.getpixel((4, 4)) > 0


@pytest.mark.parametrize(
    ("name", "controls"),
    [
        ("flat_tile", ["canny", "depth"]),
        ("npc_rle", ["edge"]),
        ("building_combo", ["canny"]),
    ],
)
def test_config_rejects_profile_controls_that_violate_canonical_asset_rules(
    name: str, controls: list[str],
) -> None:
    with pytest.raises(ConfigError, match="canonical controls"):
        PipelineConfig.from_mapping(
            {
                "project": {"name": "black-gate"},
                "paths": {"data": "game-data", "work": "remaster-data"},
                "render": {"scale": 6, "logical_width": 320, "logical_height": 200},
                "asset_profiles": {name: {"controls": controls}},
            }
        )


def test_control_artifacts_are_content_addressed_and_linked_to_the_frame(tmp_path: Path) -> None:
    frame = make_frame(tmp_path)
    bundle = prepare_controls(frame, get_profile(AssetType.NPC_RLE))
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()
    seed_frame(store, frame)

    persisted = persist_controls(store, tmp_path / "controls", bundle)
    repeated = persist_controls(store, tmp_path / "controls", bundle)

    assert persisted == repeated
    assert all(len(path.stem) == 64 for path in persisted.values())
    assert store._connection.execute("SELECT COUNT(*) FROM masks").fetchone()[0] == 3
    assert store._connection.execute("SELECT COUNT(*) FROM control_maps").fetchone()[0] == 2
    assert store._connection.execute("SELECT COUNT(*) FROM masks WHERE artifact_path = ?", (str(persisted["source"]),)).fetchone()[0] == 3


def test_prepare_controls_cli_persists_a_controls_ready_stage(tmp_path: Path) -> None:
    frame = make_frame(tmp_path, asset_type="npc_rle")
    database = tmp_path / "graph.sqlite3"
    store = AssetStore.open(database)
    store.migrate()
    seed_frame(store, frame)
    store.close()
    config = tmp_path / "pipeline.toml"
    config.write_text(
        "[project]\nname = 'black-gate'\n[paths]\ndata = 'data'\nwork = 'work'\n"
        "[render]\nscale = 6\nlogical_width = 320\nlogical_height = 200\n",
        encoding="utf-8",
    )

    assert main(["prepare-controls", "--config", str(config), "--database", str(database)]) == 0

    store = AssetStore.open(database)
    assert store._connection.execute("SELECT COUNT(*) FROM masks").fetchone()[0] == 3
    assert store._connection.execute("SELECT COUNT(*) FROM control_maps").fetchone()[0] == 2
    assert (tmp_path / "work" / "controls" / "default" / "stage.json").is_file()


def test_prepare_controls_cli_persists_content_addressed_flat_tile_atlas_and_html_report(tmp_path: Path) -> None:
    first = make_frame(tmp_path, frame_id=0, asset_type="flat_tile")
    second = make_frame(tmp_path, frame_id=1, asset_type="flat_tile")
    mismatched = make_frame(tmp_path, frame_id=2, asset_type="flat_tile")
    mismatched = FrameRecord(
        mismatched.key, 5, mismatched.height, metadata=mismatched.metadata,
    )
    database = tmp_path / "graph.sqlite3"
    store = AssetStore.open(database)
    store.migrate()
    seed_frame(store, first)
    seed_frame(store, second)
    seed_frame(store, mismatched)
    store.close()
    config = tmp_path / "pipeline.toml"
    config.write_text(
        "[project]\nname = 'black-gate'\n[paths]\ndata = 'data'\nwork = 'work'\n"
        "[render]\nscale = 6\nlogical_width = 320\nlogical_height = 200\n"
        "[asset_profiles.flat_tile]\ncontrols = ['canny']\natlas_columns = 2\natlas_rows = 1\n"
        "tile_width = 4\ntile_height = 3\n",
        encoding="utf-8",
    )

    assert main(["prepare-controls", "--config", str(config), "--database", str(database)]) == 0

    store = AssetStore.open(database)
    atlas_rows = store._connection.execute(
        "SELECT artifact_path FROM control_maps WHERE kind = 'atlas' ORDER BY frame_id"
    ).fetchall()
    assert len(atlas_rows) == 2
    assert atlas_rows[0][0] == atlas_rows[1][0]
    atlas_path = Path(atlas_rows[0][0])
    assert len(atlas_path.stem) == 64
    with Image.open(atlas_path) as atlas:
        assert atlas.size == (48, 18)
    assert store._connection.execute(
        "SELECT COUNT(*) FROM control_maps WHERE kind = 'atlas' AND frame_id = 2"
    ).fetchone()[0] == 0
    report = (tmp_path / "work" / "reports" / "default" / "prepare-controls.html").read_text()
    assert "Controls prepared" in report
    assert "http" not in report


def test_prepare_controls_cli_writes_structured_error_and_offline_html_report(tmp_path: Path) -> None:
    config = tmp_path / "pipeline.toml"
    config.write_text(
        "[project]\nname = 'black-gate'\n[paths]\ndata = 'data'\nwork = 'work'\n"
        "[render]\nscale = 6\nlogical_width = 320\nlogical_height = 200\n",
        encoding="utf-8",
    )

    assert main(["prepare-controls", "--config", str(config), "--database", str(tmp_path / "missing.sqlite3")]) == 0
    # A frame without source metadata exercises the stage error contract.
    store = AssetStore.open(tmp_path / "missing.sqlite3")
    frame = FrameRecord(FrameKey("b" * 64, 0, 8, 0), 4, 3)
    seed_frame(store, frame)
    store.close()
    assert main(["prepare-controls", "--config", str(config), "--database", str(tmp_path / "missing.sqlite3")]) == 2

    error = json.loads((tmp_path / "work" / "reports" / "default" / "prepare-controls-error.json").read_text())
    assert error == {"error": "frame metadata must include rgba_preview_path", "run_id": "default", "stage": "prepare-controls"}
    assert "Preparation failed" in (tmp_path / "work" / "reports" / "default" / "prepare-controls.html").read_text()


def test_prepare_controls_cli_reports_invalid_canonical_profile_before_stage_setup(tmp_path: Path) -> None:
    config = tmp_path / "pipeline.toml"
    config.write_text(
        "[project]\nname = 'black-gate'\n[paths]\ndata = 'data'\nwork = 'work'\n"
        "[render]\nscale = 6\nlogical_width = 320\nlogical_height = 200\n"
        "[asset_profiles.flat_tile]\ncontrols = ['canny', 'depth']\n",
        encoding="utf-8",
    )

    assert main(["prepare-controls", "--config", str(config)]) == 2

    report_root = tmp_path / "work" / "reports" / "default"
    error = json.loads((report_root / "prepare-controls-error.json").read_text())
    assert error["stage"] == "prepare-controls"
    assert "canonical controls" in error["error"]
    assert "Preparation failed" in (report_root / "prepare-controls.html").read_text()
