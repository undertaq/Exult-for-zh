import importlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

import tools.voice_acting.generate_omnivoice_u6 as generator
from tools.voice_acting.generate_omnivoice_u6 import (
    CloneJob,
    ReferenceJob,
    build_clone_jobs,
    build_reference_jobs,
    chunked,
    fallback_texts,
    load_role_manifest,
    omnivoice_instruction,
    parse_role_parts,
    load_reference_overrides,
    parse_args,
    role_key,
    select_target_jobs,
)


PROJECT = Path(__file__).resolve().parents[2]


def test_role_manifest_loader_tolerates_malformed_rows_and_normalizes_keys(tmp_path):
    manifest = tmp_path / "roles.jsonl"
    manifest.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "function_id": 1025,
                        "offset_key": " 0 ",
                        "segment": 0,
                        "source_en": "  @Hello, Avatar!@  ",
                        "text_zh": "  @你好，聖者！@  ",
                    },
                    ensure_ascii=False,
                ),
                "{ this is not JSON }",
            ]
        ),
        encoding="utf-8",
    )

    roles = load_role_manifest(manifest)

    assert roles == {
        ("0401", "0", "0"): {
            "source_en": "@Hello, Avatar!@",
            "text_zh": "@你好，聖者！@",
        }
    }
    assert role_key("1025", " 0 ", "0") == ("0401", "0", "0")
    assert role_key("0401", "0", "0") == ("0401", "0", "0")


def test_default_role_manifest_covers_every_u6_mapping_key():
    roles = load_role_manifest(generator.DEFAULT_ROLE_MANIFEST)
    mapping = json.loads(generator.DEFAULT_MAPPING.read_text(encoding="utf-8"))
    mapping_keys = {
        role_key(
            entry[f"{lang}_func_id"],
            entry[f"{lang}_offset_key"],
            entry.get(f"{lang}_segment", 0),
        )
        for entry in mapping
        for lang in ("en", "zh")
    }

    assert len(mapping) == 10_725
    assert len(roles) == 10_704
    assert set(roles) == mapping_keys


@pytest.mark.parametrize(
    ("source_en", "translated_text", "lang", "expected"),
    [
        ("@Hello, Avatar!@", "ignored", "en", [("speaker", "Hello, Avatar!")]),
        ("He smiles.", "ignored", "en", [("narrator", "He smiles.")]),
        (
            "He smiles. @Hello!@ He waves.*",
            "ignored",
            "en",
            [("narrator", "He smiles."), ("speaker", "Hello!"), ("narrator", "He waves.")],
        ),
        (
            "他微笑。 @Hello!@ 他揮手。",
            "他微笑。 @你好！@ 他揮手。",
            "zh",
            [("narrator", "他微笑。"), ("speaker", "你好！"), ("narrator", "他揮手。")],
        ),
        (
            "He smiles. @Hello!@",
            "他微笑。 「你好！」",
            "zh",
            [("speaker", "他微笑。 「你好！」")],
        ),
        (
            "He smiles. @Hello!@",
            "他微笑。你好！",
            "zh",
            [("speaker", "他微笑。你好！")],
        ),
        (
            "He smiles.",
            "他微笑。 「你好！」*",
            "zh",
            [("narrator", "他微笑。 「你好！」")],
        ),
        (
            "@Hey, my old buddy ",
            "ignored",
            "en",
            [("speaker", "Hey, my old buddy")],
        ),
        (
            "! Good to see you again.@",
            "ignored",
            "en",
            [("speaker", "! Good to see you again.")],
        ),
        (
            "! Good to see you again.@*",
            "ignored",
            "en",
            [("speaker", "! Good to see you again.")],
        ),
        (
            "Turning to you, Gwenneth says, @And what can I do",
            "ignored",
            "en",
            [
                ("narrator", "Turning to you, Gwenneth says,"),
                ("speaker", "And what can I do"),
            ],
        ),
        (
            "!@ she screams and backs away.",
            "ignored",
            "en",
            [("speaker", "!"), ("narrator", "she screams and backs away.")],
        ),
        (
            "@Hey, my old buddy ",
            "@嘿，我的老朋友 ",
            "zh",
            [("speaker", "嘿，我的老朋友")],
        ),
        (
            "! Good to see you again.@",
            "! 很高興又見到你了。@",
            "zh",
            [("speaker", "! 很高興又見到你了。")],
        ),
        (
            "@@Anything else?@",
            "ignored",
            "en",
            [("speaker", "Anything else?")],
        ),
        (
            "@@Sir Caradon..@",
            "ignored",
            "en",
            [("speaker", "Sir Caradon..")],
        ),
        (
            "@@Anything else?@",
            "@@還有其他事嗎？@",
            "zh",
            [("speaker", "還有其他事嗎？")],
        ),
        (
            "@@Sir Caradon..@",
            "@@Sir Caradon 爵士..@",
            "zh",
            [("speaker", "Sir Caradon 爵士..")],
        ),
    ],
)
def test_parse_role_parts_uses_english_markers_as_role_authority(
    source_en,
    translated_text,
    lang,
    expected,
):
    assert parse_role_parts(source_en, translated_text, lang) == expected


def _designs():
    return json.loads(
        (PROJECT / "u6_voice" / "u6_npc_voice_designs.json").read_text(
            encoding="utf-8"
        )
    )["designs"]


def test_instruction_uses_omnivoice_language_specific_tags():
    design = {
        "casting_inference": {"gender": "female", "age": "young"},
        "voice_desc_en": "A young female voice with a lively presence.",
    }

    assert omnivoice_instruction(design, "en") == (
        "female, young adult, high pitch, American accent"
    )
    assert omnivoice_instruction(design, "zh") == "女, 青年, 高音调"


@pytest.mark.parametrize(
    "description",
    [
        "A warm and lightly cheerful adult voice.",
        "A warm and lively adult voice.",
    ],
)
def test_adult_emotion_description_does_not_imply_high_pitch(description):
    design = {
        "casting_inference": {"gender": "male", "age": "adult"},
        "voice_desc_en": description,
    }

    assert omnivoice_instruction(design, "en") == "male, moderate pitch, American accent"
    assert omnivoice_instruction(design, "zh") == "男, 中音调"


