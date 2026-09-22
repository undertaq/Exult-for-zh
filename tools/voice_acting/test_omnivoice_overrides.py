import importlib
import json
from pathlib import Path

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


def test_project_manifest_covers_context_sensitive_zh_readings():
    module = _overrides_module()
    project_root = Path(__file__).resolve().parents[2]
    overrides = module.load_omnivoice_overrides(
        project_root / "u6_voice/manifests/omnivoice_overrides.json"
    )

    expected = {
        "馴蛇師": "XUN4蛇師",
        "偽裝": "WEI4裝",
        "偽預言者": "WEI4預言者",
        "虛偽": "虛WEI4",
        "一位優雅的銀髮女子": "一位優雅的銀FA4女子",
        "乾草": "GAN1草",
        "餅乾": "餅GAN1",
        "長久": "CHANG2久",
        "長袍": "CHANG2袍",
        "調整": "TIAO2整",
        "調校": "TIAO2校",
        "調查": "調查",
        "音樂": "音YUE4",
        "樂意": "樂意",
        "處理": "CHU3理",
        "此處": "此處",
        "幾乎": "JI1乎",
        "幾個": "幾個",
        "災難": "災NAN4",
        "難以": "難以",
        "答應": "答YING4",
        "應該": "應該",
        "還給": "HUAN2給",
        "還是": "還是",
        "種植": "ZHONG4植",
        "種族": "種族",
        "結實": "JIE1實",
        "運轉": "運ZHUAN4",
        "轉身": "轉身",
        "睡覺": "睡JIAO4",
        "彷彿": "FANG3彿",
        "繃帶": "BENG1帶",
        "強迫": "QIANG3迫",
        "裁縫": "裁FENG2",
        "憑藉": "憑JIE4",
        "記載": "記ZAI3",
        "彈琴": "TAN2琴",
        "籠罩": "LONG3罩",
        "數不清": "SHU3不清",
        "可惡": "可WU4",
        "成為": "成WEI2",
        "盡快": "JIN3快",
        "重啟": "CHONG2啟",
        "冠軍": "GUAN4軍",
        "銀行": "銀HANG2",
        "恰當": "恰DANG4",
        "寶藏": "寶ZANG4",
        "藏身": "CANG2身",
        "角色": "JUE2色",
        "率領": "SHUAI4領",
        "數人數": "SHU3人SHU4",
        "「..對對對..」": "DUI4 DUI4 DUI4",
        "長睫毛": "CHANG2睫毛",
        "長凳": "CHANG2凳",
        "長長的": "CHANG2 CHANG2的",
        "長兩倍": "CHANG2兩倍",
        "太長": "太CHANG2",
        "售價為": "售價WEI2",
        "價格為": "價格WEI2",
        "發音為": "發音WEI2",
        "設定為": "設定WEI2",
        "設置為": "設置WEI2",
        "替換為": "替換WEI2",
        "變更為": "變更WEI2",
        "轉化為": "轉化WEI2",
        "轉變為": "轉變WEI2",
        "名為": "名WEI2",
        "稱我為": "稱我WEI2",
        "被列為": "被列WEI2",
        "身為": "身WEI2",
        "廣為": "廣WEI2",
        "更為": "更WEI2",
        "最為": "最WEI2",
        "譯為": "譯WEI2",
        "為證": "WEI2證",
        "為所欲為": "WEI2所欲WEI2",
        "故事為": "故事WEI2",
        "盡了責": "JIN4了責",
        "受盡": "受JIN4",
        "盡你所能": "JIN4你所能",
        "懂行": "懂HANG2",
        "長大": "長大",
        "為你": "為你",
        "因為": "因為",
        "為了": "為了",
    }

    for source, tts in expected.items():
        assert overrides.tts_text(source, "zh") == tts, source
        assert overrides.tts_text(source, "en") == source, source
