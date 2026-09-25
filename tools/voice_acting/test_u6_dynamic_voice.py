import importlib.util
import json
from pathlib import Path
import tempfile
from copy import deepcopy
import unittest


MODULE_PATH = Path(__file__).with_name("u6_dynamic_voice.py")


def load_module(test_case):
    if not MODULE_PATH.is_file():
        test_case.fail("u6_dynamic_voice.py has not been implemented")
    spec = importlib.util.spec_from_file_location("u6_dynamic_voice_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class U6DynamicVoiceTest(unittest.TestCase):
    def _get_api(self, name):
        module = load_module(self)
        function = getattr(module, name, None)
        self.assertTrue(callable(function), f"{name} has not been implemented")
        return module, function

    def test_source_normalization_matches_runtime_latin1_and_utf8_rules(self):
        module = load_module(self)

        self.assertEqual(
            module.normalize_translation_source(b"Good\r\nbye\r\x92"),
            "Good\nbye\n\u0092",
        )
        self.assertEqual(
            module.normalize_translation_source(b"caf\xc3\xa9\r"),
            "café\n",
        )

    def test_translation_hash_looks_up_the_hant_template_without_losing_slots(self):
        module = load_module(self)
        load_templates = getattr(module, "load_zh_translation_templates", None)
        lookup = getattr(module, "lookup_zh_translation_template", None)
        self.assertTrue(callable(load_templates), "zh translation TSV loader is missing")
        self.assertTrue(callable(lookup), "zh source-template lookup is missing")
        source_template = "Hello <VAR0>."
        expected_sha256 = "15751d205b6065eddb132ed381316cbec3501d826f1a9b690ea8743bd1b51661"
        self.assertEqual(module.translation_source_sha256(source_template), expected_sha256)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "zh_translation.tsv"
            path.write_text(
                "# u6-translation-v1\n"
                "# kind\tkey\tsource_sha256\tzh\n"
                f"dialogue\tdialogue:0x0431:fallback_fixture:0\t{expected_sha256}\t"
                "您好<VAR0>。\n",
                encoding="utf-8",
            )
            templates = load_templates(path)

        self.assertEqual(
            lookup(source_template, templates),
            "您好<VAR0>。",
        )
        self.assertIsNone(lookup("not in table", templates))

    def test_dynamic_voice_identity_matches_the_shared_python_cpp_golden_vector(self):
        module = load_module(self)
        serialize = getattr(module, "serialize_dynamic_voice_identity", None)
        make_key = getattr(module, "dynamic_voice_key", None)
        self.assertTrue(callable(serialize), "dynamic identity serializer is missing")
        self.assertTrue(callable(make_key), "dynamic identity key function is missing")
        fixture_path = Path(__file__).with_name("fixtures") / "u6_dynamic_voice_identity_v1.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

        self.assertEqual(serialize(fixture["record"]).hex(), fixture["serialized_hex"])
        self.assertEqual(make_key(fixture["record"]), fixture["key"])

        with_runtime_value = deepcopy(fixture["record"])
        with_runtime_value["runtime_values"] = ["Joe"]
        self.assertEqual(make_key(with_runtime_value), fixture["key"])

        changed_role = deepcopy(fixture["record"])
        changed_role["role_spans"][0]["role"] = "narrator"
        self.assertNotEqual(make_key(changed_role), fixture["key"])

    def test_player_name_honorific_and_pronoun_use_reviewable_gender_variants(self):
        _module, canonicalize = self._get_api("canonicalize_dynamic_template")
        slots = [
            {"ordinal": 0, "semantic_type": "player_name"},
            {"ordinal": 1, "semantic_type": "honorific"},
            {"ordinal": 2, "semantic_type": "player_name"},
            {"ordinal": 3, "semantic_type": "pronoun", "pronoun_form": "subject"},
        ]

        male = canonicalize(
            "Thank <VAR0>, <VAR1>. I trust <VAR2> because <VAR3> is kind.",
            "感謝<VAR0>，<VAR1>。我相信<VAR2>，因為<VAR3>很善良。",
            slots,
            player_gender="male",
        )
        female = canonicalize(
            "Thank <VAR0>, <VAR1>. I trust <VAR2> because <VAR3> is kind.",
            "感謝<VAR0>，<VAR1>。我相信<VAR2>，因為<VAR3>很善良。",
            slots,
            player_gender="female",
        )

        self.assertEqual(male["en"], "Thank Avatar, milord. I trust Avatar because he is kind.")
        self.assertEqual(male["zh"], "感謝聖者，大人。我相信聖者，因為他很善良。")
        self.assertEqual(female["en"], "Thank Avatar, milord. I trust Avatar because she is kind.")
        self.assertEqual(female["zh"], "感謝聖者，大人。我相信聖者，因為她很善良。")

    def test_ambiguous_pronoun_requires_a_reviewed_form(self):
        _module, canonicalize = self._get_api("canonicalize_dynamic_template")

        with self.assertRaisesRegex(ValueError, "pronoun_form"):
            canonicalize(
                "Ask <VAR0> to help.", "請<VAR0>幫忙。",
                [{"ordinal": 0, "semantic_type": "pronoun"}],
                player_gender="male",
            )

    def test_contextual_generic_number_person_place_and_item_substitutions(self):
        _module, canonicalize = self._get_api("canonicalize_dynamic_template")
        slots = [
            {"ordinal": 0, "semantic_type": "person_name"},
            {"ordinal": 1, "semantic_type": "item_name"},
            {"ordinal": 2, "semantic_type": "place_name"},
            {"ordinal": 3, "semantic_type": "number"},
        ]

        result = canonicalize(
            "Ask <VAR0> about <VAR1> at <VAR2>; there are <VAR3>.",
            "向<VAR0>詢問<VAR1>，在<VAR2>；共有<VAR3>。",
            slots,
        )

        self.assertEqual(
            result["en"],
            "Ask that person about something at that place; there are some.",
        )
        self.assertEqual(result["zh"], "向那個人詢問某樣東西，在那個地方；共有一些。")

    def test_gender_flag_uses_matching_male_and_female_spoken_variants(self):
        _module, canonicalize = self._get_api("canonicalize_dynamic_template")
        slots = [{"ordinal": 0, "semantic_type": "gender_flag"}]
        source_en = "I saw <VAR0>."
        source_zh = "我看見<VAR0>。"

        try:
            male = canonicalize(source_en, source_zh, slots, player_gender="male")
            female = canonicalize(source_en, source_zh, slots, player_gender="female")
        except ValueError as exc:
            self.fail(f"gender_flag canonicalization was rejected: {exc}")

        self.assertEqual(male, {"en": "I saw a man.", "zh": "我看見一位男性。"})
        self.assertEqual(female, {"en": "I saw a woman.", "zh": "我看見一位女性。"})

    def test_unknown_dynamic_slot_needs_a_reviewed_whole_span_override(self):
        _module, canonicalize = self._get_api("canonicalize_dynamic_template")
        template_en = "Ask <VAR0> about <VAR1>."
        template_zh = "詢問<VAR0>關於<VAR1>。"
        slots = [
            {"ordinal": 0, "semantic_type": "person_name"},
            {"ordinal": 1, "semantic_type": "unknown"},
        ]

        with self.assertRaisesRegex(ValueError, "unknown.*VAR1|VAR1.*unknown"):
            canonicalize(template_en, template_zh, slots)

        result = canonicalize(
            template_en,
            template_zh,
            slots,
            whole_span_override={
                "en": "Ask your companion about it.",
                "zh": "詢問你的同伴此事。",
            },
        )
        self.assertEqual(result, {
            "en": "Ask your companion about it.",
            "zh": "詢問你的同伴此事。",
        })


if __name__ == "__main__":
    unittest.main()