@pytest.mark.parametrize(
    ("design_id", "expected_en", "expected_zh"),
    [
        ("u6_aaron_324a17d2", "male, moderate pitch, American accent", "男, 中音调"),
        ("u6_amanda_161b5245", "female, moderate pitch, American accent", "女, 中音调"),
        ("u6_arty_762c615c", "male, moderate pitch, American accent", "男, 中音调"),
        ("u6_budo_4b6e65fd", "male, moderate pitch, American accent", "男, 中音调"),
        ("u6_dezana_6642c6a6", "female, moderate pitch, American accent", "女, 中音调"),
        ("u6_dunbar_d41e3d0c", "male, moderate pitch, American accent", "男, 中音调"),
        ("u6_kenneth_ca70c45c", "male, moderate pitch, American accent", "男, 中音调"),
        ("u6_leonna_c563a3bc", "female, moderate pitch, American accent", "女, 中音调"),
        ("u6_marney_b33f933c", "female, low pitch, American accent", "女, 低音调"),
        ("u6_sandy_e42e5767", "male, low pitch, American accent", "男, 低音调"),
        ("u6_shawn_66e52fa9", "male, moderate pitch, American accent", "男, 中音调"),
        ("u6_timothy_f787b4f6", "male, moderate pitch, American accent", "男, 中音调"),
        ("u6_trenton_bell_50adc94b", "male, moderate pitch, American accent", "男, 中音调"),
        ("u6_wilbur_63606e9b", "male, moderate pitch, American accent", "男, 中音调"),
        ("u6_zoltan_5aadd2f1", "male, moderate pitch, American accent", "男, 中音调"),
    ],
)
def test_audited_design_overrides_take_precedence(design_id, expected_en, expected_zh):
    design = _designs()[design_id]

    assert omnivoice_instruction(design, "en", design_id) == expected_en
    assert omnivoice_instruction(design, "zh", design_id) == expected_zh


def test_manifest_overrides_can_replace_the_audited_design_defaults():
    design = _designs()["u6_sandy_e42e5767"]
    overrides = {
        "u6_sandy_e42e5767": {"en": "male, high pitch, American accent"}
    }

    assert omnivoice_instruction(
        design,
        "en",
        "u6_sandy_e42e5767",
        overrides,
    ) == "male, high pitch, American accent"
    assert omnivoice_instruction(
        design,
        "zh",
        "u6_sandy_e42e5767",
        overrides,
    ) == "男, 低音调"


def test_age_and_non_human_pitch_rules_keep_their_precedence():
    designs = _designs()
    elderly = {
        "casting_inference": {"gender": "female", "age": "elderly"},
        "voice_desc_en": "A lively elderly voice.",
    }
    non_human = {
        "casting_inference": {"gender": "non-human", "age": "adult"},
        "voice_desc_en": "A lively gargoyle voice.",
    }

    assert omnivoice_instruction(elderly, "en") == "female, elderly, low pitch, American accent"
    assert omnivoice_instruction(elderly, "zh") == "女, 老年, 低音调"
    assert omnivoice_instruction(non_human, "zh") == "极低音调"
    assert omnivoice_instruction(
        designs["u6_weaponsmith_7e98139a"], "en", "u6_weaponsmith_7e98139a"
    ) == "young adult, very low pitch, American accent"


def test_reference_jobs_keep_u7_overrides_and_generate_the_rest():
    designs = _designs()
    overrides = load_reference_overrides(
        PROJECT / "tools" / "voice_acting" / "reference_import_manifest.json"
    )
    jobs = build_reference_jobs(designs, PROJECT / "u6_voice" / "omnivoice_refs", overrides)

    assert len(jobs) == 406
    assert sum(job.source == "u7" for job in jobs) == 62
    assert sum(job.source == "omnivoice_design" for job in jobs) == 344


def test_clone_jobs_match_the_u6_mapping_counts():
    designs = _designs()
    role_sources = load_role_manifest(generator.DEFAULT_ROLE_MANIFEST)
    reference_routes = generator.stage_u7_special_references(
        PROJECT / "tools" / "voice_acting" / "reference_import_manifest.json",
        PROJECT / "voice" / "refs",
        PROJECT / "u6_voice" / "omnivoice_refs",
    )
    jobs = build_clone_jobs(
        PROJECT / "u6_voice" / "manifests" / "u6_qwen3_mapping.json",
        designs,
        PROJECT / "u6_voice" / "omnivoice_refs",
        PROJECT / "u6_voice" / "omnivoice",
        load_reference_overrides(
            PROJECT / "tools" / "voice_acting" / "reference_import_manifest.json"
        ),
        role_sources=role_sources,
        reference_routes=reference_routes,
    )

    assert sum(job.lang == "en" for job in jobs) == 10886
    assert sum(job.lang == "zh" for job in jobs) == 10853
    assert sum(job.avatar_gender == "male" for job in jobs) == 364
    assert sum(job.avatar_gender == "female" for job in jobs) == 364
    assert all(job.ref_text for job in jobs)


def test_chunked_preserves_order_and_covers_every_job():
    assert list(chunked(list(range(5)), 2)) == [[0, 1], [2, 3], [4]]


def test_fallback_texts_handle_punctuation_without_changing_normal_text():
    assert list(fallback_texts("!", "en")) == ["!", "Ah!"]
    assert list(fallback_texts(". There ya go.", "en")) == [
        ". There ya go.",
        "There ya go.",
        "There ya go",
    ]
    assert list(fallback_texts("名字", "zh")) == ["名字"]


def test_fallback_texts_collapse_repeated_terminal_punctuation():
    variants = list(fallback_texts("Excuse me..", "en"))
    assert "Excuse me." in variants
    assert "Excuse me" in variants


