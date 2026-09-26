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


def dynamic_book_function(text_before="Book entry ", text_after=".",
                         function_id=0x0432):
    func = dynamic_function(text_before, text_after, function_id)
    func["instructions"].insert(
        0, (0x00F0, b"", "calli", [0x55, 0], ""))
    return func


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
            "label": "<PLAYER_NAME>",
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

    def test_named_semantic_placeholder_is_normalized_to_slot_ordinal(self):
        self.translations = {
            self.module.translation_source_sha256(self.line["source_template_en"]):
                "您好<PLAYER_NAME>。",
        }

        rows = self.build()

        self.assertEqual(rows[0]["source_template_zh"], "您好<VAR0>。")
        self.assertEqual(
            rows[0]["canonical_transcripts"]["default"]["zh"], "您好聖者。")

    def test_day_period_canonical_value_forms_natural_chinese(self):
        canonical = self.module.canonicalize_dynamic_template(
            "this fine <VAR0>", "在這美好的<VAR0>",
            [{"ordinal": 0, "semantic_type": "day_period"}],
        )

        self.assertEqual(canonical["zh"], "在這美好的一天")

    def test_reordered_dynamic_placeholders_remain_valid(self):
        canonical = self.module.canonicalize_dynamic_template(
            "I saw <VAR0> beside <VAR1>.",
            "我在<VAR1>旁看見<VAR0>。",
            [
                {"ordinal": 0, "semantic_type": "person_name"},
                {"ordinal": 1, "semantic_type": "place_name"},
            ],
        )

        self.assertEqual(canonical["zh"], "我在那個地方旁看見那個人。")

    def test_missing_dynamic_placeholder_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "preserve slot multiplicity"):
            self.module.canonicalize_dynamic_template(
                "I saw <VAR0> beside <VAR1>.", "我看見<VAR0>。", [
                    {"ordinal": 0, "semantic_type": "person_name"},
                    {"ordinal": 1, "semantic_type": "place_name"},
                ])

    def test_translation_audit_flags_repeated_day_period_tail_without_rewriting(self):
        func = dynamic_function(
            text_before="What can I do for thee this fine ", text_after="?")
        line = self.module.disassemble_usecode.extract_say_lines(func)[0]
        line_id = self.module.dynamic_line_id(line)
        source_hash = self.module.translation_source_sha256(
            line["source_template_en"])
        translation = "在這美好的<VAR0>，我能為你做些什麼？一天?"
        records = self.module.build_dynamic_voice_manifest(
            [func],
            translation_templates={source_hash: translation},
            role_records=[{
                "function_id": line["func_id"],
                "offset_key": line["offset_key"],
                "segment": line["segment"],
                "role": "speaker",
            }],
            overrides={line_id: {
                "slots": {"0": {"semantic_type": "day_period"}},
            }},
        )

        findings = self.module.audit_dynamic_voice_translations(records)

        self.assertTrue(any(
            item == {
                "line_id": line_id,
                "language": "zh",
                "rule": "suspicious-trailing-phrase",
                "severity": "warning",
                "text": translation,
            }
            for item in findings
        ))
        self.assertEqual(records[0]["source_template_zh"], translation)
        self.assertTrue(self.module.validate_dynamic_voice_manifest(records))

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
            [span["role"] for span in rows[0]["role_spans"]],
            ["speaker", "narrator"],
        )
        self.assertEqual(
            [span["requires_audio"] for span in rows[0]["role_spans"]],
            [True, False],
        )
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

    def test_translation_uses_exact_function_offset_and_segment_before_hash(self):
        source_hash = self.module.translation_source_sha256(
            self.line["source_template_en"])
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "zh_translation.tsv"
            exact_key = (
                f"dialogue:0x{self.line['func_id']:04x}:"
                f"{self.module._offset_key(self.line['offset_key'])}:"
                f"{self.line['segment']}"
            )
            other_key = "dialogue:0x0999:0:0"
            path.write_text(
                "# u6-translation-v1\n"
                f"dialogue\t{exact_key}\t{source_hash}\t您好<VAR0>。\n"
                f"dialogue\t{other_key}\t{source_hash}\t嗨<VAR0>。\n",
                encoding="utf-8",
            )
            translations = self.module.load_zh_translation_templates(path)

        row = self.build(translation_templates=translations)[0]
        self.assertEqual(row["source_template_zh"], "您好<VAR0>。")

    def test_full_template_hash_row_wins_over_stale_line_offset_key(self):
        source_template = self.line["source_template_en"]
        source_hash = self.module.translation_source_sha256(source_template)
        function_id = int(self.line["func_id"])
        segment = int(self.line["segment"])
        line_key = (
            f"dialogue:0x{function_id:04x}:"
            f"{self.module._offset_key(self.line['offset_key'])}:{segment}"
        )
        fallback_key = (
            f"dialogue:0x{function_id:04x}:"
            f"fallback_{source_hash[:16]}:0"
        )
        rows = [
            "# u6-translation-v1",
            f"dialogue\t{line_key}\t"
            f"{self.module.translation_source_sha256('unrelated source')}\t"
            "錯誤的偏移翻譯",
            f"dialogue\t{fallback_key}\t{source_hash}\t您好<VAR0>。",
        ]
        literal_translations = ("錯誤片段", "錯誤結尾")
        for part, translated in zip(
                (part for part in self.line["source_parts"]
                 if part["kind"] == "literal"),
                literal_translations):
            part_key = (
                f"dialogue:0x{int(part['source_func_id']):04x}:"
                f"{int(part['string_offset']):x}:{segment}"
            )
            rows.append(
                f"dialogue\t{part_key}\t"
                f"{self.module.translation_source_sha256(part['text'])}\t"
                f"{translated}"
            )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "zh_translation.tsv"
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            translations = self.module.load_zh_translation_templates(path)

        row = self.build(translation_templates=translations)[0]
        self.assertEqual(row["source_template_zh"], "您好<VAR0>。")

    def test_dynamic_line_composes_hant_source_from_literal_fragment_keys(self):
        literal_parts = [
            part for part in self.line["source_parts"]
            if part["kind"] == "literal"
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "zh_translation.tsv"
            rows = ["# u6-translation-v1"]
            for part, translated in zip(literal_parts, ("您好", "。")):
                source_hash = self.module.translation_source_sha256(part["text"])
                key = (
                    f"dialogue:0x{part['source_func_id']:04x}:"
                    f"{part['string_offset']:x}:0"
                )
                rows.append(f"dialogue\t{key}\t{source_hash}\t{translated}")
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            translations = self.module.load_zh_translation_templates(path)

        row = self.build(translation_templates=translations)[0]
        self.assertEqual(row["source_template_zh"], "您好<VAR0>。")

    def test_translation_composition_preserves_unmapped_whitespace_fragments(self):
        line = {
            "segment": 0,
            "source_parts": [
                {"kind": "literal", "source_func_id": 0x0431,
                 "source_offset": 0x0100, "string_offset": 0x0600,
                 "text": "@Greeting "},
                {"kind": "dynamic", "ordinal": 0},
                {"kind": "literal", "source_func_id": 0x0431,
                 "source_offset": 0x0108, "string_offset": 0x0605,
                 "text": " "},
                {"kind": "dynamic", "ordinal": 1},
                {"kind": "literal", "source_func_id": 0x0431,
                 "source_offset": 0x010C, "string_offset": 0x0610,
                 "text": ".@"},
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "zh_translation.tsv"
            first_hash = self.module.translation_source_sha256("@Greeting ")
            last_hash = self.module.translation_source_sha256(".@")
            path.write_text(
                "# u6-translation-v1\n"
                f"dialogue\tdialogue:0x0431:600:0\t{first_hash}\t@問候\n"
                f"dialogue\tdialogue:0x0431:610:0\t{last_hash}\t。@\n",
                encoding="utf-8",
            )
            translations = self.module.load_zh_translation_templates(path)

        self.assertEqual(
            self.module._compose_zh_translation_from_parts(line, translations),
            "@問候<VAR0> <VAR1>。@",
        )

    def test_context_classifies_greeting_name_number_and_direction_slots(self):
        classify = self.module.classify_contextual_dynamic_slots
        unknown = lambda ordinal: {
            "ordinal": ordinal, "semantic_type": "unknown",
        }

        greeting = classify("@Good <VAR0>, <VAR1>.@", [unknown(0), unknown(1)])
        self.assertEqual(
            [slot["semantic_type"] for slot in greeting],
            ["greeting_time", "player_name"],
        )
        canonical = self.module.canonicalize_dynamic_template(
            "Good <VAR0>", "<VAR0>", greeting[:1])
        self.assertEqual(canonical, {"en": "Good day", "zh": "日安"})

        self.assertEqual(
            classify("Avatar karma is :@ <VAR0>", [unknown(0)])[0][
                "semantic_type"],
            "numeric_value",
        )
        self.assertEqual(
            classify("NPC training points are <VAR0>", [unknown(0)])[0][
                "semantic_type"],
            "numeric_value",
        )
        self.assertEqual(
            classify("hour is <VAR0>", [unknown(0)])[0][
                "semantic_type"],
            "numeric_value",
        )
        self.assertEqual(
            classify("you only have <VAR0> coins", [unknown(0)])[0][
                "semantic_type"],
            "number",
        )
        self.assertEqual(
            classify("travel <VAR0> to the River Maelstrom", [unknown(0)])[0][
                "semantic_type"],
            "direction",
        )
        self.assertEqual(
            classify("heading <VAR0> from here", [unknown(0)])[0][
                "semantic_type"],
            "direction",
        )
        self.assertEqual(
            classify("Careful <VAR0>, these guards are close", [unknown(0)])[0][
                "semantic_type"],
            "player_name",
        )
        self.assertEqual(
            classify("@Well <VAR0>, it is thy lucky day", [unknown(0)])[0][
                "semantic_type"],
            "player_name",
        )
        self.assertEqual(
            classify("Ah! <VAR0>, you have an injury", [unknown(0)])[0][
                "semantic_type"],
            "player_name",
        )
        self.assertEqual(
            classify("@Aye, <VAR0>, I can tell you are poisoned", [unknown(0)])[0][
                "semantic_type"],
            "player_name",
        )
        self.assertEqual(
            classify("<VAR0>, your injury is serious", [unknown(0)])[0][
                "semantic_type"],
            "player_name",
        )
        self.assertEqual(
            classify("Does <VAR0> drink it?", [unknown(0)])[0][
                "semantic_type"],
            "person_name",
        )
        self.assertEqual(
            classify("Thou hast much to learn about <VAR0>", [unknown(0)])[0][
                "semantic_type"],
            "topic_name",
        )
        self.assertEqual(
            [slot["semantic_type"] for slot in classify(
                "We have <VAR0> yellow potions, <VAR1> red potions, and "
                "<VAR2> bandages remaining",
                [unknown(0), unknown(1), unknown(2)],
            )],
            ["number", "number", "number"],
        )
        self.assertEqual(
            classify("do this <VAR0>?", [unknown(0)])[0][
                "semantic_type"],
            "day_period",
        )
        self.assertEqual(
            classify("The jailer nods and says g'<VAR0>.@", [unknown(0)])[0][
                "semantic_type"],
            "greeting_time",
        )
        self.assertEqual(
            classify("Have a nice <VAR0>.", [unknown(0)])[0][
                "semantic_type"],
            "greeting_time",
        )
        self.assertEqual(
            classify("<VAR0><VAR1>", [unknown(0), unknown(1)])[0][
                "semantic_type"],
            "unknown",
        )

    def test_semantic_type_can_be_shared_across_expression_variants(self):
        resolve = self.module.semantic_types_from_expression_variants
        unknown = {
            "kind": "dynamic", "source_func_id": 0x044E,
            "source_offset": 0x00E5, "variable_index": 16,
            "semantic_type": "unknown",
        }
        known = dict(unknown, semantic_type="player_name")

        inferred = resolve([
            {"source_parts": [unknown]},
            {"source_parts": [known]},
        ])

        self.assertEqual(inferred, {(0x044E, 0x00E5, 16): "player_name"})

    def test_topic_name_has_generic_bilingual_canonical_value(self):
        transcript = self.module.canonicalize_dynamic_template(
            "Thou hast much to learn about <VAR0>",
            "關於<VAR0>，你還有很多需要學習。",
            [{"ordinal": 0, "semantic_type": "topic_name"}],
        )

        self.assertEqual(transcript, {
            "en": "Thou hast much to learn about this subject",
            "zh": "關於這個主題，你還有很多需要學習。",
        })

    def test_reviewed_whole_span_override_produces_complete_role_transcript(self):
        override = {
            "slots": {"0": {"semantic_type": "unknown"}},
            "whole_span": {
                "en": "Hello, traveler.",
                "zh": "旅人，你好。",
            },
        }
        rows = self.build(overrides={self.line_id: override})

        self.assertEqual(rows[0]["canonical_transcripts"]["default"], {
            "en": "Hello, traveler.", "zh": "旅人，你好。",
        })
        self.assertEqual(rows[0]["role_spans"][0]["transcripts"]["default"], {
            "en": "Hello, traveler.", "zh": "旅人，你好。",
        })

    def test_hash_pinned_whole_span_override_rejects_stale_source(self):
        override = {
            "slots": {"0": {"semantic_type": "unknown"}},
            "whole_span": {
                "en": "Hello, traveler.",
                "zh": "旅人，你好。",
                "source_sha256": "0" * 64,
            },
        }

        with self.assertRaisesRegex(ValueError, "whole-span source hash is stale"):
            self.build(overrides={self.line_id: override})

    def test_explicit_exclusion_requires_matching_source_and_no_speech_route(self):
        func = dynamic_function(text_before="Value is ", text_after=".")
        line = self.module.disassemble_usecode.extract_say_lines(func)[0]
        line_id = self.module.dynamic_line_id(line)
        exclusion = {
            "line_id": line_id,
            "source_sha256": self.module.translation_source_sha256(
                line["source_template_en"]),
            "category": "ui_fragment",
            "reason": "A markerless UI value label, not conversational speech.",
        }

        rows = self.module.build_dynamic_voice_manifest(
            [func], translation_templates={}, role_records=[],
            overrides={}, exclusions={line_id: exclusion})

        self.assertEqual(rows, [])

    def test_every_dynamic_fixture_is_emitted_or_exactly_excluded(self):
        book_func = dynamic_book_function()
        book_line = self.module.disassemble_usecode.extract_say_lines(book_func)[0]
        book_line_id = self.module.dynamic_line_id(book_line)
        book_exclusion = {
            "schema": "u6-dynamic-voice-exclusion-v1",
            "line_id": book_line_id,
            "source_sha256": self.module.translation_source_sha256(
                book_line["source_template_en"]),
            "source_template_en": book_line["source_template_en"],
            "category": "book_text",
            "reason": "A dynamic book page, not spoken conversation.",
        }

        rows = self.module.build_dynamic_voice_manifest(
            [self.func, book_func],
            translation_templates=self.translations,
            role_records=self.roles,
            overrides=self.overrides,
            exclusions={book_line_id: book_exclusion},
        )

        self.assertEqual([row["line_id"] for row in rows], [self.line_id])

    def test_dynamic_book_text_requires_explicit_exclusion(self):
        book_func = dynamic_book_function()

        with self.assertRaisesRegex(ValueError, "book.*exclusion"):
            self.module.build_dynamic_voice_manifest(
                [book_func], translation_templates={}, role_records=[],
                overrides={}, exclusions={})

    def test_book_text_exclusion_cannot_hide_a_role_marked_line(self):
        book_func = dynamic_book_function("@A spoken book line ", "@.")
        line = self.module.disassemble_usecode.extract_say_lines(book_func)[0]
        line_id = self.module.dynamic_line_id(line)
        exclusion = {
            "schema": "u6-dynamic-voice-exclusion-v1",
            "line_id": line_id,
            "source_sha256": self.module.translation_source_sha256(
                line["source_template_en"]),
            "source_template_en": line["source_template_en"],
            "category": "book_text",
            "reason": "not speech",
        }
        roles = [{
            "function_id": line["func_id"],
            "offset_key": line["offset_key"],
            "segment": line["segment"],
            "role": "speaker",
        }]

        with self.assertRaisesRegex(ValueError, "cannot exclude.*role|marker"):
            self.module.build_dynamic_voice_manifest(
                [book_func], translation_templates={}, role_records=roles,
                overrides={}, exclusions={line_id: exclusion})

    def test_book_text_exclusion_category_is_source_pinned_and_loadable(self):
        book_func = dynamic_book_function()
        line = self.module.disassemble_usecode.extract_say_lines(book_func)[0]
        line_id = self.module.dynamic_line_id(line)
        exclusion = {
            "schema": "u6-dynamic-voice-exclusion-v1",
            "line_id": line_id,
            "source_sha256": self.module.translation_source_sha256(
                line["source_template_en"]),
            "source_template_en": line["source_template_en"],
            "category": "book_text",
            "reason": "A dynamic book page, not spoken conversation.",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "exclusions.jsonl"
            path.write_text(json.dumps(exclusion) + "\n", encoding="utf-8")

            loaded = self.module.load_dynamic_voice_exclusions(path)

        self.assertEqual(loaded, {line_id: exclusion})

    def test_book_text_exclusion_cannot_be_applied_to_dialogue(self):
        exclusion = {
            "schema": "u6-dynamic-voice-exclusion-v1",
            "line_id": self.line_id,
            "source_sha256": self.module.translation_source_sha256(
                self.line["source_template_en"]),
            "source_template_en": self.line["source_template_en"],
            "category": "book_text",
            "reason": "not speech",
        }

        with self.assertRaisesRegex(ValueError, "book_text.*book|not book"):
            self.build(exclusions={self.line_id: exclusion})

    def test_exclusion_cannot_hide_role_marked_or_reviewed_dialogue(self):
        exclusion = {
            "line_id": self.line_id,
            "source_sha256": self.module.translation_source_sha256(
                self.line["source_template_en"]),
            "category": "ui_fragment",
            "reason": "not speech",
        }

        with self.assertRaisesRegex(ValueError, "cannot exclude.*role|cannot exclude.*marker"):
            self.build(exclusions={self.line_id: exclusion})

    def test_reviewed_debug_output_exclusion_can_hide_only_debug_function_speech(self):
        func = dynamic_function(
            text_before="@Avatar karma is: ", text_after="@",
            function_id=0x03BB)
        line = self.module.disassemble_usecode.extract_say_lines(func)[0]
        line_id = self.module.dynamic_line_id(line)
        exclusion = {
            "schema": "u6-dynamic-voice-exclusion-v1",
            "line_id": line_id,
            "function_id": 0x03BB,
            "source_sha256": self.module.translation_source_sha256(
                line["source_template_en"]),
            "source_template_en": line["source_template_en"],
            "category": "debug_output",
            "reason": "Debug-menu output from compiled usecode function 0x03BB.",
        }

        rows = self.module.build_dynamic_voice_manifest(
            [func], translation_templates={}, role_records=[],
            overrides={}, exclusions={line_id: exclusion})

        self.assertEqual(rows, [])

    def test_debug_output_exclusion_cannot_be_reused_for_another_function(self):
        func = dynamic_function(
            text_before="@Hello ", text_after="@.", function_id=0x0431)
        line = self.module.disassemble_usecode.extract_say_lines(func)[0]
        line_id = self.module.dynamic_line_id(line)
        exclusion = {
            "line_id": line_id,
            "function_id": 0x03BB,
            "source_sha256": self.module.translation_source_sha256(
                line["source_template_en"]),
            "category": "debug_output",
            "reason": "Debug-menu output.",
        }

        with self.assertRaisesRegex(ValueError, "debug-output exclusion.*audited function"):
            self.module.build_dynamic_voice_manifest(
                [func], translation_templates={}, role_records=[],
                overrides={}, exclusions={line_id: exclusion})

    def test_reviewed_speaker_route_override_is_hash_pinned_and_recorded(self):
        func = dynamic_function(
            text_before="@Don't worry about her, ", text_after=". She is safe.@",
            function_id=0x0BCE)
        line = self.module.disassemble_usecode.extract_say_lines(func)[0]
        line_id = self.module.dynamic_line_id(line)
        source_hash = self.module.translation_source_sha256(
            line["source_template_en"])
        override = {
            "slots": {"0": {"semantic_type": "honorific"}},
            "speaker_route": {
                "targets": ["Michael"],
                "source_sha256": source_hash,
                "evidence": "The compiled caller sets the active face from itemref; this is Michael's dialogue path.",
            },
        }
        translations = {
            source_hash: "@別為她擔心，<VAR0>。她很安全。@",
        }
        roles = [{
            "function_id": line["func_id"],
            "offset_key": line["offset_key"],
            "segment": line["segment"],
            "role": "speaker",
        }]

        rows = self.module.build_dynamic_voice_manifest(
            [func], translation_templates=translations,
            role_records=roles, overrides={line_id: override})

        self.assertEqual(rows[0]["speaker"], "Michael")
        self.assertEqual(rows[0]["speaker_route_source"], "reviewed-usecode-override")
        self.assertEqual(rows[0]["speaker_route_evidence"], override["speaker_route"]["evidence"])

    def test_speaker_route_override_rejects_stale_source_hash(self):
        override = {
            **self.overrides[self.line_id],
            "speaker_route": {
                "targets": ["Michael"],
                "source_sha256": "0" * 64,
                "evidence": "Compiled caller face routing.",
            },
        }

        with self.assertRaisesRegex(ValueError, "speaker route.*stale|speaker route.*hash"):
            self.build(overrides={self.line_id: override})

    def test_exclusion_ledger_rejects_unmatched_entries(self):
        stale = {
            "line_id": "stale-line",
            "source_sha256": "0" * 64,
            "category": "ui_fragment",
            "reason": "Old extracted line.",
        }

        with self.assertRaisesRegex(ValueError, "unmatched exclusion"):
            self.build(exclusions={"stale-line": stale})

    def test_debug_output_exclusion_loader_requires_the_audited_function_id(self):
        func = dynamic_function(
            text_before="@Debug value ", text_after="@", function_id=0x03BB)
        line = self.module.disassemble_usecode.extract_say_lines(func)[0]
        record = {
            "schema": "u6-dynamic-voice-exclusion-v1",
            "line_id": self.module.dynamic_line_id(line),
            "function_id": 0x03BB,
            "source_sha256": self.module.translation_source_sha256(
                line["source_template_en"]),
            "source_template_en": line["source_template_en"],
            "category": "debug_output",
            "reason": "Output from the compiled debug menu.",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "exclusions.jsonl"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            loaded = self.module.load_dynamic_voice_exclusions(path)
            self.assertIn(record["line_id"], loaded)

            record["function_id"] = 0x0431
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "debug-output exclusion must name an audited function"):
                self.module.load_dynamic_voice_exclusions(path)

    def test_repeated_dynamic_origin_shares_contextually_inferred_person_type(self):
        source = (
            "<VAR0> and Thariand dive into the pages of several tomes. "
            "Following an extensive study session, <VAR1> finds the ability "
            "to comprehend more. In addition, <VAR2> has a better grasp."
        )
        origin = {
            "kind": "dynamic", "source_func_id": 0x049E,
            "source_offset": 0x0259, "variable_index": 34,
            "semantic_type": "unknown",
        }
        line = {
            "source_template_en": source,
            "source_parts": [dict(origin, ordinal=index)
                             for index in range(3)],
        }

        inferred = self.module.semantic_types_from_expression_variants([line])

        self.assertEqual(inferred, {(0x049E, 0x0259, 34): "person_name"})

    def test_single_role_chinese_quote_translation_keeps_source_role(self):
        source = "@None of us are carrying any gold, <VAR0>.@"
        canonical = {
            "default": {
                "en": "@None of us are carrying any gold, milord.@",
                "zh": "「我們沒有人隨身攜帶黃金，大人。",
            },
        }

        spans = self.module._build_role_spans(
            source, canonical, explicit_role=None, line_id="test-line")

        self.assertEqual([span["role"] for span in spans], ["speaker"])
        self.assertEqual(
            spans[0]["transcripts"]["default"]["zh"],
            "「我們沒有人隨身攜帶黃金，大人。",
        )

    def test_chinese_quotation_preserves_mixed_speaker_narrator_order(self):
        source = "Narrator intro. @Speaker words@ Narrator end."
        canonical = {
            "default": {
                "en": "Narrator intro. @Speaker words@ Narrator end.",
                "zh": "敘述開頭。「角色台詞」敘述結尾。",
            },
        }

        spans = self.module._build_role_spans(
            source, canonical, explicit_role=None, line_id="mixed-line")

        self.assertEqual(
            [span["role"] for span in spans],
            ["narrator", "speaker", "narrator"],
        )

    def test_unclosed_chinese_speaker_quote_can_extend_to_line_end(self):
        canonical = {
            "default": {
                "en": "Dupre whispers, @A message for you.@",
                "zh": "杜培低聲說：「有個消息要告訴你。",
            },
        }

        spans = self.module._build_role_spans(
            "Dupre whispers, @A message for you.@", canonical,
            explicit_role=None, line_id="trailing-speaker-line")

        self.assertEqual([span["role"] for span in spans], [
            "narrator", "speaker",
        ])

    def test_single_hant_at_marker_uses_source_order_for_mixed_roles(self):
        source = "He bows stiffly. @Well met, Avatar.@"
        canonical = {
            "default": {
                "en": "He bows stiffly. @Well met, Avatar.@",
                "zh": "他僵硬地鞠躬。 @幸會，聖者。",
            },
        }

        spans = self.module._build_role_spans(
            source, canonical, explicit_role=None, line_id="mixed-marker-line")

        self.assertEqual(
            [span["role"] for span in spans], ["narrator", "speaker"])
        self.assertIn("僵硬地鞠躬", spans[0]["transcripts"]["default"]["zh"])
        self.assertIn("幸會", spans[1]["transcripts"]["default"]["zh"])

    def test_hant_sentence_boundaries_align_roles_when_markers_are_absent(self):
        source = (
            "@Hello Avatar, welcome to my home.@ "
            "Her eyes are as blue as the ocean."
        )
        canonical = {
            "default": {
                "en": source,
                "zh": "你好，聖者，歡迎來到我家。她的眼睛蔚藍如海。",
            },
        }

        spans = self.module._build_role_spans(
            source, canonical, explicit_role=None,
            line_id="sentence-role-boundary")

        self.assertEqual(
            [span["role"] for span in spans], ["speaker", "narrator"])
        self.assertIn("歡迎", spans[0]["transcripts"]["default"]["zh"])
        self.assertIn("眼睛", spans[1]["transcripts"]["default"]["zh"])

    def test_sentence_alignment_keeps_multiple_sentences_in_one_role_span(self):
        source = "Her face is stern. @Wait here. I will return.@"
        canonical = {
            "default": {
                "en": source,
                "zh": "她的神情很嚴肅。請在這裡等候。我會回來。",
            },
        }

        spans = self.module._build_role_spans(
            source, canonical, explicit_role=None,
            line_id="multi-sentence-role-boundary")

        self.assertEqual([span["role"] for span in spans], [
            "narrator", "speaker",
        ])
        self.assertEqual(spans[0]["transcripts"]["default"]["zh"],
                         "她的神情很嚴肅。")
        self.assertEqual(spans[1]["transcripts"]["default"]["zh"],
                         "請在這裡等候。我會回來。")

    def test_narrator_speech_attribution_splits_from_dynamic_speaker_sentence(self):
        source = (
            "@The path of the Avatar lies beneath thy feet, worthy <VAR0>@, "
            "the gypsy intones. With a mysterious smile, she passes you the "
            "flask of shimmering liquids."
        )
        canonical = {
            "default": {
                "en": source,
                "zh": (
                    "聖者之路就在你腳下，可敬的<VAR0>，吉普賽人吟誦著。"
                    "帶著神祕的微笑，她將一瓶閃爍的液體遞給你。"
                ),
            },
        }

        spans = self.module._build_role_spans(
            source, canonical, explicit_role=None,
            line_id="speaker-followed-by-attribution")

        self.assertEqual([span["role"] for span in spans], [
            "speaker", "narrator",
        ])
        self.assertNotIn("吉普賽人吟誦", spans[0]["transcripts"]["default"]["zh"])
        self.assertIn("吉普賽人吟誦", spans[1]["transcripts"]["default"]["zh"])

    def test_hant_closing_and_opening_quotes_align_three_mixed_roles(self):
        source = (
            "@Not now, Avatar,@ he says timidly. "
            "@My shop is closed.@"
        )
        canonical = {
            "default": {
                "en": source,
                "zh": "現在不行，聖者，」他怯怯地說。「我的店關門了。」",
            },
        }

        spans = self.module._build_role_spans(
            source, canonical, explicit_role=None,
            line_id="three-role-quote-boundaries")

        self.assertEqual(
            [span["role"] for span in spans],
            ["speaker", "narrator", "speaker"],
        )
        self.assertIn("現在不行", spans[0]["transcripts"]["default"]["zh"])
        self.assertIn("怯怯地說", spans[1]["transcripts"]["default"]["zh"])
        self.assertIn("店關門了", spans[2]["transcripts"]["default"]["zh"])

    def test_punctuation_after_chinese_speaker_marker_needs_no_narrator_clip(self):
        canonical = {
            "default": {
                "en": "@Hello Avatar@",
                "zh": "@您好聖者@。",
            },
        }

        spans = self.module._build_role_spans(
            "@Hello <VAR0>@", canonical,
            explicit_role=None, line_id="punctuation-line")

        self.assertEqual([span["role"] for span in spans], ["speaker"])

    def test_drops_untranslated_tail_after_source_terminal_role_marker(self):
        source = "@A long sentence ends here.@"
        translated = "一段完整的長句。@@ Shrine of Compassion"

        clean = self.module.sanitize_dynamic_voice_translation(
            source, translated)

        self.assertEqual(clean, "一段完整的長句。@@")
        spans = self.module._build_role_spans(
            source,
            {"default": {
                "en": source,
                "zh": clean,
            }},
            explicit_role=None, line_id="translation-tail-line")
        self.assertEqual([span["role"] for span in spans], ["speaker"])

    def test_translation_sanitizer_does_not_confuse_slot_token_with_latin_tail(self):
        source = "@My name's Wilbur, <VAR0>.@"
        translated = "@我叫Wilbur，<VAR0>。"

        self.assertEqual(
            self.module.sanitize_dynamic_voice_translation(source, translated),
            translated,
        )

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
            report_path = root / "translation_audit.json"

            args = [
                "--usecode-file", str(root / "usecode"),
                "--translation-tsv", str(translation_path),
                "--roles-manifest", str(roles_path),
                "--overrides", str(overrides_path),
                "--output", str(output_path), "--check",
                "--translation-report", str(report_path),
            ]
            with mock.patch.object(self.module, "_read_functions", return_value=[self.func]):
                self.assertEqual(self.module.main(args), 0)

            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8")), [])
            self.assertEqual(output_path.read_text(encoding="utf-8"),
                             self.module._jsonl(expected))


if __name__ == "__main__":
    unittest.main()
