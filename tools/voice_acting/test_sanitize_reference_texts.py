#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("sanitize_reference_texts.py")


def load_script_module():
    spec = importlib.util.spec_from_file_location("sanitize_reference_texts_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SanitizeReferenceTextsTest(unittest.TestCase):
    def test_replaces_only_flagged_reference_text(self):
        module = load_script_module()
        payload = {
            "designs": {
                "npc_a": {
                    "npc": "A",
                    "type": "unique",
                    "ref_zh_text": "很長而且容易洩漏的原文",
                    "ref_en_text": "safe text",
                }
            }
        }
        findings = [{"design_id": "npc_a", "lang": "zh", "score": 8}]

        sanitized, changes = module.sanitize_designs_payload(payload, findings)

        self.assertEqual(len(changes), 1)
        self.assertNotEqual(sanitized["designs"]["npc_a"]["ref_zh_text"], payload["designs"]["npc_a"]["ref_zh_text"])
        self.assertEqual(sanitized["designs"]["npc_a"]["ref_en_text"], "safe text")

    def test_group_and_unique_use_different_neutral_text(self):
        module = load_script_module()

        unique = module.neutral_reference_text("en", {"type": "unique"})
        group = module.neutral_reference_text("en", {"type": "group"})

        self.assertNotEqual(unique, group)
        self.assertIn("voice", unique)
        self.assertIn("voice", group)


if __name__ == "__main__":
    unittest.main()
