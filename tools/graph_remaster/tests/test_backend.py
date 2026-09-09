from __future__ import annotations

from hashlib import sha256
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from graph_remaster.backends.base import (
    BackendUnavailable,
    GeneratedImage,
    InferenceRequest,
    precision_fallback_ladder,
)
from graph_remaster.backends.mock import MockBackend
from graph_remaster.backends.sdxl_controlnet import SdxlControlNetBackend
from graph_remaster.cli import build_parser, main
from graph_remaster.config import (
    ConfigError,
    ControlNetConfig,
    ModelConfig,
    PipelineConfig,
    canonical_asset_profile,
)
from graph_remaster.controls.prepare import ControlBundle, MaskRecord
from graph_remaster.models import FrameKey, FrameRecord, GenerationJob


def _request(*, seed: int = 1729) -> InferenceRequest:
    frame = FrameRecord(FrameKey("a" * 64, 0, 7, 2), 4, 3)
    source = Image.new("RGBA", (4, 3), (20, 40, 60, 255))
    mask = Image.new("L", (4, 3), 255)
    controls = ControlBundle(
        frame=frame,
        profile=canonical_asset_profile("flat_tile"),
        masks=MaskRecord(frame.key, mask, mask.copy(), mask.copy()),
        controls={"canny": Image.new("L", (4, 3), 100)},
    )
    job = GenerationJob(
        frame=frame.key,
        state="QUEUED",
        profile="flat_tile",
        backend="mock",
        parameters={"seed": seed, "width": 12, "height": 9},
        job_id="job-42",
    )
    return InferenceRequest(job=job, source=source, controls=controls, reference=None)


def _image_hash(image: Image.Image) -> str:
    return sha256(image.tobytes()).hexdigest()


PIN = "a" * 40


def test_mock_backend_returns_a_marked_deterministic_candidate_with_job_metadata() -> None:
    request = _request()

    candidate = MockBackend().generate(request)

    assert candidate.job_id == "job-42"
    assert candidate.seed == 1729
    assert candidate.image.mode == "RGBA"
    assert candidate.image.size == (12, 9)
    assert candidate.metadata == {
        "backend": "mock",
        "candidate_kind": "deterministic_mock",
        "control_kinds": ["canny"],
        "height": 9,
        "is_real_ai_candidate": False,
        "job_id": "job-42",
        "profile": "flat_tile",
        "precision": {
            "requested_precision": "fp16",
            "attempts": [{"mode": "mock", "outcome": "applied", "reason": "deterministic Pillow backend"}],
            "applied_mode": "mock",
            "reasons": ["deterministic Pillow backend"],
        },
        "seed": 1729,
        "source_size": [4, 3],
        "width": 12,
    }
    assert candidate.image.getpixel((0, 0)) != request.source.getpixel((0, 0))


def test_mock_backend_is_repeatable_for_the_same_request_and_seed() -> None:
    request = _request(seed=99)

    first = MockBackend().generate(request)
    second = MockBackend().generate(request)

    assert _image_hash(first.image) == _image_hash(second.image)
    assert first.metadata == second.metadata


def test_mock_backend_accepts_npc_controls_and_records_reusable_precision_metadata() -> None:
    request = _request()
    npc = canonical_asset_profile("npc_rle")
    request = InferenceRequest(
        job=GenerationJob(
            frame=request.job.frame,
            state="QUEUED",
            profile=npc.name,
            backend="mock",
            parameters=request.job.parameters,
            job_id=request.job.job_id,
        ),
        source=request.source,
        controls=ControlBundle(
            frame=request.controls.frame,
            profile=npc,
            masks=request.controls.masks,
            controls={"edge": Image.new("L", (4, 3), 80), "silhouette": Image.new("L", (4, 3), 255)},
        ),
        reference=None,
    )
    backend = MockBackend()

    backend.load("cpu", "int8")
    candidate = backend.generate(request)

    assert candidate.metadata["control_kinds"] == ["edge", "silhouette"]
    assert candidate.metadata["precision"] == {
        "requested_precision": "int8",
        "attempts": [{"mode": "mock", "outcome": "applied", "reason": "deterministic Pillow backend"}],
        "applied_mode": "mock",
        "reasons": ["deterministic Pillow backend"],
    }


