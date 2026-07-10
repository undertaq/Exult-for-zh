#!/usr/bin/env python3
import argparse
import importlib.util
import json
import os
import pickle
import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np


SCRIPT_PATH = Path(__file__).with_name("generate_qwen3_voice.py")


class FakeModel:
    generate_voice_clone_calls = 0
    create_prompt_calls = 0

    @classmethod
    def reset(cls):
        cls.generate_voice_clone_calls = 0
        cls.create_prompt_calls = 0

    @classmethod
    def from_pretrained(cls, *args, **kwargs):
        return cls()

    def generate_voice_clone(self, *args, **kwargs):
        self.__class__.generate_voice_clone_calls += 1
        texts = kwargs.get("text") or []
        return [np.zeros(24000, dtype=np.float32) for _ in texts], 24000

    def create_voice_clone_prompt(self, *args, **kwargs):
        self.__class__.create_prompt_calls += 1
        return ["prompt"]


def load_script_module():
    FakeModel.reset()

    fake_torch = types.ModuleType("torch")
    fake_torch.bfloat16 = "bfloat16"
    fake_torch.cuda = types.SimpleNamespace(empty_cache=lambda: None)

    fake_qwen = types.ModuleType("qwen_tts")
    fake_qwen.Qwen3TTSModel = FakeModel

    fake_soundfile = types.ModuleType("soundfile")

    fake_zhconv = types.ModuleType("zhconv")
    fake_zhconv.convert = lambda text, variant: text

    old_modules = {
        name: sys.modules.get(name)
        for name in ("torch", "qwen_tts", "soundfile", "zhconv")
    }
    sys.modules["torch"] = fake_torch
    sys.modules["qwen_tts"] = fake_qwen
    sys.modules["soundfile"] = fake_soundfile
    sys.modules["zhconv"] = fake_zhconv
    sys.path.insert(0, str(SCRIPT_PATH.parent))

    try:
        spec = importlib.util.spec_from_file_location("generate_qwen3_voice_under_test", SCRIPT_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPT_PATH.parent))
        for name, old in old_modules.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


