from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_remaster.db import AssetStore
from graph_remaster.models import Candidate, FrameKey, FrameRecord, GenerationJob, JobState, SourceArchive, ShapeRecord
from graph_remaster.packaging.manifest import build_package
from graph_remaster.packaging.package import run_fixture_pipeline
from graph_remaster.reports.writer import STAGES


def test_fixture_pipeline_covers_three_asset_classes_and_packages_approved_masters(tmp_path: Path) -> None:
    summary = run_fixture_pipeline(tmp_path)

    assert len(summary.candidate_ids) == 4
    manifest = json.loads(summary.manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["entries"]) == 4
    assert all(Path(entry["artifact_path"]).is_file() for entry in manifest["entries"])
    report_dir = tmp_path / "reports" / summary.run_id
    assert (report_dir / "index.html").is_file()
    assert all((report_dir / filename).is_file() for _, filename in STAGES)


def test_package_refuses_unapproved_candidate(tmp_path: Path) -> None:
    store = AssetStore.open(tmp_path / "graph.sqlite3")
    store.migrate()
    key = FrameKey("a" * 64, 0, 1, 0)
    source = tmp_path / "source.png"
    from PIL import Image
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(source)
    store.upsert_source_archive(SourceArchive(key.archive_sha256, "source.vga"))
    store.upsert_shape(ShapeRecord(key.archive_sha256, 0, 1, 8, 8, 1))
    store.upsert_frame(FrameRecord(key, 8, 8, metadata={"rgba_preview_path": str(source), "scale": 6, "asset_type": "flat_tile"}))
    job_id = store.create_generation_job(GenerationJob(key, JobState.VALIDATED, "flat_tile", "mock", {"run_id": "run"}, "job"))
    artifact = tmp_path / "candidate.png"
    Image.new("RGBA", (48, 48), (1, 2, 3, 255)).save(artifact)
    store.add_candidate(Candidate(job_id, str(artifact), metadata={"run_id": "run"}, candidate_id="candidate"))
    with pytest.raises(ValueError, match="not approved"):
        build_package("run", store, tmp_path / "package")
    store.close()
