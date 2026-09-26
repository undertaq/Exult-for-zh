from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

import audit_u6_dynamic_voice_package as audit
import generate_breeze_u6 as breeze
from u6_dynamic_voice import dynamic_voice_key


FIXTURE_OGG = Path(__file__).resolve().parents[2] / "tests/fixtures/u6_voice_tone.ogg"
REAL_PROBE_AUDIO = audit._probe_audio


def _manifest_record() -> dict:
    source_parts = [
        {"kind": "literal", "source_func_id": 1073, "source_offset": 256,
         "string_offset": 1536, "text": "Hello "},
        {"kind": "dynamic", "source_func_id": 1073, "source_offset": 260,
         "variable_index": 7, "ordinal": 0, "semantic_type": "player_name"},
        {"kind": "literal", "source_func_id": 1073, "source_offset": 264,
         "string_offset": 1552, "text": "."},
    ]
    role_spans = [{
        "index": 0,
        "role": "speaker",
        "start_char": 0,
        "end_char": len("Hello <VAR0>."),
        "requires_audio": True,
        "transcripts": {
            "default": {"en": "Hello Avatar.", "zh": "您好，聖者。"},
        },
    }]
    identity = {
        "function_id": 1073,
        "segment": 0,
        "source_template_en": "Hello <VAR0>.",
        "source_parts": source_parts,
        "role_spans": [{
            "role": "speaker", "start_char": 0,
            "end_char": len("Hello <VAR0>."),
        }],
    }
    return {
        "schema": "u6-dynamic-voice-template-v1",
        "line_id": "u6-test-line",
        "key": dynamic_voice_key(identity),
        "function_id": 1073,
        "npc": "Dupre",
        "speaker": "Dupre",
        "speaker_func_id": 1073,
        "caller_guess": "",
        "offset_key": "10",
        "addsi_offsets": ["10", "20"],
        "code_addr": 100,
        "segment": 0,
        "total_segments": 1,
        "dynamic": True,
        "source_template_en": "Hello <VAR0>.",
        "source_template_zh": "您好，<VAR0>。",
        "translation_source_sha256": "a" * 64,
        "source_parts": source_parts,
        "slots": [{"ordinal": 0, "semantic_type": "player_name"}],
        "player_gender_variants": [None],
        "canonical_transcripts": {
            "default": {"en": "Hello Avatar.", "zh": "您好，聖者。"},
        },
        "role_source": "markers",
        "role_spans": role_spans,
        "whole_span_override": None,
    }


def _job(tmp_path: Path, record: dict, lang: str = "en"):
    audio = tmp_path / lang / "0401_10_s0.ogg"
    audio.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE_OGG, audio)
    ref = breeze.Reference("u6_dupre_en", FIXTURE_OGG, "Reference text", "male")
    text = "Hello Avatar." if lang == "en" else "您好，聖者。"
    part = breeze.VoicePart("speaker", text, ref)
    return breeze.BreezeCloneJob(
        key=f"{lang}:{audio.name}", npc="Dupre", target_npc="Dupre", lang=lang,
        text=text, func_id="0x0431", offset_key="10", segment=0,
        output=audio, parts=(part,), active_gender="male", avatar_gender=None,
        cross_speaker_target=None, source_en=record["source_template_en"],
        source_zh=record["source_template_zh"],
        dynamic_template_key=record["key"], role_span_index=0,
        role_span_identity="0:speaker:0-13", player_gender=None,
        dynamic_slots=tuple(record["slots"]),
        source_template_en=record["source_template_en"],
        source_template_zh=record["source_template_zh"],
        canonical_en="Hello Avatar.", canonical_zh="您好，聖者。",
        source_parts=tuple(record["source_parts"]),
        role_span_start_char=0, role_span_end_char=13,
    )


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_sidecar(job) -> None:
    _write(job.output.with_suffix(".json"), {
        "status": "generated",
        "sample_rate": 16000,
        "sha256": breeze.sha256_file(job.output),
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
        "dynamic_job_signature": breeze.dynamic_job_signature(job),
        "same_sex_narrator": True,
        "parts": [{
            "role": "speaker", "text": job.parts[0].text,
            "reference_id": job.parts[0].reference.reference_id,
            "reference_gender": job.parts[0].reference.gender,
        }],
    })