def _override_manifest(tmp_path):
    path = tmp_path / "omnivoice_overrides.json"
    path.write_text(
        json.dumps(
            {
                "revision": "u6-omnivoice-overrides-v1",
                "voice_design": {
                    "u6_arty_762c615c": {
                        "en": "male, moderate pitch, American accent",
                        "zh": "男, 中音调",
                    }
                },
                "pronunciation": [
                    {
                        "lang": "zh",
                        "source": "馴蛇者",
                        "tts": "XUN4蛇者",
                        "expected_pinyin": "xùn shé zhě",
                        "reason": "Taiwan Mandarin reading in this phrase",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    try:
        module = importlib.import_module("tools.voice_acting.omnivoice_overrides")
    except ModuleNotFoundError:
        pytest.fail("OmniVoice override loader is not implemented")
    return module.load_omnivoice_overrides(path)


def test_clone_job_keeps_source_text_and_carries_tts_override(tmp_path):
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "npc": "Snakecharmer",
                    "zh_text": "萬歲，馴蛇者！",
                    "zh_output_filename": "line.ogg",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    designs = {
        "snake": {
            "npc": "Snakecharmer",
            "ref_zh_text": "參考文字",
            "casting_inference": {"gender": "male", "age": "adult"},
        }
    }

    jobs = build_clone_jobs(
        mapping,
        designs,
        tmp_path / "refs",
        tmp_path / "output",
        {},
        _override_manifest(tmp_path),
    )

    assert jobs[0].text == "萬歲，馴蛇者！"
    assert jobs[0].tts_text == "萬歲，XUN4蛇者！"
    assert jobs[0].override_revision == "u6-omnivoice-overrides-v1"


def test_voice_design_override_preserves_u7_reference_reuse(tmp_path):
    designs = {
        "u6_arty_762c615c": {
            "npc": "Arty",
            "ref_en_text": "Hello.",
            "ref_zh_text": "你好。",
            "casting_inference": {"gender": "male", "age": "adult"},
        }
    }
    u7 = {
        ("arty", "en"): {"path": tmp_path / "arty.ogg", "ref_text": "U7 Arty"}
    }

    jobs = build_reference_jobs(
        designs,
        tmp_path / "refs",
        u7,
        _override_manifest(tmp_path),
    )
    by_lang = {job.lang: job for job in jobs}

    assert by_lang["en"].source == "u7"
    assert by_lang["en"].override_revision is None
    assert by_lang["zh"].instruct == "男, 中音调"
    assert by_lang["zh"].override_revision == "u6-omnivoice-overrides-v1"


def test_default_manifest_covers_all_task_2_design_corrections():
    overrides = generator.load_omnivoice_overrides(generator.DEFAULT_OVERRIDES)

    assert overrides.voice_design == {
        "u6_aaron_324a17d2": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
        "u6_amanda_161b5245": {"en": "female, moderate pitch, American accent", "zh": "女, 中音调"},
        "u6_arty_762c615c": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
        "u6_budo_4b6e65fd": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
        "u6_dezana_6642c6a6": {"en": "female, moderate pitch, American accent", "zh": "女, 中音调"},
        "u6_dunbar_d41e3d0c": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
        "u6_kenneth_ca70c45c": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
        "u6_leonna_c563a3bc": {"en": "female, moderate pitch, American accent", "zh": "女, 中音调"},
        "u6_marney_b33f933c": {"en": "female, low pitch, American accent", "zh": "女, 低音调"},
        "u6_sandy_e42e5767": {"en": "male, low pitch, American accent", "zh": "男, 低音调"},
        "u6_shawn_66e52fa9": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
        "u6_timothy_f787b4f6": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
        "u6_trenton_bell_50adc94b": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
        "u6_wilbur_63606e9b": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
        "u6_zoltan_5aadd2f1": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
    }


def test_non_arty_generated_design_jobs_receive_current_revision():
    designs = _designs()
    u7 = load_reference_overrides(
        PROJECT / "tools" / "voice_acting" / "reference_import_manifest.json"
    )
    overrides = generator.load_omnivoice_overrides(generator.DEFAULT_OVERRIDES)

    refs = build_reference_jobs(
        designs,
        PROJECT / "u6_voice" / "omnivoice_refs",
        u7,
        overrides,
    )
    clones = build_clone_jobs(
        PROJECT / "u6_voice" / "manifests" / "u6_qwen3_mapping.json",
        designs,
        PROJECT / "u6_voice" / "omnivoice_refs",
        PROJECT / "u6_voice" / "omnivoice",
        u7,
        overrides,
    )

    aaron_refs = [job for job in refs if job.design_id == "u6_aaron_324a17d2"]
    aaron_clones = [job for job in clones if job.design_id == "u6_aaron_324a17d2"]
    assert {job.instruct for job in aaron_refs} == {
        "male, moderate pitch, American accent",
        "男, 中音调",
    }
    assert aaron_refs and all(job.override_revision == "u6-omnivoice-overrides-v1" for job in aaron_refs)
    assert aaron_clones and all(job.override_revision == "u6-omnivoice-overrides-v1" for job in aaron_clones)


@pytest.mark.parametrize("design_id", ["u6_amanda_161b5245", "u6_budo_4b6e65fd"])
def test_u7_owned_design_jobs_are_not_affected_by_manifest_design_entry(design_id):
    designs = _designs()
    u7 = load_reference_overrides(
        PROJECT / "tools" / "voice_acting" / "reference_import_manifest.json"
    )
    overrides = generator.load_omnivoice_overrides(generator.DEFAULT_OVERRIDES)
    assert design_id in overrides.voice_design

    refs = build_reference_jobs(
        designs,
        PROJECT / "u6_voice" / "omnivoice_refs",
        u7,
        overrides,
    )
    clones = build_clone_jobs(
        PROJECT / "u6_voice" / "manifests" / "u6_qwen3_mapping.json",
        designs,
        PROJECT / "u6_voice" / "omnivoice_refs",
        PROJECT / "u6_voice" / "omnivoice",
        u7,
        overrides,
    )

    owned_refs = [job for job in refs if job.design_id == design_id]
    owned_clones = [job for job in clones if job.design_id == design_id]
    assert owned_refs and all(job.source == "u7" and job.override_revision is None for job in owned_refs)
    assert owned_clones and all(job.override_revision is None for job in owned_clones)


def test_affected_job_metadata_and_completion_require_current_revision(tmp_path, monkeypatch):
    job = CloneJob(
        design_id="snake",
        npc="Snakecharmer",
        lang="zh",
        text="馴蛇者",
        ref_audio=tmp_path / "ref.ogg",
        ref_text="參考",
        output=tmp_path / "line.ogg",
        func_id="04c1",
        offset_key="447",
        segment=0,
        tts_text="XUN4蛇者",
        override_revision="u6-omnivoice-overrides-v1",
    )
    monkeypatch.setattr(
        generator,
        "_write_ogg_atomic",
        lambda path, audio, sample_rate: path.write_bytes(b"ogg"),
    )
    args = type("Args", (), {"model": "test-model", "gpu": 0})()

    generator._publish_clone(job, [0.1, 0.2], 2, 123, args)
    metadata = json.loads(job.output.with_suffix(".json").read_text(encoding="utf-8"))

    assert metadata["text"] == "馴蛇者"
    assert metadata["tts_text"] == "XUN4蛇者"
    assert metadata["override_revision"] == "u6-omnivoice-overrides-v1"
    assert generator._complete(job.output, job)

    metadata["override_revision"] = "stale-revision"
    job.output.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
    )
    assert not generator._complete(job.output, job)


def test_unaffected_jobs_keep_legacy_completion_compatibility(tmp_path):
    audio = tmp_path / "line.ogg"
    audio.write_bytes(b"ogg")
    audio.with_suffix(".json").write_text(
        json.dumps(
            {
                "status": "generated",
                "duration_seconds": 1.0,
                "design_id": "plain",
                "lang": "en",
                "text": "Hello",
            }
        ),
        encoding="utf-8",
    )
    job = CloneJob(
        design_id="plain",
        npc="Plain",
        lang="en",
        text="Hello",
        ref_audio=tmp_path / "ref.ogg",
        ref_text="Reference",
        output=audio,
        func_id="1",
        offset_key="2",
        segment=0,
        tts_text="Hello",
    )

    assert generator._complete(audio, job)


def test_removed_override_rejects_metadata_with_old_revision(tmp_path):
    audio = tmp_path / "line.ogg"
    audio.write_bytes(b"ogg")
    audio.with_suffix(".json").write_text(
        json.dumps(
            {
                "status": "generated",
                "duration_seconds": 1.0,
                "design_id": "plain",
                "lang": "zh",
                "text": "原文",
                "tts_text": "OLD3原文",
                "override_revision": "old-revision",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    job = CloneJob(
        design_id="plain",
        npc="Plain",
        lang="zh",
        text="原文",
        ref_audio=tmp_path / "ref.ogg",
        ref_text="參考",
        output=audio,
        func_id="1",
        offset_key="2",
        segment=0,
        tts_text="原文",
    )

    assert not generator._complete(audio, job)


def test_reference_records_mark_stale_affected_audio_missing(tmp_path):
    audio = tmp_path / "ref.ogg"
    audio.write_bytes(b"ogg")
    audio.with_suffix(".json").write_text(
        json.dumps(
            {
                "status": "generated",
                "duration_seconds": 1.0,
                "design_id": "u6_aaron_324a17d2",
                "lang": "en",
                "text": "Hello",
                "tts_text": "Hello",
                "override_revision": "old-revision",
            }
        ),
        encoding="utf-8",
    )
    job = ReferenceJob(
        design_id="u6_aaron_324a17d2",
        npc="Aaron",
        lang="en",
        text="Hello",
        instruct="male, moderate pitch, American accent",
        output=audio,
        source="omnivoice_design",
        ref_audio=None,
        ref_text="Hello",
        tts_text="Hello",
        override_revision="u6-omnivoice-overrides-v1",
    )

    assert generator._reference_records([job])[0]["status"] == "missing"


@pytest.mark.parametrize(
    ("audio_exists", "metadata_revision", "expected_status"),
    [
        (True, "u6-omnivoice-overrides-v1", "generated"),
        (True, "old-revision", "missing"),
        (False, "u6-omnivoice-overrides-v1", "missing"),
    ],
)
def test_manifest_clone_status_uses_revision_aware_completion(
    tmp_path,
    audio_exists,
    metadata_revision,
    expected_status,
):
    audio = tmp_path / "line.ogg"
    if audio_exists:
        audio.write_bytes(b"ogg")
    audio.with_suffix(".json").write_text(
        json.dumps(
            {
                "status": "generated",
                "duration_seconds": 1.0,
                "design_id": "snake",
                "lang": "zh",
                "text": "馴蛇者",
                "tts_text": "XUN4蛇者",
                "override_revision": metadata_revision,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    job = CloneJob(
        design_id="snake",
        npc="Snakecharmer",
        lang="zh",
        text="馴蛇者",
        ref_audio=tmp_path / "ref.ogg",
        ref_text="參考",
        output=audio,
        func_id="04c1",
        offset_key="447",
        segment=0,
        tts_text="XUN4蛇者",
        override_revision="u6-omnivoice-overrides-v1",
    )
    manifest_path = tmp_path / "manifest.json"
    args = type(
        "Args",
        (),
        {
            "model": "test-model",
            "manifest_path": manifest_path,
            "reference_review_dir": tmp_path / "reference_review",
        },
    )()

    generator.write_manifest(args, [], [job])
    record = json.loads(manifest_path.read_text(encoding="utf-8"))["clone_records"][0]

    assert record["status"] == expected_status
    assert record["text"] == "馴蛇者"
    assert record["tts_text"] == "XUN4蛇者"
    assert record["override_revision"] == "u6-omnivoice-overrides-v1"


def test_job_seed_changes_with_tts_text_and_override_revision(tmp_path):
    base = dict(
        design_id="snake",
        npc="Snakecharmer",
        lang="zh",
        text="馴蛇者",
        ref_audio=tmp_path / "ref.ogg",
        ref_text="參考",
        output=tmp_path / "line.ogg",
        func_id="04c1",
        offset_key="447",
        segment=0,
    )

    old = CloneJob(**base, tts_text="馴蛇者")
    tts_changed = CloneJob(**base, tts_text="XUN4蛇者")
    revision_changed = CloneJob(
        **base,
        tts_text="XUN4蛇者",
        override_revision="u6-omnivoice-overrides-v1",
    )

    assert generator._job_seed(old) != generator._job_seed(tts_changed)
    assert generator._job_seed(tts_changed) != generator._job_seed(revision_changed)


def test_job_seed_preserves_legacy_payload_and_routes_reference_hash(tmp_path):
    base = dict(
        design_id="snake",
        npc="Snakecharmer",
        lang="zh",
        text="馴蛇者",
        ref_audio=tmp_path / "ref.ogg",
        ref_text="參考",
        output=tmp_path / "line.ogg",
        func_id="04c1",
        offset_key="447",
        segment=0,
        tts_text="馴蛇者",
    )
    job = CloneJob(**base)

    historical_routing_identity = json.dumps({
        "reference_role": None,
        "reference_revision": None,
        "voice_parts": [],
        "avatar_gender": None,
        "variant": None,
    }, ensure_ascii=False, sort_keys=True)
    historical_seed = generator.stable_seed(
        job.design_id,
        job.npc,
        job.lang,
        job.text,
        generator._job_tts_text(job),
        job.override_revision or "",
        historical_routing_identity,
        job.output,
    )

    assert generator._job_seed(job) == historical_seed

    routed_a = CloneJob(
        **base,
        reference_role="speaker",
        reference_revision=generator.ROUTED_REFERENCE_REVISION,
        reference_sha256="a" * 64,
    )
    routed_b = CloneJob(
        **base,
        reference_role="speaker",
        reference_revision=generator.ROUTED_REFERENCE_REVISION,
        reference_sha256="b" * 64,
    )

    assert generator._job_seed(routed_a) != generator._job_seed(routed_b)


def test_omnivoice_generation_uses_tts_text_without_changing_source(tmp_path, monkeypatch):
    class Model:
        sampling_rate = 24000

        def generate(self, **kwargs):
            self.text = kwargs["text"]
            return [[0.1]]

    job = ReferenceJob(
        design_id="snake",
        npc="Snakecharmer",
        lang="zh",
        text="馴蛇者",
        instruct="男, 中音调",
        output=tmp_path / "ref.ogg",
        source="omnivoice_design",
        ref_audio=None,
        ref_text="馴蛇者",
        tts_text="XUN4蛇者",
        override_revision="u6-omnivoice-overrides-v1",
    )
    model = Model()
    monkeypatch.setitem(sys.modules, "torch", object())
    monkeypatch.setattr(generator, "_seed_torch", lambda seed: None)

    generator._audio_batch_from_model(model, [job])

    assert model.text == ["XUN4蛇者"]
    assert job.text == "馴蛇者"


def test_default_overrides_path_points_to_revisioned_manifest():
    assert generator.DEFAULT_OVERRIDES == (
        PROJECT / "u6_voice" / "manifests" / "omnivoice_overrides.json"
    )


def _selection_clone(tmp_path, design_id, npc, output_name, revision=None):
    return CloneJob(
        design_id=design_id,
        npc=npc,
        lang="en",
        text=f"{npc} line",
        ref_audio=tmp_path / "ref.ogg",
        ref_text="Reference",
        output=tmp_path / "omnivoice" / "en" / output_name,
        func_id="0401",
        offset_key=output_name.split("_")[1],
        segment=0,
        tts_text=f"{npc} line",
        override_revision=revision,
    )


def _write_selection_metadata(job, revision=None):
    job.output.parent.mkdir(parents=True, exist_ok=True)
    job.output.write_bytes(b"ogg")
    metadata = {
        "status": "generated",
        "duration_seconds": 1.0,
        "design_id": job.design_id,
        "lang": job.lang,
        "text": job.text,
    }
    if job.override_revision is not None:
        metadata.update({
            "tts_text": job.tts_text,
            "override_revision": revision,
        })
    job.output.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
    )


def test_target_selection_matches_npc_design_or_output_key(tmp_path):
    arty = _selection_clone(tmp_path, "u6_arty", "Arty", "arty_1_0.ogg")
    iolo = _selection_clone(tmp_path, "u6_iolo", "Iolo", "iolo_2_0.ogg")
    snake = _selection_clone(tmp_path, "u6_snake", "Snakecharmer", "snake_3_0.ogg")

    selected = select_target_jobs(
        [arty, iolo, snake],
        npcs=["iolo"],
        design_ids=["u6_arty"],
        output_keys=["en/snake_3_0.ogg"],
        lang="en",
    )

    assert selected == [arty, iolo, snake]


def test_stale_only_preserves_current_completed_jobs(tmp_path):
    stale = _selection_clone(
        tmp_path,
        "changed-design",
        "Arty",
        "stale_1_0.ogg",
        revision="current-revision",
    )
    complete = _selection_clone(
        tmp_path,
        "changed-design",
        "Arty",
        "complete_2_0.ogg",
        revision="current-revision",
    )
    unaffected = _selection_clone(tmp_path, "plain", "Iolo", "plain_3_0.ogg")
    _write_selection_metadata(stale, revision="old-revision")
    _write_selection_metadata(complete, revision="current-revision")
    _write_selection_metadata(unaffected)

    selected = select_target_jobs(
        [stale, complete, unaffected],
        design_ids=["changed-design"],
        stale_only=True,
        lang="en",
    )

    assert selected == [stale]
    assert select_target_jobs(
        [stale, complete, unaffected],
        design_ids=["changed-design"],
        lang="en",
    ) == [stale, complete]


def test_parse_args_accepts_repeatable_target_selectors(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_omnivoice_u6.py",
            "--npc-id",
            "Arty",
            "--npc-id",
            "Iolo",
            "--design-id",
            "u6_arty",
            "--output-key",
            "en/arty_1_0.ogg",
            "--stale-only",
            "--dry-run",
        ],
    )

    args = parse_args()

    assert args.target_npcs == ["Arty", "Iolo"]
    assert args.target_design_ids == ["u6_arty"]
    assert args.target_output_keys == ["en/arty_1_0.ogg"]
    assert args.stale_only is True
    assert args.dry_run is True


def test_dry_run_reports_target_counts_without_loading_model(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_omnivoice_u6.py",
            "--phase",
            "all",
            "--lang",
            "en",
            "--design-id",
            "u6_arty_762c615c",
            "--dry-run",
        ],
    )
    monkeypatch.setattr(
        generator,
        "load_model",
        lambda *_args, **_kwargs: pytest.fail("dry-run must not load OmniVoice"),
    )

    assert generator.main() == 0
    output = capsys.readouterr().out
    assert "Target references: 1 matched" in output
    assert "Target clones:" in output


def test_stage_u7_special_references_copies_verified_families_idempotently(tmp_path):
    source_refs = tmp_path / "voice_refs"
    destination_refs = tmp_path / "u6_refs"
    source_refs.mkdir()
    source_manifest = json.loads(generator.DEFAULT_U7_MANIFEST.read_text(encoding="utf-8"))
    special_ids = {
        "npc_avatar_female",
        "npc_avatar_male",
        "npc_unknown",
        "npc_narrator_male",
    }
    items = []
    for item in source_manifest["items"]:
        if item["design_id"] not in special_ids:
            continue
        payload = f"{item['destination']} source".encode("utf-8")
        (source_refs / item["destination"]).write_bytes(payload)
        item = dict(item)
        # The import manifest records the pre-sanitization candidate hash;
        # staging verifies and carries the current checked-in source clip hash.
        item["sha256"] = "pre-sanitization-candidate-hash"
        items.append(item)
    manifest = tmp_path / "references.json"
    manifest.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")

    staged = generator.stage_u7_special_references(manifest, source_refs, destination_refs)
    before = {path.name: path.stat().st_mtime_ns for path in destination_refs.iterdir()}
    staged_again = generator.stage_u7_special_references(manifest, source_refs, destination_refs)

    assert len(staged) == 8
    assert staged_again == staged
    assert {path.name for path in destination_refs.iterdir()} == {
        item["destination"] for item in items
    }
    assert {path.name: path.stat().st_mtime_ns for path in destination_refs.iterdir()} == before
    for item in items:
        lang = "en" if item["language"] == "English" else "zh"
        route = staged[(item["design_id"], lang)]
        source = source_refs / item["destination"]
        destination = destination_refs / item["destination"]
        assert route["path"] == destination
        assert route["source"] == source
        assert route["reference_id"] == item["design_id"]
        assert route["ref_text"] == item["reference_text"]
        assert route["sha256"] == generator.sha256_file(source)
        assert generator.sha256_file(destination) == route["sha256"]


def test_build_clone_jobs_routes_parts_and_expands_avatar_variants(tmp_path):
    refs = tmp_path / "refs"
    output = tmp_path / "output"
    refs.mkdir()
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {"npc": "Ada", "en_text": "Hello", "en_func_id": "0401", "en_offset_key": "0", "en_segment": 0},
                {"npc": "Ada", "en_text": "She waves.", "en_func_id": "0401", "en_offset_key": "1", "en_segment": 0},
                {"npc": "Ada", "en_text": "Hello then goodbye", "en_func_id": "0401", "en_offset_key": "2", "en_segment": 0},
                {"npc": "Budo", "en_text": "U7 hello", "en_func_id": "0401", "en_offset_key": "3", "en_segment": 0},
                {"npc": "Avatar", "en_text": "Avatar hello", "en_func_id": "0401", "en_offset_key": "4", "en_segment": 0},
                {"npc": "Ada", "en_text": "Hey old buddy", "en_func_id": "0401", "en_offset_key": "5", "en_segment": 0},
                {"npc": "Ada", "en_text": "Good again", "en_func_id": "0401", "en_offset_key": "6", "en_segment": 0},
            ]
        ),
        encoding="utf-8",
    )
    role_manifest = tmp_path / "roles.jsonl"
    role_manifest.write_text(
        "\n".join(
            json.dumps({
                "function_id": "0401", "offset_key": offset, "segment": 0,
                "source_en": source_en, "text_zh": "",
            })
            for offset, source_en in (
                ("0", "@Hello@"),
                ("1", "She waves."),
                ("2", "@Hello@ She waves. @Goodbye@"),
                ("3", "@U7 hello@"),
                ("4", "@Avatar hello@ He waves."),
                ("5", "@Hey old buddy "),
                ("6", "! Good again.@"),
            )
        ),
        encoding="utf-8",
    )
    roles = load_role_manifest(role_manifest)
    designs = {
        "u6_ada": {
            "npc": "Ada",
            "ref_en_text": "Ada reference",
            "casting_inference": {"gender": "female"},
        },
        "u6_budo": {
            "npc": "Budo",
            "ref_en_text": "Budo design reference",
            "casting_inference": {"gender": "male"},
        },
    }
    special = {
        ("npc_avatar_female", "en"): {"path": refs / "npc_avatar_female_en_ref.ogg", "ref_text": "Female Avatar", "reference_id": "npc_avatar_female", "sha256": "avatar-f"},
        ("npc_avatar_male", "en"): {"path": refs / "npc_avatar_male_en_ref.ogg", "ref_text": "Male Avatar", "reference_id": "npc_avatar_male", "sha256": "avatar-m"},
        ("npc_unknown", "en"): {"path": refs / "npc_unknown_en_ref.ogg", "ref_text": "Female narrator", "reference_id": "npc_unknown", "sha256": "narrator-f"},
        ("npc_narrator_male", "en"): {"path": refs / "npc_narrator_male_en_ref.ogg", "ref_text": "Male narrator", "reference_id": "npc_narrator_male", "sha256": "narrator-m"},
    }
    u7_budo = tmp_path / "u7_budo.ogg"
    overrides = {("budo", "en"): {"path": u7_budo, "ref_text": "Exact U7 Budo", "design_id": "npc_budo", "sha256": "u7-budo"}}

    jobs = build_clone_jobs(
        mapping, designs, refs, output, overrides,
        role_sources=roles, reference_routes=special,
    )
    by_offset = {job.offset_key: job for job in jobs if job.npc != "Avatar"}
    speaker = by_offset["0"]
    narrator = by_offset["1"]
    mixed = by_offset["2"]
    u7 = by_offset["3"]
    placeholder_open = by_offset["5"]
    placeholder_close = by_offset["6"]
    avatars = [job for job in jobs if job.npc == "Avatar"]

    assert speaker.ref_audio == refs / "u6_ada_en_ref.ogg"
    assert speaker.reference_role == "speaker"
    assert speaker.voice_parts == ()
    assert narrator.ref_audio == refs / "npc_unknown_en_ref.ogg"
    assert narrator.reference_role == "narrator_female"
    assert narrator.voice_parts == ()
    assert [(part.role, part.text, part.reference_id) for part in mixed.voice_parts] == [
        ("speaker", "Hello", "u6_ada"),
        ("narrator", "She waves.", "npc_unknown"),
        ("speaker", "Goodbye", "u6_ada"),
    ]
    assert u7.ref_audio == u7_budo
    assert u7.ref_text == "Exact U7 Budo"
    assert placeholder_open.reference_role == "speaker"
    assert placeholder_open.ref_audio == refs / "u6_ada_en_ref.ogg"
    assert placeholder_close.reference_role == "speaker"
    assert placeholder_close.ref_audio == refs / "u6_ada_en_ref.ogg"
    assert len(avatars) == 2
    assert {job.design_id for job in avatars} == {"npc_avatar_male", "npc_avatar_female"}
    assert {job.output.name for job in avatars} == {
        "0401_4_0_avatar_male.ogg",
        "0401_4_0_avatar_female.ogg",
    }
    for job in avatars:
        gender = job.avatar_gender
        assert job.func_id == "0401" and job.offset_key == "4" and job.segment == 0
        assert [(part.reference_id, part.role) for part in job.voice_parts] == [
            (f"npc_avatar_{gender}", "speaker"),
            ("npc_narrator_male" if gender == "male" else "npc_unknown", "narrator"),
        ]
        assert job.reference_revision.startswith(generator.ROUTED_REFERENCE_REVISION + ":")


def test_avatar_explicit_output_filename_keeps_its_authoritative_stem():
    assert generator._avatar_filename(
        {"en_output_filename": "0401_4_0_custom.ogg"}, "en", "male"
    ) == "0401_4_0_custom_avatar_male.ogg"


def test_routed_clone_manifest_and_completion_serialize_route_metadata(tmp_path):
    speaker_reference = tmp_path / "ada.ogg"
    narrator_reference = tmp_path / "narrator.ogg"
    speaker_reference.write_bytes(b"Ada reference")
    narrator_reference.write_bytes(b"Narrator reference")
    job = CloneJob(
        design_id="u6_ada",
        npc="Ada",
        lang="en",
        text="Hello then goodbye",
        ref_audio=speaker_reference,
        ref_text="Ada reference",
        output=tmp_path / "line.ogg",
        func_id="0401",
        offset_key="2",
        segment=0,
        reference_role="mixed",
        reference_revision=generator.ROUTED_REFERENCE_REVISION,
        reference_sha256=generator.sha256_file(speaker_reference),
        voice_parts=(
            generator.VoicePart(
                "speaker", "Hello", speaker_reference, "Ada reference", "u6_ada",
                generator.sha256_file(speaker_reference),
            ),
            generator.VoicePart(
                "narrator", "She waves.", narrator_reference, "Narrator", "npc_unknown",
                generator.sha256_file(narrator_reference),
            ),
        ),
    )
    job.output.write_bytes(b"ogg")
    metadata = {
        **generator._completion_expected(job),
        "duration_seconds": 1.0,
    }
    job.output.with_suffix(".json").write_text(json.dumps(metadata), encoding="utf-8")
    args = type("Args", (), {"model": "test", "manifest_path": tmp_path / "manifest.json", "reference_review_dir": tmp_path / "review"})()

    generator.write_manifest(args, [], [job])
    record = json.loads(args.manifest_path.read_text(encoding="utf-8"))["clone_records"][0]

    assert generator._complete(job.output, job)
    assert record["reference_revision"] == generator.ROUTED_REFERENCE_REVISION
    assert record["reference_sha256"] == generator.sha256_file(speaker_reference)
    assert metadata["reference_sha256"] == generator.sha256_file(speaker_reference)
    assert record["voice_parts"][1] == {
        "role": "narrator",
        "text": "She waves.",
        "reference_path": str(narrator_reference),
        "reference_text": "Narrator",
        "reference_id": "npc_unknown",
        "reference_sha256": generator.sha256_file(narrator_reference),
    }


def test_manifest_uses_published_actual_route_hashes_after_reference_replacement(tmp_path, monkeypatch):
    speaker_reference = tmp_path / "speaker.ogg"
    narrator_reference = tmp_path / "narrator.ogg"
    speaker_reference.write_bytes(b"old speaker")
    narrator_reference.write_bytes(b"old narrator")
    job = CloneJob(
        design_id="u6_ada", npc="Ada", lang="en", text="Hello then goodbye",
        ref_audio=speaker_reference, ref_text="Ada reference", output=tmp_path / "line.ogg",
        func_id="0401", offset_key="2", segment=0,
        reference_role="mixed", reference_revision=generator.ROUTED_REFERENCE_REVISION,
        reference_sha256=generator.sha256_file(speaker_reference),
        voice_parts=(
            generator.VoicePart("speaker", "Hello", speaker_reference, "Ada reference", "u6_ada", generator.sha256_file(speaker_reference)),
            generator.VoicePart("narrator", "She waves.", narrator_reference, "Narrator", "npc_unknown", generator.sha256_file(narrator_reference)),
        ),
    )
    speaker_reference.write_bytes(b"replacement speaker")
    narrator_reference.write_bytes(b"replacement narrator")
    monkeypatch.setattr(generator, "_write_ogg_atomic", lambda path, _audio, _rate: path.write_bytes(b"ogg"))
    publish_args = type("Args", (), {"model": "test", "gpu": 0})()
    manifest_args = type("Args", (), {
        "model": "test", "manifest_path": tmp_path / "manifest.json",
        "reference_review_dir": tmp_path / "review",
    })()

    generator._publish_clone(job, [0.1, 0.2], 2, 123, publish_args)
    generator.write_manifest(manifest_args, [], [job])

    sidecar = json.loads(job.output.with_suffix(".json").read_text(encoding="utf-8"))
    record = json.loads(manifest_args.manifest_path.read_text(encoding="utf-8"))["clone_records"][0]
    assert record["reference_sha256"] == sidecar["reference_sha256"] == generator.sha256_file(speaker_reference)
    assert record["voice_parts"] == sidecar["voice_parts"]


def test_mixed_renderer_uses_each_part_reference_caches_prompts_and_splices_in_order(tmp_path, monkeypatch):
    class Model:
        sampling_rate = 1000

        def __init__(self):
            self.prompt_calls = []
            self.generate_prompts = []

        def create_voice_clone_prompt(self, *, ref_audio, ref_text):
            self.prompt_calls.append((Path(ref_audio).name, ref_text))
            return f"prompt:{Path(ref_audio).name}:{ref_text}"

        def generate(self, *, voice_clone_prompt, **_kwargs):
            self.generate_prompts.append(voice_clone_prompt)
            value = 1.0 if "speaker.ogg" in voice_clone_prompt else 2.0
            return [np.full(4, value, dtype=np.float32)]

    speaker = tmp_path / "speaker.ogg"
    narrator = tmp_path / "narrator.ogg"
    speaker.write_bytes(b"speaker")
    narrator.write_bytes(b"narrator")
    job = CloneJob(
        design_id="u6_ada", npc="Ada", lang="en", text="whole line",
        ref_audio=speaker, ref_text="Ada reference", output=tmp_path / "line.ogg",
        func_id="0401", offset_key="2", segment=0,
        reference_role="mixed", reference_revision=generator.ROUTED_REFERENCE_REVISION,
        voice_parts=(
            generator.VoicePart("speaker", "Hello", speaker, "Ada reference", "u6_ada"),
            generator.VoicePart("narrator", "She waves.", narrator, "Narrator reference", "npc_unknown"),
            generator.VoicePart("speaker", "Goodbye", speaker, "Ada reference", "u6_ada"),
        ),
    )
    seeded = []
    monkeypatch.setattr(generator, "_seed_torch", seeded.append)

    audio, sample_rate, seed, rendered_parts = generator._render_mixed_clone(Model(), job, {})

    assert sample_rate == 1000
    assert seed == generator._job_seed(job)
    assert rendered_parts == ("Hello", "She waves.", "Goodbye")
    assert len(seeded) == 3 and len(set(seeded)) == 3
    assert np.allclose(audio, [1, 1, 1, 0, 0, 2, 2, 0, 0, 1, 1, 1])

    model = Model()
    generator._render_mixed_clone(model, job, {})
    assert model.prompt_calls == [
        ("speaker.ogg", "Ada reference"),
        ("narrator.ogg", "Narrator reference"),
    ]
    assert model.generate_prompts == [
        "prompt:speaker.ogg:Ada reference",
        "prompt:narrator.ogg:Narrator reference",
        "prompt:speaker.ogg:Ada reference",
    ]


def test_process_voice_keeps_single_reference_jobs_on_batch_path(tmp_path, monkeypatch):
    class Model:
        sampling_rate = 1000

        def __init__(self):
            self.generate_calls = []

        def create_voice_clone_prompt(self, **_kwargs):
            return "single-prompt"

        def generate(self, **kwargs):
            self.generate_calls.append(kwargs)
            return [np.array([1.0], dtype=np.float32)]

    reference = tmp_path / "speaker.ogg"
    reference.write_bytes(b"speaker")
    job = CloneJob(
        design_id="u6_ada", npc="Ada", lang="en", text="Hello",
        ref_audio=reference, ref_text="Ada reference", output=tmp_path / "line.ogg",
        func_id="0401", offset_key="0", segment=0,
    )
    model = Model()
    published = []
    args = type("Args", (), {
        "lang": "both", "worker_index": 0, "worker_count": 1, "batch_size": 4,
        "gpu": 0, "model": "fake", "last_review": float("inf"), "review_interval": float("inf"),
        "output_dir": tmp_path, "mapping": tmp_path / "mapping.json", "review_dir": tmp_path / "review",
    })()
    monkeypatch.setitem(sys.modules, "torch", object())
    monkeypatch.setattr(generator, "_seed_torch", lambda _seed: None)
    monkeypatch.setattr(generator, "load_model", lambda *_args: model)
    monkeypatch.setattr(generator, "_publish_clone", lambda *values: published.append(values))
    monkeypatch.setattr(generator, "write_clone_review", lambda *_args: None)
    monkeypatch.setattr(generator, "_render_mixed_clone", lambda *_args: pytest.fail("single job must not use mixed renderer"))

    generator.process_voice(args, [job])

    assert model.generate_calls[0]["text"] == ["Hello"]
    assert model.generate_calls[0]["voice_clone_prompt"] == ["single-prompt"]
    assert len(published) == 1


def test_routed_reference_hash_change_invalidates_completed_clone(tmp_path):
    refs = tmp_path / "refs"
    refs.mkdir()
    reference = refs / "u6_ada_en_ref.ogg"
    reference.write_bytes(b"first reference")
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps([
        {"npc": "Ada", "en_text": "Hello", "en_func_id": "0401", "en_offset_key": "0", "en_segment": 0}
    ]), encoding="utf-8")
    roles = {
        role_key("0401", "0", "0"): {"source_en": "@Hello@", "text_zh": ""}
    }
    designs = {"u6_ada": {"npc": "Ada", "ref_en_text": "Ada reference"}}

    first = build_clone_jobs(
        mapping, designs, refs, tmp_path / "out", {}, role_sources=roles, reference_routes={}
    )[0]
    first.output.parent.mkdir(parents=True)
    first.output.write_bytes(b"clone")
    first.output.with_suffix(".json").write_text(json.dumps({
        **generator._completion_expected(first), "duration_seconds": 1.0,
    }), encoding="utf-8")
    reference.write_bytes(b"replacement reference")
    replacement = build_clone_jobs(
        mapping, designs, refs, tmp_path / "out", {}, role_sources=roles, reference_routes={}
    )[0]

    assert first.reference_sha256 != replacement.reference_sha256
    assert first.reference_revision != replacement.reference_revision
    assert generator._job_seed(first) != generator._job_seed(replacement)
    assert not generator._complete(first.output, replacement)
