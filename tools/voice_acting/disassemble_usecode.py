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


from npc_data import get_npc_name_by_func as get_npc_name


# Full opcode table: opcode -> (name, param_format, [extra])
# param_format: 'n'=none, 'w'=word, 's'=signed word, 'ji'=jump offset,
#               'si'=string index, 'ci'=callis (word+byte),
#               'lt'=looptop (5 words), 'cs'=cmps (word+signed word)
# Derived from usecode/opcodes.h and usecode/ucinternal.cc
OPCODES = {
    # Loop
    0x02: ("looptop", "lt"),        # 5 words: local1,local2,local3,local4,offset
    # Conversation
    0x04: ("converse", "ji"),       # jump offset (to end of converse block)
    # Jumps
    0x05: ("jne", "ji"),
    0x06: ("jmp", "ji"),
    # String compare (conversation topic matching)
    0x07: ("cmps", "cs"),           # word count + signed word offset
    # Arithmetic
    0x09: ("add", "n"),
    0x0a: ("sub", "n"),
    0x0b: ("div", "n"),
    0x0c: ("mul", "n"),
    0x0d: ("mod", "n"),
    # Logic
    0x0e: ("and", "n"),
    0x0f: ("or", "n"),
    0x10: ("not", "n"),
    # Variables
    0x12: ("pop", "w"),
    0x13: ("push", "n", "true"),
    0x14: ("push", "n", "false"),
    # Comparisons
    0x16: ("cmpgt", "n"),
    0x17: ("cmplt", "n"),
    0x18: ("cmpge", "n"),
    0x19: ("cmple", "n"),
    0x1a: ("cmpne", "n"),
    # String operations
    0x1c: ("addsi", "si"),          # Add string from data segment
    0x1d: ("pushs", "si"),          # Push string from data segment
    0x1e: ("arrc", "w"),            # Create array
    0x1f: ("pushi", "s"),           # Push immediate
    0x21: ("push", "w"),            # Push local var
    0x22: ("cmpeq", "n"),
    # Calls
    0x24: ("call", "w"),            # Call extern
    0x25: ("ret", "n"),
    0x26: ("aidx", "w"),            # Array index (reads local var index)
    0x2c: ("ret2", "n"),            # Identical to ret
    0x2d: ("retv", "n"),            # Return value from stack
    0x2e: ("loop", "n"),            # Loop init (no params - peeks next byte)
    0x2f: ("addsv", "w"),           # Add string from variable
    0x30: ("in", "n"),              # Is value in array
    0x31: ("default", "ji"),        # Conversation default branch
    0x32: ("retz", "n"),            # Return zero
    0x33: ("say", "n"),             # Say string register
    0x38: ("callis", "ci"),         # Call intrinsic (static)
    0x39: ("calli", "ci"),          # Call intrinsic
    0x3e: ("push", "n", "itemref"),
    0x3f: ("abrt", "n"),
    0x40: ("converseloc", "n"),     # Converse jump target
    0x42: ("pushf", "w"),           # Push flag
    0x43: ("popf", "w"),            # Pop flag
    0x44: ("pushb", "b"),           # Push single byte
    0x46: ("poparr", "w"),          # Pop into array element
    0x47: ("calle", "w"),           # Call extern by index
    0x48: ("push", "n", "eventid"),
    0x4a: ("arra", "n"),            # Array append
    0x4b: ("popeventid", "n"),      # Pop event ID
    0x4c: ("dbgline", "w"),         # Debug line number
    0x50: ("pushstatic", "w"),      # Push static var
    0x51: ("popstatic", "w"),       # Pop static var
    0x52: ("callo", "w"),           # Call original
    0x53: ("callind", "n"),         # Call indirect (addr on stack)
    0x54: ("pushthv", "w"),         # Push this->var
    0x55: ("popthv", "w"),          # Pop this->var
    0x56: ("callm", "w"),           # Call method
    0x57: ("callms", "ww"),         # Call method (2 words: index, vtable)
    0x58: ("clscreate", "w"),       # Create class instance
    0x59: ("classdel", "n"),        # Delete class instance
    0x5a: ("aidxs", "w"),           # Static array index
    0x5b: ("poparrs", "w"),         # Pop into static array
    0x5c: ("looptops", "lt"),       # Loop with static array
    0x5d: ("aidxthv", "w"),         # This->var array index
    0x5e: ("poparrthv", "w"),       # Pop this->var array
    0x5f: ("looptopthv", "lt"),     # Loop with this->var array
    0x60: ("pushchoice", "n"),      # Push last user choice
    0x61: ("trystart", "ww"),       # Try/catch start (offset, local var)
    0x62: ("tryend", "n"),          # Try/catch end
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
            elif fmt == "b":  # single byte param
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
            elif fmt == "cs":  # cmps: word count + signed word offset
                cnt = read2(code_data, ip)
                raw_bytes.extend(code_data[ip:ip+2]); ip += 2
                rel = read2s(code_data, ip)
                raw_bytes.extend(code_data[ip:ip+2]); ip += 2
                target = ip + rel
                params = [cnt, target]
            elif fmt == "lt":  # looptop: 5 words
                p = []
                for _ in range(4):
                    val = read2(code_data, ip)
                    raw_bytes.extend(code_data[ip:ip+2]); ip += 2
                    p.append(val)
                rel = read2s(code_data, ip)
                raw_bytes.extend(code_data[ip:ip+2]); ip += 2
                p.append(ip + rel)
                params = p
            elif fmt == "ww":  # two words
                val1 = read2(code_data, ip)
                raw_bytes.extend(code_data[ip:ip+2]); ip += 2
                val2 = read2(code_data, ip)
                raw_bytes.extend(code_data[ip:ip+2]); ip += 2
                params = [val1, val2]
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

    # Propagate labels through variable copies.
    # Pattern: push [V1] -> pop [V2] where V1 has a known label.
    # Repeat until no new labels are found (handles copy chains).
    changed = True
    while changed:
        changed = False
        for i, (addr, raw_bytes, name, params, comment) in enumerate(instructions):
            if name == 'push' and params and params[0] in var_labels:
                src_label = var_labels[params[0]]
                # Look for pop [V] after this push
                for j in range(i + 1, min(i + 3, len(instructions))):
                    _, _, n2, p2, _ = instructions[j]
                    if n2 == 'pop' and p2:
                        if p2[0] not in var_labels:
                            var_labels[p2[0]] = src_label
                            changed = True
                        break

    return var_labels


def detect_book_mode(func):
    """Check if a function sets book mode (intrinsic 0x55) before any say opcode.
    Also detects book mode set within the function at any point.

    Returns True if the function displays book/scroll text rather than
    conversation dialog.
    """
    for addr, raw_bytes, name, params, comment in func['instructions']:
        # book_mode intrinsic (0x55) called via calli or callis
        if name in ('calli', 'callis') and params and params[0] == 0x55:
            return True
        # If we hit a say before any book_mode, it's a conversation
        if name == 'say':
            return False
    return False


def extract_say_lines(func):
    """
    Extract all say-string lines from a function by tracing addsi/addsv -> say
    sequences linearly. Tracks show_npc_face (calli 0003) calls to determine
    which NPC is speaking each line. Also labels known variable types
    (player name, pronouns, honorifics).
    """
    lines = []
    accum = []
    is_book = detect_book_mode(func)

    # Determine the default face NPC for this function.
    # If the function calls show_npc_face and all calls are for the same NPC,
    # use that as the default speaker (even for lines before the first face call).
    # Otherwise fall back to the function's own NPC ID.
    face_npcs_in_func = set()
    last_pushi_scan = []
    for addr, raw_bytes, name, params, comment in func['instructions']:
        if name == 'pushi' and params:
            last_pushi_scan.append(params[0])
            if len(last_pushi_scan) > 4:
                last_pushi_scan.pop(0)
        elif name == 'calli' and params and params[0] == 0x03 and params[1] == 2:
            if len(last_pushi_scan) >= 2:
                npc_num = last_pushi_scan[-1]
                if npc_num < 0:
                    face_npcs_in_func.add(0x400 + abs(npc_num))
    if len(face_npcs_in_func) == 1:
        default_face_npc = face_npcs_in_func.pop()
    else:
        default_face_npc = func['id']

    current_face_npc = default_face_npc
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
            # remove_npc_face. Reset to default_face_npc only when that ID
            # resolves to a known NPC - otherwise there is no useful owner
            # to hand the mic to, and we prefer keeping the current face.
            #
            # - NPC function with guests (e.g. 0x40c = Finnigan hosting Iolo):
            #   default_face_npc = func['id'] = 0x40c = "Finnigan". Reset
            #   gives the line back to Finnigan. Correct.
            # - General multi-face function (e.g. 0x9A, not an NPC face):
            #   default_face_npc = func['id'] = 0x9A, no NPC mapping. Do not
            #   reset; keep the current speaker.
            # - Single-face function: default_face_npc is that NPC, reset is
            #   a no-op.
            if get_npc_name(default_face_npc):
                current_face_npc = default_face_npc
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
                    'is_book': is_book,
                    'speaker': speaker_npc,
                    'speaker_func_id': current_face_npc,
                    'addsi_offsets': [e[1] for e in accum if e[0] == 'addsi'],
                    'code_addr': addr,
                })

            accum = []
        elif name in ('ret', 'abrt'):
            accum = []

    return lines


