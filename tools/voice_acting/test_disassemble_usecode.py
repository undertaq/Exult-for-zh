#!/usr/bin/env python3
import importlib.util
import struct
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("disassemble_usecode.py")


def load_script_module():
    spec = importlib.util.spec_from_file_location("disassemble_usecode_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPT_PATH.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPT_PATH.parent))
    return module


class DisassembleUsecodeTest(unittest.TestCase):
    def test_skip_symbol_table_handles_function_entries(self):
        module = load_script_module()
        data = bytearray()
        data += struct.pack("<II", 0xFFFFFFFF, 0x55435359)
        data += struct.pack("<II", 2, 0)

        data += b"Func0096\0"
        data += struct.pack("<HII", 6, 0x0096, 0x0096)

        data += b"ImportedThing\0"
        data += struct.pack("<HII", 7, 0x1234, 0x5678)

        expected_offset = len(data)
        data += b"\x96\x00\x00\x00"

        self.assertEqual(module.skip_symbol_table(bytes(data), 0), expected_offset)

    def test_load_npc_catalog_overrides_u7_name_collisions(self):
        module = load_script_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "npc.tsv"
            path.write_text(
                "name\tface_id\tusecode_func_id\n"
                "Chuckles\t55\t0x437\n"
                "Dupre\t4\t0x404\n"
                "no one\t356\t\n",
                encoding="utf-8",
            )
            module.load_npc_catalog(path)
        self.assertEqual(module.get_npc_name(0x437), "Chuckles")
        self.assertEqual(module.get_npc_name(0x404), "Dupre")
        self.assertEqual(module.get_npc_name(0x400 + 356), "Avatar")

    def test_extract_say_lines_restores_speaker_after_guest_face(self):
        module = load_script_module()
        # The function has two possible guest faces, so its own NPC remains
        # the default speaker before and after the temporary Dupre face.
        instructions = [
            (0x00, b"", "pushi", [0], ""),
            (0x01, b"", "pushi", [-4], ""),
            (0x02, b"", "calli", [0x03, 2], ""),
            (0x03, b"", "addsi", [0], ""),
            (0x04, b"", "say", [], ""),
            (0x05, b"", "pushi", [0], ""),
            (0x06, b"", "pushi", [-4], ""),
            (0x07, b"", "calli", [0x03, 2], ""),
            (0x08, b"", "addsi", [0], ""),
            (0x09, b"", "say", [], ""),
            (0x0A, b"", "pushi", [0], ""),
            (0x0B, b"", "pushi", [-4], ""),
            (0x0C, b"", "calli", [0x04, 1], ""),
            (0x0D, b"", "addsi", [4], ""),
            (0x0E, b"", "say", [], ""),
            (0x0F, b"", "pushi", [0], ""),
            (0x10, b"", "pushi", [-55], ""),
            (0x11, b"", "calli", [0x03, 2], ""),
        ]
        func = {
            "id": 0x0437,
            "instructions": instructions,
            "strings": {0: "guest", 4: "owner"},
            "externs": [],
        }
        names = {0x0437: "Chuckles", 0x404: "Dupre", 0x437: "Chuckles", 0x437 + 0x400: "Chuckles"}
        with mock.patch.object(module, "get_npc_name", side_effect=lambda npc: names.get(npc, "")):
            lines = module.extract_say_lines(func)

        self.assertEqual(
            [line["speaker"] for line in lines],
            ["Dupre", "Dupre", "Chuckles"],
        )


if __name__ == "__main__":
    unittest.main()
