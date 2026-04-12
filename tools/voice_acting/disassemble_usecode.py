#!/usr/bin/env python3
"""
Minimal usecode disassembler for voice line extraction.

Reads a compiled usecode binary and outputs in a format compatible with
docs/usecode.dis for diffing, or in a compact voice-relevant format.

Usage:
    python disassemble_usecode.py <usecode_file> --func 0x401
    python disassemble_usecode.py <usecode_file> --func 0x401 --format dis
    python disassemble_usecode.py <usecode_file> --all --list
"""

import argparse
import struct
import sys


def read2(data, offset):
    return struct.unpack_from("<H", data, offset)[0]

def read2s(data, offset):
    return struct.unpack_from("<h", data, offset)[0]

def read4(data, offset):
    return struct.unpack_from("<I", data, offset)[0]

def read4s(data, offset):
    return struct.unpack_from("<i", data, offset)[0]


# NPC name lookup: function_id -> NPC name
# Function IDs for NPCs are 0x400 + abs(npc_number)
# Built from content/bgkeyring/src/headers/bg/bg_npcs.uc
BG_NPC_NAMES = {
    0x400: "Avatar",       # -356 -> special case, mapped to 0x400
    0x401: "Iolo",         # -1
    0x402: "Spark",        # -2
    0x403: "Shamino",      # -3
    0x404: "Dupre",        # -4
    0x405: "Jaana",        # -5
    0x407: "Sentri",       # -7
    0x408: "Julia",        # -8
    0x409: "Katrina",      # -9
    0x40A: "Tseramed",     # -10
    0x40B: "Petre",        # -11
    0x40C: "Finnigan",     # -12
    0x40D: "Gilberto",     # -13
    0x40E: "Johnson",      # -14
    0x410: "Klog",         # -16
    0x411: "Chantu",       # -17
    0x412: "Dell",         # -18
    0x413: "Apollonia",    # -19
    0x414: "Markus",       # -20
    0x415: "Gargan",       # -21
    0x416: "Caroline",     # -22
    0x417: "Lord British", # -23
    0x418: "Nystul",       # -24
    0x419: "Chuckles",     # -25
    0x41A: "Batlin",       # -26
}


def get_npc_name(func_id):
    """Get NPC name for a function ID, or empty string if unknown."""
    return BG_NPC_NAMES.get(func_id, "")


# Full opcode table with (name, param_format)
# param_format: 'w'=word, 's'=signed word, 'b'=byte, 'n'=none
# Special: 'si'=string index, 'vi'=variable index, 'ji'=jump offset,
#          'ci'=callis (word+byte), 'li'=sloop complex
OPCODES = {
    0x04: ("jne_f", "ji"),     # Jump if false (for flags)
    0x05: ("jne", "ji"),
    0x06: ("jmp", "ji"),
    0x09: ("add", "n"),
    0x0a: ("sub", "n"),
    0x0b: ("div", "n"),
    0x0c: ("mul", "n"),
    0x0d: ("mod", "n"),
    0x0e: ("and", "n"),
    0x0f: ("or", "n"),
    0x10: ("not", "n"),
    0x12: ("pop", "w"),
    0x13: ("push", "n", "true"),   # push true
    0x14: ("push", "n", "false"),  # push false
    0x16: ("cmpgt", "n"),
    0x17: ("cmplt", "n"),
    0x18: ("cmpge", "n"),
    0x19: ("cmple", "n"),
    0x1a: ("cmpne", "n"),
    0x1c: ("addsi", "si"),
    0x1d: ("pushs", "si"),
    0x1e: ("arrc", "w"),
    0x1f: ("pushi", "s"),
    0x21: ("push", "w"),
    0x22: ("cmpeq", "n"),
    0x24: ("call", "w"),
    0x25: ("ret", "n"),
    0x26: ("aidx", "n"),       # Array index
    0x2d: ("setr", "n"),
    0x2e: ("sloop", "n"),
    0x2f: ("addsv", "w"),
    0x30: ("in", "n"),
    0x31: ("smth31", "w"),
    0x32: ("rts", "n"),
    0x33: ("say", "n"),
    0x38: ("callis", "ci"),
    0x39: ("calli", "ci"),
    0x3e: ("push", "n", "itemref"),
    0x3f: ("abrt", "n"),
    0x40: ("end_conv", "n"),
    0x42: ("pushf", "w"),
    0x43: ("popf", "w"),
    0x44: ("pushw", "b"),      # Actually reads a signed word after the byte... complex
    0x46: ("cmpgt", "n"),
    0x47: ("calle", "w"),
    0x48: ("push", "n", "eventid"),
    0x4a: ("arra", "n"),       # Array append
    0x4b: ("pop_res", "n"),
    0x4d: ("flg_eq", "n"),
    0x50: ("addsv_32", "w"),   # 32-bit variant
}


