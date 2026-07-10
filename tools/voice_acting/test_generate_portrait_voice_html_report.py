#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("generate_portrait_voice_html_report.py")


def load_script_module():
    spec = importlib.util.spec_from_file_location("generate_portrait_voice_html_report_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GeneratePortraitVoiceHtmlReportTest(unittest.TestCase):
    def test_build_report_html_includes_portrait_prompt_and_previous_prompt(self):
        module = load_script_module()
        designs = {
            "designs": {
                "npc_iolo": {
                    "npc": "Iolo",
                    "type": "unique",
                    "npcs": ["Iolo"],
                    "voice_desc_en": "Warm, elderly male voice",
                    "voice_desc_zh": "Warm, elderly male voice，用標準的普通話朗讀",
                    "ref_en_text": "Welcome to Trinsic!",
                    "_portrait_voice_analysis": {
                        "portrait": "IoloU7.png",
                        "previous_voice_desc_en": "Old bard prompt",
                        "model": "qwen2.5vl:7b",
                    },
                }
            }
        }
        report = {
            "processed": [
                {
                    "design_id": "npc_iolo",
                    "analysis": {"voice_desc_en": "Vision prompt"},
                }
            ]
        }

        html = module.build_html(designs, report)

        self.assertIn("IoloU7.png", html)
        self.assertIn("Warm, elderly male voice", html)
        self.assertIn("Old bard prompt", html)
        self.assertIn("voice_casting_tool/data/portraits/IoloU7.png", html)
        self.assertIn("qwen2.5vl:7b", html)
        self.assertIn("<audio controls", html)
        self.assertIn("../../voice/refs/npc_iolo_en_ref.ogg", html)

    def test_write_report_creates_html_file(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "report.html"
            module.write_report({"designs": {}}, {"processed": []}, out)

            self.assertTrue(out.exists())
            self.assertIn("<!doctype html>", out.read_text(encoding="utf-8"))

    def test_ref_status_includes_existing_file_size_and_missing_state(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            refs = Path(tmpdir)
            (refs / "npc_iolo_en_ref.ogg").write_bytes(b"12345")

            status = module.ref_status_html("npc_iolo", refs_dir=refs)

            self.assertIn("EN ref", status)
            self.assertIn("5 B", status)
            self.assertIn("ZH missing", status)

    def test_report_matches_portrait_for_design_without_vision_metadata(self):
        module = load_script_module()
        designs = {
            "designs": {
                "npc_iolo": {
                    "npc": "Iolo",
                    "type": "unique",
                    "npcs": ["Iolo"],
                    "voice_desc_en": "Warm voice",
                }
            }
        }

        html = module.build_html(designs, {"processed": []}, portrait_index={"iolo": Path("IoloU7.png")})

        self.assertIn("voice_casting_tool/data/portraits/IoloU7.png", html)
        self.assertIn("Not analyzed yet", html)
        self.assertIn("Warm voice", html)

    def test_report_matches_portrait_aliases(self):
        module = load_script_module()
        designs = {
            "designs": {
                "npc_lord_british": {
                    "npc": "Lord British",
                    "type": "unique",
                    "npcs": ["Lord British"],
                    "voice_desc_en": "Regal voice",
                },
                "npc_frank": {
                    "npc": "Frank",
                    "type": "unique",
                    "npcs": ["Frank"],
                    "voice_desc_en": "Fox voice",
                },
            }
        }

        html = module.build_html(
            designs,
            {"processed": []},
            portrait_index={
                "british": Path("BritishU7.PNG"),
                "frankthefox": Path("FranktheFoxU7.png"),
            },
        )

        self.assertIn("voice_casting_tool/data/portraits/BritishU7.PNG", html)
        self.assertIn("voice_casting_tool/data/portraits/FranktheFoxU7.png", html)

    def test_report_shows_all_group_member_portraits(self):
        module = load_script_module()
        designs = {
            "designs": {
                "group_actor_entertainer_female": {
                    "npc": "actor_entertainer_female",
                    "type": "group",
                    "npcs": ["Amber", "Judith", "Meryl"],
                    "voice_desc_en": "Female performers",
                },
            }
        }

        html = module.build_html(
            designs,
            {"processed": []},
            portrait_index={
                "amber": Path("Amber.gif"),
                "judith": Path("Judith.gif"),
                "meryl": Path("Meryl.PNG"),
            },
        )

        self.assertIn("voice_casting_tool/data/portraits/Amber.gif", html)
        self.assertIn("voice_casting_tool/data/portraits/Judith.gif", html)
        self.assertIn("voice_casting_tool/data/portraits/Meryl.PNG", html)

    def test_report_shows_all_analyzed_group_portraits_from_metadata(self):
        module = load_script_module()
        designs = {
            "designs": {
                "group_actor_entertainer_female": {
                    "npc": "actor_entertainer_female",
                    "type": "group",
                    "npcs": ["Amber", "Judith", "Meryl"],
                    "voice_desc_en": "Female performers",
                    "_portrait_voice_analysis": {
                        "portrait": "Amber.gif",
                        "portraits": ["Amber.gif", "Judith.gif", "Meryl.PNG"],
                    },
                },
            }
        }

        html = module.build_html(designs, {"processed": []}, portrait_index={})

        self.assertIn("voice_casting_tool/data/portraits/Amber.gif", html)
        self.assertIn("voice_casting_tool/data/portraits/Judith.gif", html)
        self.assertIn("voice_casting_tool/data/portraits/Meryl.PNG", html)


if __name__ == "__main__":
    unittest.main()
