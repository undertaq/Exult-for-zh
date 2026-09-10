from __future__ import annotations

import unittest

from tools.u6_translation.extract import (
    make_choice_key,
    make_dialogue_key,
    make_item_key,
    split_runtime_segments,
)


class RuntimeKeyTest(unittest.TestCase):
    def test_key_builders_match_accepted_cpp_formats(self) -> None:
        self.assertEqual(
            make_dialogue_key(0x0401, "1a_2f", 0),
            "dialogue:0x0401:1a_2f:0",
        )
        self.assertEqual(
            make_choice_key(0x0401, 0x0088, 2),
            "choice:0x0401:0x0088:2",
        )
        self.assertEqual(make_item_key(0x01F4, 2, 7), "item:0x01f4:2:7")

    def test_segment_split_matches_runtime_tilde_behavior(self) -> None:
        self.assertEqual(split_runtime_segments("one~two"), ["one", "two"])
        self.assertEqual(split_runtime_segments("one~~two"), ["one", "two"])
        self.assertEqual(split_runtime_segments("one~"), ["one"])
        self.assertEqual(split_runtime_segments("*one"), ["one"])


if __name__ == "__main__":
    unittest.main()
