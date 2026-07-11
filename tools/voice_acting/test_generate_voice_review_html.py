#!/usr/bin/env python3
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("generate_voice_review_html.py")


def load_script_module():
    spec = importlib.util.spec_from_file_location("generate_voice_review_html_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GenerateVoiceReviewHtmlTest(unittest.TestCase):
    def test_build_html_includes_persistent_pass_fail_review_controls(self):
        module = load_script_module()

        html = module.build_html(
            "Review",
            {
                "title": "Review",
                "rows": [
                    {
                        "kind": "generated",
                        "status": "new",
                        "character": "Iolo",
                        "lang": "zh",
                        "filename": "0401_748_765_0_npc1.ogg",
                        "text": "測試台詞",
                        "audio": "../../voice/zh/0401_748_765_0_npc1.ogg",
                    }
                ],
            },
        )

        self.assertIn("Pass", html)
        self.assertIn("Failed", html)
        self.assertIn("voiceReviewState", html)
        self.assertIn("localStorage", html)
        self.assertIn("exportReviewState", html)
        self.assertIn("importReviewState", html)

    def test_write_report_assigns_stable_review_keys_to_rows(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            _, data_path = module.write_report(
                [
                    {
                        "kind": "generated",
                        "status": "new",
                        "character": "Iolo",
                        "lang": "zh",
                        "filename": "0401_748_765_0_npc1.ogg",
                        "text": "測試台詞",
                        "audio": "",
                    }
                ],
                out_dir,
                "Review",
            )

            data = data_path.read_text(encoding="utf-8")

        self.assertIn('"review_key": "zh:0401_748_765_0_npc1.ogg"', data)


if __name__ == "__main__":
    unittest.main()
