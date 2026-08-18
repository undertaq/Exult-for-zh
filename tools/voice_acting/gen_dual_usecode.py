#!/usr/bin/env python3
"""Generate usecode.dual + dual_map.dat from usecode.zh + the review JSON.

Every dialogue trace present in bilingual_mapping_review.json gets a merged
data string: segments "<ZH>\n<EN>" joined by '~'. The trace's FIRST addsi
operand is redirected to the appended merged string; its remaining addsi
operands point to one shared empty string. All other bytes are copied
verbatim, so every other string offset stays valid.

Usage:
    python gen_dual_usecode.py [--zh PATH] [--review PATH]
                               [--out PATH] [--map-out PATH]
"""
import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import disassemble_usecode as dis


def build_merged(zh, en):
    return zh + "\n" + en


def offset_key_for(addsi_offsets):
    """hex offsets joined by '_' — matches review JSON / runtime keys."""
    return "_".join("%x" % o for o in addsi_offsets)


def load_en_by_key(review):
    """{(func_hex, offset_key): {segment: en_info_dict}}"""
    by_key = {}
    for r in review:
        fid = r.get("zh_func_id")
        key = r.get("zh_offset_key")
        seg = r.get("zh_segment")
        if not fid or not key or seg is None:
            continue
        by_key.setdefault((fid, key), {})[seg] = {
            "text": (r.get("en_raw") or r.get("en_text") or "").strip(),
            "en_func_id": r.get("en_func_id", fid),
            "en_offset_key": r.get("en_offset_key", key),
            "en_segment": r.get("en_segment", seg),
        }
    return by_key


def iter_addsi(code, extended):
    """Yield (instr_ip, data_off) for every addsi in instruction order."""
    ip = 0
    while ip < len(code):
        instr_ip = ip
        op = code[ip]
        ip += 1
        info = dis.OPCODES.get(op)
        if info is None:
            ip += 1
            continue
        fmt = info[1]
        if fmt == "si":
            val = dis.read4s(code, ip) if extended else dis.read2(code, ip)
            if op == 0x1C:      # UC_ADDSI (0x1C covers ADDSI32 too)
                yield instr_ip, val
            ip += 4 if extended else 2
        elif fmt in ("w", "s", "ji"):
            ip += 2
        elif fmt == "b":
            ip += 1
        elif fmt == "ci":
            ip += 3
        elif fmt == "cs":
            ip += 4
        elif fmt == "lt":
            ip += 10
        elif fmt == "ww":
            ip += 4
        elif fmt == "n":
            pass
        else:
            ip += 1


def parse_parts(func_data, extended):
    """Return (old_data, nargs, nvars, externs, old_code)."""
    pos = 0
    if extended:
        data_len = dis.read4s(func_data, pos); pos += 4
    else:
        data_len = dis.read2(func_data, pos); pos += 2
    old_data = func_data[pos:pos + data_len]
    pos += data_len
    nargs = dis.read2(func_data, pos); pos += 2
    nvars = dis.read2(func_data, pos); pos += 2
    nexterns = dis.read2(func_data, pos); pos += 2
    externs = func_data[pos:pos + 2 * nexterns]
    pos += 2 * nexterns
    return old_data, nargs, nvars, externs, func_data[pos:]


