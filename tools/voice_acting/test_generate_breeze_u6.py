from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace

import numpy as np
import pytest
import generate_breeze_u6 as module

from generate_breeze_u6 import (
    _catalog_gender,
    _load_reference_catalog,
    avatar_genders_for_route,
    narrator_reference_id,
    route_voice_parts,
)


def test_narrator_reference_matches_active_speaker_gender() -> None:
    assert narrator_reference_id("male") == "npc_narrator_male"
    assert narrator_reference_id("female") == "npc_unknown"


def test_mixed_usecode_line_keeps_narrator_and_speaker_parts() -> None:
    parts = route_voice_parts("Maldric says @Hello, old friend!@ He smiles.", "Maldric 說@老朋友，你好！@ 他微笑。", "en")
    assert parts == [
        ("narrator", "Maldric says"),
        ("speaker", "Hello, old friend!"),
        ("narrator", "He smiles."),
    ]


def test_avatar_route_expands_to_both_genders() -> None:
    assert avatar_genders_for_route("Avatar", routed=True) == ("male", "female")
    assert avatar_genders_for_route("Dupre", routed=True) == (None,)
    assert avatar_genders_for_route("Avatar", routed=False) == (None,)


def test_gargoyle_pronouns_resolve_male_instead_of_nonhuman_female_fallback() -> None:
    description = "a small gargoyle child. He speaks to you and his father is Valkadesh."
    assert _catalog_gender(description, "female") == "male"


def test_beh_lem_uses_male_route_gender() -> None:
    _, genders = _load_reference_catalog()
    assert genders["beh lem"] == "male"


def test_reference_metadata_gender_overrides_stale_design_inference() -> None:
    _, genders = _load_reference_catalog()
    assert genders["andreas"] == "male"


def test_beh_lem_english_output_is_peak_normalized() -> None:
    job = SimpleNamespace(target_npc="Beh Lem", lang="en")
    assert hasattr(module, "normalize_audio_for_job")
    normalized = module.normalize_audio_for_job(job, np.array([-0.1, 0.05], dtype=np.float32))
    assert float(np.max(np.abs(normalized))) == pytest.approx(10 ** (-1 / 20), abs=1e-6)


def _dynamic_row(npc: str, speaker: str, genders: list[str | None]) -> dict:
    transcripts = {
        "male": {"en": "I saw him.", "zh": "我看見他。"},
        "female": {"en": "I saw her.", "zh": "我看見她。"},
        "default": {"en": "Welcome, Avatar.", "zh": "歡迎，聖者。"},
    }
    return {
        "schema": "u6-dynamic-voice-template-v1",
        "key": "dyn_" + "a" * 64,
        "line_id": "0x0430:600:0",
        "function_id": 0x0430,
        "npc": npc,
        "speaker": speaker,
        "speaker_func_id": 0x0430,
        "caller_guess": "",
        "offset_key": "0x600",
        "segment": 0,
        "total_segments": 1,
        "source_template_en": "I saw <VAR0>.",
        "source_template_zh": "我看見<VAR0>。",
        "source_parts": [
            {"kind": "literal", "text": "I saw "},
            {"kind": "dynamic", "ordinal": 0, "semantic_type": "pronoun"},
            {"kind": "literal", "text": "."},
        ],
        "slots": [{"ordinal": 0, "semantic_type": "pronoun", "pronoun_form": "object"}],
        "player_gender_variants": genders,
        "role_spans": [
            {
                "index": 0, "role": "speaker", "start_char": 0, "end_char": 15,
                "requires_audio": True,
                "transcripts": {gender or "default": transcripts[gender or "default"]
                                for gender in genders},
            },
            {
                "index": 1, "role": "narrator", "start_char": 15, "end_char": 22,
                "requires_audio": True,
                "transcripts": {gender or "default": {
                    "en": "He looks away." if gender != "female" else "She looks away.",
                    "zh": "他移開視線。" if gender != "female" else "她移開視線。",
                } for gender in genders},
            },
        ],
    }


