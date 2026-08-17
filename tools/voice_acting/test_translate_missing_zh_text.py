import copy
import importlib
import unittest


module = importlib.import_module("tools.voice_acting.translate_missing_zh_text")


class TranslateMissingZhTextTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"index": 12, "en_text": "Already translated.", "zh_text": "已翻譯。", "tone": "neutral"},
            {"index": 83, "en_text": 'He says, "Missing."', "zh_text": "", "tone": "angry"},
            {"index": 91, "en_text": "", "zh_text": "", "tone": "neutral"},
            {"index": 95, "en_text": "Missing whitespace.", "zh_text": "   "},
            {"index": 143, "en_text": 'Dracothraxus sniffs the air distastefully, "Hello."', "zh_text": 'Dracothraxus sniffs the air distastefully, 「你好。」'},
            {"index": 2699, "en_text": "He hands you the helmet.", "zh_text": "He hands you the helmet."},
        ]

    def test_only_nonempty_english_with_empty_chinese_is_selected(self):
        selected = module.select_missing_rows(self.rows)
        self.assertEqual([row["index"] for row in selected], [83, 95, 143, 2699])

    def test_apply_changes_only_zh_text(self):
        before = copy.deepcopy(self.rows[1])
        after = module.apply_translations(self.rows, {83: "「譯文。」"})[1]
        self.assertEqual(after["zh_text"], "「譯文。」")
        self.assertEqual(
            {k: v for k, v in after.items() if k != "zh_text"},
            {k: v for k, v in before.items() if k != "zh_text"},
        )

    def test_validator_preserves_two_dialogue_spans(self):
        source = 'He says, "First." Then she says, "Second."'
        self.assertEqual(
            module.validate_translation(source, "他說：「第一句。」接著她說：「第二句。」"), []
        )
        self.assertIn(
            "dialogue span count",
            module.validate_translation(source, "他說第一句。"),
        )

    def test_validator_rejects_lost_placeholder(self):
        errors = module.validate_translation("Welcome, <PLAYER_NAME>.", "歡迎你。")
        self.assertIn("placeholder", " ".join(errors))

    def test_validator_rejects_unbalanced_corner_quotes(self):
        errors = module.validate_translation('He says, "Hello."', "他說：「你好。")
        self.assertIn("unbalanced", " ".join(errors))

    def test_prompt_is_json_only_and_contains_rows(self):
        prompt = module.build_translation_prompt(
            [{"index": 83, "en_text": 'He says, "Missing."'}]
        )
        self.assertEqual(prompt["options"]["temperature"], 0)
        self.assertEqual(prompt["format"], "json")
        text = " ".join(message["content"] for message in prompt["messages"])
        self.assertIn('"index": 83', text)
        self.assertIn("Traditional Chinese", text)

    def test_cache_key_changes_with_source(self):
        first = module.translation_cache_key("qwen3.6:35b", "one")
        second = module.translation_cache_key("qwen3.6:35b", "two")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
