#!/usr/bin/env python3
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = SCRIPT_DIR / "sync_mapping_voice_prompts.py"


def load_module():
    spec = importlib.util.spec_from_file_location("sync_mapping_voice_prompts", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def designs_fixture():
    return {
        "designs": {
            "npc_iolo": {
                "npc": "Iolo",
                "npcs": ["Iolo"],
                "voice_desc_en": "Warm old male bard.",
                "voice_desc_zh": "溫暖的年老男性吟遊詩人。",
            },
            "npc_avatar_male": {
                "npc": "Avatar male",
                "npcs": ["Avatar male"],
                "voice_desc_en": "Heroic male avatar.",
                "voice_desc_zh": "英勇的男性聖者。",
            },
            "npc_unknown": {
                "npc": "UNKNOWN",
                "npcs": ["UNKNOWN"],
                "voice_desc_en": "Neutral narrator.",
                "voice_desc_zh": "中立的旁白者。",
            },
        }
    }


class SyncMappingVoicePromptsTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_build_map_resolves_ordinary_npc(self):
        prompt_map = self.module.build_npc_to_prompt_map(designs_fixture())
        self.assertEqual(prompt_map["Iolo"], ("Warm old male bard.", "溫暖的年老男性吟遊詩人。"))

    def test_special_routing(self):
        prompt_map = self.module.build_npc_to_prompt_map(designs_fixture())
        self.assertEqual(prompt_map["Avatar"], ("Heroic male avatar.", "英勇的男性聖者。"))
        self.assertEqual(prompt_map[""], ("Neutral narrator.", "中立的旁白者。"))
        self.assertEqual(prompt_map["UNKNOWN"], ("Neutral narrator.", "中立的旁白者。"))

    def test_sync_row_changes_only_two_fields(self):
        prompt_map = self.module.build_npc_to_prompt_map(designs_fixture())
        row = {
            "npc": "Iolo",
            "voice_prompt": "OLD EN",
            "zh_text": "已翻譯",
            "en_text": "Translated",
            "en_func_id": "0x009A",
        }
        before = copy.deepcopy(row)
        changed_en, changed_zh = self.module.sync_row(row, prompt_map)
        self.assertTrue(changed_en)
        self.assertTrue(changed_zh)
        self.assertEqual(row["voice_prompt"], "Warm old male bard.")
        self.assertEqual(row["voice_prompt_zh"], "溫暖的年老男性吟遊詩人。")
        # Only the two prompt fields differ.
        stripped = {k: v for k, v in row.items() if k not in ("voice_prompt", "voice_prompt_zh")}
        self.assertEqual(stripped, {k: v for k, v in before.items() if k not in ("voice_prompt",)})

    def test_sync_row_leaves_unresolved_untouched(self):
        prompt_map = self.module.build_npc_to_prompt_map(designs_fixture())
        row = {"npc": "Ghost", "voice_prompt": "X"}
        changed_en, changed_zh = self.module.sync_row(row, prompt_map)
        self.assertFalse(changed_en)
        self.assertFalse(changed_zh)
        self.assertEqual(row["voice_prompt"], "X")

    def test_sync_mapping_counts(self):
        prompt_map = self.module.build_npc_to_prompt_map(designs_fixture())
        mapping = [
            {"npc": "Iolo", "voice_prompt": "old"},
            {
                "npc": "Iolo",
                "voice_prompt": "Warm old male bard.",
                "voice_prompt_zh": "溫暖的年老男性吟遊詩人。",
            },  # already synced
            {"npc": "Ghost"},  # unresolved
        ]
        counts = self.module.sync_mapping(mapping, prompt_map)
        self.assertEqual(counts["changed_en"], 1)
        self.assertEqual(counts["unchanged"], 1)
        self.assertEqual(counts["unresolved"], 1)
        self.assertEqual(mapping[0]["voice_prompt_zh"], "溫暖的年老男性吟遊詩人。")
        self.assertNotIn("voice_prompt_zh", mapping[2])

    def test_dry_run_writes_nothing(self):
        module = self.module
        with tempfile.TemporaryDirectory() as td:
            mapping_path = Path(td) / "mapping.json"
            designs_path = Path(td) / "designs.json"
            mapping_path.write_text(
                json.dumps([{"npc": "Iolo", "voice_prompt": "old"}]), encoding="utf-8"
            )
            designs_path.write_text(json.dumps(designs_fixture()), encoding="utf-8")
            rc = module.main(["--mapping", str(mapping_path), "--designs", str(designs_path), "--dry-run"])
            self.assertEqual(rc, 0)
            # File unchanged on disk.
            self.assertEqual(json.loads(mapping_path.read_text())[0]["voice_prompt"], "old")


if __name__ == "__main__":
    unittest.main()
