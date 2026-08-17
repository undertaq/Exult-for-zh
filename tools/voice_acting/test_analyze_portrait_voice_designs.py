#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("analyze_portrait_voice_designs.py")


def load_script_module():
    spec = importlib.util.spec_from_file_location("analyze_portrait_voice_designs_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AnalyzePortraitVoiceDesignsTest(unittest.TestCase):
    def test_portrait_index_matches_u7_suffix_case_insensitively(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            portraits = Path(tmpdir)
            (portraits / "IoloU7.png").write_bytes(b"portrait")
            (portraits / "ShaminoU7.PNG").write_bytes(b"portrait")
            (portraits / "BritishU7.PNG").write_bytes(b"portrait")
            (portraits / "FranktheFoxU7.png").write_bytes(b"portrait")

            index = module.build_portrait_index(portraits)

            self.assertEqual(index["iolo"].name, "IoloU7.png")
            self.assertEqual(index["shamino"].name, "ShaminoU7.PNG")
            self.assertEqual(module.find_portrait_for_name("Lord British", index).name, "BritishU7.PNG")
            self.assertEqual(module.find_portrait_for_name("Frank", index).name, "FranktheFoxU7.png")

    def test_parse_model_json_accepts_markdown_fenced_response(self):
        module = load_script_module()

        parsed = module.parse_model_json(
            """```json
            {"apparent_age": "elderly", "voice_desc_en": "Warm, steady bard voice"}
            ```"""
        )

        self.assertEqual(parsed["apparent_age"], "elderly")
        self.assertEqual(parsed["voice_desc_en"], "Warm, steady bard voice")

    def test_build_updated_descriptions_preserves_existing_character_context(self):
        module = load_script_module()
        design = {
            "npc": "Iolo",
            "voice_desc_en": "Male, elderly, warm and friendly companion",
            "voice_desc_zh": "男性，年長，熱情友善，用標準的普通話朗讀",
        }
        analysis = {
            "apparent_age": "elderly",
            "gender_presentation": "male",
            "visual_traits": "white hair, full beard, leaf crown, blue robe",
            "voice_desc_en": "Deep, gravelly, warm, and authoritative",
        }

        en, zh = module.build_updated_descriptions(design, analysis)

        self.assertIn("Deep, gravelly, warm, and authoritative", en)
        self.assertIn("Male, elderly, warm and friendly companion", en)
        self.assertNotIn("portrait", en.lower())
        self.assertIn("男性", zh)
        self.assertIn("年長", zh)
        self.assertIn("用標準的普通話朗讀", zh)
        self.assertIn("低沉有質感", zh)
        self.assertIn("角色音色細節", zh)
        self.assertIn("Deep, gravelly, warm, and authoritative", zh)
        self.assertIn("speaking pace:", en)
        self.assertIn("pitch:", en)
        self.assertIn("語速", zh)
        self.assertIn("音高", zh)

    def test_build_updated_descriptions_uses_chinese_gender_age_for_female_actor(self):
        module = load_script_module()
        design = {
            "npc": "actor_entertainer_female",
            "voice_desc_en": "Female, middle-aged theatrical performer",
            "voice_desc_zh": "女性，中年，戲劇表演者，用標準的普通話朗讀",
            "ref_en_text": "This lovely actress is dressed in a mouse costume.",
        }
        analysis = {
            "apparent_age": "mid-40s",
            "gender_presentation": "Female",
            "visual_traits": "festive costume",
            "voice_desc_en": "Warm, playful, and theatrical",
        }

        _, zh = module.build_updated_descriptions(design, analysis)

        self.assertIn("女性", zh)
        self.assertIn("中年", zh)
        self.assertIn("溫暖", zh)
        self.assertIn("語速偏快", zh)
        self.assertIn("音高偏高", zh)

    def test_build_updated_descriptions_preserves_explicit_male_actor_gender(self):
        module = load_script_module()
        design = {
            "npc": "Jesse",
            "voice_desc_en": "Male, 20s-30s, tall thin actor, theatrical voice, doing female roles",
            "voice_desc_zh": "男性，20-30歲，活潑有戲劇感，用標準的普通話朗讀",
            "ref_en_text": "This actor is memorizing lines for a female part.",
        }
        analysis = {
            "apparent_age": "20s-30s",
            "gender_presentation": "male",
            "visual_traits": "thin performer in costume",
            "voice_desc_en": "Theatrical, agile, expressive stage voice",
        }

        _, zh = module.build_updated_descriptions(design, analysis)

        self.assertIn("男性", zh)
        self.assertNotIn("女性", zh)
        self.assertIn("20-30歲", zh)

    def test_build_updated_descriptions_keeps_child_age_before_young(self):
        module = load_script_module()
        design = {
            "npc": "child_female",
            "voice_desc_en": "Female, child, innocent little girl voice",
            "voice_desc_zh": "女性，小孩，活潑有戲劇感，用標準的普通話朗讀",
        }
        analysis = {
            "apparent_age": "5-7 years old",
            "gender_presentation": "female",
            "visual_traits": "bright eyes",
            "voice_desc_en": "A young girl with a playful and curious tone",
        }

        _, zh = module.build_updated_descriptions(design, analysis)

        self.assertIn("女性", zh)
        self.assertIn("小孩", zh)

    def test_build_updated_descriptions_preserves_creature_identity(self):
        module = load_script_module()
        design = {
            "npc": "Hydra",
            "voice_desc_en": (
                "Deep, gravelly, authoritative tone; retain character context: "
                "Creature, three-headed hydra, deep rumbling growling monster voice"
            ),
            "voice_desc_zh": "生物，成年，低沉有質感，用標準的普通話朗讀",
        }
        analysis = {
            "apparent_age": "mid-thirties",
            "gender_presentation": "masculine",
            "visual_traits": "three heads",
            "voice_desc_en": "Deep, gravelly, authoritative tone",
        }

        _, zh = module.build_updated_descriptions(design, analysis)

        self.assertIn("生物", zh)
        self.assertNotIn("男性", zh)
        self.assertIn("中年", zh)

    def test_update_design_from_analysis_records_metadata(self):
        module = load_script_module()
        designs = {
            "_meta": {},
            "designs": {
                "npc_iolo": {
                    "npc": "Iolo",
                    "type": "unique",
                    "npcs": ["Iolo"],
                    "voice_desc_en": "old en",
                    "voice_desc_zh": "old zh，用標準的普通話朗讀",
                }
            },
        }

        changed = module.apply_analysis(
            designs,
            "npc_iolo",
            Path("IoloU7.png"),
            {"voice_desc_en": "Warm bard voice", "visual_traits": "white beard"},
            model="qwen2.5vl:7b",
        )

        self.assertTrue(changed)
        design = designs["designs"]["npc_iolo"]
        self.assertIn("Warm bard voice", design["voice_desc_en"])
        self.assertEqual(design["_portrait_voice_analysis"]["model"], "qwen2.5vl:7b")
        self.assertEqual(design["_portrait_voice_analysis"]["portrait"], "IoloU7.png")

    def test_select_portraits_for_group_returns_all_member_portraits(self):
        module = load_script_module()

        index = {
            "amber": Path("Amber.gif"),
            "judith": Path("Judith.gif"),
            "meryl": Path("Meryl.PNG"),
        }
        design = {"npcs": ["Amber", "Judith", "Meryl"]}

        portraits = module.select_portraits_for_design(design, index)

        self.assertEqual([p.name for p in portraits], ["Amber.gif", "Judith.gif", "Meryl.PNG"])


if __name__ == "__main__":
    unittest.main()