def extract_data_segment(data_segment):
    """Extract all entries from the data segment: strings and null bytes."""
    entries = []  # (offset, type, value) where type is 'str' or 'null'
    i = 0
    while i < len(data_segment):
        if data_segment[i] != 0:
            start = i
            while i < len(data_segment) and data_segment[i] != 0:
                i += 1
            text = data_segment[start:i].decode("latin-1")
            entries.append((start, "str", text))
        else:
            entries.append((i, "null", None))
        i += 1
    return entries


def format_data_dis(data_segment):
    """Format data segment in usecode.dis style, including null byte entries."""
    lines = []
    lines.append("\t\t.data")
    i = 0
    while i < len(data_segment):
        if data_segment[i] == 0:
            lines.append(f"L{i:04X}:\tdb\t00")
            i += 1
        else:
            # Start of a string
            start = i
            while i < len(data_segment) and data_segment[i] != 0:
                i += 1
            text = data_segment[start:i].decode("latin-1")
            # Split into ~60 char chunks like the original
            chunk_size = 60
            pos = 0
            first = True
            while pos < len(text):
                chunk = text[pos:pos + chunk_size]
                pos += chunk_size
                if first:
                    lines.append(f"L{start:04X}:\tdb\t'{chunk}'")
                    first = False
                else:
                    lines.append(f"\tdb\t'{chunk}'")
    return lines


def parse_function(data, offset):
    """Parse a single usecode function. Returns (func_id, func_data, extended, next_offset)."""
    func_id = read2(data, offset)
    offset += 2
    extended = False
    if func_id == 0xfffe:
        func_id = read4s(data, offset); offset += 4
        func_len = read4(data, offset); offset += 4
        extended = True
    elif func_id == 0xffff:
        func_id = read2(data, offset); offset += 2
        func_len = read4(data, offset); offset += 4
        extended = True
    else:
        func_len = read2(data, offset); offset += 2
    func_data = data[offset:offset + func_len]
    return func_id, func_data, extended, offset + func_len