def _build_dynamic_jobs(monkeypatch, manifest_path: Path, output_dir: Path, genders_by_npc):
    breeze_refs = {}
    design_refs = {}
    u7_refs = {}
    refs_by_gender = {
        (npc.casefold(), lang): module.Reference(
            f"npc_{npc.casefold()}", Path(f"/refs/{npc}_{lang}.ogg"), "reference", gender)
        for npc, gender in genders_by_npc.items()
        for lang in ("en", "zh")
    }
    catalog_genders = {npc.casefold(): gender for npc, gender in genders_by_npc.items()}
    monkeypatch.setattr(module, "_load_reference_catalog", lambda: (refs_by_gender, catalog_genders))
    monkeypatch.setattr(module, "_load_u7_references", lambda: (design_refs, u7_refs))

    def speaker_reference(npc, lang, avatar_gender, *_args):
        if npc.casefold() == "avatar":
            gender = avatar_gender
            return module.Reference(f"npc_avatar_{gender}", Path(f"/refs/avatar_{gender}_{lang}.ogg"), "ref", gender)
        return refs_by_gender[(npc.casefold(), lang)]

    monkeypatch.setattr(module, "_reference_for_npc", speaker_reference)
    monkeypatch.setattr(
        module,
        "_narrator_reference",
        lambda gender, lang, _refs: module.Reference(
            module.narrator_reference_id(gender), Path(f"/refs/narrator_{gender}_{lang}.ogg"), "narrator", gender),
    )
    return module.build_dynamic_breeze_jobs(manifest_path, output_dir)


