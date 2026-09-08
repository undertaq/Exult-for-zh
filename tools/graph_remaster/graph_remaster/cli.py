"""Command-line entry point; runtime-heavy backends are intentionally lazy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence


COMMANDS = (
    "inventory",
    "extract",
    "prepare-controls",
    "generate",
    "validate",
    "review",
    "package",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graph-remaster",
        description="Resumable Ultima VII Graph Remaster pipeline",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    for command in COMMANDS:
        subparser = subparsers.add_parser(command, help=f"run the {command} stage")
        subparser.add_argument("--config", type=Path, default=Path("pipeline.toml"))
        subparser.add_argument("--run-id")
        subparser.add_argument("selector", nargs="?")
        if command == "generate":
            subparser.add_argument("--backend", default=None)
        if command in {"inventory", "extract"}:
            subparser.add_argument("--ipack", type=Path, required=True)
            subparser.add_argument("--archive", type=Path)
            subparser.add_argument("--palette", type=Path)
            subparser.add_argument("--database", type=Path)
            subparser.set_defaults(handler=_run_source_stage)
        elif command == "prepare-controls":
            subparser.add_argument("--database", type=Path)
            subparser.set_defaults(handler=_run_controls_stage)
        else:
            subparser.set_defaults(handler=_not_implemented)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return args.handler(args)


def _not_implemented(args: argparse.Namespace) -> int:
    raise NotImplementedError(f"pipeline stage '{args.command}' is not implemented yet")


def _run_source_stage(args: argparse.Namespace) -> int:
    """Run an inventory/extraction stage without importing generation backends."""

    from .config import load_config
    from .db import AssetStore
    from .errors import SourceToolError
    from .hashing import sha256_file
    from .models import SourceArchive
    from .source_io.ipack_adapter import IpackAdapter

    config = load_config(args.config)
    run_id = args.run_id or "default"
    stage_root = config.paths.inventory if args.command == "inventory" else config.paths.work / "extract"
    stage_dir = stage_root / run_id
    report_path = config.paths.reports / run_id / f"{args.command}-error.json"
    stage_dir.mkdir(parents=True, exist_ok=True)
    archive = args.archive or (Path(args.selector) if args.selector else None)
    try:
        if archive is None:
            raise SourceToolError("source archive is required; pass --archive or selector")
        store = AssetStore.open(args.database or config.paths.work / "graph.sqlite3")
        try:
            store.migrate()
            archive_sha256 = sha256_file(archive)
            shapes = store.list_shapes(archive_sha256) if store.get_source_archive(archive_sha256) else []
            if not shapes:
                adapter = IpackAdapter(args.ipack)
                shapes = adapter.inventory(archive, stage_dir, args.palette)
                store.upsert_source_archive(
                    SourceArchive(archive_sha256, str(archive.resolve()), archive.stat().st_size)
                )
                for shape in shapes:
                    store.upsert_shape(shape)
            for shape in shapes:
                if args.command == "extract":
                    existing = {frame.key.frame_id for frame in store.list_frames(shape)}
                    expected = set(range(shape.frame_count))
                    if not expected.issubset(existing):
                        adapter = IpackAdapter(args.ipack)
                        for frame in adapter.extract(shape, stage_dir / f"shape-{shape.shape_id:04d}"):
                            if frame.key.frame_id not in existing:
                                store.upsert_frame(frame)
        finally:
            store.close()
        (stage_dir / "stage.json").write_text(
            json.dumps({"stage": args.command, "run_id": run_id, "archive_sha256": shapes[0].archive_sha256, "shape_count": len(shapes)}, sort_keys=True),
            encoding="utf-8",
        )
        return 0
    except (OSError, SourceToolError) as exc:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"stage": args.command, "run_id": run_id, "error": str(exc)}
        if isinstance(exc, SourceToolError):
            payload.update({"command": list(exc.command), "returncode": exc.returncode, "stdout": exc.stdout, "stderr": exc.stderr})
        report_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return 2


def _run_controls_stage(args: argparse.Namespace) -> int:
    """Prepare deterministic source-authoritative controls without generation backends."""

    from .config import load_config
    from .controls.prepare import CanvasSpec, build_tile_atlas, persist_controls, persist_tile_atlas, prepare_controls
    from .controls.profiles import AssetType, get_profile
    from .db import AssetStore
    from .reporting import write_stage_html_report

    config = load_config(args.config)
    run_id = args.run_id or "default"
    stage_dir = config.paths.controls / run_id
    report_path = config.paths.reports / run_id / "prepare-controls-error.json"
    html_report_path = report_path.with_name("prepare-controls.html")
    stage_dir.mkdir(parents=True, exist_ok=True)
    try:
        store = AssetStore.open(args.database or config.paths.work / "graph.sqlite3")
        try:
            store.migrate()
            frames = store.list_all_frames(args.selector)
            flat_frames: dict[object, list[object]] = {}
            for frame in frames:
                asset_type = AssetType(frame.metadata.get("asset_type", AssetType.FLAT_TILE.value))
                configured = next((item for item in config.asset_profiles if item.name == asset_type.value), None)
                profile = configured or get_profile(asset_type)
                bundle = prepare_controls(frame, profile)
                persist_controls(store, stage_dir, bundle)
                if asset_type is AssetType.FLAT_TILE:
                    flat_frames.setdefault(profile, []).append(frame)
            atlas_count = 0
            for profile, grouped_frames in flat_frames.items():
                canvas = CanvasSpec(profile.atlas_columns, profile.atlas_rows, profile.tile_width, profile.tile_height)
                capacity = canvas.columns * canvas.rows
                for start in range(0, len(grouped_frames), capacity):
                    members = grouped_frames[start:start + capacity]
                    persist_tile_atlas(store, stage_dir, members, profile, build_tile_atlas(members, config.render.scale, canvas))
                    atlas_count += 1
        finally:
            store.close()
        payload = {"stage": args.command, "run_id": run_id, "frame_count": len(frames), "atlas_count": atlas_count}
        (stage_dir / "stage.json").write_text(
            json.dumps(payload, sort_keys=True),
            encoding="utf-8",
        )
        write_stage_html_report(html_report_path, "Controls prepared", payload)
        return 0
    except (OSError, ValueError) as exc:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"stage": args.command, "run_id": run_id, "error": str(exc)}
        report_path.write_text(
            json.dumps(payload, sort_keys=True),
            encoding="utf-8",
        )
        write_stage_html_report(html_report_path, "Preparation failed", payload)
        return 2