def disassemble_function(func_id, func_data, extended):
    """Disassemble a function into structured data."""
    pos = 0
    if not extended:
        data_len = read2(func_data, pos); pos += 2
    else:
        data_len = read4s(func_data, pos); pos += 4

    data_segment = func_data[pos:pos + data_len]
    pos += data_len

    num_args = read2(func_data, pos); pos += 2
    num_vars = read2(func_data, pos); pos += 2
    num_externs = read2(func_data, pos); pos += 2
    externs_list = []
    for _ in range(num_externs):
        externs_list.append(read2(func_data, pos)); pos += 2

    code_start = pos
    code_data = func_data[pos:]
    data_entries = extract_data_segment(data_segment)

    # Build string lookup
    strings = {}
    for off, typ, val in data_entries:
        if typ == "str":
            strings[off] = val

    # Disassemble
    instructions = []
    ip = 0
    while ip < len(code_data):
        opcode_byte = code_data[ip]
        addr = ip
        raw_bytes = [opcode_byte]
        ip += 1

        info = OPCODES.get(opcode_byte)
        if not info:
            instructions.append((addr, raw_bytes, f"unk_{opcode_byte:02x}", [], None))
            continue

        name = info[0]
        fmt = info[1]
        extra = info[2] if len(info) > 2 else None
        params = []
        comment = None

        try:
            if fmt == "n":
                pass
            elif fmt == "si":  # string index (addsi/pushs)
                if not extended:
                    val = read2(code_data, ip)
                    raw_bytes.extend(code_data[ip:ip+2]); ip += 2
                else:
                    val = read4s(code_data, ip)
                    raw_bytes.extend(code_data[ip:ip+4]); ip += 4
                params = [val]
                s = strings.get(val)
                if s:
                    preview = s[:20] + "..." if len(s) > 20 else s
                    comment = f"L{val:04X}\t\t; {preview}"
            elif fmt == "w":  # word param
                val = read2(code_data, ip)
                raw_bytes.extend(code_data[ip:ip+2]); ip += 2
                params = [val]
            elif fmt == "s":  # signed word
                val = read2s(code_data, ip)
                raw_bytes.extend(code_data[ip:ip+2]); ip += 2
                params = [val]
            elif fmt == "b":  # byte param (pushw is special - reads signed word)
                if name == "pushw":
                    val = read2s(code_data, ip)
                    raw_bytes.extend(code_data[ip:ip+2]); ip += 2
                    params = [val]
                else:
                    val = code_data[ip]
                    raw_bytes.append(val); ip += 1
                    params = [val]
            elif fmt == "ji":  # jump offset
                rel = read2s(code_data, ip)
                raw_bytes.extend(code_data[ip:ip+2]); ip += 2
                target = ip + rel  # target relative to after reading params
                params = [target]
            elif fmt == "ci":  # callis: word + byte
                intrinsic = read2(code_data, ip)
                raw_bytes.extend(code_data[ip:ip+2]); ip += 2
                nargs = code_data[ip]
                raw_bytes.append(nargs); ip += 1
                params = [intrinsic, nargs]
        except (IndexError, struct.error):
            pass

        instructions.append((addr, raw_bytes, name, params, comment))

    return {
        "id": func_id,
        "extended": extended,
        "data_len": data_len,
        "data_segment": data_segment,
        "data_entries": data_entries,
        "strings": strings,
        "num_args": num_args,
        "num_vars": num_vars,
        "num_externs": num_externs,
        "externs": externs_list,
        "instructions": instructions,
    }


