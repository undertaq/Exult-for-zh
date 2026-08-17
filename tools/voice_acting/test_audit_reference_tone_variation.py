#!/usr/bin/env python3
import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np


SCRIPT_PATH = Path(__file__).with_name("audit_reference_tone_variation.py")


def load_script_module():
    spec = importlib.util.spec_from_file_location("audit_reference_tone_variation_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuditReferenceToneVariationTest(unittest.TestCase):
    def test_parse_reference_filename(self):
        module = load_script_module()

        parsed = module.parse_reference_filename(Path("npc_iolo_zh_ref.ogg"))

        self.assertEqual(parsed, ("npc_iolo", "zh"))
        self.assertIsNone(module.parse_reference_filename(Path("npc_iolo_ref.ogg")))

    def test_extract_features_tracks_pitch_and_brightness(self):
        module = load_script_module()
        sr = 24000
        t = np.arange(sr, dtype=np.float32) / sr
        low = np.sin(2 * np.pi * 120 * t).astype(np.float32)
        high = np.sin(2 * np.pi * 240 * t).astype(np.float32)

        low_features = module.extract_features(low, sr)
        high_features = module.extract_features(high, sr)

        self.assertGreater(high_features["f0_hz"], low_features["f0_hz"] * 1.5)
        self.assertGreater(high_features["spectral_centroid_hz"], low_features["spectral_centroid_hz"])

    def test_audit_flags_too_similar_pairs_within_language(self):
        module = load_script_module()
        records = [
            {
                "design_id": "npc_a",
                "npc": "A",
                "lang": "zh",
                "path": "a.ogg",
                "features": {
                    "duration_s": 8.0,
                    "rms": 0.1,
                    "zero_crossing_rate": 0.02,
                    "spectral_centroid_hz": 1800.0,
                    "spectral_bandwidth_hz": 900.0,
                    "f0_hz": 130.0,
                    "f0_std_hz": 20.0,
                },
            },
            {
                "design_id": "npc_b",
                "npc": "B",
                "lang": "zh",
                "path": "b.ogg",
                "features": {
                    "duration_s": 8.1,
                    "rms": 0.101,
                    "zero_crossing_rate": 0.021,
                    "spectral_centroid_hz": 1810.0,
                    "spectral_bandwidth_hz": 905.0,
                    "f0_hz": 131.0,
                    "f0_std_hz": 20.5,
                },
            },
            {
                "design_id": "npc_c",
                "npc": "C",
                "lang": "en",
                "path": "c.ogg",
                "features": {
                    "duration_s": 5.0,
                    "rms": 0.3,
                    "zero_crossing_rate": 0.08,
                    "spectral_centroid_hz": 3200.0,
                    "spectral_bandwidth_hz": 1500.0,
                    "f0_hz": 260.0,
                    "f0_std_hz": 45.0,
                },
            },
        ]

        result = module.audit_records(records, similarity_threshold=0.08)

        self.assertEqual(result["by_lang"]["zh"]["count"], 2)
        self.assertEqual(len(result["similar_pairs"]), 1)
        self.assertEqual(
            {result["similar_pairs"][0]["left"]["design_id"], result["similar_pairs"][0]["right"]["design_id"]},
            {"npc_a", "npc_b"},
        )

    def test_audit_flags_same_tone_even_when_text_duration_differs(self):
        module = load_script_module()
        base_features = {
            "rms": 0.1,
            "zero_crossing_rate": 0.02,
            "spectral_centroid_hz": 1800.0,
            "spectral_bandwidth_hz": 900.0,
            "f0_hz": 130.0,
            "f0_std_hz": 20.0,
        }
        records = [
            {
                "design_id": "short_text",
                "npc": "Same Prompt Short Text",
                "lang": "zh",
                "path": "short.ogg",
                "features": {"duration_s": 4.0, **base_features},
            },
            {
                "design_id": "long_text",
                "npc": "Same Prompt Long Text",
                "lang": "zh",
                "path": "long.ogg",
                "features": {"duration_s": 18.0, **base_features},
            },
        ]

        result = module.audit_records(records, similarity_threshold=0.08)

        self.assertEqual(len(result["similar_pairs"]), 1)

    def test_write_json_report(self):
        module = load_script_module()
        result = {"summary": {"total_refs": 0}, "similar_pairs": []}

        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "tone.json"
            module.write_json_report(result, out)

            self.assertIn('"total_refs": 0', out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
