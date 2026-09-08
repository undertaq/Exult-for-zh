"""Process-safe scheduler coverage using only Pillow-backed fake backends."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from graph_remaster.backends.base import GeneratedImage, InferenceRequest
from graph_remaster.cli import _normalize_cuda_device
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
    store.upsert_source_archive(SourceArchive(key.archive_sha256, "source.ipf"))
    store.upsert_shape(ShapeRecord(key.archive_sha256, key.archive_index, key.shape_id, 12, 9))
    store.upsert_frame(FrameRecord(key, 12, 9))
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