class GenerateQwen3VoiceBehaviorTest(unittest.TestCase):
    def test_phase_c_dry_run_does_not_generate_or_write_files(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            module.ZH_OUTPUT = os.path.join(tmpdir, "zh")
            module.EN_OUTPUT = os.path.join(tmpdir, "en")
            writes = []
            module.write_ogg_direct = lambda *args, **kwargs: writes.append(args)

            designs = {
                "designs": {
                    "npc_iolo": {
                        "npcs": ["Iolo"],
                    },
                },
            }
            by_npc = {
                "Iolo": [
                    {
                        "npc": "Iolo",
                        "zh_func_id": "0401",
                        "zh_offset_key": "e60",
                        "zh_segment": 0,
                        "zh_text": "「看吧？我就說！」",
                    },
                ],
            }
            clone_prompts = {"npc_iolo": {"zh": ["prompt"]}}
            args = argparse.Namespace(
                lang="zh", dry_run=True, force=True, max_npcs=None, device="cuda:0"
            )

            generated, skipped, errors = module.phase_c_generate_voice(
                designs, clone_prompts, by_npc, args
            )

            self.assertEqual((generated, skipped, errors), (0, 0, 0))
            self.assertEqual(FakeModel.generate_voice_clone_calls, 0)
            self.assertEqual(writes, [])
            self.assertEqual(os.listdir(module.ZH_OUTPUT), [])

    def test_phase_c_regenerates_existing_file_when_metadata_is_stale(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            module.ZH_OUTPUT = os.path.join(tmpdir, "zh")
            module.EN_OUTPUT = os.path.join(tmpdir, "en")
            os.makedirs(module.EN_OUTPUT)
            target = os.path.join(module.EN_OUTPUT, "091a_0_0_npc16.ogg")
            Path(target).write_bytes(b"stale")
            module.voice_file_matches_text = lambda path, text: False

            def write_file(filepath, wav, sr, npc="", text=""):
                Path(filepath).write_bytes(b"new")

            module.write_ogg_direct = write_file
            designs = {
                "designs": {
                    "npc_klog": {
                        "npcs": ["Klog"],
                    },
                },
            }
            by_npc = {
                "Klog": [
                    {
                        "npc": "Klog",
                        "en_func_id": "0x091A",
                        "en_offset_key": "0",
                        "en_segment": 0,
                        "en_text": "expected philosophy text",
                    },
                ],
            }
            clone_prompts = {"npc_klog": {"en": ["prompt"]}}
            args = argparse.Namespace(
                lang="en", dry_run=False, force=False, max_npcs=None, device="cuda:0"
            )

            generated, skipped, errors = module.phase_c_generate_voice(
                designs, clone_prompts, by_npc, args
            )

            self.assertEqual((generated, skipped, errors), (1, 0, 0))
            self.assertEqual(FakeModel.generate_voice_clone_calls, 1)
            self.assertEqual(Path(target).read_bytes(), b"new")

    def test_phase_c_generates_english_for_unpaired_zh_row_using_zh_runtime_key(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            module.ZH_OUTPUT = os.path.join(tmpdir, "zh")
            module.EN_OUTPUT = os.path.join(tmpdir, "en")

            def write_file(filepath, wav, sr, npc="", text=""):
                Path(filepath).write_bytes(text.encode("utf-8"))

            module.write_ogg_direct = write_file
            designs = {
                "designs": {
                    "npc_iolo": {
                        "npcs": ["Iolo"],
                    },
                },
            }
            by_npc = {
                "Iolo": [
                    {
                        "npc": "Iolo",
                        "confidence": "unpaired_zh",
                        "zh_func_id": "0x0401",
                        "zh_offset_key": "6af",
                        "zh_segment": 0,
                        "zh_text": "「古文譯本？」",
                        "en_func_id": "",
                        "en_offset_key": "",
                        "en_segment": 0,
                        "en_text": "The rune translator?",
                    },
                ],
            }
            clone_prompts = {"npc_iolo": {"en": ["prompt"]}}
            args = argparse.Namespace(
                lang="en", dry_run=False, force=True, max_npcs=None, device="cuda:0"
            )

            generated, skipped, errors = module.phase_c_generate_voice(
                designs, clone_prompts, by_npc, args
            )

            target = Path(module.EN_OUTPUT) / "0401_6af_0_npc1.ogg"
            self.assertEqual((generated, skipped, errors), (1, 0, 0))
            self.assertEqual(target.read_text(encoding="utf-8"), "The rune translator?")

    def test_phase_c_skips_existing_file_when_metadata_is_fresh(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            module.ZH_OUTPUT = os.path.join(tmpdir, "zh")
            module.EN_OUTPUT = os.path.join(tmpdir, "en")
            os.makedirs(module.EN_OUTPUT)
            target = os.path.join(module.EN_OUTPUT, "091a_0_0_npc16.ogg")
            Path(target).write_bytes(b"fresh")
            module.voice_file_matches_text = lambda path, text: True
            module.write_ogg_direct = lambda *args, **kwargs: self.fail("fresh file was regenerated")
            designs = {
                "designs": {
                    "npc_klog": {
                        "npcs": ["Klog"],
                    },
                },
            }
            by_npc = {
                "Klog": [
                    {
                        "npc": "Klog",
                        "en_func_id": "0x091A",
                        "en_offset_key": "0",
                        "en_segment": 0,
                        "en_text": "expected philosophy text",
                    },
                ],
            }
            clone_prompts = {"npc_klog": {"en": ["prompt"]}}
            args = argparse.Namespace(
                lang="en", dry_run=False, force=False, max_npcs=None, device="cuda:0"
            )

            generated, skipped, errors = module.phase_c_generate_voice(
                designs, clone_prompts, by_npc, args
            )

            self.assertEqual((generated, skipped, errors), (0, 1, 0))
            self.assertEqual(FakeModel.generate_voice_clone_calls, 0)
            self.assertEqual(Path(target).read_bytes(), b"fresh")

    def test_phase_c_does_not_restore_generic_fallback_by_default_when_fresh_specific_file_is_skipped(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            module.ZH_OUTPUT = os.path.join(tmpdir, "zh")
            module.EN_OUTPUT = os.path.join(tmpdir, "en")
            os.makedirs(module.EN_OUTPUT)
            specific = os.path.join(module.EN_OUTPUT, "0401_48d_1_npc1.ogg")
            generic = os.path.join(module.EN_OUTPUT, "0401_48d_1.ogg")
            Path(specific).write_bytes(b"fresh iolo stable")
            module.voice_file_matches_text = lambda path, text: True
            module.write_ogg_direct = lambda *args, **kwargs: self.fail("fresh file was regenerated")
            designs = {
                "designs": {
                    "npc_iolo": {
                        "npcs": ["Iolo"],
                    },
                },
            }
            by_npc = {
                "Iolo": [
                    {
                        "npc": "Iolo",
                        "en_func_id": "0x0401",
                        "en_offset_key": "48d",
                        "en_segment": 1,
                        "en_text": "Take a look inside the stables.",
                    },
                ],
            }
            clone_prompts = {"npc_iolo": {"en": ["prompt"]}}
            args = argparse.Namespace(
                lang="en", dry_run=False, force=False, max_npcs=None, device="cuda:0"
            )

            generated, skipped, errors = module.phase_c_generate_voice(
                designs, clone_prompts, by_npc, args
            )

            self.assertEqual((generated, skipped, errors), (0, 1, 0))
            self.assertEqual(FakeModel.generate_voice_clone_calls, 0)
            self.assertFalse(Path(generic).exists())

    def test_phase_c_restores_generic_fallback_when_explicitly_requested(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            module.ZH_OUTPUT = os.path.join(tmpdir, "zh")
            module.EN_OUTPUT = os.path.join(tmpdir, "en")
            os.makedirs(module.EN_OUTPUT)
            specific = os.path.join(module.EN_OUTPUT, "0401_48d_1_npc1.ogg")
            generic = os.path.join(module.EN_OUTPUT, "0401_48d_1.ogg")
            Path(specific).write_bytes(b"fresh iolo stable")
            module.voice_file_matches_text = lambda path, text: True
            module.write_ogg_direct = lambda *args, **kwargs: self.fail("fresh file was regenerated")
            designs = {
                "designs": {
                    "npc_iolo": {
                        "npcs": ["Iolo"],
                    },
                },
            }
            by_npc = {
                "Iolo": [
                    {
                        "npc": "Iolo",
                        "en_func_id": "0x0401",
                        "en_offset_key": "48d",
                        "en_segment": 1,
                        "en_text": "Take a look inside the stables.",
                    },
                ],
            }
            clone_prompts = {"npc_iolo": {"en": ["prompt"]}}
            args = argparse.Namespace(
                lang="en",
                dry_run=False,
                force=False,
                max_npcs=None,
                device="cuda:0",
                generic_fallbacks=True,
            )

            generated, skipped, errors = module.phase_c_generate_voice(
                designs, clone_prompts, by_npc, args
            )

            self.assertEqual((generated, skipped, errors), (0, 1, 0))
            self.assertEqual(FakeModel.generate_voice_clone_calls, 0)
            self.assertEqual(Path(generic).read_bytes(), b"fresh iolo stable")

    def test_voice_file_match_ignores_whitespace_only_metadata_drift(self):
        module = load_script_module()
        module.read_ogg_comment = lambda path: ' expected   philosophy text '

        self.assertTrue(module.voice_file_matches_text('unused.ogg', 'expected philosophy text'))

    def test_shared_caller_guess_entries_expand_to_each_possible_speaker(self):
        module = load_script_module()
        entry = {
            "npc": "Klog",
            "en_func_id": "0x091A",
            "en_offset_key": "0",
            "en_segment": 0,
            "en_text": "shared philosophy text",
            "_source_meta": {
                "en": {
                    "speaker": "",
                    "npc": "",
                    "caller_guess": "Ellen|Klog",
                },
            },
        }

        expanded = module.expand_entry_for_voice_speakers(entry)
        by_npc = {e["npc"]: e for e in expanded}

        self.assertEqual(set(by_npc), {"Ellen", "Klog"})
        self.assertEqual(module.make_filename(by_npc["Ellen"], "en"), "091a_0_0_npc236.ogg")
        self.assertEqual(module.make_filename(by_npc["Klog"], "en"), "091a_0_0_npc16.ogg")
        self.assertTrue(by_npc["Ellen"]["_suppress_generic_fallback"])
        self.assertTrue(by_npc["Klog"]["_suppress_generic_fallback"])

    def test_explicit_speaker_entries_use_speaker_voice_not_conversation_npc(self):
        module = load_script_module()
        entry = {
            "npc": "Iolo",
            "en_func_id": "0x0401",
            "en_offset_key": "437_466",
            "en_segment": 0,
            "en_text": "Petre interrupts Iolo",
            "_source_meta": {
                "en": {
                    "speaker": "Petre",
                    "npc": "Iolo",
                    "caller_guess": "",
                },
            },
        }

        expanded = module.expand_entry_for_voice_speakers(entry)

        self.assertEqual([e["npc"] for e in expanded], ["Petre"])
        self.assertEqual(module.make_filename(expanded[0], "en"), "0401_437_466_0_npc11.ogg")
        self.assertTrue(expanded[0]["_suppress_generic_fallback"])

    def test_contextual_rune_sign_entries_expand_to_party_speaker_voices(self):
        module = load_script_module()
        entry = {
            "npc": "",
            "zh_func_id": "0x095F",
            "zh_offset_key": "0",
            "zh_segment": 0,
            "zh_text": "「盧恩古文～」",
            "en_text": "Runic writing...",
        }

        expanded = module.expand_entry_for_voice_speakers(entry)
        by_npc = {e["npc"]: e for e in expanded}

        self.assertIn("Iolo", by_npc)
        self.assertIn("Shamino", by_npc)
        self.assertIn("Dupre", by_npc)
        self.assertNotIn("UNKNOWN", by_npc)
        self.assertEqual(module.make_filename(by_npc["Iolo"], "en"), "095f_0_0_npc1.ogg")
        self.assertTrue(all(e["_suppress_generic_fallback"] for e in expanded))

    def test_phase_b_dry_run_does_not_overwrite_existing_clone_prompts(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            module.REFS_DIR = tmpdir
            module.CLONE_PROMPTS_PATH = os.path.join(tmpdir, "clone_prompts.pkl")
            original = {"existing": {"zh": ["keep"], "en": ["keep"]}}
            with open(module.CLONE_PROMPTS_PATH, "wb") as f:
                pickle.dump(original, f)
            Path(tmpdir, "npc_iolo_zh_ref.ogg").write_bytes(b"fake")
            Path(tmpdir, "npc_iolo_en_ref.ogg").write_bytes(b"fake")

            designs = {
                "designs": {
                    "npc_iolo": {
                        "npc": "Iolo",
                        "npcs": ["Iolo"],
                        "ref_zh_text": "你好",
                        "ref_en_text": "Hello",
                    },
                },
            }
            args = argparse.Namespace(dry_run=True, device="cuda:0")

            prompts, built, errors = module.phase_b_build_prompts(designs, args)

            with open(module.CLONE_PROMPTS_PATH, "rb") as f:
                after = pickle.load(f)

            self.assertEqual((built, errors), (0, 0))
            self.assertEqual(prompts["npc_iolo"], {"zh": None, "en": None})
            self.assertEqual(after, original)
            self.assertEqual(FakeModel.create_prompt_calls, 0)

    def test_phase_c_refuses_to_generate_entry_with_noncanonical_runtime_key(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            module.ZH_OUTPUT = os.path.join(tmpdir, "zh")
            module.EN_OUTPUT = os.path.join(tmpdir, "en")
            module.MAPPING_PATH = str(tmp / "bilingual_mapping_review.json")
            module.EN_LINES_PATH = str(tmp / "en_voice_lines.csv")
            module.ZH_LINES_PATH = str(tmp / "zh_voice_lines.csv")

            Path(module.EN_LINES_PATH).write_text(
                "func_id,npc,speaker,caller_guess,offset_key,segment,total_segments,has_var,text\n"
                "0x0401,Iolo,Iolo,,0x748_0x765,0,1,True,\"\"\"Thou must see for thyself, <PLAYER_NAME>.\"\"\"\n",
                encoding="utf-8",
            )
            Path(module.ZH_LINES_PATH).write_text(
                "func_id,npc,speaker,caller_guess,offset_key,segment,total_segments,has_var,text\n",
                encoding="utf-8",
            )
            Path(module.MAPPING_PATH).write_text(
                json.dumps(
                    [
                        {
                            "npc": "Iolo",
                            "en_func_id": "0x08D8",
                            "en_offset_key": "748_765",
                            "en_segment": 0,
                            "en_text": '"Thou must see for thyself, Avatar."',
                        }
                    ]
                ),
                encoding="utf-8",
            )

            data, by_npc = module.load_mapping()
            self.assertEqual(data[0]["_invalid_runtime_keys"], ["en"])

            module.write_ogg_direct = lambda *args, **kwargs: self.fail("invalid row was generated")
            designs = {"designs": {"npc_iolo": {"npcs": ["Iolo"]}}}
            clone_prompts = {"npc_iolo": {"en": ["prompt"]}}
            args = argparse.Namespace(
                lang="en", dry_run=False, force=True, max_npcs=None, device="cuda:0"
            )

            generated, skipped, errors = module.phase_c_generate_voice(
                designs, clone_prompts, by_npc, args
            )

            self.assertEqual((generated, skipped, errors), (0, 0, 1))
            self.assertEqual(FakeModel.generate_voice_clone_calls, 0)

    def test_generic_fallback_does_not_replace_existing_different_file(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            npc_specific = os.path.join(tmpdir, "0401_e60_0_npc1.ogg")
            generic = os.path.join(tmpdir, "0401_e60_0.ogg")
            Path(npc_specific).write_bytes(b"npc")
            Path(generic).write_bytes(b"generic")

            module.create_generic_fallback(
                npc_specific,
                {
                    "npc": "Iolo",
                    "zh_func_id": "0401",
                    "zh_offset_key": "e60",
                    "zh_segment": 0,
                },
                "zh",
                tmpdir,
            )

            self.assertEqual(Path(generic).read_bytes(), b"generic")
            self.assertNotEqual(os.stat(generic).st_ino, os.stat(npc_specific).st_ino)

    def test_generic_fallback_copies_instead_of_hard_linking(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            npc_specific = os.path.join(tmpdir, "0401_e60_0_npc1.ogg")
            generic = os.path.join(tmpdir, "0401_e60_0.ogg")
            Path(npc_specific).write_bytes(b"npc")

            module.create_generic_fallback(
                npc_specific,
                {
                    "npc": "Iolo",
                    "zh_func_id": "0401",
                    "zh_offset_key": "e60",
                    "zh_segment": 0,
                },
                "zh",
                tmpdir,
            )

            self.assertEqual(Path(generic).read_bytes(), b"npc")
            self.assertNotEqual(os.stat(generic).st_ino, os.stat(npc_specific).st_ino)

    def test_prepare_voice_output_path_breaks_existing_hard_link(self):
        module = load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            generic = os.path.join(tmpdir, "0401_e60_0.ogg")
            npc_specific = os.path.join(tmpdir, "0401_e60_0_npc1.ogg")
            Path(generic).write_bytes(b"generic")
            os.link(generic, npc_specific)

            module.prepare_voice_output_path(npc_specific)
            Path(npc_specific).write_bytes(b"npc")

            self.assertEqual(Path(generic).read_bytes(), b"generic")
            self.assertEqual(Path(npc_specific).read_bytes(), b"npc")
            self.assertNotEqual(os.stat(generic).st_ino, os.stat(npc_specific).st_ino)

    def test_migrate_mode_returns_without_running_generation_phases(self):
        module = load_script_module()

        calls = []
        module.load_designs = lambda: {
            "_meta": {
                "total_designs": 1,
                "unique_designs": 1,
                "group_designs": 0,
                "narrator_designs": 0,
            },
            "designs": {},
        }
        module.load_mapping = lambda: ([], {})
        module.phase_migrate_existing = lambda data, by_npc, args: calls.append("migrate")
        module.phase_a_generate_refs = lambda designs, args: calls.append("refs")
        module.phase_b_build_prompts = lambda designs, args: calls.append("prompts") or ({}, 0, 0)
        module.phase_c_generate_voice = lambda designs, prompts, by_npc, args: calls.append("voice")

        old_argv = sys.argv
        sys.argv = ["generate_qwen3_voice.py", "--migrate"]
        try:
            module.main()
        finally:
            sys.argv = old_argv

        self.assertEqual(calls, ["migrate"])


class GenerateQwen3VoiceIntegrationTest(unittest.TestCase):
    def test_script_sets_numba_cache_dir_before_qwen_import(self):
        text = SCRIPT_PATH.read_text(encoding="utf-8")
        env_pos = text.find('os.environ.setdefault("NUMBA_CACHE_DIR"')
        import_pos = text.find("from qwen_tts import Qwen3TTSModel")

        self.assertNotEqual(env_pos, -1)
        self.assertNotEqual(import_pos, -1)
        self.assertLess(env_pos, import_pos)


if __name__ == "__main__":
    unittest.main()
