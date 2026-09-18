from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from tools.u6_translation.audit import (
    correctness_report,
    coverage_report,
    format_terminal_report,
    load_audit_table,
    report_exit_code,
)
from tools.u6_translation.catalog import CatalogEntry, source_sha256
from tools.u6_translation.runtime_table import RuntimeRow, load_runtime_table, write_runtime_table


FIXTURES = Path(__file__).parent / "fixtures"
GLOSSARY = Path(__file__).parents[1] / "u6_glossary.tsv"


def _entry(
    kind: str, key: str, source: str, context: str = "gameplay"
) -> CatalogEntry:
    return CatalogEntry.from_source(kind, key, source, context, "audit-fixture")


class AuditReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = [
            _entry("dialogue", "dialogue:0x0401:10:0", "Hello"),
            _entry("choice", "choice:0x0401:0x0088:0", "yes"),
            _entry("choice", "choice:0x0401:0x0088:1", "no"),
            _entry("choice", "choice:0x0401:unbound:2", "maybe"),
            _entry("textmsg", "textmsg:0x0123", "The bed is occupied."),
            _entry("item", "item:0x01f4:0:0", "a torch"),
            _entry("dialogue", "dialogue:0x0401:20:0", "Wait ~ here"),
            _entry("dialogue", "dialogue:0x0401:21:0", "Hello <PLAYER_NAME>"),
            _entry("misc", "misc:0x0042", "Welcome"),
            _entry("spell", "spell:0x0012", "@Corp Por@"),
            _entry("misc", "misc:0x0043", "The Avatar"),
            _entry("misc", "misc:0x0044", "Same"),
        ]
        self.rows = load_runtime_table(FIXTURES / "bad_translation.tsv")

    def test_coverage_reports_all_kinds_and_weighted_dialogue_choice_counts(self) -> None:
        report = coverage_report(self.catalog, self.rows)

        self.assertEqual(
            set(report["by_kind"]),
            {"dialogue", "choice", "textmsg", "item", "location", "misc", "spell"},
        )
        self.assertEqual(report["by_kind"]["choice"]["total"], 3)
        self.assertEqual(report["by_kind"]["choice"]["translated"], 2)
        self.assertEqual(report["by_kind"]["choice"]["missing"], 1)
        self.assertEqual(report["by_kind"]["choice"]["unbound"], 1)
        self.assertEqual(report["by_kind"]["item"]["duplicate"], 1)
        self.assertEqual(report["by_kind"]["textmsg"]["stale"], 1)
        self.assertEqual(len(report["orphans"]), 1)
        self.assertEqual(report["by_kind"]["dialogue"]["total"], 3)
        self.assertEqual(report["by_kind"]["dialogue"]["translated"], 3)
        self.assertEqual(report["by_kind"]["dialogue"]["weighted_coverage"], 1.0)
        self.assertEqual(report["totals"]["total"], len(self.catalog))

    def test_coverage_reports_book_contents_separately(self) -> None:
        entry = _entry(
            "dialogue", "dialogue:0x0282:10:0", "A page of book text", "book"
        )
        report = coverage_report(
            [entry],
            [RuntimeRow(entry.kind, entry.key, entry.source_sha256, "一頁書中文字")],
        )
        self.assertEqual(report["book_contents"]["total"], 1)
        self.assertEqual(report["book_contents"]["translated"], 1)
        self.assertEqual(report["book_contents"]["missing"], 0)

    def test_coverage_reports_placeholder_templates_separately(self) -> None:
        entry = _entry(
            "dialogue",
            "dialogue:0x0494:fallback_f6112e6f71da14b8:0",
            "@Good <TIME_OF_DAY>, <PLAYER_NAME>.@",
            "gameplay",
        )
        report = coverage_report(
            [entry],
            [RuntimeRow(
                entry.kind, entry.key, entry.source_sha256,
                "@美好的<TIME_OF_DAY>，<PLAYER_NAME>.@",
            )],
        )
        self.assertEqual(report["placeholder_templates"]["total"], 1)
        self.assertEqual(report["placeholder_templates"]["translated"], 1)
        self.assertEqual(report["placeholder_templates"]["missing"], 0)

    def test_blaine_good_afternoon_template_is_covered(self) -> None:
        entry = _entry(
            "dialogue",
            "dialogue:0x041b:fallback_5c487d8d34f94a12:0",
            "@Good <VAR0>.@",
            "gameplay",
        )
        report = coverage_report(
            [entry],
            [RuntimeRow(
                entry.kind,
                entry.key,
                entry.source_sha256,
                "@美好的<VAR0>。@",
            )],
        )
        self.assertEqual(report["placeholder_templates"]["total"], 1)
        self.assertEqual(report["placeholder_templates"]["translated"], 1)
        self.assertEqual(report["placeholder_templates"]["missing"], 0)

    def test_taiwan_greeting_terms_and_runtime_honorific_are_audited(self) -> None:
        morning = _entry("dialogue", "dialogue:0x0401:30:0", "@Good morning.@")
        prefix = _entry("dialogue", "dialogue:0x041b:23:0", "@Good ")
        template = _entry(
            "dialogue",
            "dialogue:0x041b:fallback_5c487d8d34f94a12:0",
            "@Good <VAR0>.@",
        )
        milord = _entry("dialogue", "dialogue:0x0000:runtime:1", "milord")
        rows = [
            RuntimeRow(morning.kind, morning.key, morning.source_sha256, "@早安。@"),
            RuntimeRow(prefix.kind, prefix.key, prefix.source_sha256, "@"),
            RuntimeRow(template.kind, template.key, template.source_sha256, "@<VAR0>。@"),
            RuntimeRow(milord.kind, milord.key, milord.source_sha256, "大人"),
        ]
        report = correctness_report([morning, prefix, template, milord], rows, GLOSSARY, None)
        checks = {issue["check"] for issue in report["deterministic"]["issues"]}
        self.assertNotIn("greeting_terms", checks)
        self.assertNotIn("chinese_output", checks)

        invalid = correctness_report(
            [morning],
            [RuntimeRow(morning.kind, morning.key, morning.source_sha256, "@早上好。@")],
            GLOSSARY,
            None,
        )
        self.assertIn(
            "greeting_terms",
            {issue["check"] for issue in invalid["deterministic"]["issues"]},
        )

    def test_runtime_overhead_key_uses_static_source_global_translation(self) -> None:
        source = "@Oh, my aching back...@"
        static = CatalogEntry.from_source(
            "dialogue",
            "dialogue:0x092e:23:0",
            source,
            "gameplay",
            "static-fallback-item-say-ucxt",
        )
        runtime = CatalogEntry.from_source(
            "dialogue",
            "dialogue:0x0000:0:0",
            source,
            "gameplay",
            "runtime-capture",
        )
        rows = [
            RuntimeRow(
                static.kind,
                static.key,
                static.source_sha256,
                "@噢，我的背好痛...@",
            )
        ]

        report = coverage_report([static, runtime], rows)

        self.assertEqual(report["by_kind"]["dialogue"]["missing"], 0)
        self.assertEqual(report["by_kind"]["dialogue"]["translated"], 2)
        self.assertEqual(report["by_kind"]["dialogue"]["orphan"], 0)

    def test_coverage_reports_untranslated_compiled_assembled_templates(self) -> None:
        source = (
            "Turning to you, Gwenneth says, @And what can I do for "
            "Iolo's friend this fine <VAR0>?@"
        )
        entry = CatalogEntry.from_source(
            "dialogue",
            "dialogue:0x0416:fallback_93fc9f7add1e08d7:0",
            source,
            "gameplay",
            "static-usecode-template",
        )

        report = coverage_report([entry], [])

        self.assertEqual(report["assembled_templates"]["total"], 1)
        self.assertEqual(report["assembled_templates"]["missing"], 1)
        self.assertEqual(
            report["assembled_templates"]["missing_keys"], [entry.key]
        )
        self.assertIn(
            "assembled templates: 1 total, 0 translated, 1 missing",
            format_terminal_report(report),
        )

    def test_fragment_rows_do_not_hide_missing_canonical_template(self) -> None:
        canonical_source = (
            "Very well, <VAR0>, I shall wait here until thy return.@"
        )
        canonical = CatalogEntry.from_source(
            "dialogue",
            "dialogue:0x0403:fallback_df8a9faac675af03:0",
            canonical_source,
            "gameplay",
            "static-usecode-template",
        )
        prefix = _entry("dialogue", "dialogue:0x0403:700:0", "Very well, ")
        suffix = _entry(
            "dialogue",
            "dialogue:0x0403:701:0",
            ", I shall wait here until thy return.@",
        )
        rows = [
            RuntimeRow(prefix.kind, prefix.key, prefix.source_sha256, "很好，"),
            RuntimeRow(
                suffix.kind,
                suffix.key,
                suffix.source_sha256,
                "我會在這裡等你回來。@",
            ),
        ]

        report = coverage_report([canonical, prefix, suffix], rows)

        self.assertEqual(report["assembled_templates"]["translated"], 0)
        self.assertEqual(report["assembled_templates"]["missing"], 1)
        self.assertEqual(
            report["assembled_templates"]["missing_keys"], [canonical.key]
        )
        self.assertEqual(report["orphan"], 0)

    def test_coverage_reports_unobserved_source_stable_placeholder_rows(self) -> None:
        key = "dialogue:0x041f:fallback_f613b0dc467ee6f2:0"
        source = "@Good <VAR0>, friend Avatar.@"
        report = coverage_report(
            [_entry("dialogue", "dialogue:0x041f:99:0", "@Good ")],
            [RuntimeRow("dialogue", key, source_sha256(source), "@美好的<VAR0>，聖者朋友。@")],
        )
        placeholder_templates = report["placeholder_templates"]
        self.assertEqual(placeholder_templates["total"], 0)
        self.assertEqual(placeholder_templates["unobserved"], 1)
        self.assertEqual(placeholder_templates["unobserved_keys"], [key])

    def test_ascii_dot_runs_are_preserved_exactly(self) -> None:
        entries = [
            _entry("dialogue", "dialogue:0x0401:200:0", "@Goodbye..@"),
            _entry("dialogue", "dialogue:0x0401:201:0", "@Wait...@"),
        ]
        valid_rows = [
            RuntimeRow(
                entries[0].kind,
                entries[0].key,
                entries[0].source_sha256,
                "@再見..@",
            ),
            RuntimeRow(
                entries[1].kind,
                entries[1].key,
                entries[1].source_sha256,
                "@等等...@",
            ),
        ]
        valid_report = correctness_report(entries, valid_rows, GLOSSARY, None)
        self.assertNotIn(
            "ascii_dot_runs",
            {issue["check"] for issue in valid_report["deterministic"]["issues"]},
        )

        invalid_rows = [
            RuntimeRow(
                entries[0].kind,
                entries[0].key,
                entries[0].source_sha256,
                "@再見。。@",
            ),
            RuntimeRow(
                entries[1].kind,
                entries[1].key,
                entries[1].source_sha256,
                "@等等……@",
            ),
        ]
        invalid_report = correctness_report(entries, invalid_rows, GLOSSARY, None)
        dot_issues = [
            issue
            for issue in invalid_report["deterministic"]["issues"]
            if issue["check"] == "ascii_dot_runs"
        ]
        self.assertEqual(len(dot_issues), 2)

    def test_item_quantity_name_format_is_preserved(self) -> None:
        entry = _entry("item", "item:0x0285:0:0", "/gold nugget//s")
        valid = RuntimeRow(entry.kind, entry.key, entry.source_sha256, "/金塊//")
        valid_report = correctness_report([entry], [valid], GLOSSARY, None)
        self.assertNotIn(
            "item_name_format",
            {issue["check"] for issue in valid_report["deterministic"]["issues"]},
        )

        invalid = RuntimeRow(entry.kind, entry.key, entry.source_sha256, "金塊")
        invalid_report = correctness_report([entry], [invalid], GLOSSARY, None)
        self.assertIn(
            "item_name_format",
            {issue["check"] for issue in invalid_report["deterministic"]["issues"]},
        )

        untranslated_plural = RuntimeRow(
            entry.kind, entry.key, entry.source_sha256, "/金塊//s"
        )
        untranslated_plural_report = correctness_report(
            [entry], [untranslated_plural], GLOSSARY, None
        )
        self.assertIn(
            "item_name_format",
            {
                issue["check"]
                for issue in untranslated_plural_report["deterministic"]["issues"]
            },
        )

    def test_correctness_reports_structural_and_translation_issues_separately(self) -> None:
        report = correctness_report(self.catalog, self.rows, GLOSSARY, [])
        issues = report["deterministic"]["issues"]
        checks = {issue["check"] for issue in issues}

        self.assertIn("protected_markers", checks)
        self.assertIn("placeholders", checks)
        self.assertIn("traditional_chinese", checks)
        self.assertIn("glossary", checks)
        self.assertIn("protected_spell_terms", checks)
        self.assertIn("source_duplication", checks)
        self.assertEqual(report["semantic_reviews"], [])
        self.assertTrue(all({"key", "check", "severity", "source_location"} <= set(issue) for issue in issues))
        simplified = next(issue for issue in issues if issue["check"] == "traditional_chinese")
        self.assertEqual(simplified["severity"], "warning")

    def test_dialogue_wrappers_are_not_protected_translation_tokens(self) -> None:
        entry = _entry("dialogue", "dialogue:0x0401:94:0", "@Hello@*")
        valid = RuntimeRow(entry.kind, entry.key, entry.source_sha256, "@你好@*")
        report = correctness_report([entry], [valid], GLOSSARY, None)
        self.assertNotIn(
            "protected_markers",
            {issue["check"] for issue in report["deterministic"]["issues"]},
        )

        invalid = RuntimeRow(entry.kind, entry.key, entry.source_sha256, "@你好@")
        invalid_report = correctness_report([entry], [invalid], GLOSSARY, None)
        self.assertIn(
            "protected_markers",
            {issue["check"] for issue in invalid_report["deterministic"]["issues"]},
        )

    def test_compiled_templates_require_usecode_speech_markers(self) -> None:
        source = "@Hello <VAR0>?@"
        entry = CatalogEntry.from_source(
            "dialogue",
            "dialogue:0x0416:fallback_0123456789abcdef:0",
            source,
            "gameplay",
            "static-usecode-template",
        )
        missing = RuntimeRow(
            entry.kind, entry.key, entry.source_sha256, "你好<VAR0>？"
        )
        missing_report = correctness_report([entry], [missing], GLOSSARY, None)
        self.assertIn(
            "dialogue_speech_markers",
            {issue["check"] for issue in missing_report["deterministic"]["issues"]},
        )

        preserved = RuntimeRow(
            entry.kind, entry.key, entry.source_sha256, "@你好<VAR0>？@"
        )
        preserved_report = correctness_report([entry], [preserved], GLOSSARY, None)
        self.assertNotIn(
            "dialogue_speech_markers",
            {issue["check"] for issue in preserved_report["deterministic"]["issues"]},
        )

    def test_ucxt_fragment_boundary_deficit_is_advisory(self) -> None:
        entry = CatalogEntry.from_source(
            "dialogue",
            "dialogue:0x043e:41:0",
            "!@",
            "gameplay",
            "static-ucxt",
        )
        omitted = RuntimeRow(entry.kind, entry.key, entry.source_sha256, "！")
        report = correctness_report([entry], [omitted], GLOSSARY, None)
        boundary_issues = [
            issue for issue in report["deterministic"]["issues"]
            if issue["check"] == "fragment_speech_boundary"
        ]
        self.assertEqual(len(boundary_issues), 1)
        self.assertEqual(boundary_issues[0]["severity"], "warning")
        self.assertFalse(boundary_issues[0]["blocking"])
        self.assertEqual(
            coverage_report([entry], [omitted])["fragment_speech_boundaries"],
            {"total": 1, "at_risk": 1, "keys": [entry.key]},
        )

        preserved = RuntimeRow(entry.kind, entry.key, entry.source_sha256, "！@")
        preserved_report = correctness_report([entry], [preserved], GLOSSARY, None)
        self.assertNotIn(
            "fragment_speech_boundary",
            {issue["check"] for issue in preserved_report["deterministic"]["issues"]},
        )

    def test_arbitrary_placeholder_names_are_protected(self) -> None:
        entry = _entry("dialogue", "dialogue:0x0401:96:0", "Ask <NPC_NAME> <VAR0>")
        valid = RuntimeRow(
            entry.kind, entry.key, entry.source_sha256, "詢問 <NPC_NAME> <VAR0>"
        )
        valid_report = correctness_report([entry], [valid], GLOSSARY, None)
        self.assertNotIn(
            "protected_markers",
            {issue["check"] for issue in valid_report["deterministic"]["issues"]},
        )

        renamed = RuntimeRow(
            entry.kind, entry.key, entry.source_sha256, "詢問 <PLAYER_NAME> <HONORIFIC>"
        )
        renamed_report = correctness_report([entry], [renamed], GLOSSARY, None)
        self.assertNotIn(
            "placeholders",
            {issue["check"] for issue in renamed_report["deterministic"]["issues"]},
        )

        invalid = RuntimeRow(
            entry.kind, entry.key, entry.source_sha256, "詢問 <NPC_NAME>"
        )
        invalid_report = correctness_report([entry], [invalid], GLOSSARY, None)
        self.assertIn("placeholders", {issue["check"] for issue in invalid_report["deterministic"]["issues"]})

    def test_translated_text_may_add_line_breaks_but_may_not_drop_source_breaks(self) -> None:
        entry = _entry("dialogue", "dialogue:0x0401:95:0", "first\nsecond")
        added = RuntimeRow(entry.kind, entry.key, entry.source_sha256, "第一\n第二\n第三")
        added_report = correctness_report([entry], [added], GLOSSARY, None)
        self.assertNotIn(
            "newlines",
            {issue["check"] for issue in added_report["deterministic"]["issues"]},
        )

        dropped = RuntimeRow(entry.kind, entry.key, entry.source_sha256, "第一第二")
        dropped_report = correctness_report([entry], [dropped], GLOSSARY, None)
        self.assertIn(
            "newlines",
            {issue["check"] for issue in dropped_report["deterministic"]["issues"]},
        )

    def test_non_linguistic_source_does_not_require_chinese_or_count_as_duplication(self) -> None:
        entry = _entry("dialogue", "dialogue:0x0401:96:0", "0")
        report = correctness_report(
            [entry],
            [RuntimeRow(entry.kind, entry.key, entry.source_sha256, "0")],
            GLOSSARY,
            None,
        )
        self.assertNotIn(
            "chinese_output",
            {issue["check"] for issue in report["deterministic"]["issues"]},
        )
        self.assertNotIn(
            "source_duplication",
            {issue["check"] for issue in report["deterministic"]["issues"]},
        )

    def test_opaque_u6_language_does_not_require_chinese_or_count_as_duplication(self) -> None:
        entries = [
            _entry("dialogue", "dialogue:0x0cff:100:0", "kuatim betlem grespor de ov"),
            _entry("dialogue", "dialogue:0x0667:101:0", "@Ex Por@"),
            _entry("dialogue", "dialogue:0x0449:102:0", "@Rrrrlr Grrtl...@"),
        ]
        report = correctness_report(
            entries,
            [RuntimeRow(entry.kind, entry.key, entry.source_sha256, entry.source) for entry in entries],
            GLOSSARY,
            None,
        )
        checks = {issue["check"] for issue in report["deterministic"]["issues"]}
        self.assertNotIn("chinese_output", checks)
        self.assertNotIn("source_duplication", checks)

    def test_runtime_and_audio_format_fragments_do_not_require_chinese(self) -> None:
        entries = [
            _entry("dialogue", "dialogue:0x0401:101:0", "NPC "),
            _entry("dialogue", "dialogue:0x0498:102:0", "FRAME_BREAD"),
            _entry("textmsg", "textmsg:0x020e", "Roland MT-32"),
        ]
        rows = [
            RuntimeRow(entry.kind, entry.key, entry.source_sha256, entry.source)
            for entry in entries
        ]
        report = correctness_report(entries, rows, GLOSSARY, None)
        checks = {issue["check"] for issue in report["deterministic"]["issues"]}
        self.assertNotIn("chinese_output", checks)
        self.assertNotIn("source_duplication", checks)

    def test_exit_code_allows_only_reviewable_missing_rows_in_non_strict_mode(self) -> None:
        missing_only = coverage_report(
            [_entry("choice", "choice:0x0401:0x0088:0", "yes")], []
        )
        self.assertEqual(report_exit_code(missing_only, strict=False), 0)
        self.assertNotEqual(report_exit_code(missing_only, strict=True), 0)

        report = coverage_report(self.catalog, self.rows)
        self.assertNotEqual(report_exit_code(report, strict=False), 0)

    def test_weighted_coverage_uses_normalized_source_lengths(self) -> None:
        entry = _entry("dialogue", "dialogue:0x0401:30:0", "Long English source")
        report = coverage_report([entry], [
            RuntimeRow(entry.kind, entry.key, entry.source_sha256, "短")
        ])
        self.assertEqual(report["totals"]["translated_source_length"], len(entry.source))
        self.assertEqual(report["weighted_coverage"], 1.0)

    def test_empty_translation_counts_as_missing(self) -> None:
        entry = _entry("choice", "choice:0x0401:0x0090:0", "yes")
        report = coverage_report([entry], [
            RuntimeRow(entry.kind, entry.key, entry.source_sha256, "   ")
        ])
        self.assertEqual(report["by_kind"]["choice"]["missing"], 1)
        self.assertEqual(report["by_kind"]["choice"]["translated"], 0)
        self.assertEqual(report_exit_code(report, strict=False), 0)

    def test_exactly_repeated_translation_is_a_blocking_issue(self) -> None:
        entry = _entry("textmsg", "textmsg:0x0000", '\"Step aside!\"')
        row = RuntimeRow(
            entry.kind,
            entry.key,
            entry.source_sha256,
            "「請讓一下！」「請讓一下！」",
        )

        report = correctness_report([entry], [row], GLOSSARY, None)

        duplicate = [
            issue for issue in report["deterministic"]["issues"]
            if issue["check"] == "duplicate_translation"
        ]
        self.assertEqual(len(duplicate), 1)
        self.assertTrue(duplicate[0]["blocking"])
        self.assertNotEqual(report_exit_code(report, strict=True), 0)

        spaced = RuntimeRow(
            entry.kind,
            entry.key,
            entry.source_sha256,
            "「請讓一下！」 「請讓一下！」",
        )
        spaced_report = correctness_report([entry], [spaced], GLOSSARY, None)
        self.assertIn(
            "duplicate_translation",
            {issue["check"] for issue in spaced_report["deterministic"]["issues"]},
        )

        legitimate = _entry("misc", "misc:0x0090", "Hello")
        legitimate_report = correctness_report(
            [legitimate],
            [RuntimeRow(legitimate.kind, legitimate.key, legitimate.source_sha256, "你好你好")],
            GLOSSARY,
            None,
        )
        self.assertNotIn(
            "duplicate_translation",
            {issue["check"] for issue in legitimate_report["deterministic"]["issues"]},
        )

    def test_intentional_source_repetition_is_not_a_duplicate_translation(self) -> None:
        entry = _entry("dialogue", "dialogue:0x0401:97:0", "Guards! Guards!")
        row = RuntimeRow(entry.kind, entry.key, entry.source_sha256, "衛兵！衛兵！")
        report = correctness_report([entry], [row], GLOSSARY, None)
        self.assertNotIn(
            "duplicate_translation",
            {issue["check"] for issue in report["deterministic"]["issues"]},
        )

    def test_english_name_can_protect_a_glossary_substring(self) -> None:
        entry = _entry("location", "location:0x002b", "Isle of the Avatar")
        row = RuntimeRow(entry.kind, entry.key, entry.source_sha256, "Isle of the Avatar")
        with tempfile.TemporaryDirectory() as directory:
            names = Path(directory) / "names.tsv"
            names.write_text(
                "category\ten\nplace\tIsle of the Avatar\n",
                encoding="utf-8",
            )
            report = correctness_report(
                [entry], [row], GLOSSARY, None, names=names
            )
        checks = {issue["check"] for issue in report["deterministic"]["issues"]}
        self.assertNotIn("glossary", checks)
        self.assertNotIn("source_duplication", checks)
        self.assertNotIn("chinese_output", checks)

    def test_name_policy_accepts_named_non_npc_entities(self) -> None:
        entry = _entry("textmsg", "textmsg:0x0091", "Empire")
        row = RuntimeRow(entry.kind, entry.key, entry.source_sha256, "Empire")
        with tempfile.TemporaryDirectory() as directory:
            names = Path(directory) / "names.tsv"
            names.write_text(
                "category\ten\nproper\tEmpire\n",
                encoding="utf-8",
            )
            report = correctness_report(
                [entry], [row], GLOSSARY, None, names=names
            )
        checks = {issue["check"] for issue in report["deterministic"]["issues"]}
        self.assertNotIn("english_name", checks)
        self.assertNotIn("source_duplication", checks)
        self.assertNotIn("chinese_output", checks)

    def test_repeated_english_source_requires_one_consistent_translation(self) -> None:
        entries = [
            _entry("dialogue", "dialogue:0x0401:80:0", "The Fellowship"),
            _entry("dialogue", "dialogue:0x0401:81:0", "The Fellowship"),
        ]
        rows = [
            RuntimeRow(entries[0].kind, entries[0].key, entries[0].source_sha256, "友誼會"),
            RuntimeRow(entries[1].kind, entries[1].key, entries[1].source_sha256, "團契"),
        ]

        report = correctness_report(entries, rows, GLOSSARY, None)

        consistency = [
            issue for issue in report["deterministic"]["issues"]
            if issue["check"] == "term_consistency"
        ]
        self.assertEqual(len(consistency), 2)
        self.assertTrue(all(issue["blocking"] for issue in consistency))

    def test_blank_source_row_is_not_a_missing_or_empty_translation_failure(self) -> None:
        entry = _entry("dialogue", "dialogue:0x0401:91:0", "")

        report = correctness_report(
            [entry],
            [RuntimeRow(entry.kind, entry.key, entry.source_sha256, "")],
            GLOSSARY,
            None,
        )

        checks = {issue["check"] for issue in report["deterministic"]["issues"]}
        self.assertNotIn("nonempty_zh", checks)
        self.assertEqual(coverage_report([entry], [RuntimeRow(entry.kind, entry.key, entry.source_sha256, "")])["missing"], 0)

    def test_glossary_configures_protected_terms_and_traditional_policy(self) -> None:
        catalog = [_entry("misc", "misc:0x0050", "Avatar Rune")]
        row = RuntimeRow("misc", "misc:0x0050", catalog[0].source_sha256, "聖者 Rune 简")
        with tempfile.TemporaryDirectory() as directory:
            glossary = Path(directory) / "glossary.tsv"
            glossary.write_text(
                "en\tzh\tpolicy\n"
                "Avatar\t聖者\ttranslated\n"
                "Rune\tRune\tprotected\n"
                "# policy traditional_chinese=warning\n",
                encoding="utf-8",
            )
            report = correctness_report(catalog, [row], glossary, None)
        self.assertFalse(report["deterministic"]["has_failures"])
        self.assertEqual({issue["check"] for issue in report["deterministic"]["issues"]}, {"traditional_chinese"})
        self.assertFalse(report["deterministic"]["issues"][0]["blocking"])
        bad_row = RuntimeRow("misc", "misc:0x0050", catalog[0].source_sha256, "聖者 符文")
        with tempfile.TemporaryDirectory() as directory:
            glossary = Path(directory) / "glossary.tsv"
            glossary.write_text("en\tzh\tpolicy\nAvatar\t聖者\ttranslated\nRune\tRune\tprotected\n", encoding="utf-8")
            bad_report = correctness_report(catalog, [bad_row], glossary, None)
        self.assertIn("protected_term", {issue["check"] for issue in bad_report["deterministic"]["issues"]})

    def test_protected_professional_terms_are_consistent_across_text_kinds(self) -> None:
        entries = [
            _entry("dialogue", "dialogue:0x0401:100:0", "The wisp appears."),
            _entry("choice", "choice:0x0401:0x0088:0", "Fight wisps"),
            _entry("dialogue", "dialogue:0x0282:100:0", "A page about wisps.", "book"),
            _entry("dialogue", "dialogue:0x0000:0:0", "Wisps overhead", "gameplay"),
            _entry("dialogue", "dialogue:0x0000:runtime:2", "wisp", "gameplay"),
            _entry("dialogue", "dialogue:0x0000:runtime:3", "wisps", "gameplay"),
        ]
        rows = [
            RuntimeRow(entries[0].kind, entries[0].key, entries[0].source_sha256, "wisp 出現了。"),
            RuntimeRow(entries[1].kind, entries[1].key, entries[1].source_sha256, "對抗 wisps"),
            RuntimeRow(entries[2].kind, entries[2].key, entries[2].source_sha256, "這是一頁介紹 wisps 的內容。"),
            RuntimeRow(entries[3].kind, entries[3].key, entries[3].source_sha256, "頭頂出現 Wisps"),
            RuntimeRow(entries[4].kind, entries[4].key, entries[4].source_sha256, "wisp"),
            RuntimeRow(entries[5].kind, entries[5].key, entries[5].source_sha256, "wisps"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            glossary = Path(directory) / "glossary.tsv"
            glossary.write_text(
                "en\tzh\tpolicy\n"
                "wisp\twisp\truntime_term+protected\n"
                "wisps\twisps\truntime_term+protected\n",
                encoding="utf-8",
            )
            report = correctness_report(entries, rows, glossary, None)
            checks = {
                issue["check"] for issue in report["deterministic"]["issues"]
            }
            self.assertNotIn("protected_term", checks)
            self.assertNotIn("source_duplication", checks)
            self.assertNotIn("chinese_output", checks)

            bad_rows = list(rows)
            bad_rows[1] = RuntimeRow(
                entries[1].kind,
                entries[1].key,
                entries[1].source_sha256,
                "對抗 靈光",
            )
            bad_report = correctness_report(entries, bad_rows, glossary, None)
            self.assertIn(
                "protected_term",
                {issue["check"] for issue in bad_report["deterministic"]["issues"]},
            )

            singular_for_plural = RuntimeRow(
                entries[1].kind,
                entries[1].key,
                entries[1].source_sha256,
                "對抗 wisp",
            )
            plural_report = correctness_report(
                entries, rows[:1] + [singular_for_plural] + rows[2:], glossary, None
            )
            self.assertIn(
                "protected_term",
                {issue["check"] for issue in plural_report["deterministic"]["issues"]},
            )

    def test_name_policy_requires_english_names_in_dialogue_and_name_rows(self) -> None:
        entries = [
            _entry("dialogue", "dialogue:0x0401:92:0", "Iolo asks about Britain"),
            _entry("location", "location:0x002a", "Britain"),
        ]
        rows = [
            RuntimeRow(entries[0].kind, entries[0].key, entries[0].source_sha256, "伊歐羅詢問不列顛"),
            RuntimeRow(entries[1].kind, entries[1].key, entries[1].source_sha256, "不列顛"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            names = Path(directory) / "names.tsv"
            names.write_text(
                "category\ten\n"
                "npc\tIolo\n"
                "town\tBritain\n",
                encoding="utf-8",
            )
            report = correctness_report(self.catalog + entries, self.rows + rows, GLOSSARY, None, names=names)

        name_issues = [
            issue for issue in report["deterministic"]["issues"]
            if issue["check"] == "english_name"
        ]
        self.assertEqual({issue["key"] for issue in name_issues}, {entry.key for entry in entries})
        self.assertTrue(all(issue["blocking"] for issue in name_issues))

        valid_rows = [
            RuntimeRow(entries[0].kind, entries[0].key, entries[0].source_sha256, "Iolo 詢問 Britain"),
            RuntimeRow(entries[1].kind, entries[1].key, entries[1].source_sha256, "Britain"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            names = Path(directory) / "names.tsv"
            names.write_text(
                "category\ten\n"
                "npc\tIolo\n"
                "town\tBritain\n",
                encoding="utf-8",
            )
            valid_report = correctness_report(
                entries, valid_rows, GLOSSARY, None, names=names
            )
        self.assertNotIn(
            "english_name",
            {issue["check"] for issue in valid_report["deterministic"]["issues"]},
        )
        self.assertFalse(valid_report["deterministic"]["has_failures"])

    def test_name_policy_rejects_transliteration_hidden_by_appended_english(self) -> None:
        entry = _entry(
            "dialogue",
            "dialogue:0x041f:bf:0",
            "@I'm Daver McCord.@",
        )
        row = RuntimeRow(
            entry.kind,
            entry.key,
            entry.source_sha256,
            "@我是戴弗·麥考德。@。 McCord Daver",
        )
        with tempfile.TemporaryDirectory() as directory:
            names = Path(directory) / "names.tsv"
            names.write_text(
                "category\ten\n"
                "npc\tDaver\n"
                "npc\tMcCord\n",
                encoding="utf-8",
            )
            report = correctness_report(
                [entry], [row], GLOSSARY, None, names=names
            )
            malformed = RuntimeRow(
                entry.kind,
                entry.key,
                entry.source_sha256,
                "我是戴弗·麥考德。@。 McCord Daver",
            )
            malformed_report = correctness_report(
                [entry], [malformed], GLOSSARY, None, names=names
            )
            name_issues = [
                issue for issue in report["deterministic"]["issues"]
                if issue["check"] == "english_name"
            ]
            self.assertEqual({issue["key"] for issue in name_issues}, {entry.key})
            self.assertEqual(
                {
                    issue["key"]
                    for issue in malformed_report["deterministic"]["issues"]
                    if issue["check"] == "english_name"
                },
                {entry.key},
            )

    def test_traditional_policy_requires_glossary_declaration(self) -> None:
        entry = _entry("misc", "misc:0x0052", "Welcome")
        row = RuntimeRow(entry.kind, entry.key, entry.source_sha256, "简体中文")
        with tempfile.TemporaryDirectory() as directory:
            undeclared = Path(directory) / "undeclared.tsv"
            undeclared.write_text("en\tzh\tpolicy\n", encoding="utf-8")
            undeclared_report = correctness_report([entry], [row], undeclared, None)

            declared = Path(directory) / "declared.tsv"
            declared.write_text(
                "en\tzh\tpolicy\n"
                "# policy traditional_chinese=error\n",
                encoding="utf-8",
            )
            declared_report = correctness_report([entry], [row], declared, None)

        self.assertNotIn(
            "traditional_chinese",
            {issue["check"] for issue in undeclared_report["deterministic"]["issues"]},
        )
        traditional = [
            issue for issue in declared_report["deterministic"]["issues"]
            if issue["check"] == "traditional_chinese"
        ]
        self.assertEqual(len(traditional), 1)
        self.assertEqual(traditional[0]["severity"], "error")
        self.assertTrue(traditional[0]["blocking"])

    def test_orphan_identity_reporting_is_sorted_and_deduplicated(self) -> None:
        rows = [
            RuntimeRow("misc", "misc:0x0099", "a" * 64, "甲"),
            RuntimeRow("misc", "misc:0x0099", "b" * 64, "乙"),
            RuntimeRow("item", "item:0x0abc:0:0", "c" * 64, "物"),
        ]
        report = coverage_report([], rows)

        self.assertEqual(
            report["by_kind"]["misc"]["orphan_identities"],
            [["misc", "misc:0x0099"]],
        )
        self.assertEqual(
            report["orphan_identities"],
            [["item", "item:0x0abc:0:0"], ["misc", "misc:0x0099"]],
        )

    def test_traditional_warning_is_non_blocking(self) -> None:
        entry = _entry("misc", "misc:0x0051", "Welcome")
        row = RuntimeRow(entry.kind, entry.key, entry.source_sha256, "简体中文")
        report = correctness_report([entry], [row], GLOSSARY, None)
        warnings = [issue for issue in report["deterministic"]["issues"] if issue["severity"] == "warning"]
        self.assertTrue(warnings)
        self.assertFalse(report["deterministic"]["has_failures"])
        self.assertEqual(report_exit_code(report, strict=False), 0)

    def test_coverage_issues_use_kind_and_key_identity(self) -> None:
        dialogue = CatalogEntry.from_source("dialogue", "dialogue:0x0401:70:0", "Hello", "gameplay", "dialogue-origin")
        choice = CatalogEntry.from_source("choice", "dialogue:0x0401:70:0", "yes", "gameplay", "choice-origin")
        rows = [
            RuntimeRow(dialogue.kind, dialogue.key, "0" * 64, "你好"),
            RuntimeRow(choice.kind, choice.key, "0" * 64, "是"),
        ]
        report = correctness_report([dialogue, choice], rows, GLOSSARY, None)
        stale = [issue for issue in report["deterministic"]["issues"] if issue["check"] == "source_hash"]
        self.assertEqual({issue["source_location"] for issue in stale}, {"dialogue-origin", "choice-origin"})

    def test_terminal_report_is_deterministic_and_mentions_kind_coverage(self) -> None:
        report = coverage_report(self.catalog, self.rows)
        terminal = format_terminal_report(report)
        self.assertIn("U6 translation audit", terminal)
        self.assertIn("choice", terminal)
        self.assertIn("weighted", terminal)
        self.assertIn("unobserved", terminal)

    def test_terminal_report_mentions_english_name_policy_results(self) -> None:
        entry = _entry("dialogue", "dialogue:0x0401:93:0", "Iolo")
        with tempfile.TemporaryDirectory() as directory:
            names = Path(directory) / "names.tsv"
            names.write_text("category\ten\nnpc\tIolo\n", encoding="utf-8")
            report = correctness_report(
                [entry],
                [RuntimeRow(entry.kind, entry.key, entry.source_sha256, "Iolo")],
                GLOSSARY,
                None,
                names=names,
            )
        terminal = format_terminal_report(report)
        self.assertIn("English-name policy: 1 names; issues: 0", terminal)

    def test_terminal_report_mentions_english_term_manifest_results(self) -> None:
        entry = _entry("dialogue", "dialogue:0x0401:94:0", "wisp")
        with tempfile.TemporaryDirectory() as directory:
            terms = Path(directory) / "terms.tsv"
            terms.write_text(
                "category\ten\tpolicy\n"
                "professional\twisp\truntime_term+protected\n",
                encoding="utf-8",
            )
            report = correctness_report(
                [entry],
                [RuntimeRow(entry.kind, entry.key, entry.source_sha256, "靈光")],
                GLOSSARY,
                None,
                terms=terms,
            )
        terminal = format_terminal_report(report)
        self.assertIn("English-term manifest: 1 entries; issues: 1", terminal)

    def test_audit_table_requires_exact_release_headers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.tsv"
            path.write_text(
                "# u6-translation-v0\n# kind\\tkey\\tsource_sha256\\tzh\n",
                encoding="utf-8",
            )
            rows, issues = load_audit_table(path)

        self.assertEqual(rows, [])
        self.assertEqual({issue["check"] for issue in issues}, {"table_version", "table_columns"})

    def test_correctness_recomputes_catalog_source_hash(self) -> None:
        entry = _entry("misc", "misc:0x0050", "Welcome")
        tampered = CatalogEntry(
            entry.kind, entry.key, entry.source, "0" * 64, entry.context,
            entry.origin, entry.protected_tokens,
        )
        row = RuntimeRow(entry.kind, entry.key, source_sha256(entry.source), "歡迎")
        report = correctness_report([tampered], [row], GLOSSARY, None)

        self.assertIn(
            "catalog_source_hash",
            {issue["check"] for issue in report["deterministic"]["issues"]},
        )

    def test_semantic_review_is_advisory_and_does_not_change_exit_status(self) -> None:
        entry = _entry("misc", "misc:0x0050", "Welcome")
        row = RuntimeRow(entry.kind, entry.key, entry.source_sha256, "歡迎")
        report = correctness_report(
            [entry], [row], GLOSSARY,
            [{"key": entry.key, "status": "advisory", "issues": ["tone"]}],
        )

        self.assertEqual(report["semantic"]["policy"], "advisory")
        self.assertFalse(report["semantic"]["has_failures"])
        self.assertEqual(report_exit_code(report, strict=True), 0)
        strict_report = correctness_report(
            [entry], [row], GLOSSARY,
            [{"key": entry.key, "status": "advisory", "issues": ["tone"]}],
            semantic_strict=True,
        )
        self.assertTrue(strict_report["semantic"]["has_failures"])
        self.assertNotEqual(report_exit_code(strict_report, strict=True), 0)


if __name__ == "__main__":
    unittest.main()