def rebuild_function(func_data, extended, traces):
    """Append merged strings; redirect addsi operands.

    traces: {addsi_tuple: merged_str}
    Returns (new_func_blob, first_offsets, empty_off).
    Raises ValueError if two traces claim the same first addsi offset.
    """
    old_data, nargs, nvars, externs, old_code = parse_parts(func_data, extended)

    new_data = bytearray(old_data)
    first_offsets = {}
    redirect = {}
    empty_off = None
    for t, merged in traces.items():
        t_first = t[0]
        if t_first in redirect:
            raise ValueError("addsi %x claimed by two traces" % t_first)
        first_offsets[t] = len(new_data)
        new_data += merged.encode("utf-8") + b"\0"
        redirect[t_first] = first_offsets[t]
    for t in traces:
        for later in t[1:]:
            if later in redirect:
                continue          # already a trace start (or previously claimed)
            if empty_off is None:
                empty_off = len(new_data)
                new_data += b"\0"
            redirect[later] = empty_off

    new_code = bytearray(old_code)
    for instr_ip, data_off in iter_addsi(old_code, extended):
        if data_off in redirect:
            new_off = redirect[data_off]
            if extended:
                new_code[instr_ip + 1:instr_ip + 5] = struct.pack("<i", new_off)
            else:
                new_code[instr_ip + 1:instr_ip + 3] = struct.pack("<H", new_off)

    if extended:
        data_len_bytes = struct.pack("<i", len(new_data))
    else:
        data_len_bytes = struct.pack("<H", len(new_data))
    blob = (data_len_bytes + bytes(new_data)
            + struct.pack("<HHH", nargs, nvars, len(externs) // 2)
            + externs + bytes(new_code))
    return blob, first_offsets, empty_off


def write_blm2(path, rows):
    with open(path, "wb") as f:
        f.write(b"BLM2")
        f.write(struct.pack("<I", len(rows)))
        for r in rows:
            f.write(struct.pack("<i", r["zh_func_id"]))
            f.write(r["zh_offset_key"].encode() + b"\0")
            f.write(struct.pack("<H", r["zh_segment"]))
            f.write(struct.pack("<i", r["en_func_id"]))
            f.write(r["en_offset_key"].encode() + b"\0")
            f.write(struct.pack("<H", r["en_segment"]))


def read_blm2(path):
    rows = []
    with open(path, "rb") as f:
        assert f.read(4) == b"BLM2", "not a BLM2 file"
        (count,) = struct.unpack("<I", f.read(4))
        for _ in range(count):
            (zh_fid,) = struct.unpack("<i", f.read(4))
            zh_key = b"".join(iter(lambda: f.read(1), b"\0")).decode()
            (zh_seg,) = struct.unpack("<H", f.read(2))
            (en_fid,) = struct.unpack("<i", f.read(4))
            en_key = b"".join(iter(lambda: f.read(1), b"\0")).decode()
            (en_seg,) = struct.unpack("<H", f.read(2))
            rows.append({"zh_func_id": zh_fid, "zh_offset_key": zh_key,
                         "zh_segment": zh_seg, "en_func_id": en_fid,
                         "en_offset_key": en_key, "en_segment": en_seg})
    return rows


def generate(zh_blob, review):
    """Returns (dual_blob, dual_rows, skipped)."""
    by_key = load_en_by_key(review)
    out = bytearray()
    dual_rows = []
    skipped = []
    offset = 0
    while offset < len(zh_blob):
        sym_next = dis.skip_symbol_table(zh_blob, offset)
        if sym_next > offset:
            out += zh_blob[offset:sym_next]    # preserve the symbol table verbatim
            offset = sym_next
            continue
        try:
            fid, fdata, ext, nxt = dis.parse_function(zh_blob, offset)
        except (struct.error, IndexError):
            break
        if nxt <= offset:
            break
        fid_hex = "0x%04X" % fid
        func = dis.disassemble_function(fid, fdata, ext)
        lines = dis.extract_say_lines(func)
        groups = {}
        for line in lines:
            key = offset_key_for(line["addsi_offsets"])
            if key:
                groups.setdefault(key, []).append(line)
        traces = {}
        for key, seg_lines in groups.items():
            info_per_seg = by_key.get((fid_hex, key)) or {}
            if not info_per_seg:
                continue          # not in the review: leave byte-identical
            merged_parts = []
            for line in seg_lines:
                zh = line["text"]
                en = info_per_seg.get(line["segment"], {}).get("text", "")
                merged_parts.append(build_merged(zh, en) if en else zh)
            if not merged_parts:
                continue
            t = tuple(seg_lines[0]["addsi_offsets"])
            if t in traces:
                skipped.append((fid_hex, key, "duplicate trace"))
                continue
            traces[t] = "~".join(merged_parts)
        if not traces:
            out += zh_blob[offset:nxt]
            offset = nxt
            continue
        try:
            new_blob, first_offsets, _ = rebuild_function(fdata, ext, traces)
        except (ValueError, struct.error, IndexError) as e:
            skipped.append((fid_hex, str(e)))
            out += zh_blob[offset:nxt]
            offset = nxt
            continue
        # Rebuild the function header (func_id + len) around the new body
        kind = zh_blob[offset:offset + 2]
        if kind == b"\xfe\xff":           # 0xFFFE marker, little-endian
            out += struct.pack("<HiI", 0xFFFE, fid, len(new_blob))
        elif kind == b"\xff\xff":         # 0xFFFF marker
            out += struct.pack("<HHI", 0xFFFF, fid, len(new_blob))
        else:
            out += struct.pack("<HH", fid, len(new_blob))
        out += new_blob
        for key, seg_lines in groups.items():
            t = tuple(seg_lines[0]["addsi_offsets"])
            if t not in first_offsets:
                continue
            new_key = "%x" % first_offsets[t]
            info_per_seg = by_key.get((fid_hex, key)) or {}
            for line in seg_lines:
                seg = line["segment"]
                dual_rows.append({"zh_func_id": fid, "zh_offset_key": new_key,
                                  "zh_segment": seg,
                                  "en_func_id": fid, "en_offset_key": key,
                                  "en_segment": seg})                # dual->zh
                info = info_per_seg.get(seg)
                if info and info["text"] and info["en_func_id"]:
                    dual_rows.append({"zh_func_id": fid,
                                      "zh_offset_key": new_key,
                                      "zh_segment": seg,
                                      "en_func_id": int(info["en_func_id"], 16),
                                      "en_offset_key": info["en_offset_key"],
                                      "en_segment": info["en_segment"]})  # dual->en
        offset = nxt
    return bytes(out), dual_rows, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zh",
                    default=str(Path(__file__).parent / "_live" / "usecode.zh"))
    ap.add_argument("--review",
                    default=str(Path(__file__).parent / "bilingual_mapping_review.json"))
    ap.add_argument("--out",
                    default=str(Path(__file__).parent / "_live" / "usecode.dual"))
    ap.add_argument("--map-out",
                    default=str(Path(__file__).parent / "_live" / "dual_map.dat"))
    args = ap.parse_args()

    zh_blob = Path(args.zh).read_bytes()
    review = json.loads(Path(args.review).read_text(encoding="utf-8"))
    dual_blob, dual_rows, skipped = generate(zh_blob, review)
    Path(args.out).write_bytes(dual_blob)
    write_blm2(args.map_out, dual_rows)
    print(f"Wrote {args.out}: {len(dual_blob)} bytes")
    print(f"Wrote {args.map_out}: {len(dual_rows)} rows")
    for item in skipped[:10]:
        print("  skipped:", item, file=sys.stderr)
    if len(skipped) > 10:
        print(f"  ... and {len(skipped) - 10} more", file=sys.stderr)


if __name__ == "__main__":
    main()