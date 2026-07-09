#!/usr/bin/env python3
import importlib.util
import struct
import sys
import unittest
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


if __name__ == "__main__":
    unittest.main()
