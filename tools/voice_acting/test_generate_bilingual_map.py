#!/usr/bin/env python3
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("generate_bilingual_map.py")


def load_script_module():
    spec = importlib.util.spec_from_file_location(
        "generate_bilingual_map_under_test", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_c_string(data, pos):
    end = data.index(b"\0", pos)
    return data[pos:end].decode("utf-8"), end + 1


def read_blmp(path):
    data = Path(path).read_bytes()
    pos = 0
    assert data[pos : pos + 4] == b"BLMP"
    pos += 4
    count = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    rows = []
    for _ in range(count):
        zh_func_id = struct.unpack_from("<i", data, pos)[0]
        pos += 4
        zh_offset_key, pos = read_c_string(data, pos)
        segment = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        en_func_id = struct.unpack_from("<i", data, pos)[0]
        pos += 4
        en_offset_key, pos = read_c_string(data, pos)
        rows.append((zh_func_id, zh_offset_key, segment, en_func_id, en_offset_key))
    assert pos == len(data)
    return rows


class GenerateBilingualMapTest(unittest.TestCase):
    def test_writes_only_paired_review_rows_to_blmp(self):
        module = load_script_module()

        rows = [
            {
                "en_text": "Thou must see for thyself.",
                "zh_text": "你必須親自看看。",
                "en_func_id": "0x0401",
                "en_offset_key": "748_765",
                "en_segment": 0,
                "zh_func_id": "0x0401",
                "zh_offset_key": "748_765",
                "zh_segment": 0,
            },
            {
                "en_text": "Same key, second segment.",
                "zh_text": "同一鍵，第二段。",
                "en_func_id": "0401",
                "en_offset_key": "748_765",
                "en_segment": 1,
                "zh_func_id": "0401",
                "zh_offset_key": "748_765",
                "zh_segment": 1,
            },
            {
                "en_text": "Unpaired English line is excluded.",
                "zh_text": "",
                "en_func_id": "0x0401",
                "en_offset_key": "999",
                "en_segment": 0,
                "zh_func_id": "",
                "zh_offset_key": "",
                "zh_segment": "",
            },
            {
                "en_text": "English voice for a Chinese-only usecode line.",
                "zh_text": "中文 usecode 專用台詞。",
                "en_func_id": "",
                "en_offset_key": "",
                "en_segment": 0,
                "zh_func_id": "0x0401",
                "zh_offset_key": "6af",
                "zh_segment": 0,
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            review_path = root / "review.json"
            output_path = root / "bilingual_map.dat"
            review_path.write_text(json.dumps(rows), encoding="utf-8")

            mappings = module.load_canonical_mappings(review_path)
            module.write_blmp(mappings, output_path)

            self.assertEqual(
                read_blmp(output_path),
                [
                    (0x0401, "748_765", 0, 0x0401, "748_765"),
                    (0x0401, "748_765", 1, 0x0401, "748_765"),
                ],
            )

    def test_rejects_rows_with_different_en_and_zh_segments(self):
        module = load_script_module()
        rows = [
            {
                "en_text": "English.",
                "zh_text": "中文。",
                "en_func_id": "0x0001",
                "en_offset_key": "10",
                "en_segment": 1,
                "zh_func_id": "0x0002",
                "zh_offset_key": "20",
                "zh_segment": 2,
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            review_path = Path(tmpdir) / "review.json"
            review_path.write_text(json.dumps(rows), encoding="utf-8")

            with self.assertRaises(ValueError):
                module.load_canonical_mappings(review_path)


if __name__ == "__main__":
    unittest.main()