def _write_review_files(tmp_path: Path, jobs: list) -> tuple[Path, Path]:
    rows = [{
        "kind": "dynamic-generated", "status": "generated", "lang": job.lang,
        "npc": job.npc, "speaker": job.target_npc, "text": job.text,
        "filename": job.output.name, "review_key": job.key,
        "audio": os.path.relpath(job.output, tmp_path / "review"),
        "template_key": job.dynamic_template_key,
        "role_span_index": job.role_span_index,
        "role_span_identity": job.role_span_identity,
        "active_gender": job.active_gender, "player_gender": job.player_gender,
        "canonical_en": job.canonical_en, "canonical_zh": job.canonical_zh,
        "source_template_en": job.source_template_en,
        "source_template_zh": job.source_template_zh,
        "dynamic_slots": list(job.dynamic_slots),
        "source_parts": list(job.source_parts),
    } for job in jobs]
    review_data = tmp_path / "review/voice_review_data.json"
    review_state = tmp_path / "review/voice_review_state.json"
    _write(review_data, {"dynamic_only": True, "rows": rows})
    _write(review_state, {"state": {job.key: "pass" for job in jobs}})
    return review_data, review_state


def _package(tmp_path: Path, monkeypatch):
    record = _manifest_record()
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    job = _job(tmp_path / "audio", record)
    _write_sidecar(job)
    review_data, review_state = _write_review_files(tmp_path, [job])
    monkeypatch.setattr(audit, "build_dynamic_breeze_jobs", lambda *_args: [job])
    monkeypatch.setattr(audit, "_probe_audio", lambda _path: SimpleNamespace(
        samplerate=16000, channels=1, frames=1000, format="OGG", subtype="VORBIS"))
    return manifest, job, review_data, review_state


def test_package_audit_accepts_complete_reviewed_dynamic_route(tmp_path, monkeypatch):
    manifest, job, review_data, review_state = _package(tmp_path, monkeypatch)

    report = audit.audit_dynamic_voice_package(
        manifest, tmp_path / "audio", review_data, review_state,
        expected_sample_rate=16000)

    assert report.errors == []
    assert report.expected_jobs == 1
    assert report.valid_audio == 1
    assert report.approved_reviews == 1


def test_package_audit_rejects_empty_expected_route_matrix(tmp_path, monkeypatch):
    manifest, _job_value, review_data, review_state = _package(tmp_path, monkeypatch)
    monkeypatch.setattr(audit, "build_dynamic_breeze_jobs", lambda *_args: [])

    report = audit.audit_dynamic_voice_package(
        manifest, tmp_path / "audio", review_data, review_state,
        expected_sample_rate=16000)

    assert not report.ok
    assert report.expected_jobs == 0
    assert any("no dynamic role-audio routes" in error for error in report.errors)


def test_package_audit_rejects_empty_audio_stream(tmp_path, monkeypatch):
    manifest, _job_value, review_data, review_state = _package(tmp_path, monkeypatch)
    monkeypatch.setattr(audit, "_probe_audio", lambda _path: SimpleNamespace(
        samplerate=16000, channels=1, frames=0, format="OGG", subtype="VORBIS"))

    report = audit.audit_dynamic_voice_package(
        manifest, tmp_path / "audio", review_data, review_state,
        expected_sample_rate=16000)

    assert any("expected a nonempty mono Ogg clip" in error for error in report.errors)


def test_package_audit_rejects_corrupt_audio_stream(tmp_path, monkeypatch):
    manifest, _job_value, review_data, review_state = _package(tmp_path, monkeypatch)

    class TruncatedStream:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, *_args, **_kwargs):
            raise RuntimeError("truncated Ogg stream")

    class FakeSoundFile:
        @staticmethod
        def SoundFile(_path):
            return TruncatedStream()

        @staticmethod
        def info(_path):
            return SimpleNamespace(
                samplerate=16000, channels=1, frames=1000,
                format="OGG", subtype="VORBIS")

    monkeypatch.setattr(audit, "_probe_audio", REAL_PROBE_AUDIO)
    monkeypatch.setattr(breeze, "sf", FakeSoundFile())
    report = audit.audit_dynamic_voice_package(
        manifest, tmp_path / "audio", review_data, review_state,
        expected_sample_rate=16000)

    assert any("truncated Ogg stream" in error for error in report.errors)