def test_precision_fallback_ladder_is_ordered_and_preserves_non_fp16_requests() -> None:
    assert precision_fallback_ladder("fp16") == (
        "fp16",
        "fp16_offload_attention_slicing_vae_tiling",
        "fp8",
        "int8",
        "int4",
    )
    assert precision_fallback_ladder("int8") == ("int8", "int4")


def test_sdxl_load_accepts_non_fp16_requests_and_exposes_pending_fallback_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return True

    class FakeTorch:
        cuda = FakeCuda()

    class FakeDiffusers:
        pass

    monkeypatch.setattr(
        "graph_remaster.backends.sdxl_controlnet.import_module",
        lambda name: {"torch": FakeTorch, "diffusers": FakeDiffusers}[name],
    )
    backend = SdxlControlNetBackend(ModelConfig())

    backend.load("cuda:0", "int8")

    assert backend.precision_provenance == {
        "requested_precision": "int8",
        "attempts": [],
        "applied_mode": None,
        "reasons": [],
    }


def test_sdxl_falls_back_to_offload_attention_slicing_and_vae_tiling_after_fp16_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return True

        @staticmethod
        def empty_cache() -> None:
            calls.append("empty_cache")

    class FakeTorch:
        cuda = FakeCuda()
        float16 = "float16"

        class Generator:
            def __init__(self, device: str) -> None:
                self.device = device

            def manual_seed(self, seed: int) -> "FakeTorch.Generator":
                return self

    class FakeControlNet:
        @staticmethod
        def from_pretrained(*args: object, **kwargs: object) -> object:
            return object()

    class FakePipeline:
        def __init__(self, first: bool) -> None:
            self.first = first

        def to(self, device: str) -> "FakePipeline":
            if self.first:
                raise RuntimeError("out of memory")
            return self

        def enable_model_cpu_offload(self) -> None:
            calls.append("offload")

        def enable_attention_slicing(self) -> None:
            calls.append("attention_slicing")

        def enable_vae_tiling(self) -> None:
            calls.append("vae_tiling")

        def __call__(self, **kwargs: object) -> object:
            return type("Result", (), {"images": [Image.new("RGB", (12, 9))]})()

    class FakePipelineFactory:
        count = 0

        @classmethod
        def from_pretrained(cls, *args: object, **kwargs: object) -> FakePipeline:
            cls.count += 1
            return FakePipeline(first=cls.count == 1)

    class FakeDiffusers:
        ControlNetModel = FakeControlNet
        StableDiffusionXLControlNetImg2ImgPipeline = FakePipelineFactory

    monkeypatch.setattr(
        "graph_remaster.backends.sdxl_controlnet.import_module",
        lambda name: {"torch": FakeTorch, "diffusers": FakeDiffusers}[name],
    )
    backend = SdxlControlNetBackend(ModelConfig())

    backend.load("cuda:0", "fp16")
    candidate = backend.generate(_request())

    assert calls == ["empty_cache", "offload", "attention_slicing", "vae_tiling"]
    assert candidate.metadata["precision"] == {
        "requested_precision": "fp16",
        "attempts": [
            {"mode": "fp16", "outcome": "failed", "reason": "out of memory"},
            {
                "mode": "fp16_offload_attention_slicing_vae_tiling",
                "outcome": "applied",
                "reason": "loaded successfully",
            },
        ],
        "applied_mode": "fp16_offload_attention_slicing_vae_tiling",
        "reasons": ["out of memory", "loaded successfully"],
    }


