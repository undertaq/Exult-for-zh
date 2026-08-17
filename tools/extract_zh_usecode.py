"""
Extract standard Exult usecode bytecode from the YSCU-wrappered ZH file.
The YSCU format has a function table header followed by standard usecode function records.
"""
import struct
import sys

def extract_standard_usecode(zh_path, output_path):
    with open(zh_path, 'rb') as f:
        data = f.read()

    assert data[:4] == b'\xff\xff\xff\xff', 'Bad magic'
    assert data[4:8] == b'YSCU', 'Bad YSCU marker'

    count = struct.unpack_from('<I', data, 8)[0]
    print(f'Expected entries: {count}', file=sys.stderr)

    # Parse the function table to find where it ends
    pos = 16  # After header
    parsed = 0
    while pos + 4 <= len(data) and data[pos:pos+4] == b'Func':
        str_start = pos + 4
        null_pos = data.index(b'\0', str_start)
        func_id_str = data[str_start:null_pos].decode('ascii')
        func_id = int(func_id_str, 16)
        flag = data[null_pos + 1]

        if flag == 6:
            entry_size = null_pos + 11 - pos  # 19 bytes
        elif flag in (1, 7):
            entry_size = null_pos + 7 - pos   # 15 bytes
        else:
            entry_size = null_pos + 7 - pos

        pos += entry_size
        parsed += 1

    print(f'Parsed {parsed} entries, table ends at offset 0x{pos:x} ({pos})', file=sys.stderr)

    # The remaining data from pos is standard usecode bytecode
    bytecode = data[pos:]

    # Verify: first few bytes should be valid usecode function records
    if len(bytecode) >= 4:
        id16 = struct.unpack_from('<H', bytecode, 0)[0]
        if id16 == 0xffff or id16 == 0xfffe:
            print(f'First function: extended format (0x{id16:04x})', file=sys.stderr)
        else:
            length = struct.unpack_from('<H', bytecode, 2)[0]
            print(f'First function: id=0x{id16:04x}, len={length}', file=sys.stderr)

    print(f'Bytecode size: {len(bytecode)} bytes', file=sys.stderr)

    with open(output_path, 'wb') as f:
        f.write(bytecode)

    print(f'Written to {output_path}', file=sys.stderr)
    return bytecode


if __name__ == '__main__':
    zh_path = 'D:/Project/Ultima_7/patch/usecode.zh'
    out_path = 'D:/Project/Ultima_7/patch/usecode_standard.bin'
    extract_standard_usecode(zh_path, out_path)
