from __future__ import annotations

import os
import shutil
from unittest import mock
import tempfile
import unittest
from pathlib import Path

from tools.u6_translation.catalog import source_sha256
from tools.u6_translation.extract import _parse_ucxt, _run_ucxt, extract_catalog, make_item_key
from tools.u6_translation.runtime_table import escape_field


FIXTURES = Path(__file__).parent / "fixtures"


class ExtractionTest(unittest.TestCase):
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
        self.assertEqual(by_key["textmsg:0x002a"].context, "location")
        self.assertIn("choice:0x0401:0x0088:0", by_key)
        self.assertNotIn("choice:0x0401:unbound:0", by_key)
        self.assertIn("static-usecode", by_key["choice:0x0401:0x0088:0"].origin)
        self.assertIn("runtime-capture", by_key["choice:0x0401:0x0088:0"].origin)

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


if __name__ == "__main__":
    unittest.main()
