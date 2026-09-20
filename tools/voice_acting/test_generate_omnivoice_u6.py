import importlib
import json
import sys
from pathlib import Path

import pytest

import tools.voice_acting.generate_omnivoice_u6 as generator
from tools.voice_acting.generate_omnivoice_u6 import (
    CloneJob,
    ReferenceJob,
    build_clone_jobs,
    build_reference_jobs,
    chunked,
    fallback_texts,
    omnivoice_instruction,
    load_reference_overrides,
    parse_args,
    select_target_jobs,
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
