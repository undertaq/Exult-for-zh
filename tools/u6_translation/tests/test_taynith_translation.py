from __future__ import annotations

from pathlib import Path
import unittest


class TaynithTranslationTest(unittest.TestCase):
    def test_cloak_folds_use_the_traditional_font_glyph(self) -> None:
        table = Path(__file__).parents[1] / "zh_translation.tsv"
        row = next(
            line
            for line in table.read_text(encoding="utf-8").splitlines()
            if "\tdialogue:0x0438:560:0\t" in line
        )
        translation = row.split("\t", 3)[3]

        self.assertIn("褶皺", translation)
        self.assertNotIn("皱", translation)


if __name__ == "__main__":
    unittest.main()
