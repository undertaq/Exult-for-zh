"""Spawn-context GPU workers with serial per-device job execution."""

from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import multiprocessing as mp
from pathlib import Path
from queue import Empty
from threading import Lock, Thread
import traceback
from typing import Callable, Mapping

from ..backends.base import GeneratedImage, InferenceBackend, InferenceRequest, PrecisionAttempt, precision_metadata
from ..db import AssetStore
from ..models import Candidate, JobState
from .devices import CudaDeviceInfo, probe_devices
from .precision import CapabilitySet, precision_components, resolve_precision


class WorkerBusyError(RuntimeError):
    """Raised when every physical-GPU worker already owns one active job."""


class ResourceFailed(RuntimeError):
    """Raised from a future after an exhausted CUDA-resource retry."""


@dataclass(frozen=True)
class _Task:
    job_id: str
    request: InferenceRequest
    profiles: tuple[str, ...]
    output_path: str


@dataclass(frozen=True)
class _Outcome:
    job_id: str
    candidate: Candidate | None = None
    error: str | None = None
    traceback_text: str = ""
    resource_failure: bool = False
    metadata: dict[str, object] | None = None


@dataclass
class _Slot:
    device: CudaDeviceInfo
    queue: object
    process: object
    busy_job_id: str | None = None


def is_cuda_oom(error: BaseException) -> bool:
    """Recognize Torch and driver OOM errors without importing Torch in the parent."""

    current: BaseException | None = error
    while current is not None:
        name = type(current).__name__.lower()
        message = str(current).lower()
        if "outofmemory" in name or "cuda out of memory" in message or "cuda error: out of memory" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


def _empty_cuda_cache() -> None:
    """Best-effort cache clearing inside the worker process only."""

    try:
        from importlib import import_module
        torch = import_module("torch")
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except (ImportError, AttributeError, RuntimeError):
        pass


def _worker_main(device: CudaDeviceInfo, tasks: object, outcomes: object, backend_factory: Callable[[], InferenceBackend]) -> None:
    """Process entry point.  It owns its backend and never receives CUDA objects."""

    # CUDA discovery happens in the child, so neither a model nor a CUDA context
    # is initialized in the scheduling parent.  Keep supplied test/CPU facts if
    # the optional runtime is unavailable there.
    discovered = {info.index: info for info in probe_devices()}
    device = discovered.get(device.index, replace(
        device, process_started_at=datetime.now(timezone.utc).isoformat()
    ))
    backend: InferenceBackend | None = None
    current_profile: str | None = None
    try:
        while True:
            task = tasks.get()
            if task is None:
                return
            assert isinstance(task, _Task)
            attempts: list[PrecisionAttempt] = []
            outcome: _Outcome | None = None
            for retry, profile in enumerate(task.profiles[:2]):
                try:
                    if backend is None or current_profile != profile:
                        if backend is not None:
                            backend.unload()
                        backend = backend_factory()
                        backend.load(device.device, profile)
                        current_profile = profile
                    generated = backend.generate(task.request)
                    generated.image.save(task.output_path)
                    attempts.append(PrecisionAttempt(profile, "applied", "generated successfully"))
                    metadata = dict(generated.metadata)
                    metadata["precision"] = {
                        **precision_metadata(task.profiles[0], attempts, profile),
                        "components": precision_components(profile),
                    }
                    metadata["worker"] = {"device": device.as_metadata(), "retry": retry}
                    candidate = Candidate(
                        task.job_id,
                        task.output_path,
                        sha256(Path(task.output_path).read_bytes()).hexdigest(),
                        metadata,
                    )
                    outcome = _Outcome(task.job_id, candidate, metadata=metadata)
                    break
                except BaseException as exc:  # Worker errors must cross the process boundary as data.
                    oom = is_cuda_oom(exc)
                    attempts.append(PrecisionAttempt(profile, "failed", str(exc)))
                    if oom and retry == 0 and len(task.profiles) > 1:
                        _empty_cuda_cache()
                        if backend is not None:
                            try:
                                backend.unload()
                            finally:
                                backend = None
                                current_profile = None
                        continue
                    failure_metadata = {
                        "precision": {
                            **precision_metadata(task.profiles[0], attempts, None),
                            "components": precision_components(profile),
                        },
                        "worker": {"device": device.as_metadata(), "retry": retry},
                    }
                    outcome = _Outcome(
                        task.job_id,
                        error=str(exc),
                        traceback_text=traceback.format_exc(),
                        resource_failure=oom,
                        metadata=failure_metadata,
                    )
                    break
            outcomes.put(outcome or _Outcome(task.job_id, error="worker exhausted precision profiles", resource_failure=True))
    finally:
        if backend is not None:
            backend.unload()


