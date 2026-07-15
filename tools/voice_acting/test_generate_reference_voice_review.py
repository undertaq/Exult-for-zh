import json
import tempfile
import unittest
from pathlib import Path

from tools.voice_acting import generate_reference_voice_review as module


class GenerateReferenceVoiceReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.candidates = self.root / "references" / "iolo"
        self.candidates.mkdir(parents=True)
        for language, index in (("English", 8), ("Chinese", 9)):
            for candidate in range(10):
                audio = self.candidates / f"candidate_{language}_{candidate}.ogg"
                audio.write_bytes(b"OggS")
                metadata = {
                    "npc": "Iolo",
                    "candidate": candidate,
                    "seed": 1000 + candidate,
                    "text": "A long reference sentence for review.",
                    "voice_prompt_enriched": "Warm elderly baritone",
                    "duration_seconds": 3.2,
                    "sample_rate": 24000,
                    "sha256": f"hash-{language}-{candidate}",
                }
                audio.with_suffix(".json").write_text(json.dumps(metadata), encoding="utf-8")
        self.selection = {
            "objective": "lexicographic_maximin_per_language_independent",
            "selected": {
                "iolo": {
                    "npc": "Iolo",
                    "slug": "iolo",
                    "english_index": 8,
                    "english_seed": 1008,
                    "chinese_index": 9,
                    "chinese_seed": 2009,
                }
            },
        }
        self.bibles = {
            "iolo": {
                "voice_prompt_enriched": "Warm elderly baritone",
                "voice_prompt_enriched_zh": "溫暖、年長的男中音。",
                "evidence": {"image_path": "iolo.png"},
            }
        }
        (self.root / "iolo.png").write_bytes(b"image")
        module.build_report.portrait_root = self.root

    def tearDown(self):
        module.build_report.portrait_root = None
        self.temp.cleanup()

    def test_report_renders_selected_and_all_candidates_inline(self):
        output = self.root / "review" / "index.html"
        page = module.build_report(self.selection, self.bibles, self.root / "references", output, {})

        self.assertIn("candidate_English_8.ogg", page)
        self.assertIn("candidate_Chinese_9.ogg", page)
        self.assertIn("<audio", page)
        self.assertIn("selected", page)
        self.assertIn("Warm elderly baritone", page)
        self.assertIn("溫暖、年長的男中音。", page)
        self.assertIn("A long reference sentence for review.", page)
        self.assertIn('loading="lazy"', page)
        self.assertIn('preload="none"', page)
        self.assertNotIn('target="_blank"', page)

    def test_review_storage_key_changes_with_selection(self):
        first = module.selection_fingerprint(self.selection)
        self.selection["selected"]["iolo"]["english_index"] = 2
        self.assertNotEqual(first, module.selection_fingerprint(self.selection))

    def test_report_contains_review_controls_persistence_and_mutually_exclusive_logic(self):
        page = module.build_report(self.selection, self.bibles, self.root / "references", self.root / "index.html", {})

        self.assertIn("ultima-ref-review:", page)
        self.assertIn('data-status="pass"', page)
        self.assertIn('data-status="failed"', page)
        self.assertIn("localStorage.setItem", page)
        self.assertIn("if (pass.checked) failed.checked=false", page)
        self.assertIn("unreviewed", page)
        self.assertIn("missing-portrait", page)
        self.assertIn("audit-warning", page)
        self.assertIn("IntersectionObserver", page)

    def test_audit_warning_and_missing_audio_are_exposed_as_filter_data(self):
        (self.candidates / "candidate_Chinese_9.ogg").unlink()
        page = module.build_report(
            self.selection,
            self.bibles,
            self.root / "references",
            self.root / "index.html",
            {"iolo": {"warnings": ["clipping ratio too high"]}},
        )

        self.assertIn('data-warning="true"', page)
        self.assertIn("Audit: clipping ratio too high", page)
        self.assertIn("missing Chinese audio", page)

    def test_bibles_can_be_loaded_from_directory(self):
        bible_dir = self.root / "voice_bibles"
        bible_dir.mkdir()
        (bible_dir / "iolo.json").write_text(json.dumps(self.bibles["iolo"]), encoding="utf-8")
        page = module.build_report(self.selection, bible_dir, self.root / "references", self.root / "index.html", {})
        self.assertIn("Warm elderly baritone", page)

    def test_portrait_uses_wiki_image_name_and_u7_suffix(self):
        portrait_root = self.root / "portraits"
        portrait_root.mkdir()
        (portrait_root / "AddomU7.PNG").write_bytes(b"image")
        bible = {
            "evidence": {
                "image_url": "https://wiki.example/images/AddomU7.PNG",
                "image_path": "artifacts/cache/hash.png",
            }
        }
        self.assertEqual(
            module._portrait_path("addom", {"npc": "Addom"}, bible, portrait_root),
            portrait_root / "AddomU7.PNG",
        )


if __name__ == "__main__":
    unittest.main()
