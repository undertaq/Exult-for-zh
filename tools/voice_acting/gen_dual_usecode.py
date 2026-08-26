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


def undo_latin1_mojibake(text):
    """Reverse disassemble_usecode's latin-1 string decoding.

    disassemble_usecode decodes usecode string bytes with latin-1, so
    'text' carries each original byte as a Latin-1 char (UTF-8 mojibake).
    Re-encoding to latin-1 restores the original bytes; UTF-8 decoding
    yields the proper string. Pure-ASCII text round-trips unchanged.
    """
    if not text:
        return text
    return text.encode("latin-1", errors="surrogateescape").decode(
        "utf-8", errors="surrogateescape")


def offset_key_for(addsi_offsets):
    """hex offsets joined by '_' — matches review JSON / runtime keys."""
    return "_".join("%x" % o for o in addsi_offsets)


def old_data_for_func(func_data, extended):
    old_data, *_ = parse_parts(func_data, extended)
    return old_data


def extract_answer_keywords(func, data_seg, extended):
    """Ordered [(pushs_data_off, keyword)] for add_answer (calli intrinsic 5).

    Handles the two emission patterns:
      pushs K            ; calli 5          (single keyword)
      pushs K1..Kn ; arrc N ; calli 5        (keyword array)
    """
    instrs = func["instructions"]

    def text_at(off):
        end = data_seg.find(b"\0", off)
        if end < 0:
            end = len(data_seg)
        return undo_latin1_mojibake(data_seg[off:end].decode("latin-1", errors="surrogateescape"))

    out = []
    for i, (addr, raw, name, params, comment) in enumerate(instrs):
        if not (name == "calli" and params and params[0] == 5):
            continue
        j = i - 1
        if j < 0:
            continue
        n2, p2 = instrs[j][2], instrs[j][3]
        if n2 == "arrc":
            # walk back over the N pushs feeding the array
            cnt = p2[0] if p2 else 0
            k = j - 1
            group = []
            while k >= 0 and cnt > 0:
                n3, p3 = instrs[k][2], instrs[k][3]
                if n3 == "pushs" and len(p3) >= 1:
                    group.append((p3[0], text_at(p3[0])))
                    cnt -= 1
                elif n3 in ("pushs",):
                    pass
                else:
                    break
                k -= 1
            out.extend(reversed(group))
        elif n2 == "pushs" and len(p2) >= 1:
            off = p2[0]
            out.append((off, text_at(off)))
    return out


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


def iter_all_instrs(code, extended):
    """Yield (ip, opcode, fmt) for every instruction in order."""
    ip = 0
    while ip < len(code):
        start = ip
        op = code[ip]
        ip += 1
        info = dis.OPCODES.get(op)
        if info is None:
            yield start, op, None
            ip += 1
            continue
        fmt = info[1]
        if fmt == "si":
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
        yield start, op, fmt


def read_si_operand(code, ip, extended):
    return dis.read4s(code, ip) if extended else dis.read2(code, ip)


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


