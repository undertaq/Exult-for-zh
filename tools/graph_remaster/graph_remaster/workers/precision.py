"""Capability filtering for the precision ladder owned by the backend layer."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec

from ..backends.base import PrecisionProfile, precision_fallback_ladder
from .devices import CudaDeviceInfo


@dataclass(frozen=True)
class CapabilitySet:
    """Optional quantizer availability, discovered without importing a runtime."""

    torchao: bool = False
    bitsandbytes: bool = False

    @classmethod
    def probe(cls) -> "CapabilitySet":
        return cls(torchao=find_spec("torchao") is not None, bitsandbytes=find_spec("bitsandbytes") is not None)


PRECISION_COMPONENTS: dict[str, dict[str, str]] = {
    "fp16": {"unet": "float16", "text_encoder": "float16", "text_encoder_2": "float16", "vae": "float16", "controlnet": "float16"},
    "fp16_offload_attention_slicing_vae_tiling": {"unet": "float16_cpu_offload", "text_encoder": "float16_cpu_offload", "text_encoder_2": "float16_cpu_offload", "vae": "float16_tiled", "controlnet": "float16_cpu_offload"},
    "fp8": {"unet": "float8_weight_only", "text_encoder": "bfloat16", "text_encoder_2": "bfloat16", "vae": "float16", "controlnet": "float8_weight_only"},
    "int8": {"unet": "int8_weight_only", "text_encoder": "int8_weight_only", "text_encoder_2": "int8_weight_only", "vae": "float16", "controlnet": "float16"},
    "int4": {"unet": "int4_weight_only", "text_encoder": "int4_weight_only", "text_encoder_2": "int4_weight_only", "vae": "float16", "controlnet": "float16"},
}


def resolve_precision(
    device: CudaDeviceInfo,
    installed: CapabilitySet,
    *,
    requested: PrecisionProfile = "fp16",
) -> list[PrecisionProfile]:
    """Return safe fallback modes beginning at the explicitly requested mode."""

    resolved: list[PrecisionProfile] = []
    for profile in precision_fallback_ladder(requested):
        if profile == "fp8" and (not installed.torchao or device.compute_capability < (8, 9)):
            continue
        if profile in {"int8", "int4"} and (not installed.bitsandbytes or device.compute_capability < (7, 5)):
            continue
        resolved.append(profile)
    return resolved


def precision_components(profile: PrecisionProfile) -> dict[str, str]:
    """Copy the explicit per-component precision mapping for persisted provenance."""

    return dict(PRECISION_COMPONENTS[profile])
