"""Process-safe scheduler coverage using only Pillow-backed fake backends."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from graph_remaster.backends.base import GeneratedImage, InferenceRequest
from graph_remaster.cli import _normalize_cuda_device, main
from graph_remaster.controls.prepare import ControlBundle, MaskRecord
from graph_remaster.db import AssetStore
from graph_remaster.models import FrameKey, FrameRecord, GenerationJob, ShapeRecord, SourceArchive
from graph_remaster.config import canonical_asset_profile
from graph_remaster.workers.devices import CudaDeviceInfo
from graph_remaster.workers.precision import CapabilitySet, resolve_precision
from graph_remaster.workers.scheduler import ResourceFailed, WorkerBusyError, WorkerPool


class RecordingBackend:
    """Picklable fake runtime used inside spawned workers."""

    def load(self, device: str, precision: str) -> None:
        self.device = device
        self.precision = precision

    def generate(self, request: InferenceRequest) -> GeneratedImage:
        return GeneratedImage(
            Image.new("RGBA", (request.job.parameters["width"], request.job.parameters["height"])),
            request.job.job_id or "missing",
            request.job.parameters["seed"],
            {"seen": {"device": self.device, "precision": self.precision,
                      "seed": request.job.parameters["seed"],
                      "width": request.job.parameters["width"],
                      "height": request.job.parameters["height"]}},
        )

    def unload(self) -> None:
        pass


class OomThenOffloadBackend(RecordingBackend):
    def generate(self, request: InferenceRequest) -> GeneratedImage:
        if self.precision == "fp16":
            raise RuntimeError("CUDA out of memory while allocating")
        return super().generate(request)


class AlwaysOomBackend(RecordingBackend):
    def generate(self, request: InferenceRequest) -> GeneratedImage:
        raise RuntimeError("CUDA out of memory while allocating")


class BrokenBackend(RecordingBackend):
    def generate(self, request: InferenceRequest) -> GeneratedImage:
        raise RuntimeError("invalid model component")


def _devices() -> list[CudaDeviceInfo]:
    return [
        CudaDeviceInfo(0, "RTX 3060", 12_000, 6_000, (8, 6), "12.8", "started"),
        CudaDeviceInfo(1, "RTX 5060 Ti", 16_000, 15_000, (12, 0), "12.8", "started"),
    ]


def _request(job_id: str, *, seed: int = 7, width: int = 12, height: int = 9) -> InferenceRequest:
    key = FrameKey("a" * 64, 0, 1, 0)
    frame = FrameRecord(key, width, height)
    source = Image.new("RGBA", (width, height), (1, 2, 3, 255))
    mask = Image.new("L", source.size, 255)
    return InferenceRequest(
        GenerationJob(key, "QUEUED", "flat_tile", "fake", {"seed": seed, "width": width, "height": height}, job_id),
        source,
        ControlBundle(frame, canonical_asset_profile("flat_tile"), MaskRecord(key, mask, mask, mask), {"canny": mask}),
    )


def _seed_job(database: Path, job_id: str) -> None:
    store = AssetStore.open(database)
    store.migrate()
    key = FrameKey("a" * 64, 0, 1, 0)
    source = database.parent / f"{job_id}.png"
    Image.new("RGBA", (12, 9), (1, 2, 3, 255)).save(source)
    store.upsert_source_archive(SourceArchive(key.archive_sha256, "source.ipf"))
    store.upsert_shape(ShapeRecord(key.archive_sha256, key.archive_index, key.shape_id, 12, 9))
    store.upsert_frame(FrameRecord(key, 12, 9, metadata={"rgba_preview_path": str(source)}))
    store.create_generation_job(GenerationJob(key, "QUEUED", "flat_tile", "fake", {"seed": 7}, job_id))
    store.close()


def test_pool_uses_one_serial_worker_per_device_and_deterministic_largest_free_assignment(tmp_path: Path) -> None:
    pool = WorkerPool(
        _devices(), RecordingBackend, {"one": _request("one"), "two": _request("two"), "three": _request("three")},
        candidates_dir=tmp_path / "candidates",
    )
    try:
        first = pool.submit("one")
        second = pool.submit("two")
        with pytest.raises(WorkerBusyError):
            pool.submit("three")

        assert first.result(timeout=10).metadata["worker"]["device"]["index"] == 1
        assert second.result(timeout=10).metadata["worker"]["device"]["index"] == 0
        assert pool.start_method == "spawn"
    finally:
        pool.close()


def test_oom_retries_once_with_offload_without_changing_seed_or_dimensions(tmp_path: Path) -> None:
    pool = WorkerPool(
        [_devices()[0]], OomThenOffloadBackend, {"job": _request("job", seed=1337, width=18, height=11)},
        candidates_dir=tmp_path / "candidates",
    )
    try:
        candidate = pool.submit("job").result(timeout=10)
    finally:
        pool.close()

    assert candidate.metadata["seen"] == {
        "device": "cuda:0", "precision": "fp16_offload_attention_slicing_vae_tiling",
        "seed": 1337, "width": 18, "height": 11,
    }
    assert candidate.metadata["precision"]["applied_mode"] == "fp16_offload_attention_slicing_vae_tiling"
    assert [attempt["mode"] for attempt in candidate.metadata["precision"]["attempts"]] == [
        "fp16", "fp16_offload_attention_slicing_vae_tiling"
    ]


def test_repeated_oom_records_resource_failure_and_traceback_in_sqlite(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    _seed_job(database, "job")
    pool = WorkerPool(
        [_devices()[0]], AlwaysOomBackend, {"job": _request("job")}, database=database,
        candidates_dir=tmp_path / "candidates", reports_dir=tmp_path / "reports",
    )
    try:
        with pytest.raises(ResourceFailed):
            pool.submit("job").result(timeout=10)
    finally:
        pool.close()

    store = AssetStore.open(database)
    assert store.job_state("job").value == "RESOURCE_FAILED"
    error = store.get_job_error("job")
    metadata = store.job_parameters("job")
    store.close()
    assert error is not None
    assert "CUDA out of memory" in error["error"]
    assert "Traceback" in error["traceback"]
    assert Path(error["report_path"]).is_file()
    assert metadata["worker"]["device"]["index"] == 0
    assert metadata["precision"]["components"]["unet"] == "float16_cpu_offload"


def test_full_supported_ladder_records_each_oom_attempt_and_writes_json_and_html_reports(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    _seed_job(database, "job")
    reports = tmp_path / "reports"
    pool = WorkerPool(
        [_devices()[1]], AlwaysOomBackend, {"job": _request("job")}, database=database,
        candidates_dir=tmp_path / "candidates", reports_dir=reports,
        capabilities=CapabilitySet(torchao=True, bitsandbytes=True),
    )
    try:
        with pytest.raises(ResourceFailed):
            pool.submit("job").result(timeout=10)
    finally:
        pool.close()

    store = AssetStore.open(database)
    error = store.get_job_error("job")
    metadata = store.job_parameters("job")
    store.close()
    assert [attempt["mode"] for attempt in metadata["precision"]["attempts"]] == [
        "fp16", "fp16_offload_attention_slicing_vae_tiling", "fp8", "int8", "int4"
    ]
    assert all(attempt["outcome"] == "failed" for attempt in metadata["precision"]["attempts"])
    assert metadata["precision"]["components"]["text_encoder"] == "int4_weight_only"
    assert error is not None
    report = Path(error["report_path"])
    assert report.is_file()
    assert report.with_suffix(".html").is_file()
    assert "CUDA out of memory" in report.with_suffix(".html").read_text(encoding="utf-8")


def test_non_oom_backend_failure_is_terminal_resource_failure_with_json_html_and_traceback(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    _seed_job(database, "job")
    pool = WorkerPool(
        [_devices()[0]], BrokenBackend, {"job": _request("job")}, database=database,
        candidates_dir=tmp_path / "candidates", reports_dir=tmp_path / "reports",
    )
    try:
        with pytest.raises(ResourceFailed, match="invalid model component"):
            pool.submit("job").result(timeout=10)
    finally:
        pool.close()

    store = AssetStore.open(database)
    assert store.job_state("job").value == "RESOURCE_FAILED"
    error = store.get_job_error("job")
    store.close()
    assert error is not None
    assert "Traceback" in error["traceback"]
    assert Path(error["report_path"]).with_suffix(".html").is_file()


def test_precision_resolution_filters_quantizers_by_runtime_and_device_capability() -> None:
    assert resolve_precision(_devices()[0], CapabilitySet(torchao=True, bitsandbytes=True)) == [
        "fp16", "fp16_offload_attention_slicing_vae_tiling", "int8", "int4"
    ]
    assert resolve_precision(_devices()[1], CapabilitySet(torchao=True, bitsandbytes=True)) == [
        "fp16", "fp16_offload_attention_slicing_vae_tiling", "fp8", "int8", "int4"
    ]


def test_cli_device_override_accepts_numeric_cuda_indexes_without_changing_existing_cuda_names() -> None:
    assert _normalize_cuda_device("0") == "cuda:0"
    assert _normalize_cuda_device("cuda:1") == "cuda:1"
    assert _normalize_cuda_device("cpu") == "cpu"


def test_generate_cli_routes_selected_job_through_worker_pool_without_constructing_a_real_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import graph_remaster.cli as cli

    assert not hasattr(cli, "probe_devices")
    config = tmp_path / "pipeline.toml"
    config.write_text(
        """[project]\nname = 'black-gate'\n[paths]\ndata = 'data'\nwork = 'work'\n[render]\nscale = 6\nlogical_width = 320\nlogical_height = 200\n""",
        encoding="utf-8",
    )
    database = tmp_path / "work" / "graph.sqlite3"
    _seed_job(database, "job")
    selected: dict[str, object] = {}

    class FakePool:
        def __init__(self, devices: object, backend_factory: object, requests: object, **kwargs: object) -> None:
            selected.update({"devices": devices, "backend_factory": backend_factory, "requests": requests, **kwargs})

        def submit(self, job_id: str):
            selected["job_id"] = job_id
            from concurrent.futures import Future
            future = Future()
            future.set_result(None)
            return future

        def close(self) -> None:
            selected["closed"] = True

    def unexpected_parent_probe() -> None:
        raise AssertionError("the CLI parent must not probe CUDA devices")

    monkeypatch.setattr("graph_remaster.cli.probe_devices", unexpected_parent_probe, raising=False)
    monkeypatch.setattr("graph_remaster.cli.WorkerPool", FakePool)

    assert main(["generate", "--config", str(config), "--backend", "mock", "job"]) == 0
    assert selected["job_id"] == "job"
    assert selected["closed"] is True
    assert selected["devices"] is None
    assert selected["device_selectors"] == ("cuda:0", "cuda:1")
    assert set(selected["requests"]) == {"job"}


def test_generate_cli_records_centered_source_to_canvas_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "pipeline.toml"
    config.write_text(
        """[project]\nname = 'black-gate'\n[paths]\ndata = 'data'\nwork = 'work'\n[render]\nscale = 6\nlogical_width = 320\nlogical_height = 200\n""",
        encoding="utf-8",
    )
    database = tmp_path / "work" / "graph.sqlite3"
    _seed_job(database, "job")
    store = AssetStore.open(database)
    try:
        job = store.get_generation_job("job")
        store.create_generation_job(GenerationJob(
            job.frame,
            "QUEUED",
            job.profile,
            job.backend,
            {"seed": 7, "width": 128, "height": 128},
            "job",
        ))
    finally:
        store.close()

    class FakePool:
        def __init__(self, devices: object, backend_factory: object, requests: object, **kwargs: object) -> None:
            self.requests = requests

        def submit(self, job_id: str):
            from concurrent.futures import Future
            future = Future()
            future.set_result(None)
            return future

        def close(self) -> None:
            return None

    monkeypatch.setattr("graph_remaster.cli.WorkerPool", FakePool)

    assert main(["generate", "--config", str(config), "--backend", "mock", "job"]) == 0

    store = AssetStore.open(database)
    try:
        parameters = store.job_parameters("job")
    finally:
        store.close()
    assert parameters["source_to_canvas"] == {
        "crop": [28, 37, 72, 54],
    }


def test_generate_cli_rejects_canvas_smaller_than_canonical_target(tmp_path: Path) -> None:
    config = tmp_path / "pipeline.toml"
    config.write_text(
        """[project]\nname = 'black-gate'\n[paths]\ndata = 'data'\nwork = 'work'\n[render]\nscale = 6\nlogical_width = 320\nlogical_height = 200\n""",
        encoding="utf-8",
    )
    database = tmp_path / "work" / "graph.sqlite3"
    _seed_job(database, "job")
    store = AssetStore.open(database)
    try:
        job = store.get_generation_job("job")
        store.create_generation_job(GenerationJob(
            job.frame,
            "QUEUED",
            job.profile,
            job.backend,
            {"seed": 7, "width": 64, "height": 64},
            "job",
        ))
    finally:
        store.close()

    with pytest.raises(ValueError, match="at least the canonical HD target"):
        main(["generate", "--config", str(config), "--backend", "mock", "job"])
