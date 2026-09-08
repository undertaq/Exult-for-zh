from __future__ import annotations

from hashlib import sha256
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from graph_remaster.backends.base import BackendUnavailable, InferenceRequest
from graph_remaster.backends.mock import MockBackend
from graph_remaster.backends.sdxl_controlnet import SdxlControlNetBackend
from graph_remaster.cli import build_parser, main
from graph_remaster.config import ModelConfig, PipelineConfig, canonical_asset_profile
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
                "revision": "base-revision",
                "canny_controlnet": "canny-model",
                "canny_revision": "canny-revision",
                "depth_controlnet": "depth-model",
                "depth_revision": "depth-revision",
            },
        }
    )

    assert config.model.base_model == "base-model"
    assert config.model.revision == "base-revision"
    assert config.model.controlnet_model("canny") == "canny-model"
    assert config.model.controlnet_revision("canny") == "canny-revision"
    assert config.model.controlnet_model("depth") == "depth-model"
    assert config.model.controlnet_revision("depth") == "depth-revision"


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
    building_profile = canonical_asset_profile("building_combo")
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
                "controlnet_conditioning_scale": {"canny": 0.7, "depth": 0.4},
            },
            job_id="job-sdxl",
        ),
        source=request.source,
        controls=ControlBundle(
            frame=request.controls.frame,
            profile=building_profile,
            masks=request.controls.masks,
            controls={"canny": request.controls.controls["canny"], "depth": Image.new("L", (4, 3), 80)},
        ),
        reference=None,
    )
    config = ModelConfig(
        base_model="base-model",
        revision="base-revision",
        canny_controlnet="canny-model",
        canny_revision="canny-revision",
        depth_controlnet="depth-model",
        depth_revision="depth-revision",
    )
    backend = SdxlControlNetBackend(config)

    backend.load("cuda:1", "fp16")
    candidate = backend.generate(request)

    assert calls["controls"] == [
        ("canny-model", {"revision": "canny-revision", "torch_dtype": "float16"}),
        ("depth-model", {"revision": "depth-revision", "torch_dtype": "float16"}),
    ]
    assert calls["pipelines"] == [
        (
            "base-model",
            {
                "revision": "base-revision",
                "controlnet": [
                    ("canny-model", {"revision": "canny-revision", "torch_dtype": "float16"}),
                    ("depth-model", {"revision": "depth-revision", "torch_dtype": "float16"}),
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
        request.controls.controls["canny"].convert("RGB"),
        request.controls.controls["depth"].convert("RGB"),
    ]
    assert generated["controlnet_conditioning_scale"] == [0.7, 0.4]
    assert candidate.image.size == (16, 8)
    assert candidate.metadata["controlnet_revisions"] == {
        "canny": "canny-revision",
        "depth": "depth-revision",
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
