#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("fix_dialogue_quote_balance.py")


def load_script_module():
    spec = importlib.util.spec_from_file_location("fix_dialogue_quote_balance_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FixDialogueQuoteBalanceTest(unittest.TestCase):
    def test_english_missing_right_quote_is_appended(self):
        module = load_script_module()

        fixed, action = module.fix_english_quotes('He says, "Hello.')

        self.assertEqual(fixed, 'He says, "Hello."')
        self.assertEqual(action, "append_english_quote")

    def test_english_missing_left_quote_is_prepended(self):
        module = load_script_module()

        fixed, action = module.fix_english_quotes('Hello."')

        self.assertEqual(fixed, '"Hello."')
        self.assertEqual(action, "prepend_english_quote")

    def test_chinese_missing_right_quote_is_appended(self):
        module = load_script_module()

        fixed, action = module.fix_chinese_corner_quotes("他說：「你好。")

        self.assertEqual(fixed, "他說：「你好。」")
        self.assertEqual(action, "append_chinese_quote")

    def test_chinese_missing_left_quote_is_prepended(self):
        module = load_script_module()

        fixed, action = module.fix_chinese_corner_quotes("你好。」")

        self.assertEqual(fixed, "「你好。」")
        self.assertEqual(action, "prepend_chinese_quote")

    def test_decodes_utf8_mojibake_text(self):
        module = load_script_module()

        self.assertEqual(module.decode_mojibake_utf8("ãä½ å¥½ã"), "「你好」")


if __name__ == "__main__":
    unittest.main()
