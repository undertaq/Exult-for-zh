"""Optional, lazy SDXL ControlNet backend."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from PIL import Image

from ..config import ModelConfig
from ..errors import ConfigError
from .base import (
    BackendUnavailable,
    GeneratedImage,
    InferenceRequest,
    PrecisionAttempt,
    PrecisionProfile,
    precision_fallback_ladder,
    precision_metadata,
)
from .mock import _dimensions, _seed


def source_resampling(parameters: dict[str, Any]) -> Image.Resampling:
    """Select the source resize filter, defaulting to pixel-faithful nearest."""

    name = str(parameters.get("source_resampling", "nearest")).lower()
    filters = {
        "nearest": Image.Resampling.NEAREST,
        "bilinear": Image.Resampling.BILINEAR,
        "bicubic": Image.Resampling.BICUBIC,
        "lanczos": Image.Resampling.LANCZOS,
    }
    try:
        return filters[name]
    except KeyError as exc:
        raise ValueError(
            f"unsupported source_resampling {name!r}; choose nearest, bilinear, bicubic, or lanczos"
        ) from exc


class SdxlControlNetBackend:
    """Run one FP16 SDXL ControlNet image-to-image request at a time."""

    def __init__(self, config: ModelConfig) -> None:
        self._config = config
        self._device: str | None = None
        self._requested_precision: PrecisionProfile = "fp16"
        self._torch: Any | None = None
        self._diffusers: Any | None = None
        self._pipelines: dict[tuple[str, ...], Any] = {}
        self._precision_attempts: list[PrecisionAttempt] = []
        self._applied_precision: str | None = None

    def load(self, device: str, precision: PrecisionProfile) -> None:
        try:
            self._config.validate_for_real_model()
            precision_fallback_ladder(precision)
        except (ConfigError, ValueError) as exc:
            raise BackendUnavailable(f"SDXL ControlNet configuration is not runnable: {exc}") from exc
        if not device.startswith("cuda"):
            raise BackendUnavailable(
                f"SDXL ControlNet requires a CUDA device; got {device!r}. Pass --device cuda:N."
            )
        try:
            torch = import_module("torch")
            diffusers = import_module("diffusers")
        except ImportError as exc:
            raise BackendUnavailable(
                "SDXL ControlNet requires optional torch and diffusers dependencies; "
                "install them with `uv sync --extra sdxl`."
            ) from exc
        if not torch.cuda.is_available():
            raise BackendUnavailable(
                "SDXL ControlNet requires CUDA, but torch.cuda.is_available() is false. "
                "Install a CUDA-enabled torch build and pass --device cuda:N."
            )
        self._device = device
        self._requested_precision = precision
        self._torch = torch
        self._diffusers = diffusers
        self._precision_attempts = []
        self._applied_precision = None

    def generate(self, request: InferenceRequest) -> GeneratedImage:
        if self._device is None:
            raise BackendUnavailable("SDXL ControlNet is not loaded; call load(device, 'fp16') before generate().")
        control_kinds, control_images = self._controls_for(request)
        pipeline = self._pipeline_for(control_kinds)
        seed = _seed(request)
        width, height = _dimensions(request)
        generator = self._torch.Generator(device=self._device).manual_seed(seed)
        parameters = request.job.parameters
        call: dict[str, Any] = {
            "prompt": str(parameters.get("prompt", "high-fidelity Ultima VII game asset")),
            "negative_prompt": str(parameters.get("negative_prompt", "text, watermark, blurry")),
            "image": request.source.convert("RGBA").resize(
                (width, height), source_resampling(parameters)
            ),
            "width": width,
            "height": height,
            "generator": generator,
            "guidance_scale": float(parameters.get("guidance_scale", 7.5)),
            "num_inference_steps": int(parameters.get("num_inference_steps", 30)),
            "strength": float(parameters.get("strength", request.controls.profile.denoise_max)),
        }
        if control_images:
            call["control_image"] = control_images[0] if len(control_images) == 1 else control_images
            scales = [_conditioning_scale(parameters, kind) for kind in control_kinds]
            call["controlnet_conditioning_scale"] = scales[0] if len(scales) == 1 else scales
        try:
            image = pipeline(**call).images[0].convert("RGBA")
        except Exception as exc:
            raise BackendUnavailable(
                "SDXL ControlNet generation failed. Verify the configured base-model and "
                "ControlNet revisions are compatible and locally available. "
                f"Configured controls: {', '.join(control_kinds) or 'none'}. Error: {exc}"
            ) from exc
        job_id = request.job.job_id or "sdxl-unsaved-job"
        return GeneratedImage(
            image=image,
            job_id=job_id,
            seed=seed,
            metadata={
                "backend": "sdxl_controlnet",
                "base_model": self._config.base_model,
                "base_model_revision": self._config.revision,
                "control_kinds": list(control_kinds),
                "controlnet_revisions": {
                    kind: self._config.controlnet_revision(kind) for kind in control_kinds
                },
                "controlnet_models": {
                    kind: self._config.controlnet_model(kind) for kind in control_kinds
                },
                "height": height,
                "is_real_ai_candidate": True,
                "job_id": job_id,
                "precision": self.precision_provenance,
                "resolved_model_revisions": self._config.resolved_revisions(control_kinds),
                "seed": seed,
                "width": width,
            },
        )
    @property
    def precision_provenance(self) -> dict[str, object]:
        """Return scheduler-compatible fallback state before or after generation."""

        return precision_metadata(
            self._requested_precision, self._precision_attempts, self._applied_precision
        )

    @property
    def torch_runtime(self) -> Any:
        """Expose the loaded runtime solely for scheduler/smoke GPU accounting."""

        if self._torch is None:
            raise BackendUnavailable("SDXL ControlNet is not loaded; CUDA accounting is unavailable.")
        return self._torch

    def unload(self) -> None:
        self._pipelines.clear()
        if (
            self._torch is not None
            and self._torch.cuda.is_available()
            and hasattr(self._torch.cuda, "empty_cache")
        ):
            self._torch.cuda.empty_cache()
        self._device = None
        self._requested_precision = "fp16"
        self._torch = None
        self._diffusers = None
        self._precision_attempts = []
        self._applied_precision = None

    def _controls_for(self, request: InferenceRequest) -> tuple[tuple[str, ...], list[Image.Image]]:
        kinds = tuple(request.controls.profile.controls)
        unmapped = tuple(kind for kind in kinds if not self._has_controlnet(kind))
        if unmapped:
            raise BackendUnavailable(
                f"profile {request.controls.profile.name!r} requested controls without configured "
                f"ControlNet mappings: {', '.join(unmapped)}."
            )
        missing = tuple(kind for kind in kinds if kind not in request.controls.controls)
        if missing:
            raise BackendUnavailable(
                f"profile {request.controls.profile.name!r} requires missing control images: {', '.join(missing)}."
            )
        if not kinds:
            raise BackendUnavailable("SDXL ControlNet requires at least one configured control image.")
        return kinds, [request.controls.controls[kind].convert("RGB") for kind in kinds]

    def _pipeline_for(self, control_kinds: tuple[str, ...]) -> Any:
        cached = self._pipelines.get(control_kinds)
        if cached is not None:
            return cached
        for mode in precision_fallback_ladder(self._requested_precision):
            unavailable_reason = self._unsupported_precision_reason(mode)
            if unavailable_reason is not None:
                self._precision_attempts.append(PrecisionAttempt(mode, "skipped", unavailable_reason))
                continue
            try:
                pipeline = self._load_pipeline(control_kinds, mode)
            except Exception as exc:
                self._precision_attempts.append(PrecisionAttempt(mode, "failed", str(exc)))
                if hasattr(self._torch.cuda, "empty_cache"):
                    self._torch.cuda.empty_cache()
                continue
            self._precision_attempts.append(PrecisionAttempt(mode, "applied", "loaded successfully"))
            self._applied_precision = mode
            self._pipelines[control_kinds] = pipeline
            return pipeline
        details = "; ".join(
            f"{attempt.mode}: {attempt.reason}" for attempt in self._precision_attempts
        )
        raise BackendUnavailable(
            "Unable to load configured SDXL/ControlNet weights with the requested precision ladder. "
            f"Attempts: {details}"
        )

    def _load_pipeline(self, control_kinds: tuple[str, ...], mode: str) -> Any:
        component_kwargs = self._precision_kwargs(mode)
        control_nets = [
            self._diffusers.ControlNetModel.from_pretrained(
                self._config.controlnet_model(kind),
                revision=self._config.controlnet_revision(kind),
                **component_kwargs,
            )
            for kind in control_kinds
        ]
        controlnet: Any = control_nets[0] if len(control_nets) == 1 else control_nets
        pipeline_kwargs = self._pipeline_precision_kwargs(mode)
        pipeline = self._diffusers.StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
            self._config.base_model,
            revision=self._config.revision,
            controlnet=controlnet,
            **pipeline_kwargs,
        )
        if mode == "fp16_offload_attention_slicing_vae_tiling":
            pipeline.enable_model_cpu_offload()
            pipeline.enable_attention_slicing()
            pipeline.enable_vae_tiling()
        else:
            pipeline = pipeline.to(self._device)
        return pipeline

    def _pipeline_precision_kwargs(self, mode: str) -> dict[str, Any]:
        """Build pipeline-level quantization kwargs for modern diffusers APIs."""

        if mode != "fp8" or not hasattr(self._diffusers, "PipelineQuantizationConfig"):
            return self._precision_kwargs(mode)
        torchao = import_module("torchao")
        quantization = getattr(torchao, "quantization", None)
        config_type = getattr(quantization, "Float8WeightOnlyConfig", None)
        if config_type is None:
            return self._precision_kwargs(mode)
        quant_mapping = {
            "unet": self._diffusers.TorchAoConfig(config_type()),
        }
        quant_config = self._diffusers.PipelineQuantizationConfig(quant_mapping=quant_mapping)
        dtype = getattr(self._torch, "bfloat16", None) or self._torch.float16
        return {"quantization_config": quant_config, "torch_dtype": dtype}

    def _unsupported_precision_reason(self, mode: str) -> str | None:
        if mode in {"fp16", "fp16_offload_attention_slicing_vae_tiling"}:
            return None if hasattr(self._torch, "float16") else "torch does not expose float16"
        if mode == "fp8":
            if not hasattr(self._torch, "float8_e4m3fn"):
                return "torch does not expose FP8 dtypes"
            if not hasattr(self._diffusers, "TorchAoConfig"):
                return "installed diffusers lacks TorchAoConfig FP8 support"
            try:
                import_module("torchao")
            except ImportError:
                return (
                    "FP8 requires the optional torchao runtime; install it with "
                    "`uv sync --extra sdxl --extra sdxl-fp8`"
                )
            return None
        if mode in {"int8", "int4"}:
            if not hasattr(self._diffusers, "BitsAndBytesConfig"):
                return "installed diffusers lacks BitsAndBytesConfig support"
            try:
                import_module("bitsandbytes")
            except ImportError:
                return (
                    f"{mode.upper()} requires the optional bitsandbytes runtime; install it with "
                    "`uv sync --extra sdxl --extra sdxl-quantized`"
                )
            return None
        return f"unknown precision mode {mode!r}"

    def _precision_kwargs(self, mode: str) -> dict[str, Any]:
        if mode in {"fp16", "fp16_offload_attention_slicing_vae_tiling"}:
            return {"torch_dtype": self._torch.float16}
        if mode == "fp8":
            # diffusers 0.40 expects an AOBaseConfig object, while older
            # releases accepted the legacy string alias.
            torchao = import_module("torchao")
            quantization = getattr(torchao, "quantization", None)
            config_type = getattr(quantization, "Float8WeightOnlyConfig", None)
            if config_type is not None:
                try:
                    quant_type = config_type()
                    return {"quantization_config": self._diffusers.TorchAoConfig(quant_type)}
                except TypeError:
                    pass
            return {"quantization_config": self._diffusers.TorchAoConfig("float8wo")}
        if mode == "int8":
            return {"quantization_config": self._diffusers.BitsAndBytesConfig(load_in_8bit=True)}
        if mode == "int4":
            return {"quantization_config": self._diffusers.BitsAndBytesConfig(load_in_4bit=True)}
        raise AssertionError(f"unhandled precision mode {mode!r}")

    def _has_controlnet(self, kind: str) -> bool:
        try:
            self._config.controlnet(kind)
        except ValueError:
            return False
        return True


def _conditioning_scale(parameters: dict[str, Any], kind: str) -> float:
    scales = parameters.get("controlnet_conditioning_scale", {})
    if isinstance(scales, dict) and kind in scales:
        return float(scales[kind])
    return float(parameters.get(f"{kind}_conditioning_scale", 1.0))
