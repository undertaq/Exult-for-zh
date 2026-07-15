"""Tests for converting selected reference voices into individual designs."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.voice_acting import reference_voice_manifest as module


def grouped_design_fixture() -> dict:
    return {
        "_meta": {"version": 1, "total_npcs": 2, "group_count": 1},
        "designs": {
            "group_companions": {
                "npcs": ["Iolo", "Dupre"],
                "voice_desc_en": "Existing English group prompt.",
                "voice_desc_zh": "Existing Chinese group prompt.",
                "ref_en_text": "Existing English reference.",
                "ref_zh_text": "Existing Chinese reference.",
            }
        },
    }


def selection_fixture() -> dict:
    return {
        "selected": {
            "iolo": {
                "npc": "Iolo",
                "english_wav": "references/iolo/candidate_English_1.ogg",
                "english_index": 1,
                "chinese_wav": "references/iolo/candidate_Chinese_2.ogg",
                "chinese_index": 2,
            },
            "dupre": {
                "npc": "Dupre",
                "english_wav": "references/dupre/candidate_English_3.ogg",
                "english_index": 3,
                "chinese_wav": "references/dupre/candidate_Chinese_4.ogg",
                "chinese_index": 4,
            },
        }
    }


class ReferenceVoiceManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.bibles = self.root / "voice_bibles"
        self.refs = self.root / "artifacts"
        self.bibles.mkdir()
        self._write_bible("iolo", "Iolo English prompt.", "Iolo Chinese prompt.")
        self._write_bible("dupre", "Dupre English prompt.", "Dupre Chinese prompt.")
        self._write_candidate("iolo", "English", 1, "Iolo English reference.")
        self._write_candidate("iolo", "Chinese", 2, "Iolo Chinese reference.")
        self._write_candidate("dupre", "English", 3, "Dupre English reference.")
        self._write_candidate("dupre", "Chinese", 4, "Dupre Chinese reference.")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_bible(self, slug: str, english: str, chinese: str) -> None:
        (self.bibles / f"{slug}.json").write_text(
            json.dumps(
                {
                    "npc": slug.title(),
                    "voice_prompt_enriched": english,
                    "voice_prompt_enriched_zh": chinese,
                }
            ),
            encoding="utf-8",
        )

    def _write_candidate(self, slug: str, language: str, index: int, text: str) -> None:
        directory = self.refs / "references" / slug
        directory.mkdir(parents=True, exist_ok=True)
        audio = directory / f"candidate_{language}_{index}.ogg"
        audio.write_bytes(f"{slug}-{language}-{index}".encode())
        metadata = {
            "npc": slug.title(),
            "slug": slug,
            "index": index,
            "language": language,
            "sample_text": text,
            "instruct": f"{language} instruction",
            "seed": 100 + index,
            "model_revision": "test-model",
            "sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
        }
        audio.with_suffix(".json").write_text(json.dumps(metadata), encoding="utf-8")

    def test_design_ids_are_individual_and_special_ids_are_stable(self) -> None:
        self.assertEqual(module.design_id_for_selection("iolo"), "npc_iolo")
        self.assertEqual(module.design_id_for_selection("avatar_male"), "npc_avatar_male")
        self.assertEqual(module.design_id_for_selection("avatar_female"), "npc_avatar_female")
        self.assertEqual(module.design_id_for_selection("narrator_male"), "npc_narrator_male")
        self.assertEqual(module.design_id_for_selection("narrator_female"), "npc_unknown")

    def test_grouped_designs_expand_to_one_design_per_selected_npc(self) -> None:
        selection = module.load_selection_data(selection_fixture(), self.refs, self.bibles)
        result = module.build_individual_designs(
            grouped_design_fixture(), selection, self.bibles, self.refs
        )

        self.assertEqual(result["designs"]["npc_iolo"]["npcs"], ["Iolo"])
        self.assertEqual(result["designs"]["npc_dupre"]["npcs"], ["Dupre"])
        self.assertEqual(
            result["designs"]["npc_iolo"]["voice_desc_en"], "Iolo English prompt."
        )
        self.assertEqual(
            result["designs"]["npc_iolo"]["ref_zh_text"], "Iolo Chinese reference."
        )
        self.assertNotIn("group_companions", result["designs"])
        self.assertEqual(result["_meta"]["group_count"], 0)

    def test_selection_requires_complete_language_pair(self) -> None:
        selection = selection_fixture()
        del selection["selected"]["iolo"]["chinese_wav"]

        with self.assertRaisesRegex(module.ManifestError, "Chinese"):
            module.load_selection_data(selection, self.refs, self.bibles)

    def test_selection_rejects_duplicate_npc_names(self) -> None:
        selection = selection_fixture()
        selection["selected"]["dupre"]["npc"] = "Iolo"

        with self.assertRaisesRegex(module.ManifestError, "duplicate NPC"):
            module.load_selection_data(selection, self.refs, self.bibles)

    def test_selection_rejects_missing_candidate_metadata(self) -> None:
        (self.refs / "references/iolo/candidate_English_1.json").unlink()

        with self.assertRaisesRegex(module.ManifestError, "metadata"):
            module.load_selection_data(selection_fixture(), self.refs, self.bibles)

    def test_selection_rejects_candidate_hash_mismatch(self) -> None:
        (self.refs / "references/iolo/candidate_English_1.ogg").write_bytes(b"tampered")

        with self.assertRaisesRegex(module.ManifestError, "sha256"):
            module.load_selection_data(selection_fixture(), self.refs, self.bibles)


if __name__ == "__main__":
    unittest.main()
