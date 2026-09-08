from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from PIL import Image

from graph_remaster.controls.prepare import (
    CanvasSpec,
    build_tile_atlas,
    prepare_controls,
    prepare_mask,
    persist_controls,
)
from graph_remaster.controls.profiles import AssetType, get_profile
from graph_remaster.cli import main
from graph_remaster.db import AssetStore
from graph_remaster.models import FrameKey, FrameRecord, ShapeRecord, SourceArchive


def make_frame(tmp_path: Path) -> FrameRecord:
    image = Image.new("RGBA", (4, 3), (0, 0, 0, 0))
    for x in (1, 2):
        for y in (1, 2):
            image.putpixel((x, y), (200, 100, 50, 255))
    source = tmp_path / "frame.png"
    image.save(source)
    return FrameRecord(
        FrameKey("a" * 64, 0, 7, 2),
        4,
        3,
        metadata={"rgba_preview_path": str(source)},
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
    assert image_hash(building.controls["depth"]) == "ded9c93d927d2592ef8c09d1a3904a53332f4ad3e21884765e4d81affff6ae46"


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
    frame = make_frame(tmp_path)
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
    assert store._connection.execute("SELECT COUNT(*) FROM control_maps").fetchone()[0] == 1
    assert (tmp_path / "work" / "controls" / "default" / "stage.json").is_file()
