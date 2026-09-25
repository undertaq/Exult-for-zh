#!/usr/bin/env python3
import importlib.util
import io
import json
import struct
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from contextlib import redirect_stdout


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
    def test_static_line_keeps_legacy_voice_and_csv_output(self):
        module = load_script_module()
        func = {
            "id": 0xFEEE,
            "data_len": 4,
            "instructions": [
                (0x0100, b"", "addsi", [0x0600], ""),
                (0x0104, b"", "say", [], ""),
            ],
            "strings": {0x0600: "Welcome home."},
            "externs": [],
        }

        line = module.extract_say_lines(func)[0]
        self.assertEqual(
            (line["offset_key"], line["segment"], line["total_segments"],
             line["has_var"], line["text"]),
            ("0x600", 0, 1, False, "Welcome home."),
        )
        self.assertEqual(
            module.format_voice(func),
            [
                "\nFunction 0xFEEE",
                "  Data: 4 bytes, 1 strings",
                '  L0600: "Welcome home."',
                "\n  Code (voice-relevant):",
                '  0100: addsi\tL0600\t; "Welcome home."',
                "  0104: say",
            ],
        )

        csv_output = io.StringIO()
        module.write_csv([func], csv_output)
        self.assertEqual(
            csv_output.getvalue().splitlines(),
            [
                "func_id,npc,speaker,caller_guess,offset_key,segment,total_segments,has_var,text",
                "0xFEEE,,,,0x600,0,1,False,Welcome home.",
            ],
        )

    def test_cli_accepts_dynamic_json_format(self):
        module = load_script_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            usecode_path = Path(temp_dir) / "empty-usecode.bin"
            usecode_path.write_bytes(b"")
            output = io.StringIO()
            with mock.patch.object(
                    sys, "argv",
                    [str(SCRIPT_PATH), str(usecode_path), "--list",
                     "--format", "dynamic-json"]):
                with redirect_stdout(output):
                    try:
                        module.main()
                    except SystemExit as exc:
                        self.fail(f"dynamic-json CLI option was rejected (exit {exc.code})")

        self.assertEqual(output.getvalue(), "Loaded 0 functions\n")

    def test_dynamic_json_outputs_segment_templates_and_origins(self):
        module = load_script_module()
        func = {
            "id": 0x0431,
            "instructions": [
                (0x0100, b"", "addsi", [0x0600], ""),
                (0x0104, b"", "addsv", [7], ""),
                (0x0108, b"", "addsi", [0x0610], ""),
                (0x010C, b"", "say", [], ""),
            ],
            "strings": {0x0600: "Hello ", 0x0610: "."},
            "externs": [],
        }

        formatter = getattr(module, "format_dynamic_json", None)
        self.assertTrue(callable(formatter), "dynamic-json formatter is not implemented")
        records = [json.loads(row) for row in formatter([func]).splitlines()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source_template_en"], "Hello <VAR0>.")
        self.assertTrue(records[0]["dynamic"])
        self.assertEqual(records[0]["func_id"], 0x0431)
        self.assertEqual(records[0]["source_parts"][1]["source_offset"], 0x0104)

    def test_extract_say_lines_keeps_dynamic_slot_source_provenance(self):
        module = load_script_module()
        func = {
            "id": 0x0431,
            "instructions": [
                (0x0100, b"", "addsi", [0x0600], ""),
                (0x0104, b"", "addsv", [7], ""),
                (0x0108, b"", "addsi", [0x0610], ""),
                (0x010C, b"", "say", [], ""),
            ],
            "strings": {0x0600: "Good afternoon, ", 0x0610: "."},
            "externs": [],
        }

        line = module.extract_say_lines(func)[0]

        self.assertEqual(line.get("source_template_en"), "Good afternoon, <VAR0>.")
        self.assertEqual(
            line.get("source_parts"),
            [
                {
                    "kind": "literal",
                    "source_func_id": 0x0431,
                    "source_offset": 0x0100,
                    "string_offset": 0x0600,
                    "text": "Good afternoon, ",
                },
                {
                    "kind": "dynamic",
                    "source_func_id": 0x0431,
                    "source_offset": 0x0104,
                    "variable_index": 7,
                    "ordinal": 0,
                    "label": "<VAR>",
                    "semantic_type": "unknown",
                },
                {
                    "kind": "literal",
                    "source_func_id": 0x0431,
                    "source_offset": 0x0108,
                    "string_offset": 0x0610,
                    "text": ".",
                },
            ],
        )

    def test_extract_say_lines_classifies_numeric_runtime_slots(self):
        module = load_script_module()
        func = {
            "id": 0x0431,
            "instructions": [
                (0x0100, b"", "pushi", [5], ""),
                (0x0102, b"", "pop", [7], ""),
                (0x0104, b"", "addsi", [0x0600], ""),
                (0x0108, b"", "addsv", [7], ""),
                (0x010C, b"", "say", [], ""),
            ],
            "strings": {0x0600: "You need "},
            "externs": [],
        }

        line = module.extract_say_lines(func)[0]

        self.assertEqual(line["source_template_en"], "You need <VAR0>")
        self.assertEqual(
            next(part for part in line["source_parts"] if part["kind"] == "dynamic")[
                "semantic_type"],
            "number",
        )

    def test_extract_say_lines_infers_unambiguous_pronoun_form(self):
        module = load_script_module()
        func = {
            "id": 0x0431,
            "instructions": [
                (0x0100, b"", "pushs", [0x0600], ""),
                (0x0104, b"", "pop", [7], ""),
                (0x0108, b"", "pushs", [0x0610], ""),
                (0x010C, b"", "pop", [7], ""),
                (0x0110, b"", "addsi", [0x0620], ""),
                (0x0114, b"", "addsv", [7], ""),
                (0x0118, b"", "say", [], ""),
            ],
            "strings": {
                0x0600: "he", 0x0610: "she", 0x0620: "Ask if ",
            },
            "externs": [],
        }

        dynamic = next(
            part for part in module.extract_say_lines(func)[0]["source_parts"]
            if part["kind"] == "dynamic")

        self.assertEqual(dynamic["semantic_type"], "pronoun")
        self.assertEqual(dynamic["pronoun_form"], "subject")

    def test_extract_say_lines_numbers_repeated_dynamic_slots_per_page(self):
        module = load_script_module()
        func = {
            "id": 0x0431,
            "instructions": [
                (0x0020, b"", "addsi", [0x0600], ""),
                (0x0024, b"", "addsv", [3], ""),
                (0x0028, b"", "addsi", [0x0610], ""),
                (0x002C, b"", "addsv", [3], ""),
                (0x0030, b"", "addsi", [0x0620], ""),
                (0x0034, b"", "addsv", [3], ""),
                (0x0038, b"", "addsi", [0x0630], ""),
                (0x003C, b"", "say", [], ""),
            ],
            "strings": {
                0x0600: "Ask ",
                0x0610: " and ",
                0x0620: " now~Then ask ",
                0x0630: " again.",
            },
            "externs": [],
        }

        lines = module.extract_say_lines(func)

        self.assertEqual([line.get("source_template_en") for line in lines], [
            "Ask <VAR0> and <VAR1> now",
            "Then ask <VAR0> again.",
        ])
        self.assertEqual(
            [[part["ordinal"] for part in line.get("source_parts", []) if part["kind"] == "dynamic"]
             for line in lines],
            [[0, 1], [0]],
        )
        self.assertEqual(
            [[part["source_offset"] for part in line.get("source_parts", []) if part["kind"] == "dynamic"]
             for line in lines],
            [[0x0024, 0x002C], [0x0034]],
        )

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