def rebuild_function(func_data, extended, traces, neutralize_addsv_ips=None,
                     pushs_redirect=None):
    """Append merged strings; redirect addsi operands.

    traces: {addsi_tuple: merged_str}
    neutralize_addsv_ips: optional set of code-relative IPs of addsv
        instructions that must push nothing (replaced by addsi of the shared
        empty string, same length in normal mode).
    Returns (new_func_blob, first_offsets, empty_off, redirect).
    Raises ValueError if two traces claim the same first addsi offset.
    """
    old_data, nargs, nvars, externs, old_code = parse_parts(func_data, extended)

    new_data = bytearray(old_data)
    first_offsets = {}
    redirect = {}
    empty_off = None
    pushs_new_off = {}
    for data_off, merged in (pushs_redirect or {}).items():
        pushs_new_off[data_off] = len(new_data)
        new_data += merged.encode("utf-8") + b"\0"
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
    for ip, op, fmt in iter_all_instrs(old_code, extended):
        if op in (0x1C, 0x1D) and fmt == "si":
            data_off = read_si_operand(old_code, ip + 1, extended)
            new_off = redirect.get(data_off)
            if new_off is None and op == 0x1D:
                new_off = pushs_new_off.get(data_off)
            if new_off is not None:
                if extended:
                    new_code[ip + 1:ip + 5] = struct.pack("<i", new_off)
                else:
                    new_code[ip + 1:ip + 3] = struct.pack("<H", new_off)

    # Neutralize addsv instructions that push variable values (avatar name,
    # honorific, pronouns) into merged strings: the values are already baked
    # in as <PLAYER_NAME>/<HONORIFIC>/<PRONOUN>/... tokens at generation
    # time, so a trailing raw push would duplicate the word at the end of the
    # displayed line. addsv (0x2F) and addsi (0x1C) are both 3 bytes in the
    # normal encoding, so swapping in `addsi <empty_off>` is length-neutral.
    if neutralize_addsv_ips and not extended:
        for ip in sorted(neutralize_addsv_ips):
            new_code[ip] = 0x1C
            new_code[ip + 1:ip + 3] = struct.pack("<H", empty_off)

    if extended:
        data_len_bytes = struct.pack("<i", len(new_data))
    else:
        data_len_bytes = struct.pack("<H", len(new_data))
    blob = (data_len_bytes + bytes(new_data)
            + struct.pack("<HHH", nargs, nvars, len(externs) // 2)
            + externs + bytes(new_code))
    return blob, first_offsets, empty_off, redirect


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


def generate(zh_blob, review, en_blob=None):
    """Returns (dual_blob, dual_rows, skipped)."""
    by_key = load_en_by_key(review)
    # English answer keywords per func (ordinal-aligned with the zh list).
    en_answers = {}
    if en_blob:
        en_off = 0
        while en_off < len(en_blob):
            sym = dis.skip_symbol_table(en_blob, en_off)
            if sym > en_off:
                en_off = sym
                continue
            try:
                e_fid, e_fdata, e_ext, e_nxt = dis.parse_function(en_blob, en_off)
            except Exception:
                break
            if e_nxt <= en_off:
                break
            try:
                e_old_data, _, _, _, _ = parse_parts(e_fdata, e_ext)
                e_func = dis.disassemble_function(e_fid, e_fdata, e_ext)
                en_answers[e_fid] = [t for _, t in extract_answer_keywords(
                    e_func, e_old_data, e_ext)]
            except Exception:
                pass
            en_off = e_nxt
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
                zh = undo_latin1_mojibake(line["text"])
                en = info_per_seg.get(line["segment"], {}).get("text", "")
                merged_parts.append(build_merged(zh, en) if en else zh)
            if not merged_parts:
                continue
            t = tuple(seg_lines[0]["addsi_offsets"])
            if t in traces:
                skipped.append((fid_hex, key, "duplicate trace"))
                continue
            traces[t] = "~".join(merged_parts)

        # Avatar topic keywords: merge as "ZH(EN)" so dual mode shows both.
        # The engine normalizes user_choice back to the ZH part on selection.
        say_claimed_offsets = set()
        for t in traces:
            say_claimed_offsets.update(t)
        pushs_redirect = {}
        zh_ans = extract_answer_keywords(
            dis.disassemble_function(fid, fdata, ext), old_data_for_func(fdata, ext), ext)
        en_ans = en_answers.get(fid, [])
        for k, (off, ztext) in enumerate(zh_ans):
            if k >= len(en_ans):
                break
            etext = en_ans[k]
            if not etext or etext == ztext or not etext.isascii():
                continue
            if off in say_claimed_offsets:
                continue      # never clobber a say-trace operand
            pushs_redirect[off] = f"{ztext}({etext})"
        if not traces and not pushs_redirect:
            out += zh_blob[offset:nxt]
            offset = nxt
            continue
        # Collect addsi/addsv instruction IPs to locate variables inside each
        # merged trace's instruction span (first addsi .. say).
        old_data, nargs, nvars, externs, old_code = parse_parts(fdata, ext)
        addsi_ip_by_off = {}
        addsv_ips = []
        for ip, op, fmt in iter_all_instrs(old_code, ext):
            if op == 0x1C and fmt == "si":
                addsi_ip_by_off[read_si_operand(old_code, ip + 1, ext)] = ip
            elif op == 0x2F and fmt == "w":
                addsv_ips.append(ip)
        neutralize = set()
        for key, seg_lines in groups.items():
            t = tuple(seg_lines[0]["addsi_offsets"])
            if t not in traces:
                continue
            say_addr = seg_lines[0]["code_addr"]
            ips = [ip for off in t
                   for ip in ([addsi_ip_by_off.get(off)] if addsi_ip_by_off.get(off) is not None else [])]
            if not ips:
                continue
            lo = min(ips)
            for ip in addsv_ips:
                if lo < ip < say_addr:
                    neutralize.add(ip)
        try:
            new_blob, first_offsets, empty_off, redirect = rebuild_function(
                fdata, ext, traces, neutralize, pushs_redirect)
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
            # Executed key: the trace's addsi offsets redirected in code
            # order, with neutralized addsv variables contributing the empty
            # offset (the runtime records them via addsi in voice_string_trace).
            say_addr = seg_lines[0]["code_addr"]
            ips = [ip for off in t
                   for ip in ([addsi_ip_by_off.get(off)] if addsi_ip_by_off.get(off) is not None else [])]
            lo = min(ips) if ips else 0
            key_parts = []
            for ip, op, fmt in iter_all_instrs(old_code, ext):
                if ip < lo:
                    continue
                if ip > say_addr:
                    break
                if op == 0x1C and fmt == "si":
                    off = read_si_operand(old_code, ip + 1, ext)
                    key_parts.append("%x" % redirect.get(off, off))
                elif op == 0x2F and fmt == "w" and ip in neutralize:
                    key_parts.append("%x" % empty_off)
            new_key = "_".join(key_parts) or ("%x" % redirect.get(t[0]))
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
    ap.add_argument("--en",
                    default=str(Path(__file__).parent / "_live" / "usecode.en"))
    ap.add_argument("--review",
                    default=str(Path(__file__).parent / "bilingual_mapping_review.json"))
    ap.add_argument("--out",
                    default=str(Path(__file__).parent / "_live" / "usecode.dual"))
    ap.add_argument("--map-out",
                    default=str(Path(__file__).parent / "_live" / "dual_map.dat"))
    args = ap.parse_args()

    zh_blob = Path(args.zh).read_bytes()
    review = json.loads(Path(args.review).read_text(encoding="utf-8"))
    en_blob = None
    en_path = Path(args.en)
    if en_path.exists():
        en_blob = en_path.read_bytes()
    else:
        print(f"  note: {en_path} not found; topics stay ZH-only", file=sys.stderr)
    dual_blob, dual_rows, skipped = generate(zh_blob, review, en_blob)
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