#!/usr/bin/env python3
import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("fix_alignment_and_tags.py")


def load_script_module():
    spec = importlib.util.spec_from_file_location("fix_alignment_and_tags_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_csv(path, rows):
    fieldnames = [
        "func_id",
        "npc",
        "speaker",
        "caller_guess",
        "offset_key",
        "segment",
        "total_segments",
        "has_var",
        "text",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class FixAlignmentAndTagsTest(unittest.TestCase):
    def test_existing_review_voice_fields_survive_when_runtime_ids_are_canonicalized(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            en_csv = tmp / "en_voice_lines.csv"
            zh_csv = tmp / "zh_voice_lines.csv"
            input_json = tmp / "bilingual_mapping_review.json"
            output_json = tmp / "bilingual_mapping_fixed.json"

            en_raw = '"Thou must see for thyself, <PLAYER_NAME>. Brace thyself, my friend. \'Tis truly a horrible sight."'
            zh_raw = "「我覺得你最好親自去看看，<PLAYER_NAME>然後─要有點心理準備，那景象蠻可怕的。」"

            write_csv(
                en_csv,
                [
                    {
                        "func_id": "0x0401",
                        "npc": "Iolo",
                        "speaker": "Iolo",
                        "caller_guess": "",
                        "offset_key": "0x748_0x765",
                        "segment": "0",
                        "total_segments": "1",
                        "has_var": "True",
                        "text": en_raw,
                    }
                ],
            )
            write_csv(
                zh_csv,
                [
                    {
                        "func_id": "0x0401",
                        "npc": "",
                        "speaker": "Iolo",
                        "caller_guess": "",
                        "offset_key": "0x808_0x830",
                        "segment": "0",
                        "total_segments": "1",
                        "has_var": "True",
                        "text": zh_raw,
                    }
                ],
            )
            input_json.write_text(
                json.dumps(
                    [
                        {
                            "index": 263,
                            "npc": "Iolo",
                            "zh_offset_key": "808_830",
                            "zh_segment": 0,
                            "zh_text": "stale zh text",
                            "en_offset_key": "748_765",
                            "en_segment": 0,
                            "en_text": "stale en text",
                            "confidence": "high",
                            "voice_gender": "male",
                            "voice_age": "elderly",
                            "voice_prompt": "Male, elderly, warm companion",
                            "voice_lang": "en",
                            "tone": "questioning",
                            "tone_instruct": " Speak with curiosity.",
                            "zh_func_id": "0x08D8",
                            "en_func_id": "0x08D8",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            old_argv = sys.argv
            sys.argv = [
                "fix_alignment_and_tags.py",
                "--en",
                str(en_csv),
                "--zh",
                str(zh_csv),
                "-i",
                str(input_json),
                "-o",
                str(output_json),
            ]
            try:
                module.main()
            finally:
                sys.argv = old_argv

            [row] = json.loads(output_json.read_text(encoding="utf-8"))
            self.assertEqual(row["en_func_id"], "0x0401")
            self.assertEqual(row["zh_func_id"], "0x0401")
            self.assertEqual(row["en_offset_key"], "748_765")
            self.assertEqual(row["zh_offset_key"], "808_830")
            self.assertEqual(row["en_segment"], 0)
            self.assertEqual(row["zh_segment"], 0)
            self.assertEqual(row["voice_prompt"], "Male, elderly, warm companion")
            self.assertEqual(row["voice_gender"], "male")
            self.assertEqual(row["voice_age"], "elderly")
            self.assertEqual(
                row["en_text"],
                '"Thou must see for thyself, Avatar. Brace thyself, my friend. \'Tis truly a horrible sight."',
            )


if __name__ == "__main__":
    unittest.main()