def test_package_audit_rejects_conflicting_duplicate_manifest_keys(tmp_path, monkeypatch):
    manifest, _job_value, _review_data, _review_state = _package(tmp_path, monkeypatch)
    record = _manifest_record()
    conflicting = dict(record, npc="Chuckles")
    manifest.write_text("\n".join(json.dumps(row) for row in (record, conflicting)) + "\n",
                        encoding="utf-8")

    report = audit.audit_dynamic_voice_package(
        manifest, tmp_path / "audio", tmp_path / "review/data.json",
        tmp_path / "review/state.json", expected_sample_rate=16000)

    assert any("conflicting duplicate key" in error for error in report.errors)


def test_package_audit_rejects_runtime_text_in_dynamic_manifest_part(tmp_path, monkeypatch):
    manifest, _job_value, _review_data, _review_state = _package(tmp_path, monkeypatch)
    record = _manifest_record()
    record["source_parts"][1]["text"] = "Joe"
    manifest.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    report = audit.audit_dynamic_voice_package(
        manifest, tmp_path / "audio", tmp_path / "review/data.json",
        tmp_path / "review/state.json", expected_sample_rate=16000)

    assert any("dynamic parts must not contain runtime text" in error
               for error in report.errors)


def test_package_audit_names_missing_audio_role_output(tmp_path, monkeypatch):
    manifest, job, review_data, review_state = _package(tmp_path, monkeypatch)
    job.output.unlink()

    report = audit.audit_dynamic_voice_package(
        manifest, tmp_path / "audio", review_data, review_state,
        expected_sample_rate=16000)

    assert any(job.output.name in error and "audio is missing" in error
               for error in report.errors)


def test_package_audit_rejects_failed_or_unreviewed_cards(tmp_path, monkeypatch):
    manifest, job, review_data, review_state = _package(tmp_path, monkeypatch)
    _write(review_state, {"state": {job.key: "failed"}})

    report = audit.audit_dynamic_voice_package(
        manifest, tmp_path / "audio", review_data, review_state,
        expected_sample_rate=16000)

    assert any("review state is 'failed'" in error for error in report.errors)


def test_package_audit_rejects_sidecar_identity_or_hash_drift(tmp_path, monkeypatch):
    manifest, job, review_data, review_state = _package(tmp_path, monkeypatch)
    sidecar_path = job.output.with_suffix(".json")
    metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
    metadata["target_npc"] = "Chuckles"
    metadata["sha256"] = "0" * 64
    _write(sidecar_path, metadata)

    report = audit.audit_dynamic_voice_package(
        manifest, tmp_path / "audio", review_data, review_state,
        expected_sample_rate=16000)

    assert any("target_npc" in error for error in report.errors)
    assert any("SHA-256" in error for error in report.errors)


def test_package_audit_rejects_unresolved_slot_placeholders(tmp_path, monkeypatch):
    manifest, job, review_data, review_state = _package(tmp_path, monkeypatch)
    record = _manifest_record()
    record["canonical_transcripts"]["default"]["en"] = "Hello <VAR0>."
    manifest.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    report = audit.audit_dynamic_voice_package(
        manifest, tmp_path / "audio", review_data, review_state,
        expected_sample_rate=16000)

    assert any("unresolved placeholder" in error for error in report.errors)


def test_package_audit_rejects_review_card_link_to_another_clip(tmp_path, monkeypatch):
    manifest, job, review_data, review_state = _package(tmp_path, monkeypatch)
    payload = json.loads(review_data.read_text(encoding="utf-8"))
    payload["rows"][0]["audio"] = "../../wrong-speaker.ogg"
    _write(review_data, payload)

    report = audit.audit_dynamic_voice_package(
        manifest, tmp_path / "audio", review_data, review_state,
        expected_sample_rate=16000)

    assert any("review card audio path differs from expected output" in error
               for error in report.errors)


def test_package_audit_rejects_voice_part_text_drift(tmp_path, monkeypatch):
    manifest, job, review_data, review_state = _package(tmp_path, monkeypatch)
    sidecar_path = job.output.with_suffix(".json")
    metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
    metadata["parts"][0]["text"] = "A different sentence."
    _write(sidecar_path, metadata)

    report = audit.audit_dynamic_voice_package(
        manifest, tmp_path / "audio", review_data, review_state,
        expected_sample_rate=16000)

    assert any("voice-part 0 route differs from job" in error
               for error in report.errors)
