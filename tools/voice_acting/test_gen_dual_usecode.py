"""Tests for gen_dual_usecode.py."""
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import gen_dual_usecode as g

ADDSI = 0x1C
SAY = 0x33


def build_func(func_id, code, data, extended=False):
    """Wrap code+data into a function blob (classic or 0xfffe header)."""
    tail = struct.pack("<HHH", 0, 0, 0) + code   # args, vars, externs
    # func_len spans the data-length field itself (2 classic / 4 extended)
    body_len = (4 if extended else 2) + len(data) + len(tail)
    if extended:
        blob = struct.pack("<H", 0xFFFE) + struct.pack("<i", func_id)
        blob += struct.pack("<I", body_len) + struct.pack("<i", len(data))
    else:
        blob = struct.pack("<H", func_id) + struct.pack("<H", body_len)
        blob += struct.pack("<H", len(data))
    return blob + data + tail


def test_offset_key_for():
    assert g.offset_key_for([0x88, 0x1A0]) == "88_1a0"
    assert g.offset_key_for([0]) == "0"


def test_build_merged():
    assert g.build_merged("zh", "en") == "zh\nen"


def test_generate_merges_and_preserves_unmerged():
    data = b"HELLO\0world\0"
    code1 = struct.pack("<B", ADDSI) + struct.pack("<H", 0) + struct.pack("<B", SAY)
    f1 = build_func(0x0123, code1, data)
    code2 = struct.pack("<B", ADDSI) + struct.pack("<H", 0) + struct.pack("<B", 0x05)
    f2 = build_func(0x0401, code2, b"BYE\0")
    zh = f1 + f2
    review = [{
        "zh_func_id": "0x0123", "zh_offset_key": "0", "zh_segment": 0,
        "zh_raw": "HELLO", "en_raw": "NIHAO",
        "en_func_id": "0x0402", "en_offset_key": "0", "en_segment": 0,
    }]
    dual, rows, skipped = g.generate(zh, review)
    assert skipped == []
    fid, fdata, ext, nxt = g.dis.parse_function(dual, 0)
    func = g.dis.disassemble_function(fid, fdata, ext)
    assert fid == 0x0123
    assert func["strings"][0] == "HELLO"          # original data preserved
    lines = g.dis.extract_say_lines(func)
    assert any(l["text"] == "HELLO\nNIHAO" for l in lines)
    # second function byte-identical
    assert dual[nxt:] == f2
    # dual->zh + dual->en rows
    assert len(rows) == 2
    zh_rows = [r for r in rows if r["en_func_id"] == 0x0123]
    en_rows = [r for r in rows if r["en_func_id"] == 0x0402]
    assert len(zh_rows) == 1 and len(en_rows) == 1
    assert en_rows[0]["zh_offset_key"] == "%x" % len(data)  # appended offset


def test_generate_two_traces_redirects_later_addsi_to_empty():
    data = b"AAA\0BBB\0CCC\0"
    code = (
        struct.pack("<B", ADDSI) + struct.pack("<H", 0)
        + struct.pack("<B", ADDSI) + struct.pack("<H", 4)
        + struct.pack("<B", SAY)
        + struct.pack("<B", ADDSI) + struct.pack("<H", 8)
        + struct.pack("<B", SAY)
    )
    zh = build_func(0x0200, code, data)
    review = [
        {"zh_func_id": "0x0200", "zh_offset_key": "0_4", "zh_segment": 0,
         "zh_raw": "AAABBB", "en_raw": "EN1",
         "en_func_id": "0x0200", "en_offset_key": "0_4", "en_segment": 0},
        {"zh_func_id": "0x0200", "zh_offset_key": "8", "zh_segment": 0,
         "zh_raw": "CCC", "en_raw": "EN2",
         "en_func_id": "0x0200", "en_offset_key": "8", "en_segment": 0},
    ]
    dual, rows, skipped = g.generate(zh, review)
    assert skipped == []
    fid, fdata, ext, _ = g.dis.parse_function(dual, 0)
    func = g.dis.disassemble_function(fid, fdata, ext)
    lines = g.dis.extract_say_lines(func)
    texts = sorted(l["text"] for l in lines)
    assert texts == ["AAABBB\nEN1", "CCC\nEN2"]
    assert len(rows) == 4
    # both merged strings present in the data segment
    merged = [s for s in func["strings"].values() if "\n" in s]
    assert len(merged) == 2


def test_generate_pair_fallback_zh():
    data = b"HELLO\0"
    code = struct.pack("<B", ADDSI) + struct.pack("<H", 0) + struct.pack("<B", SAY)
    zh = build_func(0x0123, code, data)
    review = [{"zh_func_id": "0x0123", "zh_offset_key": "0", "zh_segment": 0,
               "zh_raw": "HELLO", "en_raw": ""}]
    dual, rows, skipped = g.generate(zh, review)
    assert skipped == []
    fid, fdata, ext, _ = g.dis.parse_function(dual, 0)
    func = g.dis.disassemble_function(fid, fdata, ext)
    lines = g.dis.extract_say_lines(func)
    assert any(l["text"] == "HELLO" for l in lines)   # no \n appended
    assert len(rows) == 1                              # dual->zh only


def test_generate_skips_missing_review_row():
    data = b"HELLO\0"
    code = struct.pack("<B", ADDSI) + struct.pack("<H", 0) + struct.pack("<B", SAY)
    zh = build_func(0x0567, code, data)
    dual, rows, skipped = g.generate(zh, [])
    # no review rows: function copied byte-identical, no map rows
    assert dual == zh
    assert rows == []
    assert skipped == []


def test_blm2_roundtrip(tmp_path):
    rows = [{"zh_func_id": 0x123, "zh_offset_key": "aa", "zh_segment": 0,
             "en_func_id": 0x9ab, "en_offset_key": "bb", "en_segment": 1}]
    p = tmp_path / "dual_map.dat"
    g.write_blm2(p, rows)
    assert g.read_blm2(p) == rows


def test_generate_preserves_symbol_table():
    # Exult symbol table: ffffffff "YSCU" magic + scope count + version.
    symtab = struct.pack("<II", 0xFFFFFFFF, 0x55435359) + struct.pack("<II", 0, 0)
    data = b"HELLO\0"
    code = struct.pack("<B", ADDSI) + struct.pack("<H", 0) + struct.pack("<B", SAY)
    zh = symtab + build_func(0x0123, code, data)
    dual, rows, skipped = g.generate(zh, [])
    assert skipped == []
    assert dual[:len(symtab)] == symtab            # table copied verbatim
    assert dual[len(symtab):] == build_func(0x0123, code, data)
    assert rows == []