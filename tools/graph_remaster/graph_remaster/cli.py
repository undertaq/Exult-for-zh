"""Command-line entry point; runtime-heavy backends are intentionally lazy."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import tomllib
from typing import Sequence

from .workers.scheduler import WorkerPool


COMMANDS = (
    "inventory",
    "extract",
    "prepare-controls",
    "generate",
    "validate",
    "review",
    "package",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graph-remaster",
        description="Resumable Ultima VII Graph Remaster pipeline",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    for command in COMMANDS:
        subparser = subparsers.add_parser(command, help=f"run the {command} stage")
        subparser.add_argument("--config", type=Path, default=Path("pipeline.toml"))
        subparser.add_argument("--run-id")
        subparser.add_argument("selector", nargs="?")
        if command == "generate":
            subparser.add_argument("--backend", default=None)
            subparser.add_argument(
                "--real-model-smoke",
                action="store_true",
                help="run one fixed-seed SDXL ControlNet request; downloads/loads optional model weights",
            )
            subparser.add_argument(
                "--device",
                default=None,
                help="CUDA device override: 0/1 or cuda:0/cuda:1 (defaults to the first configured GPU)",
            )
        if command in {"inventory", "extract"}:
            subparser.add_argument("--ipack", type=Path, required=True)
            subparser.add_argument("--archive", type=Path)
            subparser.add_argument("--palette", type=Path)
            subparser.add_argument("--database", type=Path)
            subparser.set_defaults(handler=_run_source_stage)
        elif command == "prepare-controls":
            subparser.add_argument("--database", type=Path)
            subparser.set_defaults(handler=_run_controls_stage)
        elif command == "generate":
            subparser.set_defaults(handler=_run_generate_stage)
        elif command == "validate":
            subparser.add_argument("--database", type=Path)
            subparser.set_defaults(handler=_run_validate_stage)
        elif command == "review":
            subparser.add_argument("--database", type=Path)
            subparser.add_argument("--serve", action="store_true")
            subparser.add_argument("--decision")
            subparser.add_argument("--reason", default="")
            subparser.add_argument("--reviewer", default="local")
            subparser.set_defaults(handler=_run_review_stage)
        else:
            subparser.set_defaults(handler=_not_implemented)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return args.handler(args)


def _not_implemented(args: argparse.Namespace) -> int:
    raise NotImplementedError(f"pipeline stage '{args.command}' is not implemented yet")


def _run_generate_stage(args: argparse.Namespace) -> int:
    """Run the explicit real-model smoke test without changing default generation behavior."""

    if not args.real_model_smoke:
        return _run_worker_pool_generate(args)

    from PIL import Image

    from .backends.base import BackendUnavailable, InferenceRequest
    from .backends.sdxl_controlnet import SdxlControlNetBackend
    from .config import canonical_asset_profile, load_config
    from .controls.prepare import ControlBundle, MaskRecord
    from .models import FrameKey, FrameRecord, GenerationJob
    from .reporting import write_stage_html_report

    run_id = args.run_id or "default"
    backend = None
    report_path = _fallback_real_model_smoke_report_path(args.config, run_id)
    try:
        config = load_config(args.config)
        output_dir = config.paths.candidates / run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "real-model-smoke.json"
        config.model.validate_for_real_model()
        device = _normalize_cuda_device(args.device or config.gpu.devices[0])
        source = Image.new("RGBA", (64, 64), (46, 75, 102, 255))
        frame = FrameRecord(FrameKey("0" * 64, 0, 0, 0), 64, 64)
        mask = Image.new("L", source.size, 255)
        profile = canonical_asset_profile("flat_tile")
        request = InferenceRequest(
            job=GenerationJob(
                frame=frame.key,
                state="QUEUED",
                profile=profile.name,
                backend="sdxl_controlnet",
                parameters={
                    "seed": 8675309,
                    "width": 64,
                    "height": 64,
                    "num_inference_steps": 1,
                    "prompt": "a high-fidelity Ultima VII flat game tile",
                },
                job_id="real-model-smoke",
            ),
            source=source,
            controls=ControlBundle(
                frame=frame,
                profile=profile,
                masks=MaskRecord(frame.key, mask, mask.copy(), mask.copy()),
                controls={"canny": Image.new("L", source.size, 128)},
            ),
            reference=None,
        )
        backend = SdxlControlNetBackend(config.model)
        backend.load(device, config.gpu.precision)
        torch = backend.torch_runtime
        torch.cuda.reset_peak_memory_stats(device)
        candidate = backend.generate(request)
        image_path = output_dir / "real-model-smoke.png"
        candidate.image.save(image_path)
        payload = {
            "device": device,
            "image": str(image_path),
            "model_revisions": config.model.resolved_revisions(("canny",)),
            "peak_vram_bytes": int(torch.cuda.max_memory_allocated(device)),
            "precision": candidate.metadata.get("precision", {}),
            "seed": candidate.seed,
            "status": "ok",
        }
        _write_real_model_smoke_reports(report_path, "Real model smoke completed", payload, write_stage_html_report)
        return 0
    except (BackendUnavailable, OSError, ValueError) as exc:
        payload: dict[str, object] = {"error": str(exc), "status": "failed"}
        if backend is not None:
            provenance = getattr(backend, "precision_provenance", None)
            if isinstance(provenance, dict):
                payload["precision"] = provenance
        _write_real_model_smoke_reports(
            report_path,
            "Real model smoke failed",
            payload,
            write_stage_html_report,
        )
        return 2
    finally:
        if backend is not None:
            backend.unload()


def _write_real_model_smoke_reports(
    report_path: Path,
    title: str,
    payload: dict[str, object],
    write_html: Callable[[Path, str, Mapping[str, object]], None],
) -> None:
    """Persist the smoke result in machine-readable JSON and offline HTML."""

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    write_html(report_path.with_suffix(".html"), title, payload)


def _fallback_real_model_smoke_report_path(config_path: Path, run_id: str) -> Path:
    """Find a local report destination even when typed configuration cannot load."""

    config_path = Path(config_path)
    default = config_path.parent / "candidates" / run_id / "real-model-smoke.json"
    try:
        with config_path.open("rb") as stream:
            mapping = tomllib.load(stream)
        paths = mapping.get("paths", {})
        if not isinstance(paths, dict):
            return default
        work = paths.get("work")
        candidates = paths.get("candidates")
        raw = candidates if isinstance(candidates, str) and candidates else None
        if raw is None and isinstance(work, str) and work:
            raw = str(Path(work) / "candidates")
        if raw is None:
            return default
        root = Path(raw)
        if not root.is_absolute():
            root = config_path.parent / root
        return root / run_id / "real-model-smoke.json"
    except (OSError, tomllib.TOMLDecodeError):
        return default


def _normalize_cuda_device(value: str) -> str:
    """Accept the scheduler's concise numeric overrides without changing CUDA names."""

    return f"cuda:{value}" if value.isdecimal() else value


