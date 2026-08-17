#!/usr/bin/env python3
"""Sync generated voice files into Exult's runtime patch/voice_acting tree."""
import argparse
import filecmp
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent.parent
DEFAULT_SOURCE_ROOT = PROJECT_DIR / "voice"


def _normalize_config_path(value):
    return (value or "").strip().replace("\\", "/")


def resolve_patch_dir(config_path, game="blackgate"):
    """Resolve <game>/<patch> from an Exult config file."""
    config_path = Path(config_path).resolve()
    tree = ET.parse(config_path)
    node = tree.find(f".//{game}/patch")
    if node is None or not (node.text or "").strip():
        raise ValueError(f"No patch path found for game '{game}' in {config_path}")

    patch_text = _normalize_config_path(node.text)
    patch_dir = Path(patch_text)
    if not patch_dir.is_absolute():
        patch_dir = config_path.parent / patch_dir
    return patch_dir.resolve()


def default_config_path():
    local_cfg = PROJECT_DIR / "exult.cfg"
    if local_cfg.exists():
        return local_cfg
    home_cfg = Path.home() / ".exult.cfg"
    if home_cfg.exists():
        return home_cfg
    raise FileNotFoundError("Could not find exult.cfg or ~/.exult.cfg")


def sync_language(source_dir, patch_dir, lang, dry_run=False):
    """Copy changed .ogg files from source_dir to patch_dir/voice_acting/lang."""
    source_dir = Path(source_dir)
    target_dir = Path(patch_dir) / "voice_acting" / lang
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Source voice directory not found: {source_dir}")

    copied = 0
    skipped = 0
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    for source in sorted(source_dir.glob("*.ogg")):
        target = target_dir / source.name
        if target.exists() and filecmp.cmp(source, target, shallow=False):
            skipped += 1
            continue
        copied += 1
        if not dry_run:
            shutil.copy2(source, target)

    return copied, skipped


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Sync generated voice/<lang> files into <PATCH>/voice_acting/<lang>."
    )
    parser.add_argument("--config", default=None, help="Path to exult.cfg")
    parser.add_argument("--game", default="blackgate", help="Config game key to read")
    parser.add_argument("--patch-dir", default=None, help="Override resolved patch directory")
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT), help="Generated voice root")
    parser.add_argument("--lang", choices=("en", "zh", "all"), default="en")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    patch_dir = Path(args.patch_dir).resolve() if args.patch_dir else resolve_patch_dir(
        args.config or default_config_path(), args.game
    )
    source_root = Path(args.source_root).resolve()
    langs = ["zh", "en"] if args.lang == "all" else [args.lang]

    total_copied = 0
    total_skipped = 0
    for lang in langs:
        copied, skipped = sync_language(source_root / lang, patch_dir, lang, args.dry_run)
        total_copied += copied
        total_skipped += skipped
        action = "Would copy" if args.dry_run else "Copied"
        print(f"{lang}: {action} {copied}, skipped {skipped}")

    print(f"Patch voice directory: {patch_dir / 'voice_acting'}")

    blmp_src = source_root / "bilingual_map.dat"
    if blmp_src.exists():
        blmp_target = patch_dir / "voice_acting" / "bilingual_map.dat"
        if not args.dry_run:
            blmp_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(blmp_src, blmp_target)
        print(f"Synced {blmp_src.name} -> {blmp_target}")

    return 0 if total_copied >= 0 and total_skipped >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
