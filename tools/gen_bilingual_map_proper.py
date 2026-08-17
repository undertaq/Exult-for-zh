"""
Generate bilingual_map.dat by parsing the ZH usecode's function table
and matching function IDs between English and Chinese usecode.
"""
import struct
import sys

def parse_zh_usecode(path):
    """Parse the YSCU custom format to extract function table entries."""
    with open(path, 'rb') as f:
        data = f.read()

    assert data[:4] == b'\xff\xff\xff\xff', 'Bad magic'
    assert data[4:8] == b'YSCU', 'Bad YSCU marker'

    count = struct.unpack_from('<I', data, 8)[0]
    entries = []

    pos = 16  # After header
    while pos + 4 <= len(data) and data[pos:pos+4] == b'Func':
        str_start = pos + 4
        null_pos = data.index(b'\0', str_start)
        func_id_str = data[str_start:null_pos].decode('ascii')
        func_id = int(func_id_str, 16)
        flag = data[null_pos + 1]

        id1 = struct.unpack_from('<I', data, null_pos + 3)[0]
        if flag == 6:
            # 19-byte entries: flag(1) + pad(1) + id(4) + id2(4)
            id2 = struct.unpack_from('<I', data, null_pos + 7)[0]
            entry_size = null_pos + 11 - pos
        elif flag in (1, 7):
            # 15-byte entries: flag(1) + pad(1) + id(4)  (no duplicate)
            id2 = id1
            entry_size = null_pos + 7 - pos
        else:
            print(f'  Unknown flag {flag} at pos {pos}', file=sys.stderr)
            id2 = id1
            entry_size = null_pos + 7 - pos

        entries.append((func_id, id1, id2))

        pos += entry_size

    print(f'  Parsed {len(entries)} entries from ZH usecode', file=sys.stderr)
    return entries


def get_en_function_ids(path):
    """Extract function IDs from standard Exult usecode."""
    with open(path, 'rb') as f:
        data = f.read()

    pos = 0
    fids = []
    while pos + 4 <= len(data):
        id16 = struct.unpack_from('<H', data, pos)[0]
        if id16 == 0xfffe:
            extended_id = struct.unpack_from('<i', data, pos + 2)[0]
            extended_len = struct.unpack_from('<I', data, pos + 6)[0]
            fids.append(extended_id)
            pos += 10 + extended_len
        elif id16 == 0xffff:
            id16_2 = struct.unpack_from('<H', data, pos + 2)[0]
            extended_len = struct.unpack_from('<I', data, pos + 4)[0]
            fids.append(id16_2)
            pos += 8 + extended_len
        elif id16 == 0:
            break
        else:
            fun_len = struct.unpack_from('<H', data, pos + 2)[0]
            fids.append(id16)
            pos += 4 + fun_len

    return fids


def main():
    en_path = 'D:/Project/Ultima_7/STATIC/usecode'
    zh_path = 'D:/Project/Ultima_7/patch/usecode.zh'
    map_path = 'D:/Project/Ultima_7/patch/voice_acting/bilingual_map.dat'

    print('Parsing ZH usecode function table...', file=sys.stderr)
    zh_entries = parse_zh_usecode(zh_path)
    print(f'ZH entries: {len(zh_entries)}', file=sys.stderr)

    en_fids = get_en_function_ids(en_path)
    print(f'EN functions: {len(en_fids)}', file=sys.stderr)

    # Build ZH lookup by function ID
    zh_by_id = {fid: (fid, '0', 0, fid, '0') for fid, _, _ in zh_entries}
    en_set = set(en_fids)

    # Find common function IDs
    common = sorted(set(zh_by_id.keys()) & en_set)
    print(f'Common functions: {len(common)}', file=sys.stderr)

    # Generate mappings — simple 1:1 function-level mapping
    mappings = []
    for fid in common:
        zh_entry = zh_by_id[fid]
        mappings.append(zh_entry)

    # Write BLMP
    with open(map_path, 'wb') as f:
        f.write(b'BLMP')
        f.write(struct.pack('<I', len(mappings)))
        for zh_fid, zh_key, zh_seg, en_fid, en_key in mappings:
            f.write(struct.pack('<i', zh_fid))
            f.write(zh_key.encode('utf-8') + b'\0')
            f.write(struct.pack('<H', zh_seg))
            f.write(struct.pack('<i', en_fid))
            f.write(en_key.encode('utf-8') + b'\0')

    print(f'Written {len(mappings)} mappings to {map_path}', file=sys.stderr)


if __name__ == '__main__':
    main()
