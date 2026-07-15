#!/usr/bin/env python3
import argparse
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = SCRIPT_DIR / "generate_qwen3_voice.py"


def load_module():
    fake_torch = type(sys)("torch")
    fake_torch.bfloat16 = "bfloat16"
    fake_torch.cuda = type(sys)("cuda")
    fake_torch.cuda.empty_cache = lambda: None

    fake_qwen = type(sys)("qwen_tts")
    fake_qwen.Qwen3TTSModel = object

    fake_soundfile = type(sys)("soundfile")
    fake_zhconv = type(sys)("zhconv")
    fake_zhconv.convert = lambda text, variant: text

    old = {n: sys.modules.get(n) for n in ("torch", "qwen_tts", "soundfile", "zhconv")}
    sys.modules.update({"torch": fake_torch, "qwen_tts": fake_qwen, "soundfile": fake_soundfile, "zhconv": fake_zhconv})
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        spec = importlib.util.spec_from_file_location("gen_qwen_batch_under_test", SCRIPT_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPT_DIR))
        for n, v in old.items():
            if v is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = v


class CountingModel:
    def __init__(self, raise_once=False):
        self.calls = 0
        self.raise_once = raise_once
        self.seen_texts = []

    def generate_voice_clone(self, *args, **kwargs):
        self.calls += 1
        self.last_prompt = kwargs.get("voice_clone_prompt")
        texts = kwargs.get("text") or []
        self.seen_texts.append(list(texts))
        if self.raise_once and self.calls == 1:
            raise RuntimeError("CUDA out of memory")
        import numpy as np
        return [np.zeros(24000, dtype=np.float32) for _ in texts], 24000


class VoiceBatchGenerationTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_prepare_voice_jobs_splits_single_and_multi(self):
        m = self.module
        prompt_data = {"speaker": 1}
        narrator_prompt = {"narrator": 1}
        single = {"en_text": "A plain sentence without dialogue."}
        multi = {"en_text": 'He says, "Hello." Then he walks away.'}
        jobs, multis = m.prepare_voice_jobs(
            [single, multi], "en", "en_text", prompt_data, narrator_prompt, "npc_unknown"
        )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(len(multis), 1)
        # Plain text -> narrator role -> narrator prompt.
        self.assertEqual(jobs[0]["prompt"], narrator_prompt)
        self.assertEqual(jobs[0]["length_class"], "short")

    def test_prepare_voice_jobs_long_text_class(self):
        m = self.module
        long_text = "x" * (m.LONG_TEXT_THRESHOLD + 1)
        jobs, multis = m.prepare_voice_jobs(
            [{"en_text": long_text}], "en", "en_text", {"p": 1}, None, "npc_x"
        )
        self.assertEqual(jobs[0]["length_class"], "long")

    def test_bucket_groups_by_prompt_and_length(self):
        m = self.module
        p1, p2 = {"a": 1}, {"b": 2}
        jobs = [
            {"entry": {}, "text": "s1", "prompt": p1, "length_class": "short", "narrator_id": "n"},
            {"entry": {}, "text": "s2", "prompt": p1, "length_class": "short", "narrator_id": "n"},
            {"entry": {}, "text": "l1", "prompt": p1, "length_class": "long", "narrator_id": "n"},
            {"entry": {}, "text": "s3", "prompt": p2, "length_class": "short", "narrator_id": "n"},
        ]
        buckets = m.bucket_single_part_jobs(jobs, max_lines=10)
        # 3 buckets: (p1,short)x2, (p1,long)x1, (p2,short)x1
        sizes = sorted(len(b) for b in buckets)
        self.assertEqual(sizes, [1, 1, 2])

    def test_bucket_caps_at_max_lines(self):
        m = self.module
        p = {"a": 1}
        jobs = [
            {"entry": {}, "text": f"t{i}", "prompt": p, "length_class": "short", "narrator_id": "n"}
            for i in range(5)
        ]
        buckets = m.bucket_single_part_jobs(jobs, max_lines=2)
        self.assertEqual([len(b) for b in buckets], [2, 2, 1])

    def test_generate_single_part_batch_one_call_per_bucket(self):
        m = self.module
        model = CountingModel()
        p = ["speaker-prompt"]
        bucket = [
            {"entry": {"_ogg_path": f"/tmp/{i}.ogg"}, "text": f"line {i}", "prompt": p,
             "length_class": "short", "narrator_id": "npc_x"}
            for i in range(3)
        ]
        # Mock side effects that need ffmpeg / filesystem.
        m.write_ogg_direct = lambda *a, **k: None
        m.prepare_voice_output_path = lambda *a, **k: None
        m.maybe_update_full_voice_review = lambda *a, **k: 0
        m.create_generic_fallback = lambda *a, **k: None
        args = argparse.Namespace(generic_fallbacks=False)
        stats = {"generated": 0, "errors": 0}
        m.generate_single_part_batch(
            model, bucket, "English", "en", "/tmp/out", args, "NPC", 0, 0, stats
        )
        self.assertEqual(model.calls, 1)
        self.assertEqual(len(model.seen_texts[0]), 3)
        self.assertEqual(model.last_prompt, p)
        self.assertEqual(stats["generated"], 3)
        self.assertEqual(stats["errors"], 0)

    def test_generate_single_part_batch_oom_retry(self):
        m = self.module
        model = CountingModel(raise_once=True)
        p = ["speaker-prompt"]
        bucket = [
            {"entry": {"_ogg_path": f"/tmp/{i}.ogg"}, "text": f"line {i}", "prompt": p,
             "length_class": "short", "narrator_id": "npc_x"}
            for i in range(3)
        ]
        m.write_ogg_direct = lambda *a, **k: None
        m.prepare_voice_output_path = lambda *a, **k: None
        m.maybe_update_full_voice_review = lambda *a, **k: 0
        m.create_generic_fallback = lambda *a, **k: None
        args = argparse.Namespace(generic_fallbacks=False)
        stats = {"generated": 0, "errors": 0}
        m.generate_single_part_batch(
            model, bucket, "English", "en", "/tmp/out", args, "NPC", 0, 0, stats
        )
        self.assertGreaterEqual(model.calls, 2)
        self.assertEqual(stats["generated"], 3)
        self.assertEqual(model.last_prompt, p)


if __name__ == "__main__":
    unittest.main()
