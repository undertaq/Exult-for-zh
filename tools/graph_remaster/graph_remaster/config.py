"""Typed configuration for the graph remaster pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Mapping
import tomllib

from .errors import ConfigError


@dataclass(frozen=True)
class PathConfig:
    data: Path
    work: Path
    source: Path
    inventory: Path
    controls: Path
    jobs: Path
    candidates: Path
    validated: Path
    packages: Path
    reports: Path


@dataclass(frozen=True)
class RenderConfig:
    scale: int = 6
    logical_width: int = 320
    logical_height: int = 200

    @property
    def logical_size(self) -> tuple[int, int]:
        return (self.logical_width, self.logical_height)


@dataclass(frozen=True)
class GPUConfig:
    devices: tuple[str, ...] = ("cuda:0", "cuda:1")
    workers: int = 2
    precision: str = "fp16"


@dataclass(frozen=True)
class ControlNetConfig:
    """One named control image's compatible ControlNet weights."""

    name: str
    model: str
    revision: str


_SDXL_BASE_REVISION = "462165984030d82259a11f4367a4eed129e94a7b"
_CANNY_REVISION = "af5cf1ff5d508d8c0cba290a68e13b328bc1432e"
_DEPTH_REVISION = "17bb97973f29801224cd66f192c5ffacf82648b4"
_PINNED_REVISION = re.compile(r"[0-9a-f]{40,64}")


@dataclass(frozen=True)
class ModelConfig:
    backend: str = "sdxl_controlnet"
    base_model: str = "stabilityai/stable-diffusion-xl-base-1.0"
    revision: str = _SDXL_BASE_REVISION
    controlnets: tuple[ControlNetConfig, ...] = (
        ControlNetConfig("canny", "diffusers/controlnet-canny-sdxl-1.0", _CANNY_REVISION),
        ControlNetConfig("depth", "diffusers/controlnet-depth-sdxl-1.0", _DEPTH_REVISION),
        ControlNetConfig("edge", "diffusers/controlnet-canny-sdxl-1.0", _CANNY_REVISION),
        ControlNetConfig("silhouette", "diffusers/controlnet-canny-sdxl-1.0", _CANNY_REVISION),
    )

    def controlnet_model(self, kind: str) -> str:
        return self.controlnet(kind).model

    def controlnet_revision(self, kind: str) -> str:
        return self.controlnet(kind).revision

    def controlnet(self, kind: str) -> ControlNetConfig:
        for controlnet in self.controlnets:
            if controlnet.name == kind:
                return controlnet
        raise ValueError(f"no configured ControlNet mapping for control {kind!r}")

    def validate_for_real_model(self) -> None:
        """Reject mutable refs before a real runtime can resolve different weights."""

        _require_pinned_revision("model.revision", self.revision)
        if not self.controlnets:
            raise ConfigError("model.controlnets must configure at least one control mapping")
        names: set[str] = set()
        for controlnet in self.controlnets:
            if not controlnet.name or not controlnet.model:
                raise ConfigError("model.controlnets entries require non-empty name and model")
            if controlnet.name in names:
                raise ConfigError(f"model.controlnets contains duplicate control {controlnet.name!r}")
            names.add(controlnet.name)
            _require_pinned_revision(
                f"model.controlnets.{controlnet.name}.revision", controlnet.revision
            )

    def resolved_revisions(self, control_kinds: tuple[str, ...] | None = None) -> dict[str, object]:
        """Return the pinned base and selected control revisions for persisted provenance."""

        selected = control_kinds or tuple(controlnet.name for controlnet in self.controlnets)
        return {
            "base_model": {"model": self.base_model, "revision": self.revision},
            "controlnets": {
                kind: {"model": self.controlnet_model(kind), "revision": self.controlnet_revision(kind)}
                for kind in selected
            },
        }


@dataclass(frozen=True)
class AssetProfile:
    name: str
    controls: tuple[str, ...] = ()
    denoise_min: float = 0.0
    denoise_max: float = 1.0
    threshold_low: int = 100
    threshold_high: int = 200
    atlas_columns: int = 1
    atlas_rows: int = 1
    tile_width: int = 8
    tile_height: int = 8


