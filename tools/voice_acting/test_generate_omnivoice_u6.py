import json
from pathlib import Path

import pytest

from tools.voice_acting.generate_omnivoice_u6 import (
    build_clone_jobs,
    build_reference_jobs,
    chunked,
    fallback_texts,
    omnivoice_instruction,
    load_reference_overrides,
)


PROJECT = Path(__file__).resolve().parents[2]


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
    assert omnivoice_instruction(design, "zh") == "女, 青年, 高音調"


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
    assert omnivoice_instruction(design, "zh") == "男, 中音調"


@pytest.mark.parametrize(
    ("design_id", "expected_en", "expected_zh"),
    [
        ("u6_aaron_324a17d2", "male, moderate pitch, American accent", "男, 中音調"),
        ("u6_amanda_161b5245", "female, moderate pitch, American accent", "女, 中音調"),
        ("u6_arty_762c615c", "male, moderate pitch, American accent", "男, 中音調"),
        ("u6_budo_4b6e65fd", "male, moderate pitch, American accent", "男, 中音調"),
        ("u6_dezana_6642c6a6", "female, moderate pitch, American accent", "女, 中音調"),
        ("u6_dunbar_d41e3d0c", "male, moderate pitch, American accent", "男, 中音調"),
        ("u6_kenneth_ca70c45c", "male, moderate pitch, American accent", "男, 中音調"),
        ("u6_leonna_c563a3bc", "female, moderate pitch, American accent", "女, 中音調"),
        ("u6_marney_b33f933c", "female, low pitch, American accent", "女, 低音調"),
        ("u6_sandy_e42e5767", "male, low pitch, American accent", "男, 低音調"),
        ("u6_shawn_66e52fa9", "male, moderate pitch, American accent", "男, 中音調"),
        ("u6_timothy_f787b4f6", "male, moderate pitch, American accent", "男, 中音調"),
        ("u6_trenton_bell_50adc94b", "male, moderate pitch, American accent", "男, 中音調"),
        ("u6_wilbur_63606e9b", "male, moderate pitch, American accent", "男, 中音調"),
        ("u6_zoltan_5aadd2f1", "male, moderate pitch, American accent", "男, 中音調"),
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
    ) == "男, 低音調"


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
    assert omnivoice_instruction(elderly, "zh") == "女, 老年, 低音調"
    assert omnivoice_instruction(non_human, "zh") == "極低音調"
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
    jobs = build_clone_jobs(
        PROJECT / "u6_voice" / "manifests" / "u6_qwen3_mapping.json",
        designs,
        PROJECT / "u6_voice" / "omnivoice_refs",
        PROJECT / "u6_voice" / "omnivoice",
        load_reference_overrides(
            PROJECT / "tools" / "voice_acting" / "reference_import_manifest.json"
        ),
    )

    assert sum(job.lang == "en" for job in jobs) == 10522
    assert sum(job.lang == "zh" for job in jobs) == 10489
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
