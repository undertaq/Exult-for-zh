#!/usr/bin/env python3
"""Generate usecode.dual + dual_map.dat from usecode.zh + the review JSON.

Every dialogue trace present in bilingual_mapping_review.json gets a merged
data string: segments "<ZH>\n<EN>" joined by '~'. The trace's FIRST addsi
operand is redirected to the appended merged string; its remaining addsi
operands point to one shared empty string. All other bytes are copied
verbatim, so every other string offset stays valid.

Runtime variable slots (<PLAYER_NAME>, <HONORIFIC>, <PRONOUN>,
<GENDER_FLAG>) are resolved at display time by the engine; addsv
instructions feeding those are neutralized. Generic <VAR> addsv stay live so
the real runtime value (numbers etc.) reaches the string; the engine's ADDSV
handler substitutes pending "<VAR>" tokens instead of appending.

When --en (usecode.en) is given, conversation ANSWER strings (the avatar's
topic list, pushed via `pushs` in cmps-bearing functions) are also paired
positionally between the two binaries and emitted as "ZH\\nEN" merges, so
dual mode shows bilingual questions.

Usage:
    python gen_dual_usecode.py [--zh PATH] [--en PATH] [--review PATH]
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


def iter_addsi(code, extended, ops=(0x1C,)):
    """Yield (instr_ip, data_off) for every listed si-opcode in order.

    0x1C = addsi, 0x1D = pushs (same operand encoding).
    """
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
            if op in ops:
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
                     answer_redirect=None):
    """Append merged strings; redirect addsi operands.

    traces: {addsi_tuple: merged_str}
    neutralize_addsv_ips: optional set of code-relative IPs of addsv
        instructions that must push nothing (replaced by addsi of the shared
        empty string, same length in normal mode).
    answer_redirect: optional {data_off: merged_str} for pushs operands
        (avatar answers); appended like trace strings and redirected too.
        Offsets already claimed by a trace are skipped (say wins).
    Returns (new_func_blob, first_offsets, empty_off, redirect).
    Raises ValueError if two traces claim the same first addsi offset.
    """
    old_data, nargs, nvars, externs, old_code = parse_parts(func_data, extended)

    new_data = bytearray(old_data)
    first_offsets = {}
    redirect = {}
    empty_off = None

    def alloc_empty():
        nonlocal empty_off, new_data
        if empty_off is None:
            empty_off = len(new_data)
            new_data += b"\0"
        return empty_off

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
            redirect[later] = alloc_empty()
    if answer_redirect:
        for off in sorted(answer_redirect):
            if off in redirect:
                continue          # say-trace owns this string
            merged = answer_redirect[off]
            redirect[off] = len(new_data)
            new_data += merged.encode("utf-8") + b"\0"

    new_code = bytearray(old_code)
    # addsi AND pushs operands both carry si encodings; rewrite every op
    # whose offset was redirected.
    for instr_ip, data_off in iter_addsi(old_code, extended, ops=(0x1C, 0x1D)):
        if data_off in redirect:
            new_off = redirect[data_off]
            if extended:
                new_code[instr_ip + 1:instr_ip + 5] = struct.pack("<i", new_off)
            else:
                new_code[instr_ip + 1:instr_ip + 3] = struct.pack("<H", new_off)

    # Neutralize addsv instructions that push variable values (avatar name,
    # honorific, pronouns) into merged strings: the values are already baked
    # in as <PLAYER_NAME>/<HONORIFIC>/<PRONOUN>/... tokens at generation
    # time, so a trailing raw push would duplicate the word at the end of the
    # displayed line. Generic <VAR> addsv are NOT neutralized: they stay live
    # so the engine's ADDSV handler can substitute real runtime values into
    # the pending "<VAR>" slots. addsv (0x2F) and addsi (0x1C) are both 3
    # bytes in the normal encoding, so swapping in `addsi <empty_off>` is
    # length-neutral.
    if neutralize_addsv_ips and not extended:
        for ip in sorted(neutralize_addsv_ips):
            new_code[ip] = 0x1C
            new_code[ip + 1:ip + 3] = struct.pack("<H", alloc_empty())

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


def _disasm_all(blob):
    """Disassemble every function in a usecode blob: {fid: func_dict}."""
    funcs = {}
    offset = 0
    while offset < len(blob):
        sym_next = dis.skip_symbol_table(blob, offset)
        if sym_next > offset:
            offset = sym_next
            continue
        try:
            fid, fdata, ext, nxt = dis.parse_function(blob, offset)
        except (struct.error, IndexError):
            break
        if nxt <= offset:
            break
        try:
            funcs[fid] = dis.disassemble_function(fid, fdata, ext)
        except (struct.error, IndexError, ValueError):
            pass
        offset = nxt
    return funcs


def _has_cmps(func):
    return any(name == "cmps" for _, _, name, _, _ in func["instructions"])


def _func_pushs_texts(func):
    """pushs operand strings in code order."""
    texts = []
    for _addr, _raw, name, params, _comment in func["instructions"]:
        if name == "pushs" and params:
            texts.append(func["strings"].get(params[0], ""))
    return texts


def _answer_mergeable(text):
    """Only plain single-line topic strings qualify for answer merging."""
    if not text or len(text) > 120:
        return False
    return not any(c in text for c in "~*\n\r@")


def build_merged_answer(zh, en):
    """Avatar answers render inline as ZH(EN) on a single row."""
    return "%s(%s)" % (zh, en)


def _align_pairs(zp, ep, known):
    """Anchor-seeded alignment of two pushs text sequences.

    Functions whose zh/en pushs counts differ are skipped by positional
    pairing. Here trusted `(zh, en)` anchor pairs (greedy, order-preserving)
    split both sequences into segments; each segment pair is then zipped
    positionally, so translations around a known topic are recovered even
    when the two binaries added or dropped strings. Returns harvested
    (zh, en) pairs.
    """
    n, m = len(zp), len(ep)
    if not n or not m or not known:
        return []
    used_z, used_e = set(), set()
    cuts = []    # (zi, ei) trusted anchor index pairs, order-preserving
    last_j = -1
    for i, z in enumerate(zp):
        for j in range(last_j + 1, m):
            if j in used_e:
                continue
            if (z, ep[j]) in known:
                cuts.append((i, j))
                used_z.add(i)
                used_e.add(j)
                last_j = j
                break

    def bounds(seq_len, used):
        pts = sorted(used)
        segs = []
        prev = -1
        for p in pts:
            segs.append((prev + 1, p))     # segment before this anchor
            prev = p
        segs.append((prev + 1, seq_len))
        return segs

    z_segs = bounds(n, used_z)
    e_segs = bounds(m, used_e)
    pairs = []
    for (zi, ej) in cuts:
        pairs.append((zp[zi], ep[ej]))
    # Segment 0 lies before the first anchor; segment k (k>=1) sits between
    # anchor k-1 and anchor k; the final segment trails the last anchor.
    for k in range(len(cuts) + 1):
        zs, es = z_segs[k], e_segs[k]
        for off in range(min(zs[1] - zs[0], es[1] - es[0])):
            pairs.append((zp[zs[0] + off], ep[es[0] + off]))
    return pairs


def build_answer_map(zh_blob, en_blob):
    """Pair conversation answer strings between the zh and en binaries.

    Answers are pushed with `pushs` inside conversation functions (those
    containing `cmps`). Equal-count functions pair positionally; count-
    mismatched functions go through anchor-seeded alignment using the pairs
    collected so far. Every zh text keeps translating: its EN partner is the
    most frequent one across the corpus (e.g. 職業 -> job), so ambiguous
    topics stay bilingual instead of dropping out.
    Returns {zh_text: en_text}.
    """
    zh_funcs = _disasm_all(zh_blob)
    en_funcs = _disasm_all(en_blob)

    def clean_texts(func):
        out = []
        for raw in _func_pushs_texts(func):
            t = undo_latin1_mojibake(raw).strip()
            if _answer_mergeable(t):
                out.append(t)
        return out

    votes = {}     # zh_text -> {en_text: count}
    mismatched = []
    for fid, zfunc in zh_funcs.items():
        efunc = en_funcs.get(fid)
        if efunc is None or not _has_cmps(zfunc) or not _has_cmps(efunc):
            continue
        zp = clean_texts(zfunc)
        ep = clean_texts(efunc)
        if not zp or not ep:
            continue
        if len(zp) == len(ep):
            for ztext, etext in zip(zp, ep):
                votes.setdefault(ztext, {})
                votes[ztext][etext] = votes[ztext].get(etext, 0) + 1
        else:
            mismatched.append((zp, ep))
    known = {(z, e) for z, ens in votes.items() for e in ens}
    for zp, ep in mismatched:
        # Anchors stay phase-1-only: harvested pairs do not seed later
        # alignments, so one mispair cannot compound.
        for ztext, etext in _align_pairs(zp, ep, known):
            votes.setdefault(ztext, {})
            votes[ztext][etext] = votes[ztext].get(etext, 0) + 1
    return {z: sorted(ens.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            for z, ens in votes.items()}


def generate(zh_blob, review, en_blob=None):
    """Returns (dual_blob, dual_rows, skipped)."""
    by_key = load_en_by_key(review)
    answer_map = build_answer_map(zh_blob, en_blob) if en_blob else {}
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
        if not traces and not answer_map:
            out += zh_blob[offset:nxt]
            offset = nxt
            continue
        # Collect addsi/addsv instruction IPs to locate variables inside each
        # merged trace's instruction span (first addsi .. say).
        old_data, nargs, nvars, externs, old_code = parse_parts(fdata, ext)
        addsi_ip_by_off = {}
        addsv_ips = []
        pushs_offs = []
        for ip, op, fmt in iter_all_instrs(old_code, ext):
            if op == 0x1C and fmt == "si":
                addsi_ip_by_off[read_si_operand(old_code, ip + 1, ext)] = ip
            elif op == 0x2F and fmt == "w":
                addsv_ips.append(ip)
            elif op == 0x1D and fmt == "si":
                pushs_offs.append(read_si_operand(old_code, ip + 1, ext))
        # Answer merging: redirect pushs operands whose zh text has an
        # EN partner (avatar topic list), rendered inline as ZH(EN).
        func_answer_redirect = {}
        if answer_map:
            for off in pushs_offs:
                raw = func["strings"].get(off)
                if not raw:
                    continue
                zh_text = undo_latin1_mojibake(raw)
                en_text = answer_map.get(zh_text)
                if en_text:
                    func_answer_redirect[off] = build_merged_answer(zh_text, en_text)
        # Companion/Avatar BARKS (pushs -> call [extern 0x08FF]): merge as
        # "ZH\nEN"; the bark-bubble renderer splits embedded newlines. EN
        # comes from the review rows ingested by ingest_bark_lines.py,
        # keyed by the pushs data offset.
        ext_map = {}
        for i in range(len(externs) // 2):
            if i * 2 + 2 <= len(externs):
                ext_map[i] = dis.read2(externs, i * 2)
        last_pushs = None
        for ip, op, fmt in iter_all_instrs(old_code, ext):
            if op == 0x1D and fmt == "si":
                last_pushs = read_si_operand(old_code, ip + 1, ext)
                continue
            if op == 0x24 and fmt == "w":
                ext_idx = dis.read2(old_code, ip + 1)
                if (
                    last_pushs is not None
                    and ext_map.get(ext_idx) == 0x08FF
                    and last_pushs not in func_answer_redirect
                ):
                    bark_info = by_key.get((fid_hex, "%x" % last_pushs)) or {}
                    en_text = (bark_info.get(0) or {}).get("text", "")
                    raw = func["strings"].get(last_pushs)
                    if en_text and raw:
                        zh_text = undo_latin1_mojibake(raw).strip()
                        if (
                            zh_text.startswith("@")
                            and zh_text.endswith("@")
                            and len(zh_text) >= 2
                        ):
                            zh_text = zh_text[1:-1].strip()
                        func_answer_redirect[last_pushs] = zh_text + "\n" + en_text
            last_pushs = None
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
            labels = seg_lines[0].get("addsv_labels") or []
            span_addsv = [ip for ip in addsv_ips if lo < ip < say_addr]
            # Neutralize only semantic-label addsv (<PLAYER_NAME> etc.);
            # generic <VAR> ones stay live so runtime values reach the text.
            for ip, label in zip(span_addsv, labels):
                if label != "<VAR>":
                    neutralize.add(ip)
        try:
            new_blob, first_offsets, empty_off, redirect = rebuild_function(
                fdata, ext, traces, neutralize,
                answer_redirect=func_answer_redirect or None)
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
    ap.add_argument("--no-answers", action="store_true",
                    help="Skip answer (pushs) merging even if --en exists")
    args = ap.parse_args()

    zh_blob = Path(args.zh).read_bytes()
    review = json.loads(Path(args.review).read_text(encoding="utf-8"))
    en_blob = None
    if not args.no_answers and Path(args.en).exists():
        en_blob = Path(args.en).read_bytes()
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