def format_dis(func):
    """Format function in usecode.dis style."""
    lines = []
    lines.append(f"\t\t.funcnumber\t{func['id']:04X}H")

    # Data segment
    lines.extend(format_data_dis(func['data_segment']))

    # Code metadata
    lines.append("\t\t.code")
    lines.append(f"\t\t.argc {func['num_args']:04X}H")
    lines.append(f"\t\t.localc {func['num_vars']:04X}H")
    lines.append(f"\t\t.externsize {func['num_externs']:04X}H")
    for ext in func['externs']:
        lines.append(f"\t\t.extern {ext:04X}H")

    # Instructions
    for addr, raw_bytes, name, params, comment in func['instructions']:
        hex_str = " ".join(f"{b:02X}" for b in raw_bytes)
        hex_col = f"{hex_str:<16}"

        if name in ("addsi", "pushs") and params:
            s = func['strings'].get(params[0])
            if s:
                preview = s[:20] + "..." if len(s) > 20 else s
                lines.append(f"{addr:04X}: {hex_col}\t{name}\tL{params[0]:04X}\t\t\t; {preview}")
            else:
                lines.append(f"{addr:04X}: {hex_col}\t{name}\tL{params[0]:04X}")
        elif name == "addsv" and params:
            lines.append(f"{addr:04X}: {hex_col}\t{name}\t[{params[0]:04X}]")
        elif name in ("jne", "jmp", "jne_f") and params:
            lines.append(f"{addr:04X}: {hex_col}\t{name}\t{params[0]:04X}")
        elif name == "say":
            lines.append(f"{addr:04X}: {hex_col}\t{name}")
        elif name == "ret":
            lines.append(f"{addr:04X}: {hex_col}\t{name}")
        elif name == "abrt":
            lines.append(f"{addr:04X}: {hex_col}\t{name}")
        elif name in ("pop", "push") and params:
            extra_label = ""
            lines.append(f"{addr:04X}: {hex_col}\t{name}\t[{params[0]:04X}]")
        elif name == "push" and not params:
            extra_name = ""
            entry = OPCODES.get(raw_bytes[0])
            if entry and len(entry) > 2:
                extra_name = entry[2]
            lines.append(f"{addr:04X}: {hex_col}\t{name}\t{extra_name}")
        elif name == "pushi" and params:
            val = params[0]
            lines.append(f"{addr:04X}: {hex_col}\t{name}\t{val:04X}H\t\t\t; {val}")
        elif name == "pushw" and params:
            val = params[0] & 0xFFFF
            lines.append(f"{addr:04X}: {hex_col}\t{name}\t{val:04X}H\t\t\t; {params[0]}")
        elif name in ("callis", "calli") and len(params) >= 2:
            lines.append(f"{addr:04X}: {hex_col}\t{name}\t{params[0]:04X}, {params[1]}")
        elif name in ("call", "calle") and params:
            if name == "call":
                ext_id = func['externs'][params[0]] if params[0] < len(func['externs']) else 0
                lines.append(f"{addr:04X}: {hex_col}\t{name}\t[{params[0]:04X}]\t\t\t; {ext_id:04X}H")
            else:
                lines.append(f"{addr:04X}: {hex_col}\t{name}\t{params[0]:04X}H")
        elif name in ("pushf", "popf") and params:
            lines.append(f"{addr:04X}: {hex_col}\t{name}\tflag:[{params[0]:04X}]")
        elif name == "arrc" and params:
            lines.append(f"{addr:04X}: {hex_col}\t{name}\t{params[0]:04X}H\t\t\t; {params[0]}")
        else:
            if params:
                param_str = ", ".join(f"{p:04X}" for p in params)
                lines.append(f"{addr:04X}: {hex_col}\t{name}\t{param_str}")
            else:
                lines.append(f"{addr:04X}: {hex_col}\t{name}")

    return lines


def format_voice(func):
    """Format function showing only voice-relevant info."""
    lines = []
    lines.append(f"\nFunction 0x{func['id']:04X}")
    lines.append(f"  Data: {func['data_len']} bytes, {len(func['strings'])} strings")

    for offset, text in sorted(func['strings'].items()):
        preview = text[:70] + ("..." if len(text) > 70 else "")
        lines.append(f"  L{offset:04X}: \"{preview}\"")

    lines.append(f"\n  Code (voice-relevant):")
    for addr, raw_bytes, name, params, comment in func['instructions']:
        if name in ('addsi', 'addsv', 'say', 'jne', 'jmp', 'jne_f', 'ret', 'abrt'):
            if name == 'addsi' and params:
                s = func['strings'].get(params[0], "???")
                preview = s[:50] + ("..." if len(s) > 50 else "")
                lines.append(f"  {addr:04X}: {name}\tL{params[0]:04X}\t; \"{preview}\"")
            elif name == 'addsv' and params:
                lines.append(f"  {addr:04X}: {name}\t[{params[0]:04X}]")
            elif name in ('jne', 'jmp', 'jne_f') and params:
                lines.append(f"  {addr:04X}: {name}\t{params[0]:04X}")
            else:
                lines.append(f"  {addr:04X}: {name}")

    return lines


