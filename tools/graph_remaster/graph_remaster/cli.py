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
        adapter = IpackAdapter(args.ipack)
        shapes = adapter.inventory(archive, stage_dir, args.palette)
        store = AssetStore.open(args.database or config.paths.work / "graph.sqlite3")
        try:
            store.migrate()
            store.upsert_source_archive(
                SourceArchive(sha256_file(archive), str(archive.resolve()), archive.stat().st_size)
            )
            for shape in shapes:
                store.upsert_shape(shape)
                if args.command == "extract":
                    for frame in adapter.extract(shape, stage_dir / f"shape-{shape.shape_id:04d}"):
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
