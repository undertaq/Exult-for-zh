from __future__ import annotations

import os
import shutil
from unittest import mock
import tempfile
import unittest
from pathlib import Path

from tools.u6_translation.catalog import CatalogEntry, source_sha256
from tools.u6_translation.extract import (
    _canonicalize_runtime_key_collisions,
    _parse_ucxt,
    _pair_usecode_translation_rows,
    _run_ucxt,
    extract_catalog,
    make_item_key,
)
from tools.u6_translation.runtime_table import escape_field


FIXTURES = Path(__file__).parent / "fixtures"


class ExtractionTest(unittest.TestCase):
    def test_book_dialogue_is_marked_and_dynamic_templates_are_cataloged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patch = root / "Ultima6v1.3" / "patch"
            patch.mkdir(parents=True)
            (patch / "usecode").write_bytes(b"fixture")
            ucxt = root / "ucxt-fixture"
            ucxt.write_text(
                "#!/bin/sh\n"
                "printf '%s' '<0x0282>\n"
                "  <0x0010>\n"
                "  `Book content`\n"
                "  </>\n"
                "</>\n"
                "<0x0494>\n"
                "  <0x0600>\n"
                "  `@Good `\n"
                "  </>\n"
                "  <0x060a>\n"
                "  `. What wouldst thou speak of?@`\n"
                "  </>\n"
                "</>\n"
                "<0x0cdb>\n"
                "  <0x0010>\n"
                "  `Book extension`\n"
                "  </>\n"
                "</>'\n",
                encoding="utf-8",
            )
            ucxt.chmod(ucxt.stat().st_mode | 0o111)

            entries = extract_catalog(root, ucxt, None)

        by_key = {(entry.kind, entry.key): entry for entry in entries}
        book = by_key[("dialogue", "dialogue:0x0282:10:0")]
        self.assertEqual(book.context, "book")
        self.assertEqual(by_key[("dialogue", "dialogue:0x0cdb:10:0")].context, "book")
        template = by_key[("dialogue", "dialogue:0x0494:template_lord_british_greeting:0")]
        self.assertEqual(
            template.source,
            "@Good <TIME_OF_DAY>, <PLAYER_NAME>. What wouldst thou speak of?@",
        )
        self.assertEqual(template.context, "dynamic-template")

    def test_ucxt_decimal_function_tags_use_decimal_ids(self) -> None:
        entries = _parse_ucxt(
            "<401>\n"
            "  <0x0010>\n"
            "  `Decimal function`\n"
            "  </>\n"
            "</>\n"
            "<0x0401>\n"
            "  <0x0020>\n"
            "  `Hex function`\n"
            "  </>\n"
            "</>\n"
        )

        self.assertEqual(
            [entry.key for entry in entries],
            ["dialogue:0x0191:10:0", "dialogue:0x0401:20:0"],
        )

    def test_ucxt_joins_wrapped_translation_table_strings(self) -> None:
        entries = _parse_ucxt(
            "<0x0282>\n"
            "  <0x0010>\n"
            "  `A book sentence that was wrapped\n"
            "continues on the next output line.`\n"
            "  </>\n"
            "</>\n"
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(
            entries[0].source,
            "A book sentence that was wrappedcontinues on the next output line.",
        )

    def test_ucxt_preserves_indented_newlines_inside_book_strings(self) -> None:
        entries = _parse_ucxt(
            "<0x0282>\n"
            "  <0x0010>\n"
            "  `First page.~\n"
            "\t\tSecond page.\n"
            "\n"
            "\t\tThird page.`\n"
            "  </>\n"
            "</>\n"
        )

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].source, "First page.")
        self.assertEqual(entries[1].source, "\n\t\tSecond page.\n\n\t\tThird page.")
        self.assertEqual(
            entries[1].source_sha256,
            source_sha256("\n\t\tSecond page.\n\n\t\tThird page."),
        )

    def test_ucxt_does_not_split_latin1_utf8_continuation_bytes_as_lines(self) -> None:
        entries = _parse_ucxt(
            "<0x0282>\n"
            "  <0x0010>\n"
            "  `prefix\x85suffix`\n"
            "  </>\n"
            "</>\n"
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].source, "prefix\x85suffix")

    def test_fallback_book_rows_pair_addsi_references_in_order(self) -> None:
        rows = _pair_usecode_translation_rows(
            english_data={(0x0282, 0x0010): "~~ ~~BOOK~~  ~~by Author*"},
            chinese_data={(0x0282, 0x0020): "~~ ~~《書名》~~  ~~作者 著*"},
            english_references={0x0282: [0x0010]},
            chinese_references={0x0282: [0x0020]},
            functions={0x0282},
        )

        self.assertEqual(
            [(row.key, row.source_sha256, row.zh) for row in rows],
            [
                (
                    "dialogue:0x0282:fallback_10:1",
                    source_sha256("BOOK"),
                    "《書名》",
                ),
                (
                    "dialogue:0x0282:fallback_10:3",
                    source_sha256("by Author*"),
                    "作者 著*",
                ),
            ],
        )

    def test_ucxt_permission_error_does_not_double_shell_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            usecode = root / "Ultima6v1.3" / "patch" / "usecode"
            usecode.parent.mkdir(parents=True)
            usecode.write_bytes(b"fixture")
            ucxt = root / "ucxt-fixture"
            ucxt.write_text("exit 0\n", encoding="utf-8")

            shell_command = ["/bin/sh", str(ucxt), "-nc", "-ftt", f"-i{usecode}", "-a"]
            with mock.patch(
                "tools.u6_translation.extract.subprocess.check_output",
                side_effect=[PermissionError(), "output"],
            ) as check_output:
                self.assertEqual(_run_ucxt(root, ucxt), "output")

        self.assertEqual(check_output.call_args_list[0].args[0], shell_command)
        self.assertEqual(check_output.call_args_list[1].args[0], shell_command)

    def test_ucxt_uses_the_mod_usecode_file_and_decodes_raw_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            usecode = root / "Ultima6v1.3" / "patch" / "usecode"
            usecode.parent.mkdir(parents=True)
            usecode.write_bytes(b"compiled U6 usecode")
            ucxt = root / "ucxt-fixture"
            ucxt.write_text("exit 0\n", encoding="utf-8")
            ucxt.chmod(ucxt.stat().st_mode | os.X_OK)

            with mock.patch(
                "tools.u6_translation.extract.subprocess.check_output",
                return_value=b"text \xb4\n",
            ) as check_output:
                self.assertEqual(_run_ucxt(root, ucxt), "text ´\n")

        self.assertEqual(
            check_output.call_args.args[0],
            [str(ucxt), "-nc", "-ftt", f"-i{usecode}", "-a"],
        )

    def test_ucxt_textmsg_and_runtime_rows_merge_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patch = root / "Ultima6v1.3" / "patch"
            patch.mkdir(parents=True)
            (patch / "usecode").write_bytes(b"fixture")
            (patch / "textmsg.txt").write_text(
                "%%section msgs\n"
                "0x0123:Line message\n"
                "0x0124: \n"
                "%%endsection\n"
                "%%section locations\n"
                "0x002a:Britain\n"
                "%%endsection\n",
                encoding="utf-8",
            )
            (root / "dialogue.uc").write_text(
                "void Func0401() {\n"
                "  UI_add_answer([\"yes\", \"no\"]);\n"
                "}\n",
                encoding="utf-8",
            )
            ucxt = root / "ucxt-fixture"
            ucxt.write_text(
                "#!/bin/sh\n"
                "printf '%s' '<trans>\n"
                "  <0x0401>\n"
                "    <0x0010>\n"
                "    `First~Second`\n"
                "    </>\n"
                "  </>\n"
                "</>'\n",
                encoding="utf-8",
            )
            ucxt.chmod(ucxt.stat().st_mode | os.X_OK)
            runtime = root / "runtime.tsv"
            runtime.write_text(
                "# u6-runtime-catalog-v1\n"
                "# kind\tkey\tsource_sha256\tenglish\n"
                "choice\tchoice:0x0401:0x0088:0\t"
                f"{source_sha256('yes')}\tyes\n",
                encoding="utf-8",
            )

            entries = extract_catalog(root, ucxt, runtime)

        by_key = {entry.key: entry for entry in entries}
        self.assertIn("dialogue:0x0401:10:0", by_key)
        self.assertIn("dialogue:0x0401:10:1", by_key)
        self.assertIn("textmsg:0x0123", by_key)
        self.assertNotIn("textmsg:0x0124", by_key)
        self.assertEqual(by_key["textmsg:0x002a"].context, "location")
        self.assertIn("choice:0x0401:0x0088:0", by_key)
        self.assertNotIn("choice:0x0401:unbound:0", by_key)
        self.assertIn("static-usecode", by_key["choice:0x0401:0x0088:0"].origin)
        self.assertIn("runtime-capture", by_key["choice:0x0401:0x0088:0"].origin)

    def test_runtime_dialogue_reuses_static_key_when_offset_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patch = root / "Ultima6v1.3" / "patch"
            patch.mkdir(parents=True)
            (patch / "usecode").write_bytes(b"fixture")
            source = "@A question assembled at runtime?@"
            (root / "ucxt_fixture.sh").write_text(
                "#!/bin/sh\n"
                "printf '%s' '<0x0401>\n"
                "  <0x2048>\n"
                "  `@A question assembled at runtime?@`\n"
                "  </>\n"
                "  <0x02e2>\n"
                "  `Spirituality`\n"
                "  </>\n"
                "</>'\n",
                encoding="utf-8",
            )
            ucxt = root / "ucxt_fixture.sh"
            ucxt.chmod(ucxt.stat().st_mode | os.X_OK)
            runtime = root / "runtime.tsv"
            runtime.write_text(
                "dialogue\tdialogue:0x0401:2e2:0\t"
                f"{source_sha256(source)}\t{source}\n",
                encoding="utf-8",
            )

            entries = extract_catalog(root, ucxt, runtime)

        by_key = {entry.key: entry for entry in entries}
        self.assertIn("dialogue:0x0401:2048:0", by_key)
        self.assertIn("static-ucxt", by_key["dialogue:0x0401:2048:0"].origin)
        self.assertIn("runtime-capture", by_key["dialogue:0x0401:2048:0"].origin)
        self.assertEqual(
            by_key["dialogue:0x0401:2048:0"].source,
            source,
        )
        self.assertEqual(
            by_key["dialogue:0x0401:2e2:0"].source,
            "Spirituality",
        )

    def test_indexed_u6_resources_emit_item_variants_and_location_context(self) -> None:
        root = FIXTURES / "indexed_mod"
        entries = extract_catalog(root, root / "ucxt_fixture.sh", None)
        by_key = {entry.key: entry for entry in entries}

        self.assertEqual(make_item_key(0x01F4, 0, 0), "item:0x01f4:0:0")
        self.assertEqual(by_key["item:0x01f4:0:0"].source, "a torch")
        self.assertEqual(by_key["item:0x01f4:2:7"].source, "a jeweled torch")
        self.assertEqual(by_key["item:0x01f4:2:7"].context, "gameplay")
        self.assertEqual(by_key["textmsg:0x002a"].source, "Britain")
        self.assertEqual(by_key["textmsg:0x002a"].context, "location")
        self.assertEqual(by_key["spell:0x0000"].source, "Awaken")
        self.assertEqual(by_key["spell:0x0012"].source, "Corp Por")

    def test_ucxt_resets_function_callsite_and_segment_ordinals(self) -> None:
        root = FIXTURES / "indexed_mod"
        entries = extract_catalog(root, root / "ucxt_fixture.sh", None)
        keys = [entry.key for entry in entries if entry.kind == "dialogue"]
        self.assertEqual(
            keys,
            [
                "dialogue:0x0401:10:0",
                "dialogue:0x0401:10:1",
                "dialogue:0x0401:20:0",
                "dialogue:0x0402:30:0",
            ],
        )

    def test_ucxt_normalizes_compound_addsi_offset_marker(self) -> None:
        entries = _parse_ucxt(
            "<0x0401>\n"
            "  <0x001a> <0x002f>\n"
            "  `Compound`\n"
            "  </>\n"
            "</>\n"
        )

        self.assertEqual(
            [entry.key for entry in entries],
            ["dialogue:0x0401:1a_2f:0"],
        )

    def test_ucxt_omits_blank_segments_without_renumbering_following_segments(self) -> None:
        entries = _parse_ucxt(
            "<0x0401>\n"
            "  <0x0010>\n"
            "  `~~ ~~Captain`\n"
            "  </>\n"
            "</>\n"
        )

        self.assertEqual(
            [(entry.key, entry.source) for entry in entries],
            [("dialogue:0x0401:10:1", "Captain")],
        )

    def test_choices_bind_by_function_callsite_and_ordinal_not_source_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "indexed_mod"
            shutil.copytree(FIXTURES / "indexed_mod", root)
            runtime = root / "choices.tsv"
            rows = [
                ("choice", "choice:0x0402:0x0088:0", source_sha256("repeat"), "repeat"),
                ("choice", "choice:0x0401:0x0099:0", source_sha256("repeat"), "repeat"),
                ("choice", "choice:0x0401:0x0088:0", source_sha256("repeat"), "repeat"),
                ("choice", "choice:0x0401:0x0088:1", source_sha256("repeat"), "repeat"),
            ]
            runtime.write_text(
                "\n".join("\t".join(escape_field(field) for field in row) for row in rows) + "\n",
                encoding="utf-8",
            )
            entries = extract_catalog(root, root / "ucxt_fixture.sh", runtime)
        by_key = {entry.key: entry for entry in entries}

        for key in (
            "choice:0x0401:0x0088:0",
            "choice:0x0401:0x0088:1",
            "choice:0x0401:0x0099:0",
            "choice:0x0402:0x0088:0",
        ):
            self.assertIn(key, by_key)
            self.assertIn("static-usecode", by_key[key].origin)
            self.assertIn("runtime-capture", by_key[key].origin)
        self.assertIn("choice:0x0403:unbound:0", by_key)

    def test_dynamic_runtime_rows_use_source_stable_keys_when_callsite_repeats(self) -> None:
        question = "@Dost thou choose the first path, or the second path?@"
        first_answer = "choose the first path"
        second_answer = "choose the second path"
        rows = [
            CatalogEntry.from_source(
                "dialogue", "dialogue:0x0464:2e2:0", question,
                "gameplay", "runtime-capture",
            ),
            CatalogEntry.from_source(
                "dialogue", "dialogue:0x0464:2e2:0", "Another question?",
                "gameplay", "runtime-capture",
            ),
            CatalogEntry.from_source(
                "choice", "choice:0x0956:0x000b:0", first_answer,
                "gameplay", "runtime-capture",
            ),
            CatalogEntry.from_source(
                "choice", "choice:0x0956:0x000b:0", second_answer,
                "gameplay", "runtime-capture",
            ),
        ]

        canonical = _canonicalize_runtime_key_collisions(rows)
        keys = {entry.key for entry in canonical}
        question_hash = source_sha256(question)
        another_hash = source_sha256("Another question?")
        first_hash = source_sha256(first_answer)
        second_hash = source_sha256(second_answer)
        self.assertIn(f"dialogue:0x0464:{question_hash}:0", keys)
        self.assertIn(f"dialogue:0x0464:{another_hash}:0", keys)
        self.assertIn(f"choice:0x0956:0x{first_hash[:16]}:0", keys)
        self.assertIn(f"choice:0x0956:0x{second_hash[:16]}:0", keys)


if __name__ == "__main__":
    unittest.main()