def build_caller_map(all_functions):
    """Build a map of function_id -> set of NPC function IDs that call it.

    For each function, examine its externs list. If any extern references
    a function, record that the current function calls that extern.
    Then resolve callers to NPC names where possible.

    Returns dict: func_id -> set of calling func_ids
    """
    callers_of = {}
    for fid, func in all_functions.items():
        for ext_fid in func['externs']:
            if ext_fid not in callers_of:
                callers_of[ext_fid] = set()
            callers_of[ext_fid].add(fid)
    return callers_of


def infer_speaker_from_callers(func_id, callers_of, depth=0):
    """Try to infer the NPC speaker for a non-NPC function by tracing
    its callers. If all callers resolve to the same NPC, return that NPC name.

    Recurses up to 3 levels to handle chains like:
      NPC func -> utility1 -> utility2 -> target
    """
    if depth > 3:
        return ""

    # Direct NPC check
    name = get_npc_name(func_id)
    if name:
        return name

    callers = callers_of.get(func_id, set())
    if not callers:
        return ""

    # Resolve each caller to an NPC
    npc_names = set()
    for caller_fid in callers:
        caller_name = get_npc_name(caller_fid)
        if caller_name:
            npc_names.add(caller_name)
        else:
            # Recurse up the call chain
            inferred = infer_speaker_from_callers(caller_fid, callers_of, depth + 1)
            if inferred:
                npc_names.add(inferred)

    if len(npc_names) == 1:
        return npc_names.pop()
    elif len(npc_names) > 1:
        # Multiple NPCs call this - return them all as a hint
        return "|".join(sorted(npc_names))
    return ""


