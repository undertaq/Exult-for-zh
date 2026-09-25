import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).with_name("build_u6_dynamic_voice_manifest.py")


def load_module(test_case):
    if not MODULE_PATH.is_file():
        test_case.fail("build_u6_dynamic_voice_manifest.py has not been implemented")
    spec = importlib.util.spec_from_file_location(
        "build_u6_dynamic_voice_manifest_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dynamic_function(text_before="Hello ", text_after=".", function_id=0x0431):
    instructions = [(0x0100, b"", "addsi", [0x0600], "")]
    strings = {0x0600: text_before}
    if text_before:
        instructions[0] = (0x0100, b"", "addsi", [0x0600], "")
    instructions.append((0x0104, b"", "addsv", [7], ""))
    if text_after:
        strings[0x0610] = text_after
        instructions.append((0x0108, b"", "addsi", [0x0610], ""))
    instructions.append((0x010C, b"", "say", [], ""))
    return {
        "id": function_id,
        "instructions": instructions,
        "strings": strings,
        "externs": [],
    }


class BuildU6DynamicVoiceManifestTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module(self)
        catalog = Path(__file__).resolve().parents[2] / "u6_voice/u6_npc_catalog.tsv"
        self.module.disassemble_usecode.load_npc_catalog(catalog)
        self.func = dynamic_function()
        self.line = self.module.disassemble_usecode.extract_say_lines(self.func)[0]
        self.line_id = self.module.dynamic_line_id(self.line)
        self.roles = [{
            "function_id": self.line["func_id"],
            "offset_key": self.line["offset_key"],
            "segment": self.line["segment"],
            "role": "speaker",
            "role_source": "markers",
        }]
        self.overrides = {self.line_id: {
            "slots": {"0": {"semantic_type": "player_name"}},
        }}
        self.translations = {
            self.module.translation_source_sha256(self.line["source_template_en"]):
                "您好<VAR0>。",
        }

    def build(self, **overrides):
        args = {
            "translation_templates": self.translations,
            "role_records": self.roles,
            "overrides": self.overrides,
        }
        args.update(overrides)
        return self.module.build_dynamic_voice_manifest([self.func], **args)

    def test_manifest_contains_identity_transcripts_roles_and_source_provenance(self):
        rows = self.build()

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertRegex(row["key"], r"^dyn_[0-9a-f]{64}$")
        self.assertEqual(row["source_template_en"], "Hello <VAR0>.")
        self.assertEqual(row["source_template_zh"], "您好<VAR0>。");
        self.assertEqual(row["canonical_transcripts"], {
            "default": {"en": "Hello Avatar.", "zh": "您好聖者。"},
        })
        self.assertEqual(row["slots"], [{
            "ordinal": 0,
            "label": "<VAR>",
            "semantic_type": "player_name",
            "source_func_id": 0x0431,
            "source_offset": 0x0104,
            "variable_index": 7,
        }])
        self.assertEqual(row["role_spans"][0]["role"], "speaker")
        self.assertEqual(
            row["role_spans"][0]["transcripts"],
            {"default": {"en": "Hello Avatar.", "zh": "您好聖者。"}},
        )

    def test_player_gender_variants_apply_even_when_npc_is_speaker(self):
        func = dynamic_function(text_before="@He saw ", text_after="@.")
        line = self.module.disassemble_usecode.extract_say_lines(func)[0]
        line_id = self.module.dynamic_line_id(line)
        translations = {
            self.module.translation_source_sha256(line["source_template_en"]):
                "@他看見<VAR0>@。",
        }
        overrides = {line_id: {"slots": {"0": {
            "semantic_type": "pronoun", "pronoun_form": "object",
        }}}}
        roles = [{
            "function_id": line["func_id"], "offset_key": line["offset_key"],
            "segment": line["segment"], "role": "mixed",
        }]

        rows = self.module.build_dynamic_voice_manifest(
            [func], translation_templates=translations,
            role_records=roles, overrides=overrides)

        self.assertEqual(rows[0]["speaker"], "Wanda")
        self.assertEqual(rows[0]["player_gender_variants"], ["male", "female"])
        self.assertEqual(
            [span["transcripts"] for span in rows[0]["role_spans"]],
            [
                {
                    "male": {"en": "He saw him", "zh": "他看見他"},
                    "female": {"en": "He saw her", "zh": "他看見她"},
                },
                {
                    "male": {"en": ".", "zh": "。"},
                    "female": {"en": ".", "zh": "。"},
                },
            ],
        )

    def test_missing_translation_unknown_slot_and_role_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "missing.*translation"):
            self.build(translation_templates={})

        with self.assertRaisesRegex(ValueError, "unknown.*VAR0|VAR0.*unknown"):
            self.build(overrides={})

        with self.assertRaisesRegex(ValueError, "role"):
            self.build(role_records=[])

    def test_check_rejects_unresolved_tokens_and_conflicting_duplicate_keys(self):
        validate = getattr(self.module, "validate_dynamic_voice_manifest", None)
        self.assertTrue(callable(validate), "strict manifest validator is missing")
        rows = self.build()
        bad = dict(rows[0])
        bad["role_spans"] = [dict(rows[0]["role_spans"][0])]
        bad["role_spans"][0]["transcripts"] = {
            "default": {"en": "Hello <VAR0>.", "zh": "您好聖者。"}}
        with self.assertRaisesRegex(ValueError, "unresolved|placeholder"):
            validate([bad])

        conflicting = dict(rows[0])
        conflicting["source_template_en"] = "different <VAR0>"
        with self.assertRaisesRegex(ValueError, "conflicting duplicate key"):
            validate([rows[0], conflicting])

    def test_cli_check_accepts_explicit_inputs_and_verifies_existing_jsonl(self):
        expected = self.build()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            translation_path = root / "zh_translation.tsv"
            translation_hash = self.module.translation_source_sha256(
                self.line["source_template_en"])
            translation_path.write_text(
                "# u6-translation-v1\n"
                "# kind\tkey\tsource_sha256\tzh\n"
                f"dialogue\tfixture\t{translation_hash}\t您好<VAR0>。\n",
                encoding="utf-8",
            )
            roles_path = root / "roles.jsonl"
            roles_path.write_text(
                "\n".join(json.dumps(row) for row in self.roles) + "\n",
                encoding="utf-8",
            )
            overrides_path = root / "overrides.json"
            overrides_path.write_text(json.dumps(self.overrides), encoding="utf-8")
            output_path = root / "manifest.jsonl"
            output_path.write_text(self.module._jsonl(expected), encoding="utf-8")

            args = [
                "--usecode-file", str(root / "usecode"),
                "--translation-tsv", str(translation_path),
                "--roles-manifest", str(roles_path),
                "--overrides", str(overrides_path),
                "--output", str(output_path), "--check",
            ]
            with mock.patch.object(self.module, "_read_functions", return_value=[self.func]):
                self.assertEqual(self.module.main(args), 0)


if __name__ == "__main__":
    unittest.main()