def analyze_variables(func):
    """
    Analyze function setup code to determine which local variables contain
    the player name, pronouns, or honorifics.

    Returns a dict mapping variable index -> label string:
      e.g. {0: "<PLAYER_NAME>", 3: "<HONORIFIC>"}
    """
    var_labels = {}
    instructions = func['instructions']
    externs = func['externs']

    for i, (addr, raw_bytes, name, params, comment) in enumerate(instructions):
        # Pattern: call [N] (where extern[N] is 0x908) followed by pop [V]
        # 0x908 = get_avatar_ref + get_npc_name → player name
        if name == 'call' and params:
            extern_idx = params[0]
            if extern_idx < len(externs):
                extern_func = externs[extern_idx]
                if extern_func == 0x908:  # Player name function
                    # Look for the next pop instruction
                    for j in range(i + 1, min(i + 4, len(instructions))):
                        _, _, n2, p2, _ = instructions[j]
                        if n2 == 'pop' and p2:
                            var_labels[p2[0]] = "<PLAYER_NAME>"
                            break
                elif extern_func == 0x909:  # Honorific function (milord/milady)
                    for j in range(i + 1, min(i + 4, len(instructions))):
                        _, _, n2, p2, _ = instructions[j]
                        if n2 == 'pop' and p2:
                            var_labels[p2[0]] = "<HONORIFIC>"
                            break

        # Pattern: callis 005A (IsPlayerFemale) followed by pop [V]
        # The gender flag variable itself isn't inserted into strings,
        # but we track it to identify pronoun variables set in branches.
        if name == 'callis' and params and params[0] == 0x5A:
            for j in range(i + 1, min(i + 4, len(instructions))):
                _, _, n2, p2, _ = instructions[j]
                if n2 == 'pop' and p2:
                    var_labels[p2[0]] = "<GENDER_FLAG>"
                    break

    # Detect pronoun variables: variables set by pushing a string like
    # "him"/"her"/"he"/"she" in a gender-conditional branch.
    # Pattern: pushs "her" -> pop [V] in one branch, pushs "him" -> pop [V] in another
    pronouns = {"him", "her", "he", "she", "his", "hers"}
    for i, (addr, raw_bytes, name, params, comment) in enumerate(instructions):
        if name == 'pushs' and params:
            s = func['strings'].get(params[0], "")
            if s.lower() in pronouns:
                # Look for pop [V] after this
                for j in range(i + 1, min(i + 3, len(instructions))):
                    _, _, n2, p2, _ = instructions[j]
                    if n2 == 'pop' and p2:
                        var_labels[p2[0]] = "<PRONOUN>"
                        break

    return var_labels


def extract_say_lines(func):
    """
    Extract all say-string lines from a function by tracing addsi/addsv -> say
    sequences linearly. Tracks show_npc_face (calli 0003) calls to determine
    which NPC is speaking each line. Also labels known variable types
    (player name, pronouns, honorifics).
    """
    lines = []
    accum = []
    current_face_npc = func['id']
    last_pushi_values = []

    # Analyze variables to label player name, pronouns, etc.
    var_labels = analyze_variables(func)

    for addr, raw_bytes, name, params, comment in func['instructions']:
        if name == 'pushi' and params:
            last_pushi_values.append(params[0])
            if len(last_pushi_values) > 4:
                last_pushi_values.pop(0)
        elif name == 'calli' and params and params[0] == 0x03 and params[1] == 2:
            if len(last_pushi_values) >= 2:
                npc_num = last_pushi_values[-1]
                if npc_num < 0:
                    current_face_npc = 0x400 + abs(npc_num)
                else:
                    current_face_npc = npc_num
        elif name == 'calli' and params and params[0] == 0x04:
            current_face_npc = func['id']
        elif name == 'addsi' and params:
            offset = params[0]
            text = func['strings'].get(offset, "")
            accum.append(('addsi', offset, text))
        elif name == 'addsv' and params:
            accum.append(('addsv', params[0], None))
        elif name == 'say':
            if not accum:
                continue

            # Build the offset key (only addsi offsets)
            addsi_offsets = [hex(e[1]) for e in accum if e[0] == 'addsi']
            offset_key = "_".join(addsi_offsets)

            # Build the template text with labeled placeholders
            template_parts = []
            has_var = False
            for typ, val, text in accum:
                if typ == 'addsi':
                    template_parts.append(text)
                else:
                    label = var_labels.get(val, "<VAR>")
                    template_parts.append(label)
                    has_var = True
            full_template = "".join(template_parts)

            # Determine the speaker
            speaker_npc = get_npc_name(current_face_npc)

            # Split at ~~ to get individual displayed segments
            segments = []
            current = full_template
            while current:
                current = current.lstrip('*')
                if not current:
                    break
                tilde_pos = current.find('~')
                if tilde_pos == -1:
                    segments.append(current.rstrip('*'))
                    break
                segment = current[:tilde_pos].rstrip('*')
                if segment:
                    segments.append(segment)
                current = current[tilde_pos + 1:]
                if current.startswith('~'):
                    current = current[1:]

            for seg_idx, seg_text in enumerate(segments):
                lines.append({
                    'func_id': func['id'],
                    'offset_key': offset_key,
                    'segment': seg_idx,
                    'total_segments': len(segments),
                    'text': seg_text,
                    'has_var': has_var,
                    'speaker': speaker_npc,
                    'speaker_func_id': current_face_npc,
                    'addsi_offsets': [e[1] for e in accum if e[0] == 'addsi'],
                    'code_addr': addr,
                })

            accum = []
        elif name in ('ret', 'abrt'):
            accum = []

    return lines