def write_csv(functions_data, outfile, callers_of=None, include_books=False):
    """Write extracted say-lines as CSV to a file object."""
    import csv

    writer = csv.writer(outfile)
    header = [
        'func_id', 'npc', 'speaker', 'caller_guess', 'offset_key',
        'segment', 'total_segments', 'has_var',
    ]
    if include_books:
        header.append('is_book')
    header.append('text')
    writer.writerow(header)

    for func in functions_data:
        say_lines = extract_say_lines(func)
        npc = get_npc_name(func['id'])

        # Infer speaker from call graph for non-NPC functions
        caller_guess = ""
        if callers_of and not npc:
            caller_guess = infer_speaker_from_callers(func['id'], callers_of)

        for line in say_lines:
            if line['is_book'] and not include_books:
                continue

            row = [
                f"0x{line['func_id']:04X}",
                npc,
                line['speaker'],
                caller_guess,
                line['offset_key'],
                line['segment'],
                line['total_segments'],
                line['has_var'],
            ]
            if include_books:
                row.append(line['is_book'])
            row.append(line['text'])
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="Disassemble Ultima 7 usecode")
    parser.add_argument("usecode_file", help="Path to usecode binary file")
    parser.add_argument("--func", "-f", action="append",
                        help="Function ID (hex, e.g., 0x401). Can repeat.")
    parser.add_argument("--all", action="store_true", help="All functions")
    parser.add_argument("--list", action="store_true", help="Just list function IDs")
    parser.add_argument("--format", choices=["voice", "dis", "csv"], default="voice",
                        help="Output format: 'voice' (compact), 'dis' (usecode.dis style), or 'csv'")
    parser.add_argument("--include-books", action="store_true",
                        help="Include book/scroll text in CSV output (excluded by default)")
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
        # Build caller map from ALL functions for speaker inference,
        # even if we're only extracting a subset.
        all_disassembled = {}
        for fid, (fdata, extended) in functions.items():
            all_disassembled[fid] = disassemble_function(fid, fdata, extended)
        callers_of = build_caller_map(all_disassembled)

        funcs_data = []
        for fid in sorted(target_ids):
            if fid not in all_disassembled:
                print(f"Function 0x{fid:04X} not found!", file=sys.stderr)
                continue
            funcs_data.append(all_disassembled[fid])
        import sys, os
        # Prevent double \r\n on Windows by using binary mode stdout
        sys.stdout.reconfigure(newline="")
        write_csv(funcs_data, sys.stdout, callers_of,
                  include_books=args.include_books)
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