def test_dynamic_jobs_keep_player_gender_separate_from_npc_voice_gender(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "dynamic.jsonl"
    manifest.write_text(json.dumps(_dynamic_row("Wanda", "Wanda", ["male", "female"])) + "\n", encoding="utf-8")

    jobs = _build_dynamic_jobs(monkeypatch, manifest, tmp_path / "out", {"Wanda": "female"})
    en_jobs = [job for job in jobs if job.lang == "en"]

    assert {(job.role_span_index, job.player_gender) for job in en_jobs} == {
        (0, "male"), (0, "female"), (1, "male"), (1, "female"),
    }
    assert all(job.active_gender == "female" for job in en_jobs)
    assert all(job.dynamic_template_key == "dyn_" + "a" * 64 for job in en_jobs)
    assert all(job.dynamic_slots[0]["semantic_type"] == "pronoun" for job in en_jobs)
    assert all(job.output.parent == tmp_path / "out" / "en" for job in en_jobs)
    assert all(job.template_key in job.output.name for job in en_jobs)
    assert any(job.text == "I saw him." for job in en_jobs)
    assert any(job.text == "I saw her." for job in en_jobs)
    assert {job.parts[0].reference.reference_id for job in en_jobs if job.route_mode == "narrator"} == {"npc_unknown"}


def test_dynamic_jobs_expand_shared_helper_caller_routes_without_filename_collision(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "dynamic.jsonl"
    row = _dynamic_row("", "", ["male", "female"])
    row["caller_guess"] = "Wanda|Dupre"
    manifest.write_text(json.dumps(row) + "\n", encoding="utf-8")

    jobs = _build_dynamic_jobs(
        monkeypatch, manifest, tmp_path / "out", {"Wanda": "female", "Dupre": "male"})
    en_jobs = [job for job in jobs if job.lang == "en" and job.role_span_index == 0 and job.player_gender == "male"]

    assert {job.target_npc for job in en_jobs} == {"Wanda", "Dupre"}
    assert {job.active_gender for job in en_jobs} == {"female", "male"}
    assert len({job.output for job in en_jobs}) == 2
    assert len({job.parts[0].reference.reference_id for job in en_jobs}) == 2


def test_dynamic_avatar_jobs_include_both_active_reference_genders(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "dynamic.jsonl"
    row = _dynamic_row("Avatar", "Avatar", [None])
    row["slots"] = [{"ordinal": 0, "semantic_type": "player_name"}]
    row["player_gender_variants"] = [None]
    row["role_spans"] = [row["role_spans"][0]]
    row["role_spans"][0]["transcripts"] = {
        "default": {"en": "Welcome, Avatar.", "zh": "歡迎，聖者。"}}
    manifest.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    jobs = _build_dynamic_jobs(monkeypatch, manifest, tmp_path / "out", {"Avatar": "male"})
    en_jobs = [job for job in jobs if job.lang == "en"]

    assert {job.active_gender for job in en_jobs} == {"male", "female"}
    assert {job.avatar_gender for job in en_jobs} == {"male", "female"}
    assert {job.player_gender for job in en_jobs} == {None}
    assert {job.parts[0].reference.reference_id for job in en_jobs} == {
        "npc_avatar_male", "npc_avatar_female",
    }


def test_dynamic_resume_requires_matching_template_and_job_metadata(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "dynamic.jsonl"
    manifest.write_text(json.dumps(_dynamic_row("Wanda", "Wanda", ["male", "female"])) + "\n", encoding="utf-8")
    jobs = _build_dynamic_jobs(monkeypatch, manifest, tmp_path / "out", {"Wanda": "female"})
    job = next(job for job in jobs if job.lang == "en" and job.player_gender == "male" and job.role_span_index == 0)
    job.output.parent.mkdir(parents=True)
    job.output.write_bytes(b"fake")
    metadata_path = module._metadata_path(job.output)
    metadata_path.write_text(json.dumps({
        "status": "generated",
        "dynamic_job_signature": module.dynamic_job_signature(job),
    }), encoding="utf-8")
    monkeypatch.setattr(module, "_usable_output", lambda *_args: True)

    assert module._usable_output_for_job(job)
    metadata_path.write_text(json.dumps({
        "status": "generated",
        "dynamic_job_signature": "stale-source-signature",
    }), encoding="utf-8")
    assert not module._usable_output_for_job(job)


def test_dynamic_review_rows_include_portrait_slots_roles_and_bilingual_text(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "dynamic.jsonl"
    manifest.write_text(json.dumps(_dynamic_row("Wanda", "Wanda", ["male", "female"])) + "\n", encoding="utf-8")
    jobs = _build_dynamic_jobs(monkeypatch, manifest, tmp_path / "out", {"Wanda": "female"})
    monkeypatch.setattr(module, "_portrait_for_npc", lambda _npc: "/portraits/wanda.gif")

    rows = module.dynamic_review_rows(jobs)
    row = next(row for row in rows if row["lang"] == "en" and row["player_gender"] == "male")
    assert row["portrait"] == "/portraits/wanda.gif"
    assert row["speaker"] == "Wanda"
    assert row["source_template_en"] == "I saw <VAR0>."
    assert row["dynamic_slots"][0]["semantic_type"] == "pronoun"
    assert row["role_span_identity"].startswith("0:speaker:")
    assert row["active_gender"] == "female"
    assert row["player_gender"] == "male"
    assert row["text"] == "I saw him."
    assert row["ref_audio"]
    assert "Canonical zh-Hant: 我看見他。" in row["note"]

    review_dir = tmp_path / "review"
    module.write_dynamic_review(jobs, completed=0, review_dir=review_dir)
    page = (review_dir / "index.html").read_text(encoding="utf-8")
    data = (review_dir / "voice_review_data.json").read_text(encoding="utf-8")
    assert "<img class=\\\"portrait\\\"" in page or '<img class="portrait"' in page
    assert "Source EN: I saw <VAR0>." in data
    assert "dynamic_only" in data


def test_dynamic_paths_reject_existing_voice_and_review_trees(tmp_path) -> None:
    assert module.validate_dynamic_output_paths(
        tmp_path / "dynamic_audio", tmp_path / "dynamic_review")

    with pytest.raises(ValueError, match="protected existing"):
        module.validate_dynamic_output_paths(
            module.OUTPUT / "nested", tmp_path / "dynamic_review")
    with pytest.raises(ValueError, match="protected existing"):
        module.validate_dynamic_output_paths(
            module.DYNAMIC_REVIEW / "nested", tmp_path / "dynamic_review")

    with pytest.raises(ValueError, match="overlap"):
        module.validate_dynamic_output_paths(
            tmp_path / "same", tmp_path / "same" / "review")


def test_dynamic_cli_rejects_negative_job_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        module.sys, "argv",
        ["generate_breeze_u6.py", "--dynamic-only", "--max-jobs", "-1"],
    )
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2
