#!/usr/bin/env python3
"""Validate and atomically install selected bilingual reference voices."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Sequence

try:
    from tools.voice_acting.reference_voice_manifest import design_id_for_selection, slugify_npc
except ModuleNotFoundError:  # Direct execution from tools/voice_acting.
    from reference_voice_manifest import design_id_for_selection, slugify_npc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REFS_DIR = PROJECT_ROOT / "voice" / "refs"
DEFAULT_BACKUP_ROOT = PROJECT_ROOT / "voice_backup"
DEFAULT_CLONE_PROMPTS = Path(__file__).with_name("clone_prompts.pkl")


class InstallError(ValueError):
    """Raised when selected references cannot be safely installed."""


@dataclass(frozen=True)
class InstallItem:
    """One preflight-validated reference source and its runtime destination."""

    design_id: str
    npc: str
    slug: str
    language: str
    source: Path
    source_relative: str
    destination: Path
    sha256: str
    reference_text: str
    candidate_index: int
    candidate_seed: int | None
    model_revision: str | None


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InstallError(f"missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InstallError(f"invalid {label}: {path}") from exc
    if not isinstance(value, dict):
        raise InstallError(f"{label} is not an object: {path}")
    return value


def _source_path(source_root: Path, value: object, slug: str, language: str) -> tuple[Path, str]:
    if not isinstance(value, str) or not value:
        raise InstallError(f"{slug}: missing {language} candidate path")
    relative = Path(value)
    if relative.is_absolute():
        raise InstallError(f"{slug}: {language} candidate path must be relative")
    root = source_root.resolve()
    path = (root / relative).resolve()
    try:
        source_relative = str(path.relative_to(root))
    except ValueError as exc:
        raise InstallError(f"{slug}: {language} candidate path escapes source root") from exc
    if not path.is_file():
        raise InstallError(f"{slug}: missing {language} candidate audio: {path}")
    return path, source_relative


def _candidate_item(
    *,
    source_root: Path,
    record: dict[str, Any],
    slug: str,
    design_id: str,
    design: dict[str, Any],
    language: str,
) -> InstallItem:
    language_key = language.lower()
    source, source_relative = _source_path(
        source_root, record.get(f"{language_key}_wav"), slug, language
    )
    index = record.get(f"{language_key}_index")
    if not isinstance(index, int):
        raise InstallError(f"{slug}: missing {language} candidate index")

    metadata = _read_json(source.with_suffix(".json"), f"{language} candidate metadata")
    if metadata.get("slug") != slug:
        raise InstallError(f"{slug}: {language} candidate metadata slug mismatch")
    if metadata.get("language") != language:
        raise InstallError(f"{slug}: {language} candidate metadata language mismatch")
    if metadata.get("index") != index:
        raise InstallError(f"{slug}: {language} candidate metadata index mismatch")
    expected_hash = metadata.get("sha256")
    if not isinstance(expected_hash, str) or not expected_hash:
        raise InstallError(f"{slug}: {language} candidate metadata has no sha256")
    expected_hash = expected_hash.lower()
    if sha256_file(source) != expected_hash:
        raise InstallError(f"{slug}: {language} candidate sha256 mismatch")

    text_key = "ref_en_text" if language == "English" else "ref_zh_text"
    sample_text = metadata.get("sample_text")
    if not isinstance(sample_text, str) or not sample_text:
        raise InstallError(f"{slug}: {language} candidate metadata has no sample_text")
    if design.get(text_key) != sample_text:
        raise InstallError(f"{slug}: {language} reference text does not match design")

    code = "en" if language == "English" else "zh"
    return InstallItem(
        design_id=design_id,
        npc=str(record.get("npc", "")).strip(),
        slug=slug,
        language=language,
        source=source,
        source_relative=source_relative,
        destination=Path(f"{design_id}_{code}_ref.ogg"),
        sha256=expected_hash,
        reference_text=sample_text,
        candidate_index=index,
        candidate_seed=metadata.get("seed") if isinstance(metadata.get("seed"), int) else None,
        model_revision=(
            metadata.get("model_revision") if isinstance(metadata.get("model_revision"), str) else None
        ),
    )


def preflight(
    selection: dict[str, Any], source_root: Path, designs: dict[str, Any]
) -> list[InstallItem]:
    """Validate selected candidate pairs and return immutable installation items."""
    selected = selection.get("selected")
    if not isinstance(selected, dict) or not selected:
        raise InstallError("selection has no selected records")
    design_records = designs.get("designs")
    if not isinstance(design_records, dict) or not design_records:
        raise InstallError("designs has no design records")

    items: list[InstallItem] = []
    seen_slugs: set[str] = set()
    seen_designs: set[str] = set()
    seen_destinations: set[Path] = set()
    for key, record in sorted(selected.items()):
        if not isinstance(record, dict):
            raise InstallError(f"{key}: selected record is not an object")
        slug = slugify_npc(record.get("slug", key))
        if not slug:
            raise InstallError(f"{key}: selected record has no slug")
        if slug in seen_slugs:
            raise InstallError(f"{slug}: duplicate selected slug")
        seen_slugs.add(slug)
        npc = str(record.get("npc", "")).strip()
        if not npc:
            raise InstallError(f"{slug}: selected record has no NPC")

        design_id = design_id_for_selection(slug)
        if design_id in seen_designs:
            raise InstallError(f"{slug}: duplicate design assignment: {design_id}")
        seen_designs.add(design_id)
        design = design_records.get(design_id)
        if not isinstance(design, dict):
            raise InstallError(f"{slug}: missing design: {design_id}")
        if design.get("npc") != npc:
            raise InstallError(f"{slug}: selected NPC does not match design: {design_id}")
        if design.get("npcs") != [npc]:
            raise InstallError(f"{slug}: design must be assigned to exactly one NPC: {design_id}")

        for language in ("English", "Chinese"):
            item = _candidate_item(
                source_root=Path(source_root),
                record=record,
                slug=slug,
                design_id=design_id,
                design=design,
                language=language,
            )
            if item.destination in seen_destinations:
                raise InstallError(f"{slug}: duplicate destination: {item.destination}")
            seen_destinations.add(item.destination)
            items.append(item)

    unselected_designs = sorted(set(design_records) - seen_designs)
    if unselected_designs:
        raise InstallError(
            "designs without exactly one bilingual selection: " + ", ".join(unselected_designs)
        )
    return items


def verify_installed(items: list[InstallItem], refs_dir: Path) -> int:
    """Check that every installed destination still matches the selected source hash."""
    refs_dir = Path(refs_dir)
    for item in items:
        destination = refs_dir / item.destination
        if not destination.is_file():
            raise InstallError(f"missing installed reference: {destination}")
        if sha256_file(destination) != item.sha256:
            raise InstallError(f"installed sha256 mismatch: {destination}")
    return len(items)


def _backup_id() -> str:
    return "refs_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _reserve_backup_dir(backup_root: Path) -> tuple[str, Path]:
    """Create and reserve a unique final backup directory without replacement."""
    backup_root.mkdir(parents=True, exist_ok=True)
    base = _backup_id()
    suffix = 0
    while True:
        backup_id = base if suffix == 0 else f"{base}_{suffix:02d}"
        backup_dir = backup_root / backup_id
        try:
            backup_dir.mkdir(exist_ok=False)
        except FileExistsError:
            suffix += 1
            continue
        return backup_id, backup_dir


def _create_backup(refs_dir: Path, backup_root: Path, clone_prompts_path: Path) -> tuple[str, Path, bool]:
    backup_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".reference-backup-", dir=backup_root) as temporary:
        backup_stage = Path(temporary)
        if refs_dir.exists():
            if not refs_dir.is_dir():
                raise InstallError(f"reference destination is not a directory: {refs_dir}")
            shutil.copytree(refs_dir, backup_stage / "refs")
        else:
            (backup_stage / "refs").mkdir()
        clone_prompts_backed_up = False
        if clone_prompts_path.exists():
            if not clone_prompts_path.is_file():
                raise InstallError(f"clone prompts path is not a file: {clone_prompts_path}")
            shutil.copy2(clone_prompts_path, backup_stage / clone_prompts_path.name)
            clone_prompts_backed_up = True
        backup_id, backup_dir = _reserve_backup_dir(backup_root)
        try:
            shutil.copytree(backup_stage / "refs", backup_dir / "refs")
            if clone_prompts_backed_up:
                shutil.copy2(
                    backup_stage / clone_prompts_path.name,
                    backup_dir / clone_prompts_path.name,
                )
        except Exception:
            shutil.rmtree(backup_dir)
            raise
    return backup_id, backup_dir, clone_prompts_backed_up


def _restore_published(
    published: list[tuple[InstallItem, bool]], refs_dir: Path, backup_dir: Path
) -> None:
    for item, existed in reversed(published):
        destination = refs_dir / item.destination
        if not existed:
            destination.unlink(missing_ok=True)
            continue
        original = backup_dir / "refs" / item.destination
        if not original.is_file():
            raise InstallError(f"cannot restore missing backup reference: {original}")
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.name}.", dir=destination.parent, delete=False
        ) as handle:
            rollback = Path(handle.name)
        try:
            shutil.copyfile(original, rollback)
            rollback.replace(destination)
        finally:
            rollback.unlink(missing_ok=True)


def _manifest_payload(
    items: list[InstallItem], backup_id: str, clone_prompts_backed_up: bool
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "backup_id": backup_id,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "clone_prompts_backed_up": clone_prompts_backed_up,
        "items": [
            {
                **asdict(item),
                "source": item.source_relative,
                "destination": str(item.destination),
            }
            for item in items
        ],
    }


def write_manifest_atomic(path: Path, manifest: dict[str, Any]) -> None:
    """Publish provenance JSON with a same-directory replace operation."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix=f".{path.stem}.", suffix=".json", dir=path.parent,
        delete=False,
    ) as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, default=str)
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def install(
    items: list[InstallItem],
    refs_dir: Path,
    backup_root: Path,
    clone_prompts_path: Path,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Stage, back up, publish, and record selected reference files."""
    if not items:
        raise InstallError("no install items")
    refs_dir = Path(refs_dir)
    backup_root = Path(backup_root)
    clone_prompts_path = Path(clone_prompts_path)
    refs_dir.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".reference-install-", dir=refs_dir.parent) as temporary:
        staging = Path(temporary)
        for item in items:
            if item.destination.is_absolute() or ".." in item.destination.parts:
                raise InstallError(f"invalid install destination: {item.destination}")
            staged = staging / item.destination
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item.source, staged)
            if sha256_file(staged) != item.sha256:
                raise InstallError(f"staged sha256 mismatch: {item.source}")

        backup_id, backup_dir, clone_prompts_backed_up = _create_backup(
            refs_dir, backup_root, clone_prompts_path
        )
        published: list[tuple[InstallItem, bool]] = []
        try:
            for item in items:
                destination = refs_dir / item.destination
                destination.parent.mkdir(parents=True, exist_ok=True)
                existed = destination.exists()
                (staging / item.destination).replace(destination)
                published.append((item, existed))
            verify_installed(items, refs_dir)
            manifest = _manifest_payload(items, backup_id, clone_prompts_backed_up)
            if manifest_path is not None:
                write_manifest_atomic(manifest_path, manifest)
            return manifest
        except Exception as exc:
            try:
                _restore_published(published, refs_dir, backup_dir)
            except Exception as rollback_error:
                raise InstallError(
                    f"installation failed ({exc}); rollback failed ({rollback_error})"
                ) from exc
            if isinstance(exc, InstallError):
                raise
            raise InstallError(f"installation failed: {exc}") from exc


def _load_cli_json(path: Path, label: str) -> dict[str, Any]:
    return _read_json(path, label)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--designs", type=Path, required=True)
    parser.add_argument("--refs-dir", type=Path, default=DEFAULT_REFS_DIR)
    parser.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    parser.add_argument("--clone-prompts", type=Path, default=DEFAULT_CLONE_PROMPTS)
    parser.add_argument("--manifest", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    mode.add_argument("--verify-installed", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        selection = _load_cli_json(args.selection, "selection JSON")
        designs = _load_cli_json(args.designs, "designs JSON")
        items = preflight(selection, args.source_root, designs)
        if args.dry_run:
            print(json.dumps({"mode": "dry-run", "items": len(items)}, sort_keys=True))
            return 0
        if args.verify_only:
            print(json.dumps({"mode": "verify-only", "items": len(items)}, sort_keys=True))
            return 0
        if args.verify_installed:
            print(json.dumps({"mode": "verify-installed", "items": verify_installed(items, args.refs_dir)}, sort_keys=True))
            return 0
        if args.manifest is None:
            raise InstallError("--manifest is required when installing references")
        manifest = install(items, args.refs_dir, args.backup_root, args.clone_prompts, args.manifest)
    except (InstallError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({"backup_id": manifest["backup_id"], "items": len(items)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
