#!/usr/bin/env python3
"""
Generate bilingual mapping from static analysis of English and Chinese usecode files.

Scans both usecode binaries for ALL string references (NPC speech, dialogue options,
books), extracts the text, and matches English/Chinese pairs by (func_id, position
order within function). No gameplay required.

Outputs bilingual_mapping.csv in the format that generate_bilingual_mapping_data.py
expects: func_id, en_offset_key, en_segment, en_text, zh_text.

Usage:
    python generate_bilingual_mapping_static.py \\
        --en <path_to_en_usecode> --zh <path_to_zh_usecode> \\
        -o bilingual_mapping_static.csv
"""

import argparse
import csv
import os
import struct
import sys

from npc_data import get_npc_name_by_func

# ── opcode table ──────────────────────────────────────────────────────

OPCODES_BY_ID = {
    0x02: ("looptop", "lt"),
    0x04: ("converse", "ji"),
    0x05: ("jne", "ji"),
    0x06: ("jmp", "ji"),
    0x07: ("cmps", "cs"),
    0x09: ("add", "n"),
    0x0a: ("sub", "n"),
    0x0b: ("div", "n"),
    0x0c: ("mul", "n"),
    0x0d: ("mod", "n"),
    0x0e: ("and", "n"),
    0x0f: ("or", "n"),
    0x10: ("not", "n"),
    0x1c: ("addsi", "si"),
    0x1d: ("pushs", "si"),
    0x1e: ("arrc", "w"),
    0x1f: ("pushi", "s"),
    0x21: ("push", "w"),
    0x22: ("cmpeq", "n"),
    0x24: ("call", "w"),
    0x25: ("ret", "n"),
    0x26: ("aidx", "w"),
    0x2c: ("ret2", "n"),
    0x2d: ("retv", "n"),
    0x2e: ("loop", "n"),
    0x2f: ("addsv", "w"),
    0x30: ("in", "n"),
    0x31: ("default", "ji"),
    0x32: ("retz", "n"),
    0x33: ("say", "n"),
    0x38: ("callis", "ci"),
    0x39: ("calli", "ci"),
    0x3e: ("push", "n", "itemref"),
    0x3f: ("abrt", "n"),
    0x40: ("converseloc", "n"),
    0x42: ("pushf", "w"),
    0x43: ("popf", "w"),
    0x44: ("pushb", "b"),
    0x46: ("poparr", "w"),
    0x47: ("calle", "w"),
    0x48: ("push", "n", "eventid"),
    0x4a: ("arra", "n"),
    0x4b: ("popeventid", "n"),
    0x4c: ("dbgline", "w"),
    0x50: ("pushstatic", "w"),
    0x51: ("popstatic", "w"),
    0x52: ("callo", "w"),
    0x53: ("callind", "n"),
    0x54: ("pushthv", "w"),
    0x55: ("popthv", "w"),
    0x56: ("callm", "w"),
    0x57: ("callms", "ww"),
    0x58: ("clscreate", "w"),
    0x59: ("classdel", "n"),
    0x5a: ("aidxs", "w"),
    0x5b: ("poparrs", "w"),
    0x5c: ("looptops", "lt"),
    0x5d: ("aidxthv", "w"),
    0x5e: ("poparrthv", "w"),
    0x5f: ("looptopthv", "lt"),
    0x60: ("pushchoice", "n"),
    0x61: ("trystart", "ww"),
    0x62: ("tryend", "n"),
}


