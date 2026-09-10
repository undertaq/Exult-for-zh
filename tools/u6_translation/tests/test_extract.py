from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tools.u6_translation.catalog import source_sha256
from tools.u6_translation.extract import extract_catalog


class ExtractionTest(unittest.TestCase):
    def test_ucxt_textmsg_and_runtime_rows_merge_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patch = root / "Ultima6v1.3" / "patch"
            patch.mkdir(parents=True)
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
        self.assertIn("dialogue:0x0401:0x0010:0", by_key)
        self.assertIn("dialogue:0x0401:0x0010:1", by_key)
        self.assertIn("textmsg:0x0123", by_key)
        self.assertEqual(by_key["textmsg:0x002a"].context, "location")
        self.assertIn("choice:0x0401:0x0088:0", by_key)
        self.assertNotIn("choice:0x0401:unbound:0", by_key)
        self.assertIn("static-usecode", by_key["choice:0x0401:0x0088:0"].origin)
        self.assertIn("runtime-capture", by_key["choice:0x0401:0x0088:0"].origin)


if __name__ == "__main__":
    unittest.main()
