from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile


DEPLOY_ROOT = Path(__file__).with_name("deploy")
DEPLOY_RELATIVE_PATHS: tuple[str, ...] = (
    "patch/autonotes.txt",
    "patch/textmsg.txt",
    "mods/Ultima6v1.3/patch/zh_translation.tsv",
)
VOICE_DEPLOY_RELATIVE_PATHS: tuple[str, ...] = (
    "mods/Ultima6v1.3/patch/voice_acting/en_voices.pak",
    "mods/Ultima6v1.3/patch/voice_acting/en_voices.idx",
    "mods/Ultima6v1.3/patch/voice_acting/zh_voices.pak",
    "mods/Ultima6v1.3/patch/voice_acting/zh_voices.idx",
)
DEFAULT_TABLE_PATH = (
    DEPLOY_ROOT / "mods" / "Ultima6v1.3" / "patch" / "zh_translation.tsv"
)


@dataclass(frozen=True)
class DeploymentReport:
    copied: tuple[Path, ...]
    skipped: tuple[Path, ...]
    dry_run: bool


def _relative_parts(relative: str) -> tuple[str, ...]:
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe deployment path: {relative}")
    return path.parts


def _inside(root: Path, path: Path, description: str) -> Path:
    resolved_root = root.resolve()
    resolved_path = path.resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"{description} escapes root: {path}") from error
    return resolved_path


def _deploy_relative_paths(include_voice: bool) -> tuple[str, ...]:
    if include_voice:
        return DEPLOY_RELATIVE_PATHS + VOICE_DEPLOY_RELATIVE_PATHS
    return DEPLOY_RELATIVE_PATHS


def validate_staging(
    stage_root: Path = DEPLOY_ROOT,
    *,
    include_voice: bool = False,
) -> tuple[Path, ...]:
    """Validate the complete checked-in release tree and return source paths."""

    stage_root = Path(stage_root)
    if not stage_root.is_dir():
        raise ValueError(f"staging root is not a directory: {stage_root}")
    resolved_root = stage_root.resolve()

    sources: list[Path] = []
    expected: set[str] = set()
    relative_paths = _deploy_relative_paths(include_voice)
    for relative in relative_paths:
        parts = _relative_parts(relative)
        expected.add(PurePosixPath(*parts).as_posix())
        source = _inside(resolved_root, resolved_root.joinpath(*parts), "staged path")
        if not source.is_file():
            raise ValueError(f"staged file is missing: {relative}")
        sources.append(source)

    actual = {
        path.relative_to(resolved_root).as_posix()
        for path in resolved_root.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise ValueError("staging manifest mismatch: " + "; ".join(details))
    return tuple(sources)


def _target_path(game_root: Path, relative: str) -> Path:
    parts = _relative_parts(relative)
    target = game_root.joinpath(*parts)
    _inside(game_root, target, "deployment target")
    if target.is_symlink():
        raise ValueError(f"deployment target is a symlink: {target}")
    if target.exists() and not target.is_file():
        raise ValueError(f"deployment target is not a regular file: {target}")

    parent = target.parent
    resolved_root = game_root.resolve()
    while parent != resolved_root and parent != parent.parent:
        if parent.is_symlink():
            raise ValueError(f"deployment parent is a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"deployment parent is not a directory: {parent}")
        parent = parent.parent
    return target


def _same_file(source: Path, target: Path) -> bool:
    if not target.is_file() or target.is_symlink():
        return False
    return (
        source.read_bytes() == target.read_bytes()
        and stat.S_IMODE(source.stat().st_mode) == stat.S_IMODE(target.stat().st_mode)
    )


def _copy_atomically(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=f".{target.name}.", delete=False
        ) as temporary:
            temporary_name = temporary.name
            with source.open("rb") as input_file:
                shutil.copyfileobj(input_file, temporary)
        shutil.copystat(source, temporary_name, follow_symlinks=False)
        os.replace(temporary_name, target)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def deploy_staged_files(
    game_root: Path,
    stage_root: Path = DEPLOY_ROOT,
    *,
    dry_run: bool = False,
    include_voice: bool = False,
) -> DeploymentReport:
    """Copy every validated staged release file into a mirrored game tree."""

    stage_root = Path(stage_root)
    game_root = Path(game_root)
    if game_root.exists() and not game_root.is_dir():
        raise ValueError(f"game root is not a directory: {game_root}")

    relative_paths = _deploy_relative_paths(include_voice)
    sources = validate_staging(stage_root, include_voice=include_voice)
    targets = tuple(
        _target_path(game_root, relative)
        for relative in relative_paths
    )

    copied: list[Path] = []
    skipped: list[Path] = []
    for source, target in zip(sources, targets):
        if _same_file(source, target):
            skipped.append(target)
            continue
        copied.append(target)
        if not dry_run:
            _copy_atomically(source, target)

    return DeploymentReport(tuple(copied), tuple(skipped), dry_run)
