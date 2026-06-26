#!/usr/bin/env python3
"""
Extract voice lines from Exult patch usecode by scanning raw bytecode
for addsi(0x1c) → say(0x33) patterns.  No full function parsing needed —
we hunt the opcode sequence directly within the function data.

Usage:
    python disassemble_patch_usecode.py <patch_usecode_file> > voice_lines.csv
"""

import csv
import struct
import sys

OPCODES = {
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


def skip_symbol_table(data, offset):
    """
    Skip Exult symbol table (magic + entires).
    The symbol table format:
      [8-byte magic: FFFFFFFF YSCU]
      [4-byte cnt][4-byte version]
      [entries: name\0 + kind(2) + value(4) + extra(kind-dependent)]
        - kind=1 (var): no extra
        - kind=2 (scope): children then trailing nm(2)+nm*2+2
        - kind=3 (type): extra 4 bytes
        - kind=6 (func): extra 4 bytes (repeated ID)
        - kind=7 (import): extra 4 bytes
    """
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
                # type (3), function (6), import (7): each has 4 extra bytes
                pos += 4
            # kind=1 (variable): no extra bytes
        return pos

    return skip_scope(offset + 8)


def extract_addsi_say_sequences(func_data, extended):
    """
    Scan raw function data for addsi(0x1c)+say(0x33) chains.
    Returns list of offset_key strings.
    
    We first try the standard function layout:
      [data_len(2|4)] [data_segment(data_len)] [nargs(2)] [nvars(2)] [nexterns(2)] [externs(2*nexterns)] [code...]
    
    If that fails (externs run past buffer), fall back to scanning the
    entire func_data for the bytecode pattern.
    """
    # Try standard layout first
    code_start = None
    try:
        pos = 0
        if extended:
            dl = read4s(func_data, pos); pos += 4
        else:
            dl = read2(func_data, pos); pos += 2
        
        if dl >= 0 and dl < len(func_data) - pos:
            pos += dl  # skip data segment
            nargs = read2(func_data, pos); pos += 2
            nvars = read2(func_data, pos); pos += 2
            nexterns = read2(func_data, pos); pos += 2
            externs_end = pos + 2 * nexterns
            if externs_end <= len(func_data):
                code_start = externs_end
    except (struct.error, ValueError):
        pass

    if code_start is None:
        # Fallback: search for function code by finding the first valid opcode
        # after the data segment.  Data segment ends at first 0x1c or 0x33
        # that isn't part of the data.  This is heuristic.
        code_start = find_code_start(func_data, extended)

    # Now scan bytecode for addsi→say chains
    ip = code_start
    sequences = []
    current_addsi = []
    multi_seg_text = []  # segments within same say()
    
    while ip < len(func_data):
        opcode = func_data[ip]
        info = OPCODES.get(opcode)
        
        if not info:
            ip += 1
            continue
        
        name = info[0]
        fmt = info[1]
        
        # Skip tracking: we only care about addsi, addsv, and say
        
        if opcode == 0x1c:  # addsi — opcode(1) + offset(2|4) + chin(1)
            if extended:
                off = read4s(func_data, ip + 1)
                ip += 6  # opcode(1) + offset(4) + chin(1)
            else:
                off = read2(func_data, ip + 1)
                ip += 4  # opcode(1) + offset(2) + chin(1)
            current_addsi.append(off)
        elif opcode == 0x2f:  # addsv — opcode(1) + word(2), does NOT affect voice trace
            ip += 3
        elif opcode == 0x33:  # say
            ip += 1
            if current_addsi:
                # Build offset key from addsi chain
                parts = [f"{o:x}" for o in current_addsi]
                offset_key = "_".join(parts)
                sequences.append(offset_key)
                current_addsi = []
        elif fmt == "n":
            ip += 1
        elif fmt == "b":
            ip += 2
        elif fmt in ("w", "s", "si"):
            ip += 1 + (2 if not extended else 4) if fmt == "si" else 3
        elif fmt == "ji":
            ip += 3
        elif fmt == "ci":
            ip += 4
        elif fmt == "ww":
            ip += 5
        elif fmt == "cs":
            ip += 4
        elif fmt == "lt":
            ip += 11
        else:
            ip += 1
    
    return sequences


def find_code_start(func_data, extended):
    """
    Heuristic: find where code likely starts by scanning for the first
    valid opcode after what appears to be the data segment.
    Data typically ends at a null-byte region, then header fields follow.
    """
    # Simple heuristic: skip the data_len header, then the data segment,
    # then read header fields.  If data_len seems sensible, use it.
    pos = 0
    try:
        if extended:
            dl = read4s(func_data, pos); pos += 4
        else:
            dl = read2(func_data, pos); pos += 2
        
        if 0 <= dl < len(func_data) - pos:
            pos += dl
            # Read header fields
            nargs = read2(func_data, pos); pos += 2
            nvars = read2(func_data, pos); pos += 2
            nexterns = read2(func_data, pos); pos += 2
            externs_end = pos + 2 * nexterns
            if externs_end <= len(func_data):
                return externs_end
    except (struct.error, ValueError):
        pass
    
    # Ultimate fallback: data segment might start at offset 0 (no header)
    # In that case, code might start after the data segment nulls
    # Try to find the first 0x1c byte
    for i in range(min(len(func_data), 100)):
        if func_data[i] == 0x1c or func_data[i] == 0x33:
            # Found what looks like code — back up to find data segment end
            # (data ends at last null byte before first opcode)
            break
    
    # Last resort: start from beginning and scan for opcodes
    return 0


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Extract voice lines from patch usecode via raw opcode scan")
    parser.add_argument("usecode_file", help="Path to patch usecode binary")
    parser.add_argument("-o", "--output", default=None,
                        help="Output CSV path (default: stdout)")
    args = parser.parse_args()

    with open(args.usecode_file, "rb") as f:
        data = f.read()

    offset = skip_symbol_table(data, 0)

    out = sys.stdout
    if args.output:
        out = open(args.output, "w", newline='', encoding='utf-8')

    writer = csv.writer(out)
    writer.writerow(["func_id", "offset_key", "segment"])

    while offset < len(data):
        try:
            func_id_raw = read2(data, offset)
            if func_id_raw == 0xFFFF:
                func_id = read2(data, offset + 2)
                func_len = read4(data, offset + 4)
                func_data = data[offset + 8: offset + 8 + func_len]
                extended = True
                offset += 8 + func_len
            elif func_id_raw == 0xFFFE:
                func_id = read4s(data, offset + 2)
                func_len = read4(data, offset + 6)
                func_data = data[offset + 10: offset + 10 + func_len]
                extended = True
                offset += 10 + func_len
            else:
                func_id = func_id_raw
                func_len = read2(data, offset + 2)
                func_data = data[offset + 4: offset + 4 + func_len]
                extended = False
                offset += 4 + func_len

            if func_len > 0 and func_len <= len(data) - offset:
                sequences = extract_addsi_say_sequences(func_data, extended)
                for seq in sequences:
                    parts = seq.split('_')
                    valid = True
                    for p in parts:
                        try:
                            int(p, 16)
                        except ValueError:
                            valid = False
                            break
                    if valid:
                        writer.writerow([f"0x{func_id:04X}", seq, 0])
        except (struct.error, IndexError, ValueError):
            break

    if args.output:
        out.close()


if __name__ == "__main__":
    main()
