#!/usr/bin/env python3
import io
import json
import sys
import tempfile
import types
import unittest
from contextlib import nullcontext, redirect_stdout
from unittest.mock import patch
from pathlib import Path

import numpy as np

from tools.voice_acting import generate_reference_candidates as generator
from tools.voice_acting import select_reference_candidates as selector


def designs_fixture():
    return {
        "designs": {
            "npc_iolo": {
                "npc": "Iolo",
                "npcs": ["Iolo"],
                "voice_desc_en": "Warm, elderly male bard voice.",
                "voice_desc_zh": "温暖的老年男性吟游诗人声音。",
            },
            "npc_dupre": {
                "npc": "Dupre",
                "npcs": ["Dupre"],
                "voice_desc_en": "Confident adult male knight voice.",
                "voice_desc_zh": "自信的成年男性骑士声音。",
            },
        },
    }


class CandidateGenerationTest(unittest.TestCase):
    def test_jobs_include_ten_independent_language_candidates(self):
        jobs = generator.build_candidate_jobs(designs_fixture(), Path("out"), 10)

        self.assertEqual(len(jobs), 40)
        self.assertEqual(jobs[0].output.name, "candidate_Chinese_0.ogg")
        self.assertEqual(jobs[0].language, "Chinese")
        self.assertEqual(jobs[0].text, generator.SAMPLE_TEXT["Chinese"])
        self.assertEqual(jobs[-1].output.name, "candidate_English_9.ogg")

    def test_normalize_voice_bibles_adapts_bible_fields_at_cli_boundary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bible = Path(tmpdir, "iolo.json")
            bible.write_text(
                '{"npc": "Iolo", "slug": "iolo", '
                '"voice_prompt_enriched": "English bard", '
                '"voice_prompt_enriched_zh": "中文吟游诗人"}',
                encoding="utf-8",
            )

            designs = generator.load_designs_or_voice_bibles(None, Path(tmpdir))

        jobs = generator.build_candidate_jobs(designs, Path("out"), 1)
        self.assertEqual([job.instruct for job in jobs], ["中文吟游诗人", "English bard"])

    def test_voice_bible_overlay_removes_its_npc_from_grouped_designs(self):
        source_designs = {
            "designs": {
                "npc_group": {
                    "npcs": ["Iolo", "Spark"],
                    "voice_desc_en": "Shared party voice.",
                    "voice_desc_zh": "共享的队伍声音。",
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            designs_path = Path(tmpdir, "designs.json")
            designs_path.write_text(json.dumps(source_designs), encoding="utf-8")
            bible_dir = Path(tmpdir, "bibles")
            bible_dir.mkdir()
            (bible_dir / "iolo.json").write_text(
                '{"npc": "Iolo", "voice_prompt_enriched": "Dedicated Iolo voice"}',
                encoding="utf-8",
            )

            designs = generator.load_designs_or_voice_bibles(designs_path, bible_dir)

        jobs = generator.build_candidate_jobs(designs, Path("out"), 1)
        self.assertEqual(
            [(job.npc, job.language) for job in jobs],
            [("Spark", "Chinese"), ("Spark", "English"), ("Iolo", "Chinese"), ("Iolo", "English")],
        )

    def test_jobs_expand_grouped_design_to_each_npc(self):
        designs = {
            "designs": {
                "npc_group": {
                    "npcs": ["Iolo", "Spark"],
                    "voice_desc_en": "Shared party voice.",
                    "voice_desc_zh": "共享的队伍声音。",
                },
            },
        }

        jobs = generator.build_candidate_jobs(designs, Path("out"), 1)

        self.assertEqual(len(jobs), 4)
        self.assertEqual(
            [(job.npc, job.slug, job.language) for job in jobs],
            [
                ("Iolo", "iolo", "Chinese"),
                ("Iolo", "iolo", "English"),
                ("Spark", "spark", "Chinese"),
                ("Spark", "spark", "English"),
            ],
        )

    def test_unknown_narrator_uses_the_canonical_female_narrator_slug(self):
        for npc in ("UNKNOWN", "npc_unknown"):
            with self.subTest(npc=npc):
                designs = {
                    "designs": {
                        "npc_unknown": {
                            "npc": npc,
                            "npcs": [npc],
                            "voice_desc_en": "Calm female narrator.",
                            "voice_desc_zh": "平静的女性旁白。",
                        },
                    },
                }

                jobs = generator.build_candidate_jobs(designs, Path("out"), 1)

                self.assertEqual({job.slug for job in jobs}, {"narrator_female"})

    def test_candidate_output_directory_rejects_approved_refs_and_descendants(self):
        refs = Path(generator.PROJECT_DIR, "voice", "refs")

        with self.assertRaisesRegex(ValueError, "voice/refs"):
            generator.build_candidate_jobs(designs_fixture(), refs, 1)
        with self.assertRaisesRegex(ValueError, "voice/refs"):
            generator.build_candidate_jobs(designs_fixture(), refs / "nested", 1)

    def test_skip_existing_regenerates_orphaned_or_hash_mismatched_candidate_pair(self):
        class Model:
            def __init__(self):
                self.calls = 0

            def generate_voice_design(self, **kwargs):
                self.calls += 1
                return [np.zeros(8, dtype=np.float32)], 4

        with tempfile.TemporaryDirectory() as tmpdir:
            job = generator.build_candidate_jobs(designs_fixture(), Path(tmpdir), 1)[0]
            job.output.parent.mkdir(parents=True)
            job.output.write_bytes(b"old candidate")
            model = Model()
            written = []
            original = generator.write_candidate
            generator.write_candidate = lambda item, wav, sr, batch_seed, batch_position, *provenance: (
                written.append((item, batch_seed)) or item.output
            )
            try:
                generator.generate_jobs(model, [job], seed_base=1000, batch_size=1, skip_existing=True)
            finally:
                generator.write_candidate = original

            self.assertEqual(model.calls, 1)
            self.assertEqual(written, [(job, 1000)])

            job.output.with_suffix(".json").write_text(
                '{"sha256": "not-the-audio-hash"}', encoding="utf-8"
            )
            self.assertFalse(generator.candidate_pair_is_complete(job))

    def test_resume_rejects_sidecars_with_stale_generation_inputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            job = generator.build_candidate_jobs(designs_fixture(), Path(tmpdir), 1)[0]
            job.output.parent.mkdir(parents=True)
            job.output.write_bytes(b"candidate audio")
            metadata = {
                "npc": job.npc,
                "slug": job.slug,
                "index": job.index,
                "language": job.language,
                "sample_text": job.text,
                "instruct": job.instruct,
                "model_revision": generator.MODEL_ID,
                "sha256": generator.sha256_file(job.output),
            }
            for field, stale_value in (
                ("sample_text", "old sample text"),
                ("instruct", "old instruction"),
                ("model_revision", "old-model"),
            ):
                with self.subTest(field=field):
                    stale_metadata = dict(metadata)
                    stale_metadata[field] = stale_value
                    job.output.with_suffix(".json").write_text(
                        json.dumps(stale_metadata), encoding="utf-8"
                    )

                    self.assertFalse(generator.candidate_pair_is_complete(job))

    def test_resume_rejects_sidecars_without_batch_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            job = generator.build_candidate_jobs(designs_fixture(), Path(tmpdir), 1)[0]
            job.output.parent.mkdir(parents=True)
            job.output.write_bytes(b"candidate audio")
            job.output.with_suffix(".json").write_text(
                json.dumps({
                    "npc": job.npc,
                    "slug": job.slug,
                    "index": job.index,
                    "language": job.language,
                    "sample_text": job.text,
                    "instruct": job.instruct,
                    "model_revision": generator.MODEL_ID,
                    "sha256": generator.sha256_file(job.output),
                    "seed": 1000,
                }),
                encoding="utf-8",
            )

            self.assertFalse(generator.candidate_pair_is_complete(job))

    def test_resume_rejects_invalid_audio_metrics_and_mismatched_batch_provenance(self):
        class Model:
            def __init__(self):
                self.calls = []

            def generate_voice_design(self, **kwargs):
                self.calls.append(kwargs["text"])
                return [np.zeros(8, dtype=np.float32) for _ in kwargs["text"]], 4

        invalid_overrides = {
            "nonpositive sample rate": {"sample_rate": 0},
            "nonpositive duration": {"duration_seconds": 0},
            "wrong batch seed": {"seed": 999, "batch_seed": 999},
            "wrong batch position": {"batch_position": 1},
            "wrong batch size": {"batch_size": 1},
        }
        for label, overrides in invalid_overrides.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmpdir:
                jobs = generator.build_candidate_jobs(designs_fixture(), Path(tmpdir), 1)[:2]
                for position, job in enumerate(jobs):
                    job.output.parent.mkdir(parents=True, exist_ok=True)
                    job.output.write_bytes(f"candidate {position}".encode("ascii"))
                    metadata = {
                        "npc": job.npc,
                        "slug": job.slug,
                        "index": job.index,
                        "language": job.language,
                        "sample_text": job.text,
                        "instruct": job.instruct,
                        "model_revision": generator.MODEL_ID,
                        "sha256": generator.sha256_file(job.output),
                        "sample_rate": 4,
                        "duration_seconds": 2.0,
                        "seed": 1000,
                        "batch_seed": 1000,
                        "batch_position": position,
                        "batch_size": 2,
                    }
                    if position == 0:
                        metadata.update(overrides)
                    job.output.with_suffix(".json").write_text(
                        json.dumps(metadata), encoding="utf-8"
                    )

                model = Model()
                original_write = generator.write_candidate
                generator.write_candidate = lambda *args, **kwargs: args[0].output
                try:
                    generated = generator.generate_jobs(
                        model, jobs, seed_base=1000, batch_size=2, skip_existing=True
                    )
                finally:
                    generator.write_candidate = original_write

                self.assertEqual(model.calls, [[jobs[0].text, jobs[1].text]])
                self.assertEqual(generated, [job.output for job in jobs])

    def test_generate_jobs_splits_oom_batches_and_writes_metadata(self):
        class Model:
            def __init__(self):
                self.calls = []

            def generate_voice_design(self, **kwargs):
                self.calls.append(kwargs)
                if len(kwargs["text"]) > 1:
                    raise RuntimeError("CUDA out of memory")
                return [np.zeros(8, dtype=np.float32)], 4

        jobs = generator.build_candidate_jobs(designs_fixture(), Path("out"), 1)[:2]
        model = Model()
        written = []
        original = generator.write_candidate
        generator.write_candidate = (
            lambda job, wav, sr, batch_seed, batch_position, batch_size, effective_seed:
            written.append((job, batch_seed, batch_position, batch_size, effective_seed, sr)) or job.output
        )
        try:
            generated = generator.generate_jobs(model, jobs, seed_base=1000, batch_size=2, skip_existing=False)
        finally:
            generator.write_candidate = original

        self.assertEqual(len(generated), 2)
        self.assertEqual(len(model.calls), 3)
        self.assertEqual(
            [tuple(provenance) for _, *provenance, _ in written],
            [(1000, 0, 2, 1000), (1000, 1, 2, 1001)],
        )

    def test_generate_jobs_records_shared_batch_seeds_and_positions(self):
        class Model:
            def generate_voice_design(self, **kwargs):
                return [np.zeros(8, dtype=np.float32) for _ in kwargs["text"]], 4

        jobs = generator.build_candidate_jobs(designs_fixture(), Path("out"), 1)
        written = []
        original = generator.write_candidate
        generator.write_candidate = (
            lambda job, wav, sr, batch_seed, batch_position, batch_size, effective_seed:
            written.append((batch_seed, batch_position, batch_size, effective_seed)) or job.output
        )
        try:
            generator.generate_jobs(Model(), jobs, seed_base=1000, batch_size=2, skip_existing=False)
        finally:
            generator.write_candidate = original

        self.assertEqual(
            written,
            [
                (1000, 0, 2, 1000),
                (1000, 1, 2, 1000),
                (1002, 0, 2, 1002),
                (1002, 1, 2, 1002),
            ],
        )

    def test_resumed_batches_record_the_applied_seed_and_batch_position(self):
        class Model:
            def __init__(self):
                self.calls = []

            def generate_voice_design(self, **kwargs):
                self.calls.append(kwargs["text"])
                return [np.zeros(8, dtype=np.float32) for _ in kwargs["text"]], 4

        jobs = generator.build_candidate_jobs(designs_fixture(), Path("out"), 1)
        model = Model()
        written = []
        original_complete = generator.candidate_pair_is_complete
        original_write = generator.write_candidate
        generator.candidate_pair_is_complete = lambda job, *args, **kwargs: job == jobs[0]
        generator.write_candidate = lambda *args: written.append(args) or args[0].output
        try:
            generator.generate_jobs(model, jobs, seed_base=1000, batch_size=2, skip_existing=True)
        finally:
            generator.candidate_pair_is_complete = original_complete
            generator.write_candidate = original_write

        self.assertEqual(
            model.calls,
            [[jobs[0].text, jobs[1].text], [jobs[2].text, jobs[3].text]],
        )
        self.assertEqual(
            [(args[0], args[3], args[4]) for args in written],
            [
                (jobs[0], 1000, 0),
                (jobs[1], 1000, 1),
                (jobs[2], 1002, 0),
                (jobs[3], 1002, 1),
            ],
        )

    def test_npcs_filter_trims_unrequested_members_from_grouped_design(self):
        grouped_designs = {
            "designs": {
                "npc_group": {
                    "npcs": ["Iolo", "Spark"],
                    "voice_desc_en": "Shared party voice.",
                    "voice_desc_zh": "\u5171\u4eab\u7684\u961f\u4f0d\u58f0\u97f3\u3002",
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            designs_path = Path(tmpdir, "designs.json")
            designs_path.write_text(json.dumps(grouped_designs), encoding="utf-8")
            args = generator.build_parser().parse_args([
                "--designs", str(designs_path),
                "--output-dir", str(Path(tmpdir, "candidates")),
                "--npcs", "Iolo",
                "--candidates", "1",
                "--dry-run",
            ])

            output = io.StringIO()
            with redirect_stdout(output):
                generated, skipped = generator.run(args)

        self.assertEqual((generated, skipped), (0, 0))
        self.assertEqual(output.getvalue().count("would generate"), 2)
        self.assertIn("/iolo/", output.getvalue())
        self.assertNotIn("/spark/", output.getvalue())


class CandidateSelectionTest(unittest.TestCase):
    def test_special_candidates_use_the_within_character_medoid(self):
        picks = selector.select_medoids({
            "avatar_female": [
                np.array([1.0, 0.0]),
                np.array([0.9, 0.1]),
                np.array([-1.0, 0.0]),
            ],
        })

        self.assertEqual(picks, {"avatar_female": 1})

    def test_maximin_avoids_near_duplicate_cast_pair(self):
        root3 = np.sqrt(3.0) / 2.0
        embeddings = {
            "iolo": [np.array([-0.5, -root3]), np.array([1.0, 0.0])],
            "dupre": [np.array([-0.5, -root3]), np.array([1.0, 0.0])],
            "spark": [np.array([1.0, 0.0]), np.array([-0.5, root3])],
        }

        picks = selector.select_maximin(embeddings, candidates=2, restarts=4)

        self.assertEqual(picks, {"iolo": 1, "dupre": 0, "spark": 1})

    def test_audio_audit_fallback_replaces_invalid_selection_with_most_distinct_valid_candidate(self):
        invalid = selector.AudioAudit(Path("bad.ogg"), False, "clipping_ratio", 4.0, 0.02, 0.1)
        valid = selector.AudioAudit(Path("good.ogg"), True, None, 4.0, 0.0, 0.1)
        audits = {"iolo": [invalid, valid], "dupre": [valid, valid]}
        embeddings = {
            "iolo": [np.array([1.0, 0.0]), np.array([-1.0, 0.0])],
            "dupre": [np.array([1.0, 0.0]), np.array([0.0, 1.0])],
        }
        selection = {"iolo": {"index": 0}, "dupre": {"index": 0}}

        replaced = selector.replace_invalid_selections(selection, audits, embeddings)

        self.assertEqual(replaced["iolo"]["index"], 1)
        self.assertEqual(replaced["iolo"]["replaced_index"], 0)
        self.assertEqual(replaced["iolo"]["replacement_reason"], "clipping_ratio")
        self.assertEqual(replaced["iolo"]["audit_metrics"]["duration_seconds"], 4.0)

    def test_unreadable_candidates_are_not_embedded(self):
        unreadable = selector.AudioAudit(Path("bad.ogg"), False, "unreadable", 0.0, 0.0, 1.0)
        valid = selector.AudioAudit(Path("good.ogg"), True, None, 4.0, 0.0, 0.1)
        calls = []
        original = selector.embed_candidates
        selector.embed_candidates = lambda encoder, paths, device: calls.append(paths) or [np.array([1.0, 0.0])]
        try:
            vectors = selector.embed_valid_candidates(object(), [Path("bad.ogg"), Path("good.ogg")], [unreadable, valid], "cpu")
        finally:
            selector.embed_candidates = original

        self.assertEqual(calls, [[Path("good.ogg")]])
        self.assertEqual(list(vectors), [1])

    def test_embed_candidates_resamples_24khz_audio_to_16khz_before_ecapa(self):
        class FakeTensor:
            def __init__(self, values):
                self.values = np.asarray(values, dtype=np.float32)

            def __len__(self):
                return len(self.values)

            def unsqueeze(self, _):
                return self

            def to(self, _):
                return self

            def squeeze(self):
                return self

            def cpu(self):
                return self

            def numpy(self):
                return self.values

        class FakeEncoder:
            def __init__(self):
                self.batches = []

            def encode_batch(self, batch):
                self.batches.append(batch.values.copy())
                return FakeTensor([3.0, 4.0])

        encoder = FakeEncoder()
        resample_calls = []

        def resample(wav, source_rate, target_rate):
            resample_calls.append((source_rate, target_rate))
            return FakeTensor(np.zeros(len(wav) * target_rate // source_rate, dtype=np.float32))

        fake_torch = types.SimpleNamespace(no_grad=nullcontext, tensor=FakeTensor)
        fake_torchaudio_functional = types.ModuleType("torchaudio.functional")
        fake_torchaudio_functional.resample = resample
        fake_torchaudio = types.ModuleType("torchaudio")
        fake_torchaudio.functional = fake_torchaudio_functional
        native_wav = np.linspace(-1.0, 1.0, 24000, dtype=np.float32)

        with patch.object(selector, "load_audio", return_value=(native_wav, 24000)), patch.dict(
            sys.modules,
            {
                "torch": fake_torch,
                "torchaudio": fake_torchaudio,
                "torchaudio.functional": fake_torchaudio_functional,
            },
        ):
            selector.embed_candidates(encoder, [Path("candidate.ogg")], "cpu")

        self.assertEqual(resample_calls, [(24000, 16000)])
        self.assertEqual(encoder.batches[0].shape, (16000,))

    def test_canonical_female_narrator_uses_medoid_selection(self):
        embeddings = {
            "npc_unknown": [
                np.array([1.0, 0.0]),
                np.array([0.9, 0.1]),
                np.array([-1.0, 0.0]),
            ],
            "iolo": [np.array([0.0, 1.0]), np.array([0.0, -1.0])],
        }

        picks = selector.select_language_candidates(embeddings, candidates=3, restarts=2)

        self.assertEqual(picks["npc_unknown"], 1)

    def test_invalid_selection_without_valid_alternative_raises(self):
        invalid = selector.AudioAudit(Path("bad.ogg"), False, "unreadable", 0.0, 0.0, 1.0)

        with self.assertRaisesRegex(ValueError, "iolo"):
            selector.replace_invalid_selections(
                {"iolo": {"index": 0}},
                {"iolo": [invalid]},
                {"iolo": [np.array([1.0, 0.0])]},
            )


if __name__ == "__main__":
    unittest.main()
