from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.u6_translation.catalog import CatalogEntry, load_catalog, write_catalog
from tools.u6_translation.runtime_table import RuntimeRow, load_runtime_table, write_runtime_table
from tools.u6_translation.speaker_map import load_speaker_capture, speaker_map_from_capture
from tools.u6_translation.voice_manifest import (
    VoiceManifestRow,
    build_voice_rows,
    load_voice_assignments,
    normalize_tts_text,
    parse_voice_key,
    voice_filename,
    voice_key_collisions,
    write_generation_manifests,
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

    def test_duplicate_voice_keys_are_reported_when_english_hashes_match(self) -> None:
        rows = [
            row_with(
                text_zh="一",
                tts_zh="一",
                speaker="Iolo",
            ),
            row_with(
                text_zh="壹",
                tts_zh="壹",
                speaker="Dupre",
            ),
        ]

        collisions = voice_key_collisions(rows)

        self.assertEqual(
            collisions,
            [
                {
                    "key": "dialogue:0x0401:1a:0",
                    "source_sha256": [rows[0].source_sha256],
                    "row_count": 2,
                }
            ],
        )


class VoiceManifestMergeTests(unittest.TestCase):
    def _fixtures(self, directory: Path) -> tuple[list[CatalogEntry], list[RuntimeRow], dict[str, str], object]:
        entry = CatalogEntry.from_source(
            "dialogue", "dialogue:0x0401:1a_2f:0", "Hello <PLAYER_NAME>", "gameplay", "test"
        )
        catalog_path = directory / "catalog.jsonl"
        write_catalog(catalog_path, [entry])
        translations_path = directory / "translations.tsv"
        write_runtime_table(
            translations_path,
            [RuntimeRow(entry.kind, entry.key, entry.source_sha256, "你好，<PLAYER_NAME>")],
        )
        speakers_path = directory / "speakers.tsv"
        speakers_path.write_text(
            "dialogue\tdialogue:0x0401:1a_2f:0\t1\tIolo\n", encoding="utf-8"
        )
        assignments_path = directory / "assignments.csv"
        assignments_path.write_text(
            "speaker,speaker_id,en_voice_id,zh_voice_id,voice_desc,status\n"
            "Iolo,1,en-test-voice,zh-test-voice,test voice,approved\n",
            encoding="utf-8",
        )
        return (
            load_catalog(catalog_path),
            load_runtime_table(translations_path),
            speaker_map_from_capture(load_speaker_capture(speakers_path)),
            load_voice_assignments(assignments_path),
        )

    def test_build_voice_rows_joins_all_u6_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog, translations, speakers, assignments = self._fixtures(Path(directory))
            rows = build_voice_rows(catalog, translations, speakers, assignments)

        self.assertEqual(rows[0].key, "dialogue:0x0401:1a_2f:0")
        self.assertEqual(rows[0].source_en, "Hello <PLAYER_NAME>")
        self.assertEqual(rows[0].text_zh, "你好，<PLAYER_NAME>")
        self.assertEqual(rows[0].speaker, "Iolo")
        self.assertEqual(rows[0].voice_id_en, "en-test-voice")
        self.assertEqual(rows[0].voice_id_zh, "zh-test-voice")
        self.assertEqual(rows[0].status, "approved")

    def test_missing_translation_and_ambiguous_speaker_are_review_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog, _translations, _speakers, assignments = self._fixtures(Path(directory))
            ambiguous_speakers = {catalog[0].key: "Ambiguous · Dupre / Shamino"}
            rows = build_voice_rows(catalog, [], ambiguous_speakers, assignments)

        self.assertEqual(rows[0].status, "needs-review")
        self.assertIn("translation", rows[0].skip_reason)
        self.assertIn("speaker", rows[0].skip_reason)


class VoiceManifestOutputTests(unittest.TestCase):
    def test_generation_manifests_share_approved_filenames_and_keep_review_rows_jsonl(self) -> None:
        approved = row_with(
            key="dialogue:0x0401:1a_2f:0",
            offset_key="1a_2f",
            source_en="Hello <PLAYER_NAME>",
            text_zh="你好，<PLAYER_NAME>",
            tts_en="Hello Avatar",
            tts_zh="你好，你",
            voice_id_en="en-test-voice",
            voice_id_zh="zh-test-voice",
        )
        review = row_with(
            key="dialogue:0x0401:1a_2f:1",
            offset_key="1a_2f",
            segment=1,
            status="needs-review",
            skip_reason="translation",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_generation_manifests(output, [approved, review])
            with (output / "en_manifest.csv").open(encoding="utf-8", newline="") as handle:
                english = list(csv.DictReader(handle))
            with (output / "zh_manifest.csv").open(encoding="utf-8", newline="") as handle:
                chinese = list(csv.DictReader(handle))
            full_rows = [json.loads(line) for line in (output / "u6_voice_manifest.jsonl").read_text(encoding="utf-8").splitlines()]

        header = [
            "filename", "func_id", "offset_key", "segment", "speaker", "speaker_source", "npc_num",
            "voice_id", "voice_desc", "prev_text", "next_text", "text",
        ]
        self.assertEqual(list(english[0]), header)
        self.assertEqual(list(chinese[0]), header)
        self.assertEqual([row["filename"] for row in english], ["0401_1a_2f_0.ogg"])
        self.assertEqual([row["filename"] for row in chinese], ["0401_1a_2f_0.ogg"])
        self.assertEqual(english[0]["voice_id"], "en-test-voice")
        self.assertEqual(chinese[0]["voice_id"], "zh-test-voice")
        self.assertEqual(english[0]["text"], "Hello Avatar")
        self.assertEqual(chinese[0]["text"], "你好，你")
        self.assertEqual(len(full_rows), 2)


if __name__ == "__main__":
    unittest.main()