@dataclass(frozen=True)
class _BackendFactory:
    """Picklable, lazy backend constructor passed across the spawn boundary."""

    backend_name: str
    model_config: object

    def __call__(self):
        if self.backend_name == "mock":
            from .backends.mock import MockBackend
            return MockBackend()
        if self.backend_name == "sdxl_controlnet":
            from .backends.sdxl_controlnet import SdxlControlNetBackend
            return SdxlControlNetBackend(self.model_config)
        raise ValueError(f"unsupported generation backend {self.backend_name!r}")


def _run_worker_pool_generate(args: argparse.Namespace) -> int:
    """Dispatch one persisted queued job through the process-isolated worker pool."""

    from PIL import Image

    from .backends.base import InferenceRequest
    from .config import canonical_asset_profile, load_config
    from .controls.prepare import prepare_controls
    from .db import AssetStore
    from .models import JobState

    if not args.selector:
        raise ValueError("generate requires a queued job id selector unless --real-model-smoke is used")
    config = load_config(args.config)
    database = config.paths.work / "graph.sqlite3"
    store = AssetStore.open(database)
    try:
        store.migrate()
        job = store.get_generation_job(args.selector)
        if job.state == JobState.CONTROLS_READY:
            store.transition_job(job.job_id or args.selector, JobState.CONTROLS_READY, JobState.QUEUED)
            job = store.get_generation_job(args.selector)
        if job.state != JobState.QUEUED:
            raise ValueError(f"generation job {args.selector!r} must be QUEUED, not {job.state}")
        frame = store.get_frame(job.frame)
    finally:
        store.close()

    configured_profile = next((item for item in config.asset_profiles if item.name == job.profile), None)
    profile = configured_profile or canonical_asset_profile(job.profile)
    with Image.open(str(frame.metadata["rgba_preview_path"])) as source_image:
        source = source_image.convert("RGBA")
    request = InferenceRequest(job, source, prepare_controls(frame, profile))
    backend_name = args.backend or job.backend or config.model.backend
    pool = WorkerPool(
        None,
        _BackendFactory(backend_name, config.model),
        {args.selector: request},
        candidates_dir=config.paths.candidates / (args.run_id or "default"),
        database=database,
        reports_dir=config.paths.reports / (args.run_id or "default"),
        device=args.device,
        device_selectors=config.gpu.devices,
        workers=config.gpu.workers,
    )
    try:
        pool.submit(args.selector).result()
    finally:
        pool.close()
    return 0


