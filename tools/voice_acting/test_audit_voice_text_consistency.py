#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("audit_voice_text_consistency.py")


def load_script_module():
    spec = importlib.util.spec_from_file_location("audit_voice_text_consistency_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuditVoiceTextConsistencyTest(unittest.TestCase):
    def test_normalize_text_removes_punctuation_and_case(self):
        module = load_script_module()

        self.assertEqual(module.normalize_text("Hello, Avatar!"), "hello avatar")
        self.assertEqual(module.normalize_text("「你好，阿凡達！」"), "你好阿凡達")

    def test_character_error_rate_scores_identical_text_as_zero(self):
        module = load_script_module()

        self.assertEqual(module.character_error_rate("hello", "hello"), 0.0)

    def test_evaluate_transcript_marks_matching_text_pass(self):
        module = load_script_module()

        result = module.evaluate_transcript(
            expected="Thou must see for thyself, Joe.",
            transcript="thou must see for thyself joe",
            lang="en",
            pass_threshold=0.18,
        )

        self.assertEqual(result["audit_status"], "pass")
        self.assertLess(result["cer"], 0.18)

    def test_evaluate_transcript_marks_mismatched_text_failed(self):
        module = load_script_module()

        result = module.evaluate_transcript(
            expected="只有在那時，我才會允許你借用筆記本。",
            transcript="我離開 Britannia 大陸，來到 New Magincia。",
            lang="zh",
            pass_threshold=0.18,
        )

        self.assertEqual(result["audit_status"], "failed")
        self.assertGreater(result["cer"], 0.18)


if __name__ == "__main__":
    unittest.main()
