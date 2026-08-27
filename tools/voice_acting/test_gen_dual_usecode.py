"""Tests for gen_dual_usecode.py."""
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import gen_dual_usecode as g

ADDSI = 0x1C
PUSHS = 0x1D
ADDSV = 0x2F
CALL = 0x24
POP = 0x12
SAY = 0x33


def build_func(func_id, code, data, extended=False, externs=b""):
    """Wrap code+data into a function blob (classic or 0xfffe header)."""
    tail = (struct.pack("<HHH", 0, 0, len(externs) // 2) + externs + code)
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
    # dual->zh rows (one row per review entry; en_func_id matches zh_func_id)
    assert len(rows) == 1
    zh_rows = [r for r in rows if r["en_func_id"] == 0x0123]
    # en_rows no longer emitted; en_func_id matches zh_func_id
    assert len(zh_rows) == 1


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
    assert len(rows) == 2
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


# ---- <VAR> support: per-addsv labels + selective addsv neutralization ----


def var_template_func():
    """addsi "Hello " + addsv[<PLAYER_NAME> var] + addsi " gold " +
    addsv[plain var] + say.

    Var 0 is labeled <PLAYER_NAME> via call extern 0x908 + pop; var 1 stays
    generic (<VAR>).
    """
    data = b"Hello \0 gold \0"
    code = (
        struct.pack("<B", CALL) + struct.pack("<H", 0)          # ext[0]=0x908
        + struct.pack("<B", POP) + struct.pack("<H", 0)
        + struct.pack("<B", ADDSI) + struct.pack("<H", 0)
        + struct.pack("<B", ADDSV) + struct.pack("<H", 0)
        + struct.pack("<B", ADDSI) + struct.pack("<H", 7)
        + struct.pack("<B", ADDSV) + struct.pack("<H", 1)
        + struct.pack("<B", SAY)
    )
    return build_func(0x0700, code, data, externs=struct.pack("<H", 0x908))


def test_extract_say_lines_reports_addsv_labels():
    fid, fdata, ext, _ = g.dis.parse_function(var_template_func(), 0)
    func = g.dis.disassemble_function(fid, fdata, ext)
    lines = g.dis.extract_say_lines(func)
    assert len(lines) == 1
    line = lines[0]
    assert line["text"] == "Hello <PLAYER_NAME> gold <VAR>"
    assert line["addsv_labels"] == ["<PLAYER_NAME>", "<VAR>"]


def test_generate_neutralizes_only_semantic_addsv():
    zh = var_template_func()
    review = [{
        "zh_func_id": "0x0700", "zh_offset_key": "0_7", "zh_segment": 0,
        "zh_raw": "Hello <PLAYER_NAME> gold <VAR>",
        "en_raw": "Hi <PLAYER_NAME>, <VAR> gold",
        "en_func_id": "0x0700", "en_offset_key": "0_7", "en_segment": 0,
    }]
    dual, rows, skipped = g.generate(zh, review)
    assert skipped == []
    fid, fdata, ext, _ = g.dis.parse_function(dual, 0)
    func = g.dis.disassemble_function(fid, fdata, ext)
    names = [name for _, _, name, _, _ in func["instructions"]]
    # The generic <VAR> addsv must stay live so the runtime value reaches the
    # string; only the semantic <PLAYER_NAME> one is neutralized.
    assert names.count("addsv") == 1
    # Merged template still appended.
    merged = [s for s in func["strings"].values() if "\n" in s]
    assert merged == [
        "Hello <PLAYER_NAME> gold <VAR>\nHi <PLAYER_NAME>, <VAR> gold"
    ]

# ---- Answer (pushs) merging for the avatar's question list ----


def converse_func(func_id, topic_bytes):
    """pushs <topic> + cmps + ret ??minimal conversation-shaped function."""
    data = topic_bytes + b"\0"
    code = (
        struct.pack("<B", PUSHS) + struct.pack("<H", 0)
        + struct.pack("<B", 0x07) + struct.pack("<H", 1) + struct.pack("<h", 2)
        + struct.pack("<B", 0x25)                                   # ret
    )
    return build_func(func_id, code, data)


def plain_func(func_id, topic_bytes):
    """pushs without cmps ??must never be answer-merged."""
    data = topic_bytes + b"\0"
    code = struct.pack("<B", PUSHS) + struct.pack("<H", 0)
    return build_func(func_id, code, data)


def test_generate_merges_answers_from_en_blob():
    zh = converse_func(0x0401, b"MZ") + plain_func(0x0402, b"OT")
    en = converse_func(0x0401, b"NAME") + plain_func(0x0402, b"OTH")
    dual, rows, skipped = g.generate(zh, [], en_blob=en)
    assert skipped == []
    funcs = {fid: (fd, e) for fid, fd, e, _ in iter_funcs(dual)}
    # Conversation function: pushs redirected to appended merged answer,
    # rendered inline as ZH(EN).
    func = g.dis.disassemble_function(0x0401, *funcs[0x0401])
    merged = [s for s in func["strings"].values() if "(" in s]
    assert merged == ["MZ(NAME)"]
    assert not [s for s in func["strings"].values() if "\n" in s]
    # Non-conversation function untouched.
    func2 = g.dis.disassemble_function(0x0402, *funcs[0x0402])
    assert not [s for s in func2["strings"].values() if "(" in s]


def test_answer_map_frequency_beats_ambiguity():
    # Same zh topic paired with several EN strings across functions: keep
    # translating, choosing the most frequent partner (職業 -> job case).
    zh = (converse_func(0x0401, b"MZ") + converse_func(0x0403, b"MZ")
          + converse_func(0x0405, b"MZ"))
    en = (converse_func(0x0401, b"NAME") + converse_func(0x0403, b"NAME")
          + converse_func(0x0405, b"OTHER"))
    amap = g.build_answer_map(zh, en)
    assert amap == {"MZ": "NAME"}
    dual, rows, skipped = g.generate(zh, [], en_blob=en)
    for fid, fdata, ext, _off in iter_funcs(dual):
        func = g.dis.disassemble_function(fid, fdata, ext)
        merged = [s for s in func["strings"].values() if "(" in s]
        assert merged == ["MZ(NAME)"]


def test_answer_map_aligns_mismatched_functions():
    # Function whose pushs sequence has extra/fewer strings: anchor-seeded
    # alignment must still pair the surrounding topics.
    # Seed AA->XX from a well-formed function...
    zh = converse_func(0x0411, b"AA")
    en = converse_func(0x0411, b"XX")
    # ...then a mismatched one: zh [BB, AA, CC] vs en [YY, XX, ZZ, WW].
    def multi_func(func_id, topics):
        data = b"".join(t + b"\0" for t in topics)
        code = b"".join(
            struct.pack("<B", PUSHS) + struct.pack("<H", i * (len(t) + 1))
            for i, t in enumerate(topics))
        code += struct.pack("<B", 0x07) + struct.pack("<H", len(topics)) + struct.pack("<h", 2)
        code += struct.pack("<B", 0x25)
        return build_func(func_id, code, data)

    zh += multi_func(0x0412, [b"BB", b"AA", b"CC"])
    en += multi_func(0x0412, [b"YY", b"XX", b"ZZ", b"WW"])
    amap = g.build_answer_map(zh, en)
    assert amap["AA"] == "XX"
    assert amap["BB"] == "YY"
    assert amap["CC"] == "ZZ"
    assert "WW" not in amap.values()


def iter_funcs(blob):
    off = 0
    while off < len(blob):
        try:
            fid, fdata, ext, nxt = g.dis.parse_function(blob, off)
        except Exception:
            break
        yield fid, fdata, ext, off
        off = nxt