def _run_validate_stage(args: argparse.Namespace) -> int:
    """Validate one generated candidate and retain review-gated approval."""

    from .config import load_config
    from .db import AssetStore
    from .reporting import write_stage_html_report
    from .validation.runner import run_validation

    if not args.selector:
        raise ValueError("validate requires a candidate id selector")
    config = load_config(args.config)
    run_id = args.run_id or "default"
    report_path = config.paths.reports / run_id / "validate-error.json"
    store = AssetStore.open(args.database or config.paths.work / "graph.sqlite3")
    try:
        store.migrate()
        report = run_validation(args.selector, store)
    except (OSError, ValueError, KeyError) as exc:
        payload = {"stage": "validate", "candidate_id": args.selector, "error": str(exc)}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        write_stage_html_report(report_path.with_suffix(".html"), "Validation failed", payload)
        return 2
    finally:
        store.close()
    write_stage_html_report(
        config.paths.reports / run_id / "validate.html", "Validation report", report.as_dict()
    )
    return 0 if report.passed else 2


def _run_review_stage(args: argparse.Namespace) -> int:
    """Serve offline reports or record one local, review-gated decision."""

    from .config import load_config
    from .db import AssetStore
    from .models import ReviewDecision
    from .reports.server import ReviewServer
    from .reports.writer import STAGES, write_run_index, write_stage_report

    if not args.selector and not args.serve:
        raise ValueError("review requires a candidate selector or --serve")
    config = load_config(args.config)
    run_id = args.run_id or "default"
    database = args.database or config.paths.work / "graph.sqlite3"
    report_dir = config.paths.reports / run_id
    server = ReviewServer(database, report_dir)
    if args.serve:
        write_run_index(run_id, report_dir)
        server.serve_forever()
        return 0
    if not args.decision:
        store = AssetStore.open(database)
        try:
            store.migrate()
            write_run_index(run_id, report_dir)
            for stage, _ in STAGES:
                write_stage_report(stage, run_id, store, report_dir)
        finally:
            store.close()
        return 0
    server.record_review(
        args.selector,
        ReviewDecision(args.selector, args.decision, args.reviewer, args.reason),
    )
    return 0


def _run_source_stage(args: argparse.Namespace) -> int:
    """Run an inventory/extraction stage without importing generation backends."""

    from .config import load_config
    from .db import AssetStore
    from .errors import SourceToolError
    from .hashing import sha256_file
    from .models import SourceArchive
    from .reporting import write_stage_html_report
    from .source_io.ipack_adapter import IpackAdapter

    config = load_config(args.config)
    run_id = args.run_id or "default"
    stage_root = config.paths.inventory if args.command == "inventory" else config.paths.work / "extract"
    stage_dir = stage_root / run_id
    report_path = config.paths.reports / run_id / f"{args.command}-error.json"
    stage_dir.mkdir(parents=True, exist_ok=True)
    archive = args.archive or (Path(args.selector) if args.selector else None)
    try:
        if archive is None:
            raise SourceToolError("source archive is required; pass --archive or selector")
        store = AssetStore.open(args.database or config.paths.work / "graph.sqlite3")
        try:
            store.migrate()
            archive_sha256 = sha256_file(archive)
            shapes = store.list_shapes(archive_sha256) if store.get_source_archive(archive_sha256) else []
            if not shapes:
                adapter = IpackAdapter(args.ipack)
                shapes = adapter.inventory(archive, stage_dir, args.palette)
                store.upsert_source_archive(
                    SourceArchive(archive_sha256, str(archive.resolve()), archive.stat().st_size)
                )
                for shape in shapes:
                    store.upsert_shape(shape)
            for shape in shapes:
                if args.command == "extract":
                    existing = {frame.key.frame_id for frame in store.list_frames(shape)}
                    expected = set(range(shape.frame_count))
                    if not expected.issubset(existing):
                        adapter = IpackAdapter(args.ipack)
                        for frame in adapter.extract(shape, stage_dir / f"shape-{shape.shape_id:04d}"):
                            if frame.key.frame_id not in existing:
                                store.upsert_frame(frame)
        finally:
            store.close()
        (stage_dir / "stage.json").write_text(
            json.dumps({"stage": args.command, "run_id": run_id, "archive_sha256": shapes[0].archive_sha256, "shape_count": len(shapes)}, sort_keys=True),
            encoding="utf-8",
        )
        write_stage_html_report(
            config.paths.reports / run_id / f"{args.command}.html",
            f"{args.command.title()} report",
            {"stage": args.command, "run_id": run_id, "archive_sha256": shapes[0].archive_sha256, "shape_count": len(shapes)},
        )
        return 0
    except (OSError, SourceToolError) as exc:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"stage": args.command, "run_id": run_id, "error": str(exc)}
        if isinstance(exc, SourceToolError):
            payload.update({"command": list(exc.command), "returncode": exc.returncode, "stdout": exc.stdout, "stderr": exc.stderr})
        report_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        write_stage_html_report(report_path.with_suffix(".html"), f"{args.command.title()} failed", payload)
        return 2