@pytest.mark.parametrize(
    ("mode", "runtime_name", "expected_quantizer"),
    [
        ("fp8", "torchao", "TorchAoConfig"),
        ("int8", "bitsandbytes", "BitsAndBytesConfig"),
        ("int4", "bitsandbytes", "BitsAndBytesConfig"),
    ],
)
def test_sdxl_applies_available_quantized_precision_modes_without_downloading_weights(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    runtime_name: str,
    expected_quantizer: str,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return True

    class FakeTorch:
        cuda = FakeCuda()
        float8_e4m3fn = "float8"

        class Generator:
            def __init__(self, device: str) -> None:
                self.device = device

            def manual_seed(self, seed: int) -> "FakeTorch.Generator":
                return self

    class TorchAoConfig:
        def __init__(self, mode: str) -> None:
            self.mode = mode

    class BitsAndBytesConfig:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class FakeControlNet:
        @staticmethod
        def from_pretrained(*args: object, **kwargs: object) -> object:
            calls.append(kwargs)
            return object()

    class FakePipeline:
        def to(self, device: str) -> "FakePipeline":
            return self

        def __call__(self, **kwargs: object) -> object:
            return type("Result", (), {"images": [Image.new("RGB", (12, 9))]})()

    class FakePipelineFactory:
        @staticmethod
        def from_pretrained(*args: object, **kwargs: object) -> FakePipeline:
            calls.append(kwargs)
            return FakePipeline()

    FakeDiffusers = type(
        "FakeDiffusers",
        (),
        {
            "ControlNetModel": FakeControlNet,
            "StableDiffusionXLControlNetImg2ImgPipeline": FakePipelineFactory,
            "TorchAoConfig": TorchAoConfig,
            "BitsAndBytesConfig": BitsAndBytesConfig,
        },
    )

    def fake_import(name: str) -> object:
        return {
            "torch": FakeTorch,
            "diffusers": FakeDiffusers,
            runtime_name: object(),
        }[name]

    monkeypatch.setattr("graph_remaster.backends.sdxl_controlnet.import_module", fake_import)
    backend = SdxlControlNetBackend(ModelConfig())

    backend.load("cuda:0", mode)
    candidate = backend.generate(_request())

    assert candidate.metadata["precision"]["applied_mode"] == mode
    assert candidate.metadata["precision"]["attempts"] == [
        {"mode": mode, "outcome": "applied", "reason": "loaded successfully"}
    ]
    assert type(calls[0]["quantization_config"]).__name__ == expected_quantizer


def test_sdxl_quantized_precision_failure_names_the_required_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return True

    class FakeTorch:
        cuda = FakeCuda()

        class Generator:
            def __init__(self, device: str) -> None:
                self.device = device

            def manual_seed(self, seed: int) -> "FakeTorch.Generator":
                return self

    class FakeDiffusers:
        class BitsAndBytesConfig:
            pass

    def fake_import(name: str) -> object:
        if name == "torch":
            return FakeTorch
        if name == "diffusers":
            return FakeDiffusers
        raise ImportError(name)

    monkeypatch.setattr("graph_remaster.backends.sdxl_controlnet.import_module", fake_import)
    backend = SdxlControlNetBackend(ModelConfig())

    backend.load("cuda:0", "int8")
    with pytest.raises(BackendUnavailable, match=r"sdxl-quantized"):
        backend.generate(_request())


def test_sdxl_backend_rejects_a_non_cuda_device_without_importing_optional_runtime() -> None:
    backend = SdxlControlNetBackend(ModelConfig())

    with pytest.raises(BackendUnavailable, match=r"CUDA device.*cuda:N"):
        backend.load("cpu", "fp16")

    assert "torch" not in sys.modules
    assert "diffusers" not in sys.modules


def test_generate_parser_exposes_opt_in_real_model_smoke_on_a_selected_device() -> None:
    args = build_parser().parse_args(["generate", "--real-model-smoke", "--device", "cuda:1"])

    assert args.real_model_smoke is True
    assert args.device == "cuda:1"


def test_model_config_reads_each_sdxl_and_controlnet_revision_from_pipeline_config() -> None:
    config = PipelineConfig.from_mapping(
        {
            "project": {"name": "black-gate"},
            "paths": {"data": "game", "work": "work"},
            "render": {"scale": 6, "logical_width": 320, "logical_height": 200},
            "model": {
                "base_model": "base-model",
                "revision": PIN,
                "controlnets": {
                    "canny": {"model": "canny-model", "revision": PIN},
                    "depth": {"model": "depth-model", "revision": PIN},
                    "edge": {"model": "edge-model", "revision": PIN},
                    "silhouette": {"model": "silhouette-model", "revision": PIN},
                },
            },
        }
    )

    assert config.model.base_model == "base-model"
    assert config.model.revision == PIN
    assert config.model.controlnet_model("canny") == "canny-model"
    assert config.model.controlnet_revision("canny") == PIN
    assert config.model.controlnet_model("depth") == "depth-model"
    assert config.model.controlnet_revision("depth") == PIN
    assert config.model.controlnet_model("edge") == "edge-model"
    assert config.model.controlnet_model("silhouette") == "silhouette-model"


def test_real_model_config_rejects_mutable_revisions() -> None:
    config = ModelConfig(
        base_model="base-model",
        revision="main",
        controlnets=(ControlNetConfig("canny", "canny-model", PIN),),
    )

    with pytest.raises(ConfigError, match="pinned commit SHA"):
        config.validate_for_real_model()


def test_sdxl_backend_lazily_uses_configured_revisions_and_profile_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {"controls": [], "pipelines": []}

    class FakeGenerator:
        def __init__(self, device: str) -> None:
            self.device = device
            self.seed: int | None = None

        def manual_seed(self, seed: int) -> "FakeGenerator":
            self.seed = seed
            return self

    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return True

        @staticmethod
        def empty_cache() -> None:
            return None

    class FakeTorch:
        cuda = FakeCuda()
        float16 = "float16"
        Generator = FakeGenerator

    class FakeControlNetModel:
        @staticmethod
        def from_pretrained(model: str, **kwargs: object) -> tuple[str, dict[str, object]]:
            calls["controls"].append((model, kwargs))  # type: ignore[union-attr]
            return (model, kwargs)

    class FakePipeline:
        def __init__(self) -> None:
            self.call: dict[str, object] | None = None

        def to(self, device: str) -> "FakePipeline":
            calls["device"] = device
            return self

        def __call__(self, **kwargs: object) -> object:
            self.call = kwargs
            calls["request"] = kwargs
            return type("Result", (), {"images": [Image.new("RGB", (16, 8), (1, 2, 3))]})()

    class FakePipelineFactory:
        @staticmethod
        def from_pretrained(model: str, **kwargs: object) -> FakePipeline:
            calls["pipelines"].append((model, kwargs))  # type: ignore[union-attr]
            return FakePipeline()

    class FakeDiffusers:
        ControlNetModel = FakeControlNetModel
        StableDiffusionXLControlNetImg2ImgPipeline = FakePipelineFactory

    def fake_import(name: str) -> object:
        return {"torch": FakeTorch, "diffusers": FakeDiffusers}[name]

    monkeypatch.setattr("graph_remaster.backends.sdxl_controlnet.import_module", fake_import)
    request = _request(seed=77)
    building_profile = canonical_asset_profile("npc_rle")
    request = InferenceRequest(
        job=GenerationJob(
            frame=request.job.frame,
            state="QUEUED",
            profile=building_profile.name,
            backend="sdxl_controlnet",
            parameters={
                "seed": 77,
                "width": 16,
                "height": 8,
                "controlnet_conditioning_scale": {"edge": 0.7, "silhouette": 0.4},
            },
            job_id="job-sdxl",
        ),
        source=request.source,
        controls=ControlBundle(
            frame=request.controls.frame,
            profile=building_profile,
            masks=request.controls.masks,
            controls={"edge": Image.new("L", (4, 3), 80), "silhouette": Image.new("L", (4, 3), 255)},
        ),
        reference=None,
    )
    config = ModelConfig(
        base_model="base-model",
        revision=PIN,
        controlnets=(
            ControlNetConfig("edge", "edge-model", PIN),
            ControlNetConfig("silhouette", "silhouette-model", PIN),
        ),
    )
    backend = SdxlControlNetBackend(config)

    backend.load("cuda:1", "fp16")
    candidate = backend.generate(request)

    assert calls["controls"] == [
        ("edge-model", {"revision": PIN, "torch_dtype": "float16"}),
        ("silhouette-model", {"revision": PIN, "torch_dtype": "float16"}),
    ]
    assert calls["pipelines"] == [
        (
            "base-model",
            {
                "revision": PIN,
                "controlnet": [
                    ("edge-model", {"revision": PIN, "torch_dtype": "float16"}),
                    ("silhouette-model", {"revision": PIN, "torch_dtype": "float16"}),
                ],
                "torch_dtype": "float16",
            },
        )
    ]
    generated = calls["request"]
    assert isinstance(generated, dict)
    assert generated["image"].size == (16, 8)
    assert generated["generator"].device == "cuda:1"
    assert generated["generator"].seed == 77
    assert generated["control_image"] == [
        request.controls.controls["edge"].convert("RGB"),
        request.controls.controls["silhouette"].convert("RGB"),
    ]
    assert generated["controlnet_conditioning_scale"] == [0.7, 0.4]
    assert candidate.image.size == (16, 8)
    assert candidate.metadata["controlnet_revisions"] == {
        "edge": PIN,
        "silhouette": PIN,
    }
    assert candidate.metadata["precision"] == {
        "requested_precision": "fp16",
        "attempts": [{"mode": "fp16", "outcome": "applied", "reason": "loaded successfully"}],
        "applied_mode": "fp16",
        "reasons": ["loaded successfully"],
    }
    assert candidate.metadata["resolved_model_revisions"] == {
        "base_model": {"model": "base-model", "revision": PIN},
        "controlnets": {
            "edge": {"model": "edge-model", "revision": PIN},
            "silhouette": {"model": "silhouette-model", "revision": PIN},
        },
    }


def test_real_model_smoke_returns_actionable_nonzero_failure_without_downloading_weights(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.toml"
    config_path.write_text(
        "[project]\nname = 'black-gate'\n[paths]\ndata = 'game'\nwork = 'work'\n"
        "[render]\nscale = 6\nlogical_width = 320\nlogical_height = 200\n",
        encoding="utf-8",
    )

    status = main(["generate", "--config", str(config_path), "--real-model-smoke", "--device", "cpu"])

    report = json.loads(
        (tmp_path / "work" / "candidates" / "default" / "real-model-smoke.json").read_text(
            encoding="utf-8"
        )
    )
    assert status == 2
    assert report["status"] == "failed"
    assert "CUDA device" in report["error"]
    html = (tmp_path / "work" / "candidates" / "default" / "real-model-smoke.html").read_text(
        encoding="utf-8"
    )
    assert "Real model smoke failed" in html


def test_real_model_smoke_rejects_mutable_model_revision_and_writes_offline_html(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.toml"
    config_path.write_text(
        "[project]\nname = 'black-gate'\n[paths]\ndata = 'game'\nwork = 'work'\n"
        "[render]\nscale = 6\nlogical_width = 320\nlogical_height = 200\n"
        "[model]\nrevision = 'main'\n",
        encoding="utf-8",
    )

    status = main(["generate", "--config", str(config_path), "--real-model-smoke", "--device", "cuda:0"])

    report_root = tmp_path / "work" / "candidates" / "default"
    report = json.loads((report_root / "real-model-smoke.json").read_text(encoding="utf-8"))
    html = (report_root / "real-model-smoke.html").read_text(encoding="utf-8")
    assert status == 2
    assert "pinned commit SHA" in report["error"]
    assert "Real model smoke failed" in html


def test_real_model_smoke_writes_an_offline_html_report_on_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "pipeline.toml"
    config_path.write_text(
        "[project]\nname = 'black-gate'\n[paths]\ndata = 'game'\nwork = 'work'\n"
        "[render]\nscale = 6\nlogical_width = 320\nlogical_height = 200\n",
        encoding="utf-8",
    )

    seen_devices: list[object] = []
    initialized = False

    class FakeCuda:
        @staticmethod
        def init() -> None:
            nonlocal initialized
            initialized = True

        @staticmethod
        def reset_peak_memory_stats(device: object) -> None:
            assert initialized
            seen_devices.append(device)
            return None

        @staticmethod
        def max_memory_allocated(device: object) -> int:
            seen_devices.append(device)
            return 123

    class FakeTorch:
        cuda = FakeCuda()

        @staticmethod
        def device(value: str) -> tuple[str, str]:
            return ("torch-device", value)

    class FakeBackend:
        torch_runtime = FakeTorch()

        def __init__(self, config: ModelConfig) -> None:
            self.config = config

        def load(self, device: str, precision: str) -> None:
            return None

        def generate(self, request: InferenceRequest) -> GeneratedImage:
            return GeneratedImage(Image.new("RGBA", (64, 64)), "real-model-smoke", 8675309, {})

        def unload(self) -> None:
            return None

    monkeypatch.setattr("graph_remaster.backends.sdxl_controlnet.SdxlControlNetBackend", FakeBackend)

    status = main(["generate", "--config", str(config_path), "--real-model-smoke", "--device", "cuda:0"])

    html = (tmp_path / "work" / "candidates" / "default" / "real-model-smoke.html").read_text(
        encoding="utf-8"
    )
    assert status == 0
    assert "Real model smoke completed" in html
    assert "peak_vram_bytes" in html
    assert initialized
    assert seen_devices == [("torch-device", "cuda:0"), ("torch-device", "cuda:0")]
