"""Display-scope fixture for the U6 runtime translation pipeline.

Task 6 supplies the catalog codec and runtime-manager seams imported here.
The small lookup seams below deliberately model the C++ boundary: raw data
lookups remain English, while gameplay display helpers receive translated
copies.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from tools.u6_translation.catalog import CatalogEntry, source_sha256


TEXT_MESSAGE_KEY = "textmsg:0x0123"
ITEM_KEY = "item:0x01f4:2:7"
MISC_KEY = "misc:0x0042"

RAW_VALUES = {
    TEXT_MESSAGE_KEY: "The bed is occupied.",
    ITEM_KEY: "a torch",
    MISC_KEY: "the Avatar",
}

TRANSLATED_VALUES = {
    TEXT_MESSAGE_KEY: "床鋪有人。",
    ITEM_KEY: "火炬",
    MISC_KEY: "聖者",
}


def _entry(kind: str, key: str) -> CatalogEntry:
    source = RAW_VALUES[key]
    return CatalogEntry(
        kind=kind,
        key=key,
        source=source,
        source_sha256=source_sha256(source),
        context="gameplay",
        origin="display-scope-fixture",
        protected_tokens=(),
    )


FIXTURE_ENTRIES = (
    _entry("textmsg", TEXT_MESSAGE_KEY),
    _entry("item", ITEM_KEY),
    _entry("misc", MISC_KEY),
)


@dataclass
class RecordingManager:
    """Task 6-compatible manager seam used to assert display boundaries."""

    translations: dict[str, str]

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def translate(self, kind: str, key: str, english: str) -> str:
        self.calls.append((kind, key, english))
        return self.translations.get(key, english)


def raw_text_message(message_id: int) -> str:
    assert message_id == 0x0123
    return RAW_VALUES[TEXT_MESSAGE_KEY]


def gameplay_text_message(manager: RecordingManager, message_id: int) -> str:
    english = raw_text_message(message_id)
    return manager.translate("textmsg", TEXT_MESSAGE_KEY, english)


def raw_item_name(shape: int, frame: int, quality: int) -> str:
    assert (shape, frame, quality) == (0x01F4, 2, 7)
    return RAW_VALUES[ITEM_KEY]


def gameplay_item_name(manager: RecordingManager, shape: int, frame: int, quality: int) -> str:
    english = raw_item_name(shape, frame, quality)
    return manager.translate("item", ITEM_KEY, english)


def raw_avatar_name() -> str:
    return RAW_VALUES[MISC_KEY]


def gameplay_avatar_name(manager: RecordingManager) -> str:
    english = raw_avatar_name()
    return manager.translate("misc", MISC_KEY, english)


def exult_menu_text_message() -> str:
    """An Exult menu uses the raw lookup, never the gameplay manager."""

    return raw_text_message(0x0123)


class DisplayScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = RecordingManager(dict(TRANSLATED_VALUES))

    def test_gameplay_helpers_translate_display_copies_only(self) -> None:
        self.assertEqual(gameplay_text_message(self.manager, 0x0123), "床鋪有人。")
        self.assertEqual(
            gameplay_item_name(self.manager, 0x01F4, 2, 7), "火炬"
        )
        self.assertEqual(gameplay_avatar_name(self.manager), "聖者")

        self.assertEqual(raw_text_message(0x0123), "The bed is occupied.")
        self.assertEqual(raw_item_name(0x01F4, 2, 7), "a torch")
        self.assertEqual(raw_avatar_name(), "the Avatar")

    def test_exult_menu_lookup_does_not_call_gameplay_helper(self) -> None:
        self.assertEqual(exult_menu_text_message(), "The bed is occupied.")
        self.assertEqual(self.manager.calls, [])


if __name__ == "__main__":
    unittest.main()
