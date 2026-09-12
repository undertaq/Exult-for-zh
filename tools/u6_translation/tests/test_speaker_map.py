from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools.u6_translation.speaker_map import (
    load_speaker_capture,
    speaker_map_from_capture,
)


class SpeakerMapTest(unittest.TestCase):
    def test_loads_escaped_runtime_rows_and_ignores_non_dialogue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "speakers.tsv"
            path.write_text(
                "# u6-runtime-speakers-v1\n"
                "# kind\tkey\tspeaker_id\tspeaker\n"
                "dialogue\tdialogue:0x0401:10:0\t1\tIolo\\t(the bard)\n"
                "choice\tchoice:0x0401:10:0\t1\tignored\n",
                encoding="utf-8",
            )

            rows = load_speaker_capture(path)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].speaker, "Iolo\t(the bard)")
        self.assertEqual(
            speaker_map_from_capture(rows),
            {"dialogue:0x0401:10:0": "Iolo\t(the bard)"},
        )

    def test_deduplicates_same_name_and_marks_conflicting_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "speakers.tsv"
            path.write_text(
                "dialogue\tdialogue:0x0401:10:0\t1\tIolo\n"
                "dialogue\tdialogue:0x0401:10:0\t1\tIolo\n"
                "dialogue\tdialogue:0x0401:10:1\t1\tDupre\n"
                "dialogue\tdialogue:0x0401:10:1\t2\tShamino\n",
                encoding="utf-8",
            )

            mapping = speaker_map_from_capture(load_speaker_capture(path))

        self.assertEqual(mapping["dialogue:0x0401:10:0"], "Iolo")
        self.assertEqual(
            mapping["dialogue:0x0401:10:1"],
            "Ambiguous · Dupre / Shamino",
        )

    def test_numeric_only_rows_remain_explicitly_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "speakers.tsv"
            path.write_text(
                "dialogue\tdialogue:0x0401:10:0\t17\t\n"
                "dialogue\tdialogue:0x0401:10:1\t17\t\n"
                "dialogue\tdialogue:0x0401:10:2\t17\t\n"
                "dialogue\tdialogue:0x0401:10:2\t18\t\n",
                encoding="utf-8",
            )

            mapping = speaker_map_from_capture(load_speaker_capture(path))

        self.assertEqual(mapping["dialogue:0x0401:10:0"], "Unresolved · NPC 17")
        self.assertEqual(
            mapping["dialogue:0x0401:10:2"],
            "Ambiguous · NPC 17 / NPC 18",
        )

    def test_rejects_bad_field_count_and_speaker_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "speakers.tsv"
            path.write_text("dialogue\tkey\tnot-an-id\tName\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "speaker_id"):
                load_speaker_capture(path)

            path.write_text("dialogue\tkey\t1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "expected 4 fields"):
                load_speaker_capture(path)


if __name__ == "__main__":
    unittest.main()
