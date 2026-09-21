from tools.voice_acting.generate_u6_avatar_manifest import build_avatar_entries


def _runtime(key, source, digest="digest"):
    return {
        "key": key,
        "source_en": source,
        "source_sha256": digest,
    }


def _translation(key, text, digest="digest"):
    return {
        "key": key,
        "source_sha256": digest,
        "text_zh": text,
    }


def test_build_avatar_entries_preserves_runtime_source_and_normalizes_tts_text():
    key = "dialogue:0x038a:476:0"
    rows = build_avatar_entries(
        [
            {
                "func_id": "0x038A",
                "offset_key": "0x476",
                "segment": "0",
                "speaker": "Avatar",
                "text": "ignored static spelling",
            }
        ],
        {key: _runtime(key, "@Runtime source@*")},
        {key: _translation(key, "@執行時翻譯@*")},
    )

    assert rows == [
        {
            "npc": "Avatar",
            "en_func_id": "038a",
            "en_offset_key": "476",
            "en_segment": 0,
            "en_text": "Runtime source",
            "en_voice_desc": "Avatar",
            "en_output_filename": "038a_476_0.ogg",
            "zh_func_id": "038a",
            "zh_offset_key": "476",
            "zh_segment": 0,
            "zh_text": "執行時翻譯",
            "zh_voice_desc": "Avatar",
            "zh_output_filename": "038a_476_0.ogg",
        }
    ]


def test_build_avatar_entries_skips_unresolved_missing_and_duplicate_keys():
    duplicate_key = "dialogue:0x0401:10:0"
    unresolved_key = "dialogue:0x0401:11:0"
    missing_key = "dialogue:0x0401:12:0"
    rows = build_avatar_entries(
        [
            {"func_id": "0401", "offset_key": "10", "segment": 0, "speaker": "Avatar"},
            {"func_id": "0401", "offset_key": "10", "segment": 0, "speaker": "Avatar"},
            {"func_id": "0401", "offset_key": "11", "segment": 0, "speaker": "Avatar"},
            {"func_id": "0401", "offset_key": "12", "segment": 0, "speaker": "Avatar"},
        ],
        {
            duplicate_key: _runtime(duplicate_key, "@one@"),
            unresolved_key: _runtime(unresolved_key, "<VAR>"),
        },
        {
            duplicate_key: _translation(duplicate_key, "@一@"),
            unresolved_key: _translation(unresolved_key, "@變數@"),
        },
    )

    assert [row["en_offset_key"] for row in rows] == ["10"]