CANONICAL_ASSET_PROFILES = {
    "flat_tile": AssetProfile(
        "flat_tile", ("canny",), 0.05, 0.20, 80, 160, 8, 8, 8, 8
    ),
    "npc_rle": AssetProfile(
        "npc_rle", ("edge", "silhouette"), 0.20, 0.40, 60, 140, 1, 1, 8, 16
    ),
    "building_combo": AssetProfile(
        "building_combo", ("canny", "depth"), 0.30, 0.55, 100, 200, 1, 1, 8, 8
    ),
}


def canonical_asset_profile(name: str) -> AssetProfile:
    """Return the approved defaults for one canonical asset type."""

    return CANONICAL_ASSET_PROFILES[name]


@dataclass(frozen=True)
class PipelineConfig:
    project_name: str
    paths: PathConfig
    render: RenderConfig
    gpu: GPUConfig = field(default_factory=GPUConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    asset_profiles: tuple[AssetProfile, ...] = ()

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "PipelineConfig":
        project = _section(mapping, "project")
        paths = _section(mapping, "paths")
        render = _section(mapping, "render")

        project_name = project.get("name")
        if not isinstance(project_name, str) or not project_name.strip():
            raise ConfigError("project.name is required")
        if project_name != "black-gate":
            raise ConfigError("project.name must be black-gate")

        data = _required_path(paths, "data")
        work = _required_path(paths, "work")
        path_values = {
            "data": data,
            "work": work,
            "source": _path_or_default(paths, "source", work / "source"),
            "inventory": _path_or_default(paths, "inventory", work / "inventory"),
            "controls": _path_or_default(paths, "controls", work / "controls"),
            "jobs": _path_or_default(paths, "jobs", work / "jobs"),
            "candidates": _path_or_default(paths, "candidates", work / "candidates"),
            "validated": _path_or_default(paths, "validated", work / "validated"),
            "packages": _path_or_default(paths, "packages", work / "packages"),
            "reports": _path_or_default(paths, "reports", work / "reports"),
        }

        render_config = RenderConfig(
            scale=_int_value(render, "scale", 6),
            logical_width=_int_value(render, "logical_width", 320),
            logical_height=_int_value(render, "logical_height", 200),
        )
        if render_config.scale != 6:
            raise ConfigError("render.scale must be 6")
        if render_config.logical_size != (320, 200):
            raise ConfigError("render logical dimensions must be 320x200")

        gpu = _section(mapping, "gpu")
        model = _section(mapping, "model")
        devices = _devices(gpu.get("devices", GPUConfig.devices))
        workers = _int_value(gpu, "workers", len(devices))
        if workers < 1:
            raise ConfigError("gpu.workers must be positive")
        if workers > len(devices):
            raise ConfigError("gpu.workers cannot exceed gpu.devices")
        return cls(
            project_name=project_name,
            paths=PathConfig(**path_values),
            render=render_config,
            gpu=GPUConfig(
                devices=devices,
                workers=workers,
                precision=str(gpu.get("precision", "fp16")),
            ),
            model=ModelConfig(
                backend=str(model.get("backend", "sdxl_controlnet")),
                base_model=str(model.get("base_model", ModelConfig.base_model)),
                revision=str(model.get("revision", ModelConfig.revision)),
                controlnets=_controlnets(model),
            ),
            asset_profiles=_profiles(mapping.get("asset_profiles", {})),
        )


def load_config(path: Path) -> PipelineConfig:
    """Load a TOML config and resolve every configured path from its directory."""

    config_path = Path(path)
    try:
        with config_path.open("rb") as stream:
            mapping = tomllib.load(stream)
    except OSError as exc:
        raise ConfigError(f"cannot read config {config_path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {config_path}: {exc}") from exc

    base = config_path.parent.resolve()
    paths = dict(_section(mapping, "paths"))
    for key, value in list(paths.items()):
        if isinstance(value, str):
            candidate = Path(value)
            paths[key] = candidate if candidate.is_absolute() else base / candidate
    resolved = dict(mapping)
    resolved["paths"] = paths
    return PipelineConfig.from_mapping(resolved)


def _section(mapping: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = mapping.get(name, {})
    if not isinstance(value, Mapping):
        raise ConfigError(f"{name} must be a table")
    return value


def _required_path(section: Mapping[str, Any], name: str) -> Path:
    value = section.get(name)
    if not isinstance(value, (str, Path)) or not str(value):
        raise ConfigError(f"paths.{name} is required")
    return Path(value)


def _path_or_default(section: Mapping[str, Any], name: str, default: Path) -> Path:
    value = section.get(name, default)
    if not isinstance(value, (str, Path)) or not str(value):
        raise ConfigError(f"paths.{name} must be a path")
    return Path(value)


def _int_value(section: Mapping[str, Any], name: str, default: int) -> int:
    value = section.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{name} must be an integer")
    return value


def _devices(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ConfigError("gpu.devices must be a sequence")
    if any(not isinstance(device, str) or not device for device in value):
        raise ConfigError("gpu.devices entries must be non-empty strings")
    devices = tuple(value)
    if len(set(devices)) != len(devices):
        raise ConfigError("gpu.devices must contain unique device IDs")
    return devices


def _profiles(value: Any) -> tuple[AssetProfile, ...]:
    if not isinstance(value, Mapping):
        raise ConfigError("asset_profiles must be a table")
    profiles = []
    for name, raw in value.items():
        if not isinstance(raw, Mapping):
            raise ConfigError(f"asset_profiles.{name} must be a table")
        profile_name = str(name)
        defaults = CANONICAL_ASSET_PROFILES.get(profile_name, AssetProfile(profile_name))
        profile = AssetProfile(
            name=profile_name,
            controls=tuple(str(control) for control in raw.get("controls", defaults.controls)),
            denoise_min=float(raw.get("denoise_min", defaults.denoise_min)),
            denoise_max=float(raw.get("denoise_max", defaults.denoise_max)),
            threshold_low=_int_value(raw, "threshold_low", defaults.threshold_low),
            threshold_high=_int_value(raw, "threshold_high", defaults.threshold_high),
            atlas_columns=_int_value(raw, "atlas_columns", defaults.atlas_columns),
            atlas_rows=_int_value(raw, "atlas_rows", defaults.atlas_rows),
            tile_width=_int_value(raw, "tile_width", defaults.tile_width),
            tile_height=_int_value(raw, "tile_height", defaults.tile_height),
        )
        if profile_name in CANONICAL_ASSET_PROFILES and profile.controls != defaults.controls:
            raise ConfigError(
                f"asset_profiles.{profile_name} controls must match canonical controls {defaults.controls}"
            )
        profiles.append(profile)
    return tuple(profiles)


def _controlnets(model: Mapping[str, Any]) -> tuple[ControlNetConfig, ...]:
    raw = model.get("controlnets")
    if raw is None:
        return ModelConfig.controlnets
    if not isinstance(raw, Mapping):
        raise ConfigError("model.controlnets must be a table")
    controlnets = []
    for name, value in raw.items():
        if not isinstance(name, str) or not name:
            raise ConfigError("model.controlnets names must be non-empty strings")
        if not isinstance(value, Mapping):
            raise ConfigError(f"model.controlnets.{name} must be a table")
        model_id = value.get("model")
        revision = value.get("revision")
        if not isinstance(model_id, str) or not model_id:
            raise ConfigError(f"model.controlnets.{name}.model is required")
        if not isinstance(revision, str) or not revision:
            raise ConfigError(f"model.controlnets.{name}.revision is required")
        controlnets.append(ControlNetConfig(name, model_id, revision))
    return tuple(controlnets)


def _require_pinned_revision(name: str, revision: str) -> None:
    if not _PINNED_REVISION.fullmatch(revision):
        raise ConfigError(f"{name} must be a pinned commit SHA; mutable refs such as 'main' are forbidden")
