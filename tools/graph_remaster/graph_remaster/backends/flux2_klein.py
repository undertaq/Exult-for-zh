"""Lazy, local Flux2 Klein image-editing backend."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

from PIL import Image

from ..config import ModelConfig
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


class Flux2KleinBackend:
    """Run a single-reference Flux2 Klein edit with lazy local model loading."""

    def __init__(self, config: ModelConfig) -> None:
        self._config = config
        self._device: str | None = None
        self._requested_precision: PrecisionProfile = "fp16"
        self._torch: Any | None = None
        self._diffusers: Any | None = None
        self._pipeline: Any | None = None
        self._precision_attempts: list[PrecisionAttempt] = []
        self._applied_precision: str | None = None

    def load(self, device: str, precision: PrecisionProfile) -> None:
        try:
            precision_fallback_ladder(precision)
        except ValueError as exc:
            raise BackendUnavailable(
                f"Flux2 Klein configuration is not runnable: {exc}"
            ) from exc
        if not device.startswith("cuda"):
            raise BackendUnavailable(
                f"Flux2 Klein requires a CUDA device; got {device!r}. Pass --device cuda:N."
            )
        model_path = Path(self._config.base_model)
        if model_path.is_absolute() and not model_path.is_dir():
            raise BackendUnavailable(
                f"Flux2 Klein local model directory does not exist: {model_path}"
            )
        try:
            torch = import_module("torch")
            diffusers = import_module("diffusers")
        except ImportError as exc:
            raise BackendUnavailable(
                "Flux2 Klein requires optional torch and diffusers dependencies."
            ) from exc
        if not torch.cuda.is_available():
            raise BackendUnavailable(
                "Flux2 Klein requires CUDA, but torch.cuda.is_available() is false."
            )
        if not hasattr(diffusers, "Flux2KleinPipeline"):
            raise BackendUnavailable(
                "installed diffusers lacks Flux2KleinPipeline; upgrade the local Diffusers runtime"
            )
        if not hasattr(torch, "bfloat16"):
            raise BackendUnavailable("installed torch lacks bfloat16 support required by Flux2 Klein")
        self._device = device
        self._requested_precision = precision
        self._torch = torch
        self._diffusers = diffusers
        self._pipeline = None
        self._precision_attempts = []
        self._applied_precision = None

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
            raise BackendUnavailable("Flux2 Klein is not loaded; CUDA accounting is unavailable.")
        return self._torch

    def generate(self, request: InferenceRequest) -> GeneratedImage:
        if self._device is None or self._torch is None:
            raise BackendUnavailable("Flux2 Klein is not loaded; call load(device, precision) first.")
        pipeline = self._pipeline_for()
        seed = _seed(request)
        width, height = _dimensions(request)
        parameters = request.job.parameters
        source = request.source.convert("RGBA").resize(
            (width, height), source_resampling(parameters)
        ).convert("RGB")
        generator = self._torch.Generator(device=self._device).manual_seed(seed)
        call: dict[str, Any] = {
            "image": source,
            "prompt": str(parameters.get("prompt", "polished hand-painted fantasy RPG game asset")),
            "width": width,
            "height": height,
            "guidance_scale": float(parameters.get("guidance_scale", 1.0)),
            "num_inference_steps": int(parameters.get("num_inference_steps", 4)),
            "generator": generator,
        }
        try:
            with self._torch.inference_mode():
                image = pipeline(**call).images[0].convert("RGBA")
        except Exception as exc:
            raise BackendUnavailable(
                "Flux2 Klein image editing failed. Verify the local model revision and "
                f"input dimensions. Error: {exc}"
            ) from exc
        job_id = request.job.job_id or "flux2-klein-unsaved-job"
        return GeneratedImage(
            image=image,
            job_id=job_id,
            seed=seed,
            metadata={
                "backend": "flux2_klein",
                "base_model": self._config.base_model,
                "base_model_revision": self._config.revision,
                "control_kinds": [],
                "height": height,
                "is_real_ai_candidate": True,
                "job_id": job_id,
                "negative_prompt_supported": False,
                "precision": self.precision_provenance,
                "precision_components": self._precision_components(),
                "reference_mode": "single_image_edit",
                "seed": seed,
                "source_resampling": str(parameters.get("source_resampling", "nearest")),
                "width": width,
            },
        )

    def unload(self) -> None:
        self._pipeline = None
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

    def _pipeline_for(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        mode = self._requested_precision
        try:
            pipeline = self._load_pipeline(mode)
        except Exception as exc:
            self._precision_attempts.append(PrecisionAttempt(mode, "failed", str(exc)))
            if self._torch is not None and hasattr(self._torch.cuda, "empty_cache"):
                self._torch.cuda.empty_cache()
            raise BackendUnavailable(
                "Unable to load Flux2 Klein with the requested precision. "
                f"Attempt {mode}: {exc}"
            ) from exc
        self._precision_attempts.append(PrecisionAttempt(mode, "applied", "loaded successfully"))
        self._applied_precision = mode
        self._pipeline = pipeline
        return pipeline

    def _load_pipeline(self, mode: str) -> Any:
        if mode not in {"fp8", "fp16", "fp16_offload_attention_slicing_vae_tiling"}:
            raise BackendUnavailable(
                f"Flux2 Klein supports fp8 or BF16 CPU-offload modes, not {mode!r}"
            )
        kwargs: dict[str, Any] = {"torch_dtype": self._torch.bfloat16}
        model_path = Path(self._config.base_model)
        if model_path.is_absolute():
            kwargs["local_files_only"] = True
        else:
            kwargs["revision"] = self._config.revision
        if mode == "fp8":
            torchao = import_module("torchao")
            quantization = getattr(torchao, "quantization", None)
            config_type = getattr(quantization, "Float8WeightOnlyConfig", None)
            if config_type is None:
                raise BackendUnavailable("torchao lacks Float8WeightOnlyConfig")
            if not hasattr(self._diffusers, "PipelineQuantizationConfig"):
                raise BackendUnavailable("installed diffusers lacks PipelineQuantizationConfig")
            if not hasattr(self._diffusers, "TorchAoConfig"):
                raise BackendUnavailable("installed diffusers lacks TorchAoConfig")
            kwargs["quantization_config"] = self._diffusers.PipelineQuantizationConfig(
                quant_mapping={
                    "transformer": self._diffusers.TorchAoConfig(config_type())
                }
            )
        pipeline = self._diffusers.Flux2KleinPipeline.from_pretrained(
            self._config.base_model, **kwargs
        )
        pipeline.enable_model_cpu_offload()
        return pipeline

    def _precision_components(self) -> dict[str, str]:
        if self._applied_precision == "fp8":
            return {
                "transformer": "float8_weight_only",
                "text_encoder": "bfloat16",
                "vae": "bfloat16",
            }
        return {
            "transformer": "bfloat16",
            "text_encoder": "bfloat16",
            "vae": "bfloat16",
        }
