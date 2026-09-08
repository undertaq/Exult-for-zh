"""Typed configuration for the graph remaster pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
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
class ModelConfig:
    backend: str = "sdxl_controlnet"
    base_model: str = ""
    revision: str = ""


@dataclass(frozen=True)
class AssetProfile:
    name: str
    controls: tuple[str, ...] = ()
    denoise_min: float = 0.0
    denoise_max: float = 1.0


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
                base_model=str(model.get("base_model", "")),
                revision=str(model.get("revision", "")),
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
    return tuple(value)


def _profiles(value: Any) -> tuple[AssetProfile, ...]:
    if not isinstance(value, Mapping):
        raise ConfigError("asset_profiles must be a table")
    profiles = []
    for name, raw in value.items():
        if not isinstance(raw, Mapping):
            raise ConfigError(f"asset_profiles.{name} must be a table")
        profiles.append(
            AssetProfile(
                name=str(name),
                controls=tuple(str(control) for control in raw.get("controls", ())),
                denoise_min=float(raw.get("denoise_min", 0.0)),
                denoise_max=float(raw.get("denoise_max", 1.0)),
            )
        )
    return tuple(profiles)
