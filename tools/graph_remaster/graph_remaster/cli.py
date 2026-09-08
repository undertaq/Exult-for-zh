"""Command-line entry point; runtime-heavy backends are intentionally lazy."""

from __future__ import annotations

import argparse
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
