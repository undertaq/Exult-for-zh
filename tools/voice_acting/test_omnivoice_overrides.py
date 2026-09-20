import importlib
import json

import pytest


def _overrides_module():
    try:
        return importlib.import_module("tools.voice_acting.omnivoice_overrides")
    except ModuleNotFoundError:
        pytest.fail("OmniVoice override loader is not implemented")


def _write_manifest(tmp_path, *, voice_design=None, pronunciation=None):
    path = tmp_path / "overrides.json"
    path.write_text(
        json.dumps(
            {
                "revision": "test-revision",
                "voice_design": voice_design or {},
                "pronunciation": pronunciation or [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _rule(**updates):
    rule = {
        "lang": "zh",
        "source": "馴蛇者",
        "tts": "XUN4蛇者",
        "expected_pinyin": "xùn shé zhě",
        "reason": "Taiwan Mandarin reading in this phrase",
    }
    rule.update(updates)
    return rule


def test_exact_phrase_replacement_preserves_source_and_ignores_wrong_language(tmp_path):
    module = _overrides_module()
    overrides = module.load_omnivoice_overrides(
        _write_manifest(tmp_path, pronunciation=[_rule()])
    )
    source = "萬歲，馴蛇者！"

    assert overrides.tts_text(source, "zh") == "萬歲，XUN4蛇者！"
    assert overrides.tts_text(source, "en") == source
    assert source == "萬歲，馴蛇者！"


@pytest.mark.parametrize(
    ("pronunciation", "message"),
    [
        ([_rule(), _rule(tts="XUN2蛇者")], "duplicate"),
        ([_rule(), _rule(source="馴蛇", tts="XUN4蛇")], "overlap"),
        ([_rule(tts="XUN蛇者")], "tone"),
        ([_rule(tts="JIA3甲0")], "tone"),
        ([_rule(tts="JIA3甲-4")], "tone"),
        ([_rule(lang="")], "lang"),
        ([_rule(expected_pinyin="")], "expected_pinyin"),
    ],
)
def test_invalid_pronunciation_rules_are_rejected(tmp_path, pronunciation, message):
    module = _overrides_module()

    with pytest.raises(ValueError, match=message):
        module.load_omnivoice_overrides(
            _write_manifest(tmp_path, pronunciation=pronunciation)
        )


def test_voice_design_requires_both_language_values(tmp_path):
    module = _overrides_module()

    with pytest.raises(ValueError, match="zh"):
        module.load_omnivoice_overrides(
            _write_manifest(
                tmp_path,
                voice_design={"u6_arty_762c615c": {"en": "male, moderate pitch, American accent"}},
            )
        )


def test_valid_tone_controls_remain_accepted(tmp_path):
    module = _overrides_module()
    path = _write_manifest(
        tmp_path,
        pronunciation=[_rule(), _rule(source="偽先知", tts="WEI4先知")],
    )

    overrides = module.load_omnivoice_overrides(path)

    assert overrides.tts_text("馴蛇者與偽先知", "zh") == "XUN4蛇者與WEI4先知"