def _run_controls_stage(args: argparse.Namespace) -> int:
    """Prepare deterministic source-authoritative controls without generation backends."""

    from .config import load_config
    from .controls.prepare import CanvasSpec, build_tile_atlas, persist_controls, persist_tile_atlas, prepare_controls
    from .controls.profiles import AssetType, get_profile
    from .db import AssetStore
    from .reporting import write_stage_html_report

    run_id = args.run_id or "default"
    report_path = _fallback_controls_report_path(args.config, run_id)
    html_report_path = report_path.with_name("prepare-controls.html")
    try:
        config = load_config(args.config)
        report_path = config.paths.reports / run_id / "prepare-controls-error.json"
        html_report_path = report_path.with_name("prepare-controls.html")
        stage_dir = config.paths.controls / run_id
        stage_dir.mkdir(parents=True, exist_ok=True)
        store = AssetStore.open(args.database or config.paths.work / "graph.sqlite3")
        try:
            store.migrate()
            frames = store.list_all_frames(args.selector)
            flat_frames: dict[object, list[object]] = {}
            for frame in frames:
                asset_type = AssetType(frame.metadata.get("asset_type", AssetType.FLAT_TILE.value))
                configured = next((item for item in config.asset_profiles if item.name == asset_type.value), None)
                profile = configured or get_profile(asset_type)
                bundle = prepare_controls(frame, profile)
                persist_controls(store, stage_dir, bundle)
                if asset_type is AssetType.FLAT_TILE:
                    flat_frames.setdefault(profile, []).append(frame)
            atlas_count = 0
            for profile, grouped_frames in flat_frames.items():
                canvas = CanvasSpec(profile.atlas_columns, profile.atlas_rows, profile.tile_width, profile.tile_height)
                capacity = canvas.columns * canvas.rows
                for start in range(0, len(grouped_frames), capacity):
                    members = grouped_frames[start:start + capacity]
                    persist_tile_atlas(store, stage_dir, members, profile, build_tile_atlas(members, config.render.scale, canvas))
                    atlas_count += 1
        finally:
            store.close()
        payload = {"stage": args.command, "run_id": run_id, "frame_count": len(frames), "atlas_count": atlas_count}
        (stage_dir / "stage.json").write_text(
            json.dumps(payload, sort_keys=True),
            encoding="utf-8",
        )
        write_stage_html_report(html_report_path, "Controls prepared", payload)
        return 0
    except (OSError, ValueError) as exc:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"stage": args.command, "run_id": run_id, "error": str(exc)}
        report_path.write_text(
            json.dumps(payload, sort_keys=True),
            encoding="utf-8",
        )
        write_stage_html_report(html_report_path, "Preparation failed", payload)
        return 2


def _fallback_controls_report_path(config_path: Path, run_id: str) -> Path:
    """Find the conventional report directory when full config validation fails."""

    base = Path(config_path).parent.resolve()
    reports = base / "reports"
    try:
        with Path(config_path).open("rb") as stream:
            paths = tomllib.load(stream).get("paths", {})
        if isinstance(paths, dict):
            configured_reports = paths.get("reports")
            configured_work = paths.get("work")
            candidate = configured_reports or (
                str(Path(configured_work) / "reports") if isinstance(configured_work, str) else None
            )
            if isinstance(candidate, str) and candidate:
                path = Path(candidate)
                reports = path if path.is_absolute() else base / path
    except (OSError, tomllib.TOMLDecodeError):
        pass
    return reports / run_id / "prepare-controls-error.json"
