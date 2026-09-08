"""Optional, lazy SDXL ControlNet backend."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from PIL import Image

from ..config import ModelConfig
from .base import BackendUnavailable, GeneratedImage, InferenceRequest, PrecisionProfile
from .mock import _dimensions, _seed


class SdxlControlNetBackend:
    """Run one FP16 SDXL ControlNet image-to-image request at a time."""

    def __init__(self, config: ModelConfig) -> None:
        self._config = config
        self._device: str | None = None
        self._precision: PrecisionProfile | None = None
        self._torch: Any | None = None
        self._diffusers: Any | None = None
        self._pipelines: dict[tuple[str, ...], Any] = {}

    def load(self, device: str, precision: PrecisionProfile) -> None:
        if precision != "fp16":
            raise BackendUnavailable(
                f"SDXL ControlNet requires the pipeline's fp16 profile, not {precision!r}"
            )
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
        self._precision = precision
        self._torch = torch
        self._diffusers = diffusers

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
            "image": request.source.convert("RGBA").resize((width, height), Image.Resampling.NEAREST),
            "generator": generator,
            "guidance_scale": float(parameters.get("guidance_scale", 7.5)),
            "num_inference_steps": int(parameters.get("num_inference_steps", 30)),
            "strength": float(parameters.get("strength", request.controls.profile.denoise_max)),
        }
        if control_images:
            call["control_image"] = control_images
            call["controlnet_conditioning_scale"] = [
                _conditioning_scale(parameters, kind) for kind in control_kinds
            ]
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
                "precision": self._precision,
                "seed": seed,
                "width": width,
            },
        )

    @property
    def torch_runtime(self) -> Any:
        """Expose the loaded runtime solely for scheduler/smoke GPU accounting."""

        if self._torch is None:
            raise BackendUnavailable("SDXL ControlNet is not loaded; CUDA accounting is unavailable.")
        return self._torch

    def unload(self) -> None:
        self._pipelines.clear()
        if self._torch is not None and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()
        self._device = None
        self._precision = None
        self._torch = None
        self._diffusers = None

    def _controls_for(self, request: InferenceRequest) -> tuple[tuple[str, ...], list[Image.Image]]:
        kinds = tuple(request.controls.profile.controls)
        unsupported = tuple(kind for kind in kinds if kind not in {"canny", "depth"})
        if unsupported:
            raise BackendUnavailable(
                "SDXL ControlNet supports only configured canny/depth controls; "
                f"profile {request.controls.profile.name!r} requested {', '.join(unsupported)}."
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
        try:
            control_nets = [
                self._diffusers.ControlNetModel.from_pretrained(
                    self._config.controlnet_model(kind),
                    revision=self._config.controlnet_revision(kind),
                    torch_dtype=self._torch.float16,
                )
                for kind in control_kinds
            ]
            controlnet: Any = control_nets[0] if len(control_nets) == 1 else control_nets
            pipeline = self._diffusers.StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
                self._config.base_model,
                revision=self._config.revision,
                controlnet=controlnet,
                torch_dtype=self._torch.float16,
            ).to(self._device)
        except Exception as exc:
            raise BackendUnavailable(
                "Unable to load configured SDXL/ControlNet weights. Check network/cache access and "
                "that base_model, revision, and requested ControlNet revisions are compatible. "
                f"Base: {self._config.base_model}@{self._config.revision}; controls: "
                + ", ".join(
                    f"{self._config.controlnet_model(kind)}@{self._config.controlnet_revision(kind)}"
                    for kind in control_kinds
                )
                + f". Error: {exc}"
            ) from exc
        self._pipelines[control_kinds] = pipeline
        return pipeline


def _conditioning_scale(parameters: dict[str, Any], kind: str) -> float:
    scales = parameters.get("controlnet_conditioning_scale", {})
    if isinstance(scales, dict) and kind in scales:
        return float(scales[kind])
    return float(parameters.get(f"{kind}_conditioning_scale", 1.0))