def read2(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


def read4(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def read4s(data, offset):
    return struct.unpack_from("<i", data, offset)[0]


# ── symbol table skip ────────────────────────────────────────────────

def skip_symbol_table(data, offset):
    """Skip Exult symbol table if present."""
    if offset + 8 > len(data):
        return offset
    magic0 = read4(data, offset)
    magic1 = read4(data, offset + 4)
    if magic0 != 0xFFFFFFFF or magic1 != 0x55435359:
        return offset

    def skip_scope(pos):
        cnt = read4(data, pos); pos += 4
        pos += 4  # version
        for _ in range(cnt):
            while pos < len(data) and data[pos] != 0:
                pos += 1
            pos += 1
            kind = read2(data, pos); pos += 2
            pos += 4  # value
            if kind == 2:
                pos = skip_scope(pos)
                nm = read2(data, pos); pos += 2
                pos += 2 * nm
                pos += 2
            elif kind in (3, 6, 7):
                pos += 4
        return pos

    return skip_scope(offset + 8)


# ── function parsing ──────────────────────────────────────────────────

def parse_functions(data):
    """Iterate over functions in the usecode binary. Yields (func_id, func_data, extended)."""
    offset = skip_symbol_table(data, 0)
    while offset < len(data):
        try:
            func_id_raw = read2(data, offset)
            if func_id_raw == 0xFFFF:
                # Extended: 2-byte marker + 2-byte func_id + 4-byte length
                func_id = read2(data, offset + 2)
                func_len = read4(data, offset + 4)
                func_data = data[offset + 8: offset + 8 + func_len]
                extended = True
                offset += 8 + func_len
            elif func_id_raw == 0xFFFE:
                # Signed extended: 2-byte marker + 4-byte func_id + 4-byte length
                func_id = read4s(data, offset + 2)
                func_len = read4(data, offset + 6)
                func_data = data[offset + 10: offset + 10 + func_len]
                extended = True
                offset += 10 + func_len
            else:
                # Standard: 2-byte func_id + 2-byte length
                func_id = func_id_raw
                func_len = read2(data, offset + 2)
                func_data = data[offset + 4: offset + 4 + func_len]
                extended = False
                offset += 4 + func_len

            if func_len > 0 and func_len <= len(data) - offset:
                yield (func_id, func_data, extended)
            elif func_len == 0:
                pass  # empty function, skip
            else:
                break
        except (struct.error, IndexError, ValueError):
            break


# ── string extraction ────────────────────────────────────────────────

def split_segments(text):
    """Split text by ~~ sequence separators, return list of segment texts.
    
    Matches the game's say_string() logic where ~~ (two or more consecutive
    tildes) separates segments. The extra tildes beyond the first two are
    consumed (e.g., ~~~ counts as a separator, consuming 2 tildes).
    """
    parts = []
    i = 0
    buf = []
    while i < len(text):
        if text[i] == '~':
            # Look ahead for second tilde
            tilde_count = 1
            j = i + 1
            while j < len(text) and text[j] == '~':
                tilde_count += 1
                j += 1
            if tilde_count >= 2:
                # ~~ is a segment separator
                parts.append(''.join(buf))
                buf = []
                i = j
            else:
                # Single ~ is literal text (rare but possible in edge cases)
                buf.append('~')
                i += 1
        else:
            buf.append(text[i])
            i += 1
    if buf:
        parts.append(''.join(buf))
    return parts if parts else ['']


def extract_text_sequences(func_data, extended, encoding='utf-8'):
    """
    Scan function bytecode for ALL ADDSI sequences and extract the text.
    
    Returns (addsi_seqs, pushs_seqs, data_seg) where:
      addsi_seqs: list of (offset_key, text, segments) from ADDSI chains
      pushs_seqs: list of (offset_key, text, segments) from PUSHS opcodes
    A sequence is one or more consecutive ADDSI/ADDSV ops whose offsets
    are combined into the key, and whose strings are concatenated into
    the text. 'segments' is the text split by ~~ separators.
    encoding: string encoding for the data segment (e.g. 'utf-8', 'cp950', 'gbk')
    """
    # Locate code start
    code_start = None
    data_seg = b""
    try:
        pos = 0
        if extended:
            dl = read4s(func_data, pos); pos += 4
        else:
            dl = read2(func_data, pos); pos += 2

        if dl >= 0 and dl < len(func_data) - pos:
            data_seg = func_data[pos:pos + dl]
            pos += dl
            nargs = read2(func_data, pos); pos += 2
            nvars = read2(func_data, pos); pos += 2
            nexterns = read2(func_data, pos); pos += 2
            externs_end = pos + 2 * nexterns
            if externs_end <= len(func_data):
                code_start = externs_end
    except (struct.error, ValueError):
        pass

    if code_start is None:
        code_start = 0

    # Scan bytecode for ADDSI chains and PUSHS opcodes
    ip = code_start
    addsi_seqs = []   # sequences from ADDSI chains (with ~~ splitting)
    pushs_seqs = []   # individual strings from PUSHS (no ~~ splitting)
    current_addsi = []
    current_text_parts = []

    def flush():
        if current_addsi:
            # 1. Output the combined sequence (if there's more than one offset)
            if len(current_addsi) > 1:
                parts = [f"{o:x}" for o in current_addsi if o >= 0]
                offset_key = "_".join(parts) if parts else str(current_addsi[0])
                text = "".join(current_text_parts)
                segs = split_segments(text)
                addsi_seqs.append((offset_key, text, segs))
            # 2. Output individual sequences for each offset
            for o, s in zip(current_addsi, current_text_parts):
                if o >= 0:
                    addsi_seqs.append((f"{o:x}", s, split_segments(s)))
            current_addsi.clear()
            current_text_parts.clear()

    while ip < len(func_data):
        opcode = func_data[ip]
        info = OPCODES_BY_ID.get(opcode)

        if not info:
            # Unknown opcode: end any in-progress sequence
            flush()
            ip += 1
            continue

        fmt = info[1]

        if opcode == 0x1c:  # addsi — push string, offset in data segment
            if extended:
                off = read4s(func_data, ip + 1)
                ip += 6  # opcode(1) + offset(4) + chin(1)
            else:
                off = read2(func_data, ip + 1)
                ip += 4  # opcode(1) + offset(2) + chin(1)
            if off >= 0 and off < len(data_seg):
                end = data_seg.find(b'\0', off)
                if end == -1:
                    end = len(data_seg)
                raw = data_seg[off:end]
                try:
                    s = raw.decode(encoding)
                except UnicodeDecodeError:
                    s = raw.decode(encoding, errors='replace')
                current_addsi.append(off)
                current_text_parts.append(s)
            else:
                flush()
        elif opcode == 0x1d:  # pushs — push string to stack (used by dialogue options)
            flush()
            if extended:
                pushs_off = read4s(func_data, ip + 1)
                ip += 5
            else:
                pushs_off = read2(func_data, ip + 1)
                ip += 3
            if pushs_off >= 0 and pushs_off < len(data_seg):
                end = data_seg.find(b'\0', pushs_off)
                if end == -1:
                    end = len(data_seg)
                raw = data_seg[pushs_off:end]
                try:
                    s = raw.decode(encoding)
                except UnicodeDecodeError:
                    s = raw.decode(encoding, errors='replace')
                pushs_seqs.append((f"{pushs_off:x}", s, [s]))
        elif opcode == 0x2f:  # addsv — variable push (not a string literal)
            current_addsi.append(-1)
            ip += 3
        elif opcode in (0x33,):  # say — ends the sequence
            ip += 1
            flush()
        elif opcode in (0x38, 0x39):  # callis/calli — intrinsic call, consumes stack
            ip += 4
            flush()
        elif fmt == "n":
            ip += 1
        elif fmt == "b":
            ip += 2
            flush()
        elif fmt == "w":
            ip += 3
            # push/pop that might follow a string — be conservative and flush
            # unless it's addsv (already handled) or a known non-consumer
            if opcode not in (0x2f, 0x1d, 0x21, 0x42, 0x43, 0x50, 0x51, 0x54, 0x55):
                flush()
        elif fmt == "s":
            ip += 3
            flush()
        elif fmt == "si":
            # addsv (0x2f) falls through here — handle generic flush
            ip += 1 + (4 if extended else 2)
            flush()
        elif fmt == "ji":
            ip += 3
            flush()
        elif fmt == "cs":
            ip += 4
            flush()
        elif fmt == "lt":
            ip += 11
            flush()
        elif fmt == "ww":
            ip += 5
            flush()
        elif fmt == "ci":
            ip += 4
            flush()
        else:
            ip += 1
            flush()

    flush()
    return addsi_seqs, pushs_seqs, data_seg


# ── main ──────────────────────────────────────────────────────────────

def build_sequence_map(usecode_path, encoding='utf-8'):
    """
    Parse a usecode file and extract all text sequences per function.
    Returns: (addsi_map, pushs_map) where each is { func_id: [(offset_key, text, segments), ...] }
    encoding: string encoding for the data segment (e.g. 'utf-8', 'cp950')
    """
    with open(usecode_path, "rb") as f:
        data = f.read()

    addsi_result = {}
    pushs_result = {}
    for func_id, func_data, extended in parse_functions(data):
        addsi, pushs, _ = extract_text_sequences(func_data, extended, encoding)
        if addsi:
            addsi_result[func_id] = addsi
        if pushs:
            pushs_result[func_id] = pushs
    return addsi_result, pushs_result


def extract_ascii_tokens(text):
    """Extract ASCII word tokens (proper nouns, numbers) from text.
    Returns set of lowercase tokens."""
    tokens = set()
    word = []
    for ch in text:
        if 'A' <= ch <= 'Z' or 'a' <= ch <= 'z' or '0' <= ch <= '9':
            word.append(ch.lower())
        else:
            if word and len(word) >= 2:
                tokens.add(''.join(word))
            word = []
    if word and len(word) >= 2:
        tokens.add(''.join(word))
    return tokens


def compute_match_score(en_seq, zh_seq):
    """Compute content similarity score between EN and ZH sequences.
    Returns number of shared ASCII tokens (proper nouns, names, numbers).
    Requires at least 2 shared tokens, or 1 shared token if the EN text
    has 3 or fewer tokens (short phrases like 'Trinsic' or 'stables')."""
    en_tokens = extract_ascii_tokens(en_seq[1])  # (key, text, segments)
    zh_tokens = extract_ascii_tokens(zh_seq[1])
    if not en_tokens or not zh_tokens:
        return -1  # no overlap possible
    shared = en_tokens & zh_tokens
    if not shared:
        return -1
    if len(shared) >= 2:
        return len(shared)
    # Single shared token: only accept if EN text has <= 3 tokens
    # or the shared token is a proper noun (starts with uppercase)
    if len(en_tokens) <= 3:
        return len(shared)
    # Check if the single shared token is a proper noun
    token = next(iter(shared))
    if token and token[0].isupper():
        return len(shared)
    return -1


def pair_sequences(en_seqs, zh_seqs, fid, npc_name, seq_type):
    """Pair EN and ZH sequences. Primary: content-based matching (shared ASCII tokens).
    For sequences with no ASCII tokens, falls back to position-based pairing.
    Returns list of row dicts."""
    # Phase 1: content-based matching for sequences with ASCII tokens
    matched_en = set()
    matched_zh = set()
    content_rows = []

    # Build score matrix for all pairs
    scores = []
    for ei, en_seq in enumerate(en_seqs):
        for zi, zh_seq in enumerate(zh_seqs):
            score = compute_match_score(en_seq, zh_seq)
            if score >= 1:
                # Prefer matches close in position (|ei-zi| <= 3) to avoid
                # false positives from shared names in different contexts
                pos_dist = abs(ei - zi)
                if pos_dist > 3:
                    score = 0  # too far apart, reject
                else:
                    scores.append((score, ei, zi))

    # Sort by score descending, greedy match
    scores.sort(key=lambda x: -x[0])
    for score, ei, zi in scores:
            if ei in matched_en or zi in matched_zh:
                continue
            matched_en.add(ei)
            matched_zh.add(zi)
            en_key, en_text, en_segs = en_seqs[ei]
            zh_key, zh_text, zh_segs = zh_seqs[zi]
            seg_count = min(len(en_segs), len(zh_segs))
            for j in range(seg_count):
                content_rows.append({
                    "func_id": f"0x{fid:04X}",
                    "npc": npc_name,
                    "en_offset_key": en_key,
                    "en_segment": str(j),
                    "en_text": en_segs[j],
                    "zh_offset_key": zh_key,
                    "zh_segment": str(j),
                    "zh_text": zh_segs[j],
                    "confidence": f"matched_{seq_type}",
                })
            for j in range(seg_count, len(en_segs)):
                content_rows.append({
                    "func_id": f"0x{fid:04X}",
                    "npc": npc_name,
                    "en_offset_key": en_key,
                    "en_segment": str(j),
                    "en_text": en_segs[j],
                    "zh_offset_key": "",
                    "zh_segment": "0",
                    "zh_text": "",
                    "confidence": f"unpaired_{seq_type}_en",
                })
            for j in range(seg_count, len(zh_segs)):
                content_rows.append({
                    "func_id": f"0x{fid:04X}",
                    "npc": npc_name,
                    "en_offset_key": "",
                    "en_segment": "0",
                    "en_text": "",
                    "zh_offset_key": zh_key,
                    "zh_segment": str(j),
                    "zh_text": zh_segs[j],
                    "confidence": f"unpaired_{seq_type}_zh",
                })

    # Phase 2: position-based fallback for unmatched sequences (no ASCII tokens)
    unpaired_en = [i for i in range(len(en_seqs)) if i not in matched_en]
    unpaired_zh = [i for i in range(len(zh_seqs)) if i not in matched_zh]
    fallback_rows = []

    count = min(len(unpaired_en), len(unpaired_zh))
    for k in range(count):
        ei = unpaired_en[k]
        zi = unpaired_zh[k]
        en_key, en_text, en_segs = en_seqs[ei]
        zh_key, zh_text, zh_segs = zh_seqs[zi]
        seg_count = min(len(en_segs), len(zh_segs))
        for j in range(seg_count):
            fallback_rows.append({
                "func_id": f"0x{fid:04X}",
                "npc": npc_name,
                "en_offset_key": en_key,
                "en_segment": str(j),
                "en_text": en_segs[j],
                "zh_offset_key": zh_key,
                "zh_segment": str(j),
                "zh_text": zh_segs[j],
                "confidence": f"static_{seq_type}",
            })
        for j in range(seg_count, len(en_segs)):
            fallback_rows.append({
                "func_id": f"0x{fid:04X}",
                "npc": npc_name,
                "en_offset_key": en_key,
                "en_segment": str(j),
                "en_text": en_segs[j],
                "zh_offset_key": "",
                "zh_segment": "0",
                "zh_text": "",
                "confidence": f"unpaired_{seq_type}_en",
            })
        for j in range(seg_count, len(zh_segs)):
            fallback_rows.append({
                "func_id": f"0x{fid:04X}",
                "npc": npc_name,
                "en_offset_key": "",
                "en_segment": "0",
                "en_text": "",
                "zh_offset_key": zh_key,
                "zh_segment": str(j),
                "zh_text": zh_segs[j],
                "confidence": f"unpaired_{seq_type}_zh",
            })

    # Remaining unpaired entries
    for i in unpaired_en[count:]:
        en_key, en_text, en_segs = en_seqs[i]
        for j, seg_text in enumerate(en_segs):
            fallback_rows.append({
                "func_id": f"0x{fid:04X}",
                "npc": npc_name,
                "en_offset_key": en_key,
                "en_segment": str(j),
                "en_text": seg_text,
                "zh_offset_key": "",
                "zh_segment": "0",
                "zh_text": "",
                "confidence": f"unpaired_{seq_type}_en",
            })
    for i in unpaired_zh[count:]:
        zh_key, zh_text, zh_segs = zh_seqs[i]
        for j, seg_text in enumerate(zh_segs):
            fallback_rows.append({
                "func_id": f"0x{fid:04X}",
                "npc": npc_name,
                "en_offset_key": "",
                "en_segment": "0",
                "en_text": "",
                "zh_offset_key": zh_key,
                "zh_segment": str(j),
                "zh_text": seg_text,
                "confidence": f"unpaired_{seq_type}_zh",
            })

    return content_rows + fallback_rows


def main():
    parser = argparse.ArgumentParser(
        description="Generate bilingual mapping via static usecode analysis")
    parser.add_argument("--en", required=True,
                        help="Path to English usecode binary")
    parser.add_argument("--zh", required=True,
                        help="Path to Chinese usecode binary")
    parser.add_argument("--en-encoding", default="utf-8",
                        help="Encoding of English usecode strings (default: utf-8)")
    parser.add_argument("--zh-encoding", default="utf-8",
                        help="Encoding of Chinese usecode strings (default: utf-8)")
    parser.add_argument("-o", "--output", default="bilingual_mapping_static.csv",
                        help="Output CSV path")
    args = parser.parse_args()

    print(f"Parsing English usecode: {args.en}", file=sys.stderr)
    en_addsi, en_pushs = build_sequence_map(args.en, args.en_encoding)
    print(f"  ADDSI: {len(en_addsi)} functions, PUSHS: {len(en_pushs)} functions", file=sys.stderr)

    print(f"Parsing Chinese usecode: {args.zh}", file=sys.stderr)
    zh_addsi, zh_pushs = build_sequence_map(args.zh, args.zh_encoding)
    print(f"  ADDSI: {len(zh_addsi)} functions, PUSHS: {len(zh_pushs)} functions", file=sys.stderr)

    rows = []

    # ── Pair ADDSI sequences (NPC speech) ──────────────────────────────
    print("Pairing ADDSI sequences...", file=sys.stderr)
    common_addsi = sorted(set(en_addsi.keys()) & set(zh_addsi.keys()))
    print(f"  Common ADDSI functions: {len(common_addsi)}", file=sys.stderr)
    en_only_addsi = sorted(set(en_addsi.keys()) - set(zh_addsi.keys()))
    zh_only_addsi = sorted(set(zh_addsi.keys()) - set(en_addsi.keys()))
    if en_only_addsi:
        print(f"  EN-only ADDSI functions: {len(en_only_addsi)}", file=sys.stderr)
    if zh_only_addsi:
        print(f"  ZH-only ADDSI functions: {len(zh_only_addsi)}", file=sys.stderr)

    for fid in common_addsi:
        npc_name = get_npc_name_by_func(fid) if fid >= 0x400 else ""
        rows.extend(pair_sequences(en_addsi[fid], zh_addsi[fid], fid, npc_name, "addsi"))

    # ── Pair PUSHS sequences (dialogue options) ────────────────────────
    print("Pairing PUSHS sequences...", file=sys.stderr)
    common_pushs = sorted(set(en_pushs.keys()) & set(zh_pushs.keys()))
    print(f"  Common PUSHS functions: {len(common_pushs)}", file=sys.stderr)
    en_only_pushs = sorted(set(en_pushs.keys()) - set(zh_pushs.keys()))
    zh_only_pushs = sorted(set(zh_pushs.keys()) - set(en_pushs.keys()))
    if en_only_pushs:
        print(f"  EN-only PUSHS functions: {len(en_only_pushs)}", file=sys.stderr)
    if zh_only_pushs:
        print(f"  ZH-only PUSHS functions: {len(zh_only_pushs)}", file=sys.stderr)

    for fid in common_pushs:
        npc_name = get_npc_name_by_func(fid) if fid >= 0x400 else ""
        rows.extend(pair_sequences(en_pushs[fid], zh_pushs[fid], fid, npc_name, "pushs"))

    print(f"Total entries: {len(rows)}", file=sys.stderr)

    # Write output CSV
    fieldnames = [
        "func_id", "npc",
        "en_offset_key", "en_segment", "en_text",
        "zh_offset_key", "zh_segment", "zh_text",
        "confidence",
    ]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
