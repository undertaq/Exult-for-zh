#!/usr/bin/env python3
"""Strictly audit reviewed U6 dynamic voice outputs before packaging."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from build_u6_dynamic_voice_manifest import validate_dynamic_voice_manifest
import generate_breeze_u6 as breeze
from generate_breeze_u6 import build_dynamic_breeze_jobs


UNRESOLVED = re.compile(
    r"<(?:VAR\d*|PLAYER_NAME|HONORIFIC|PRONOUN|GENDER_FLAG)[^>]*>|@[A-Za-z_-]+@",
    re.IGNORECASE,
)
RUNTIME_VALUE_FIELDS = {
    "runtime_value", "actual_value", "resolved_value", "runtime_text", "spoken_value"
}


@dataclass
class AuditReport:
    expected_jobs: int = 0
    valid_audio: int = 0
    approved_reviews: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {error.msg}") from error
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: each manifest row must be an object")
        rows.append(value)
    return rows


def _reject_runtime_values(value: Any, location: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in RUNTIME_VALUE_FIELDS:
                errors.append(f"{location}: runtime-value field {key!r} is not packageable")
            _reject_runtime_values(child, f"{location}.{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_runtime_values(child, f"{location}[{index}]", errors)


def _check_manifest(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    try:
        records = _read_jsonl(path)
        if not records:
            raise ValueError(f"{path}: dynamic source manifest is empty")
        validate_dynamic_voice_manifest(records)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError,
            AttributeError) as error:
        errors.append(f"source manifest: {error}")
        return []
    for index, record in enumerate(records):
        _reject_runtime_values(record, f"manifest row {index}", errors)
        for part_index, part in enumerate(record.get("source_parts", [])):
            if (isinstance(part, dict) and part.get("kind") == "dynamic"
                    and "text" in part):
                errors.append(
                    f"manifest row {index} source part {part_index}: dynamic parts must not "
                    "contain runtime text")
    return records


def _load_json(path: Path, label: str, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        errors.append(f"{label}: could not read {path}: {error}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label}: {path} must contain a JSON object")
        return {}
    _reject_runtime_values(value, label, errors)
    return value


def _probe_audio(path: Path):
    if breeze.sf is None:
        raise RuntimeError("Python soundfile is required to validate generated Ogg clips")
    decoded_frames = 0
    # `info()` only inspects stream metadata; decode in bounded blocks as well
    # so a valid header with a truncated/corrupt Ogg body cannot pass audit.
    with breeze.sf.SoundFile(str(path)) as stream:
        while True:
            block = stream.read(8192, dtype="float32", always_2d=True)
            frames = block.shape[0]
            if frames == 0:
                break
            decoded_frames += frames
    info = breeze.sf.info(str(path))
    if decoded_frames == 0:
        raise RuntimeError("audio stream decodes to zero frames")
    if info.frames > 0 and decoded_frames != info.frames:
        raise RuntimeError(
            f"decoded {decoded_frames} frames but Ogg metadata declares {info.frames}")
    return info


def _same(actual: Any, expected: Any) -> bool:
    return actual == expected


def _check_sidecar(job, expected_sample_rate: int, errors: list[str]) -> bool:
    audio_path = Path(job.output)
    label = f"{job.lang}/{audio_path.name}"
    if not audio_path.is_file():
        errors.append(f"{label}: audio is missing")
        return False

    sidecar_path = audio_path.with_suffix(".json")
    metadata = _load_json(sidecar_path, f"{label} sidecar", errors)
    valid = bool(metadata)
    try:
        info = _probe_audio(audio_path)
    except (OSError, RuntimeError, ValueError) as error:
        errors.append(f"{label}: Ogg metadata validation failed: {error}")
        return False
    if (info.format != "OGG" or info.subtype != "VORBIS"
            or info.channels != 1 or info.frames <= 100):
        errors.append(
            f"{label}: expected a nonempty mono Ogg clip; got "
            f"format={info.format}, subtype={info.subtype}, "
            f"channels={info.channels}, frames={info.frames}")
        valid = False
    if info.samplerate != expected_sample_rate:
        errors.append(
            f"{label}: sample rate is {info.samplerate}, expected {expected_sample_rate}")
        valid = False
    if metadata.get("status") != "generated":
        errors.append(f"{label}: sidecar status is not generated")
        valid = False
    try:
        actual_sha256 = hashlib.sha256(audio_path.read_bytes()).hexdigest()
    except OSError as error:
        errors.append(f"{label}: could not hash audio: {error}")
        return False
    if metadata.get("sha256") != actual_sha256:
        errors.append(f"{label}: sidecar SHA-256 does not match audio bytes")
        valid = False

    exact_fields = {
        "func_id": job.func_id,
        "offset_key": job.offset_key,
        "segment": job.segment,
        "npc": job.npc,
        "dynamic_template_key": job.dynamic_template_key,
        "role_span_index": job.role_span_index,
        "role_span_identity": job.role_span_identity,
        "lang": job.lang,
        "player_gender": job.player_gender,
        "active_gender": job.active_gender,
        "target_npc": job.target_npc,
        "text": job.text,
        "source_template_en": job.source_template_en,
        "source_template_zh": job.source_template_zh,
        "canonical_en": job.canonical_en,
        "canonical_zh": job.canonical_zh,
        "dynamic_slots": list(job.dynamic_slots),
        "source_parts": list(job.source_parts),
    }
    for name, expected in exact_fields.items():
        if not _same(metadata.get(name), expected):
            errors.append(f"{label}: sidecar {name} differs from the reviewed job")
            valid = False
    if metadata.get("sample_rate") != info.samplerate:
        errors.append(f"{label}: sidecar sample_rate differs from Ogg metadata")
        valid = False
    signature = breeze.dynamic_job_signature(job)
    if metadata.get("dynamic_job_signature") != signature:
        errors.append(f"{label}: dynamic job signature is stale or missing")
        valid = False

    expected_parts = []
    narrator_reference_id = breeze.narrator_reference_id(job.active_gender)
    same_sex_narrator = True
    for part in job.parts:
        expected_parts.append({
            "role": part.role,
            "text": part.text,
            "reference_id": part.reference.reference_id,
            "reference_gender": part.reference.gender,
        })
        if part.role == "narrator" and (
                part.reference.reference_id != narrator_reference_id
                or part.reference.gender != job.active_gender):
            same_sex_narrator = False
    actual_parts = metadata.get("parts")
    if not isinstance(actual_parts, list) or len(actual_parts) != len(expected_parts):
        errors.append(f"{label}: sidecar voice-part routing is missing or incomplete")
        valid = False
    else:
        for index, expected in enumerate(expected_parts):
            actual = actual_parts[index]
            if not isinstance(actual, dict) or any(
                    actual.get(name) != value for name, value in expected.items()):
                errors.append(f"{label}: sidecar voice-part {index} route differs from job")
                valid = False
    if not same_sex_narrator or metadata.get("same_sex_narrator") is not True:
        errors.append(f"{label}: narrator reference gender does not match active speaker")
        valid = False

    for field_name in ("text", "canonical_en", "canonical_zh"):
        value = metadata.get(field_name)
        if isinstance(value, str) and UNRESOLVED.search(value):
            errors.append(f"{label}: sidecar {field_name} contains an unresolved placeholder")
            valid = False
    return valid


def _check_review_rows(jobs: list, review_data: dict[str, Any],
                       review_state: dict[str, Any], review_data_path: Path,
                       errors: list[str]) -> int:
    if review_data.get("dynamic_only") is not True:
        errors.append("review data: expected a dynamic-only Breeze review export")
    rows = review_data.get("rows")
    if not isinstance(rows, list):
        errors.append("review data: rows must be an array")
        return 0
    dynamic_rows = [row for row in rows
                    if isinstance(row, dict) and row.get("kind") == "dynamic-generated"]
    by_key: dict[str, dict[str, Any]] = {}
    for row in dynamic_rows:
        key = str(row.get("review_key") or f"{row.get('lang', '')}:{row.get('filename', '')}")
        if key in by_key:
            errors.append(f"review data: duplicate dynamic review key {key}")
        by_key[key] = row
    state = review_state.get("state")
    if not isinstance(state, dict):
        errors.append("review state: expected exported voice_review_state.json with a state object")
        state = {}

    expected_keys = set()
    approved = 0
    review_fields = {
        "filename": "output_name",
        "npc": "npc",
        "speaker": "target_npc",
        "text": "text",
        "template_key": "dynamic_template_key",
        "role_span_index": "role_span_index",
        "role_span_identity": "role_span_identity",
        "lang": "lang",
        "active_gender": "active_gender",
        "player_gender": "player_gender",
        "canonical_en": "canonical_en",
        "canonical_zh": "canonical_zh",
        "source_template_en": "source_template_en",
        "source_template_zh": "source_template_zh",
        "dynamic_slots": "dynamic_slots",
        "source_parts": "source_parts",
    }
    for job in jobs:
        key = job.key
        expected_keys.add(key)
        label = f"{job.lang}/{Path(job.output).name}"
        row = by_key.get(key)
        if row is None:
            errors.append(f"{label}: dynamic review card is missing")
            continue
        if row.get("status") != "generated":
            errors.append(f"{label}: review card does not report a generated clip")
        for row_field, job_field in review_fields.items():
            expected = (Path(job.output).name if job_field == "output_name"
                        else getattr(job, job_field))
            if isinstance(expected, tuple):
                expected = list(expected)
            if row.get(row_field) != expected:
                errors.append(f"{label}: review card {row_field} differs from job")
        audio_url = row.get("audio")
        if not isinstance(audio_url, str) or not audio_url:
            errors.append(f"{label}: review card has no audio path")
        elif (review_data_path.parent / unquote(audio_url)).resolve() != Path(job.output).resolve():
            errors.append(f"{label}: review card audio path differs from expected output")
        for name in ("text", "canonical_en", "canonical_zh"):
            value = row.get(name)
            if isinstance(value, str) and UNRESOLVED.search(value):
                errors.append(f"{label}: review card {name} contains an unresolved placeholder")
        review_status = state.get(key, "unreviewed")
        if review_status != "pass":
            errors.append(f"{label}: review state is {review_status!r}, expected 'pass'")
        else:
            approved += 1
    for key in sorted(set(by_key) - expected_keys):
        errors.append(f"review data: unexpected dynamic review card {key}")
    return approved


def audit_dynamic_voice_package(manifest_path: Path, output_dir: Path,
                                review_data_path: Path,
                                review_state_path: Path | None,
                                expected_sample_rate: int | None = None) -> AuditReport:
    """Return exact manifest, sidecar, audio, and human-review coverage gaps."""
    report = AuditReport()
    manifest_path = Path(manifest_path)
    records = _check_manifest(manifest_path, report.errors)
    if not records:
        return report

    try:
        jobs = build_dynamic_breeze_jobs(manifest_path, Path(output_dir))
    except (OSError, KeyError, ValueError, RuntimeError, TypeError,
            AttributeError) as error:
        report.errors.append(f"expected route matrix: could not build jobs: {error}")
        return report
    report.expected_jobs = len(jobs)
    if not jobs:
        report.errors.append(
            "expected route matrix: no dynamic role-audio routes were generated")
        return report
    sample_rate = expected_sample_rate or breeze.SAMPLE_RATE
    for job in jobs:
        if _check_sidecar(job, sample_rate, report.errors):
            report.valid_audio += 1

    review_data = _load_json(Path(review_data_path), "review data", report.errors)
    if review_state_path is None:
        review_state = {}
        report.errors.append("review state: supply the exported voice_review_state.json")
    else:
        review_state = _load_json(Path(review_state_path), "review state", report.errors)
    report.approved_reviews = _check_review_rows(
        jobs, review_data, review_state, Path(review_data_path), report.errors)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dynamic-manifest", type=Path,
                        default=breeze.DYNAMIC_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=breeze.DYNAMIC_OUTPUT)
    parser.add_argument("--review-data", type=Path,
                        default=breeze.DYNAMIC_REVIEW / "voice_review_data.json")
    parser.add_argument(
        "--review-state", type=Path,
        help="exported voice_review_state.json with every required dynamic card marked Pass")
    args = parser.parse_args(argv)
    report = audit_dynamic_voice_package(
        args.dynamic_manifest, args.output_dir, args.review_data, args.review_state)
    print(
        f"U6 dynamic package audit: {report.valid_audio}/{report.expected_jobs} valid audio, "
        f"{report.approved_reviews}/{report.expected_jobs} approved review cards")
    for error in report.errors:
        print(f"ERROR: {error}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
