from __future__ import annotations

import hashlib
import unittest

from tools.u6_translation.voice_manifest import (
    VoiceManifestRow,
    normalize_tts_text,
    parse_voice_key,
    voice_filename,
    voice_key_collisions,
)


def row_with(**changes: object) -> VoiceManifestRow:
    values = {
        "key": "dialogue:0x0401:1a:0",
        "function_id": 0x0401,
        "offset_key": "1a",
        "segment": 0,
        "source_en": "one",
        "source_sha256": hashlib.sha256(b"one").hexdigest(),
        "text_zh": "一",
        "tts_en": "one",
        "tts_zh": "一",
        "speaker_id": 1,
        "speaker": "Iolo",
        "voice_id_en": "en-iolo",
        "voice_id_zh": "zh-iolo",
        "voice_desc": "Iolo",
        "status": "approved",
        "skip_reason": "",
    }
    values.update(changes)
    if "source_sha256" not in changes and "source_en" in changes:
        values["source_sha256"] = hashlib.sha256(
            str(values["source_en"]).encode("utf-8")
        ).hexdigest()
    return VoiceManifestRow(**values)


class VoiceManifestKeyTests(unittest.TestCase):
    def test_parse_runtime_dialogue_key_and_emit_one_shared_filename(self) -> None:
        function_id, offset_key, segment = parse_voice_key(
            "dialogue:0x0401:1a_2f:3"
        )
        self.assertEqual((function_id, offset_key, segment), (0x0401, "1a_2f", 3))
        self.assertEqual(
            voice_filename(function_id, offset_key, segment),
            "0401_1a_2f_3.ogg",
        )

    def test_reject_non_dialogue_translation_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "dialogue key"):
            parse_voice_key("choice:0x0401:0x0088:0")


class VoiceManifestTtsTests(unittest.TestCase):
    def test_normalize_tts_text_uses_stable_language_placeholders(self) -> None:
        self.assertEqual(
            normalize_tts_text("@Hello <PLAYER_NAME>!@", "en"),
            "Hello Avatar!",
        )
        self.assertEqual(
            normalize_tts_text("@你好，<PLAYER_NAME>！@", "zh"),
            "你好，你！",
        )

    def test_unresolved_placeholder_is_reported_not_synthesized(self) -> None:
        with self.assertRaisesRegex(ValueError, "unresolved placeholder"):
            normalize_tts_text("Hello <VAR0>", "en")

    def test_duplicate_voice_keys_are_reported_before_generation(self) -> None:
        rows = [
            row_with(key="dialogue:0x0401:1a:0", source_en="one"),
            row_with(key="dialogue:0x0401:1a:0", source_en="two"),
        ]
        collisions = voice_key_collisions(rows)
        self.assertEqual(len(collisions), 1)
        self.assertEqual(collisions[0]["key"], "dialogue:0x0401:1a:0")
        self.assertEqual(
            collisions[0]["source_sha256"],
            sorted(row.source_sha256 for row in rows),
        )


if __name__ == "__main__":
    unittest.main()