class WorkerPool:
    """A bounded scheduler: one spawned, serial worker per distinct physical GPU."""

    def __init__(
        self,
        devices: list[CudaDeviceInfo],
        backend_factory: Callable[[], InferenceBackend],
        requests: Mapping[str, InferenceRequest],
        *,
        candidates_dir: Path,
        database: Path | None = None,
        reports_dir: Path | None = None,
        device: int | str | None = None,
        capabilities: CapabilitySet | None = None,
    ) -> None:
        if not devices:
            raise ValueError("WorkerPool requires at least one discovered CUDA device")
        if len({info.index for info in devices}) != len(devices):
            raise ValueError("WorkerPool requires one worker per distinct physical GPU index")
        self._context = mp.get_context("spawn")
        self.start_method = self._context.get_start_method()
        self._requests = dict(requests)
        self._database = None if database is None else Path(database)
        self._reports_dir = None if reports_dir is None else Path(reports_dir)
        self._candidates_dir = Path(candidates_dir)
        self._candidates_dir.mkdir(parents=True, exist_ok=True)
        self._capabilities = capabilities or CapabilitySet.probe()
        self._device_override = _device_index(device)
        eligible = [info for info in devices if self._device_override is None or info.index == self._device_override]
        if not eligible:
            raise ValueError(f"requested CUDA device {device!r} was not discovered")
        self._outcomes = self._context.Queue()
        self._slots = [self._start_slot(info, backend_factory) for info in sorted(eligible, key=lambda item: item.index)]
        self._futures: dict[str, Future[Candidate]] = {}
        self._lock = Lock()
        self._closed = False
        self._monitor = Thread(target=self._monitor_outcomes, name="graph-remaster-worker-monitor", daemon=True)
        self._monitor.start()

    def _start_slot(self, device: CudaDeviceInfo, backend_factory: Callable[[], InferenceBackend]) -> _Slot:
        tasks = self._context.Queue()
        process = self._context.Process(target=_worker_main, args=(device, tasks, self._outcomes, backend_factory), daemon=True)
        process.start()
        return _Slot(device, tasks, process)

    def submit(self, job_id: str) -> Future[Candidate]:
        """Assign one queued job to a deterministic idle GPU or reject immediately."""

        with self._lock:
            if self._closed:
                raise RuntimeError("WorkerPool is closed")
            if job_id in self._futures:
                raise ValueError(f"job {job_id!r} is already submitted")
            request = self._requests.get(job_id)
            if request is None:
                raise KeyError(f"no inference request registered for job {job_id!r}")
            slot = self._select_slot(request)
            if slot is None:
                raise WorkerBusyError("all GPU workers already have one active serial job")
            profiles = tuple(resolve_precision(slot.device, self._capabilities))
            if not profiles:
                raise ResourceFailed(f"no usable precision profile for {slot.device.device}")
            output = self._candidates_dir / f"{job_id}.png"
            future: Future[Candidate] = Future()
            self._futures[job_id] = future
            slot.busy_job_id = job_id
            slot.queue.put(_Task(job_id, request, profiles, str(output)))
            return future

    def _select_slot(self, request: InferenceRequest) -> _Slot | None:
        requested = _device_index(request.job.parameters.get("device"))
        available = [slot for slot in self._slots if slot.busy_job_id is None]
        if requested is not None:
            return next((slot for slot in available if slot.device.index == requested), None)
        return min(available, key=lambda slot: (-slot.device.free_vram_bytes, slot.device.index), default=None)

    def _monitor_outcomes(self) -> None:
        while not self._closed or any(slot.busy_job_id is not None for slot in self._slots):
            try:
                outcome = self._outcomes.get(timeout=0.1)
            except Empty:
                self._record_dead_workers()
                continue
            self._finish(outcome)

    def _record_dead_workers(self) -> None:
        for slot in self._slots:
            if slot.busy_job_id is not None and not slot.process.is_alive():
                job_id = slot.busy_job_id
                slot.busy_job_id = None
                self._fail(
                    job_id,
                    f"worker for {slot.device.device} exited unexpectedly",
                    "",
                    True,
                    {"worker": {"device": slot.device.as_metadata()}},
                )

    def _finish(self, outcome: _Outcome) -> None:
        with self._lock:
            slot = next((item for item in self._slots if item.busy_job_id == outcome.job_id), None)
            if slot is not None:
                slot.busy_job_id = None
            future = self._futures.get(outcome.job_id)
        if future is None or future.done():
            return
        if outcome.candidate is not None:
            self._record_success(outcome.job_id, outcome.candidate)
            future.set_result(outcome.candidate)
            return
        self._fail(
            outcome.job_id,
            outcome.error or "worker failed",
            outcome.traceback_text,
            outcome.resource_failure,
            outcome.metadata,
        )

    def _record_success(self, job_id: str, candidate: Candidate) -> None:
        if self._database is None:
            return
        store = AssetStore.open(self._database)
        try:
            store.transition_job(job_id, JobState.QUEUED, JobState.GENERATED)
            store.add_candidate(candidate)
            store.record_job_metadata(job_id, {
                "precision": candidate.metadata.get("precision", {}),
                "worker": candidate.metadata.get("worker", {}),
            })
        finally:
            store.close()

    def _fail(
        self,
        job_id: str,
        error: str,
        traceback_text: str,
        resource_failure: bool,
        metadata: dict[str, object] | None = None,
    ) -> None:
        report_path = self._write_failure_report(job_id, error, traceback_text)
        if self._database is not None:
            store = AssetStore.open(self._database)
            try:
                store.transition_job(job_id, JobState.QUEUED, JobState.GENERATED)
                if resource_failure:
                    store.transition_job(job_id, JobState.GENERATED, JobState.RESOURCE_FAILED)
                if metadata is not None:
                    store.record_job_metadata(job_id, metadata)
                store.record_job_error(job_id, error, traceback_text, str(report_path))
            finally:
                store.close()
        future = self._futures.get(job_id)
        if future is not None and not future.done():
            exception: BaseException = ResourceFailed(error) if resource_failure else RuntimeError(error)
            future.set_exception(exception)

    def _write_failure_report(self, job_id: str, error: str, traceback_text: str) -> Path:
        directory = self._reports_dir or self._candidates_dir
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{job_id}.resource-failure.json"
        path.write_text(json.dumps({"job_id": job_id, "error": error, "traceback": traceback_text}, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def close(self) -> None:
        """Drain and terminate only this pool's spawned worker processes."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            for slot in self._slots:
                if slot.process.is_alive():
                    slot.queue.put(None)
        for slot in self._slots:
            slot.process.join(timeout=5)
            if slot.process.is_alive():
                slot.process.terminate()
                slot.process.join(timeout=5)
        self._monitor.join(timeout=5)


def _device_index(value: object) -> int | None:
    if value is None or value == "":
        return None
    text = str(value)
    if text.startswith("cuda:"):
        text = text.removeprefix("cuda:")
    try:
        index = int(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"device override must be an integer CUDA index, got {value!r}") from exc
    if index < 0:
        raise ValueError("device override must be non-negative")
    return index
