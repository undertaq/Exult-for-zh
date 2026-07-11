#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("audit_reference_leak_risk.py")


def load_script_module():
    spec = importlib.util.spec_from_file_location("audit_reference_leak_risk_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuditReferenceLeakRiskTest(unittest.TestCase):
    def test_scores_long_specific_reference_with_short_targets_as_high_risk(self):
        module = load_script_module()
        designs = {
            "npc_adjhar": {
                "npc": "Adjhar",
                "npcs": ["Adjhar"],
                "ref_zh_text": "「我們被……創造出來保護原則神殿。只有……聖者應該使用它們的力量。Adjhar 和我正在守衛。」",
            }
        }
        rows = [
            {"npc": "Adjhar", "zh_text": "「我把我的給他！」"},
            {"npc": "Adjhar", "zh_text": "「我們被……創造出來保護原則神殿。只有……聖者應該使用它們的力量。Adjhar 和我正在守衛。」"},
        ]

        findings = module.audit_reference_leak_risk(designs, rows, min_score=5)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["design_id"], "npc_adjhar")
        self.assertIn("specific_names", findings[0]["risk_terms"])
        self.assertGreaterEqual(findings[0]["score"], 5)

    def test_neutral_short_reference_is_not_flagged(self):
        module = load_script_module()
        designs = {
            "npc_adjhar": {
                "npc": "Adjhar",
                "npcs": ["Adjhar"],
                "ref_zh_text": "我是守護者。我會慢慢地說話，保持冷靜。",
            }
        }
        rows = [{"npc": "Adjhar", "zh_text": "「我把我的給他！」"}]

        findings = module.audit_reference_leak_risk(designs, rows, min_score=5)

        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