def format_csv(functions_data):
    """Format extracted say-lines as CSV."""
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'func_id', 'npc', 'speaker', 'offset_key', 'segment', 'total_segments',
        'has_var', 'text'
    ])

    for func in functions_data:
        say_lines = extract_say_lines(func)
        npc_name = get_npc_name(func['id'])
        for line in say_lines:
            writer.writerow([
                f"0x{line['func_id']:04X}",
                npc_name,
                line['speaker'],
                line['offset_key'],
                line['segment'],
                line['total_segments'],
                line['has_var'],
                line['text'],
            ])

    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description="Disassemble Ultima 7 usecode")
    parser.add_argument("usecode_file", help="Path to usecode binary file")
    parser.add_argument("--func", "-f", action="append",
                        help="Function ID (hex, e.g., 0x401). Can repeat.")
    parser.add_argument("--all", action="store_true", help="All functions")
    parser.add_argument("--list", action="store_true", help="Just list function IDs")
    parser.add_argument("--format", choices=["voice", "dis", "csv"], default="voice",
                        help="Output format: 'voice' (compact), 'dis' (usecode.dis style), or 'csv'")
    args = parser.parse_args()

    with open(args.usecode_file, "rb") as f:
        data = f.read()

    functions = {}
    offset = 0
    while offset < len(data):
        try:
            func_id, func_data, extended, next_offset = parse_function(data, offset)
            functions[func_id] = (func_data, extended)
            offset = next_offset
        except (struct.error, IndexError):
            break

    if args.list:
        print(f"Loaded {len(functions)} functions")
        for fid in sorted(functions.keys()):
            fdata, ext = functions[fid]
            print(f"  0x{fid:04X}  ({len(fdata)} bytes)")
        return

    target_ids = set()
    if args.all:
        target_ids = set(functions.keys())
    elif args.func:
        for f in args.func:
            target_ids.add(int(f, 16) if f.startswith("0x") else int(f))
    else:
        target_ids = {0x401, 0x40c, 0x885, 0x903}

    if args.format == "csv":
        funcs_data = []
        for fid in sorted(target_ids):
            if fid not in functions:
                print(f"Function 0x{fid:04X} not found!", file=sys.stderr)
                continue
            fdata, extended = functions[fid]
            funcs_data.append(disassemble_function(fid, fdata, extended))
        print(format_csv(funcs_data), end="")
    else:
        for fid in sorted(target_ids):
            if fid not in functions:
                print(f"Function 0x{fid:04X} not found!", file=sys.stderr)
                continue
            fdata, extended = functions[fid]
            func = disassemble_function(fid, fdata, extended)
            if args.format == "dis":
                for line in format_dis(func):
                    print(line)
            else:
                for line in format_voice(func):
                    print(line)


if __name__ == "__main__":
    main()
