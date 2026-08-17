"""
Smart extractor: find real function records in the ZH file by
locating the first known function and parsing forward from there.
"""
import struct
import sys

def find_func_record(data, target_id, start=0):
    """Find a function record with the given ID in the data."""
    for i in range(start, len(data) - 4):
        id16 = struct.unpack_from('<H', data, i)[0]
        if id16 == target_id:
            # Check if next field is a reasonable length
            length = struct.unpack_from('<H', data, i + 2)[0]
            if 0 < length < 100000 and i + 4 + length <= len(data):
                return i
    return -1

zh_path = 'D:/Project/Ultima_7/patch/usecode.zh'
out_path = 'D:/Project/Ultima_7/patch/usecode_standard.bin'

with open(zh_path, 'rb') as f:
    data = f.read()

# First, skip the YSCU header and function table
# We know function 0x0096 is the first standard function
pos_0096 = find_func_record(data, 0x0096)
print(f'Function 0x0096 found at 0x{pos_0096:x}', file=sys.stderr)

# Verify by checking if 0x009A follows
pos_0096_len = struct.unpack_from('<H', data, pos_0096 + 2)[0]
expected_009a = pos_0096 + 4 + pos_0096_len
actual_009a = find_func_record(data, 0x009A, pos_0096 + 4)

if actual_009a == expected_009a:
    print(f'  Verified: 0x009A follows at 0x{expected_009a:x} ✓', file=sys.stderr)
    start_pos = pos_0096
else:
    print(f'  WARNING: Expected 0x009A at 0x{expected_009a:x}, found at 0x{actual_009a:x}', file=sys.stderr)
    # There might be a symbol table or other data between YSCU table and real functions
    # Let's still use the first 0x0096 position
    start_pos = pos_0096

print(f'Extracting from 0x{start_pos:x} to end ({len(data) - start_pos} bytes)', file=sys.stderr)

# Extract from start_pos onwards
bytecode = data[start_pos:]

# Verify: parse all functions to get count
pos = 0
real_fids = set()
total = 0
while pos + 4 <= len(bytecode):
    id16 = struct.unpack_from('<H', bytecode, pos)[0]
    if id16 == 0:
        pos += 1
        continue
    if id16 == 0xfffe:
        ext_id = struct.unpack_from('<i', bytecode, pos + 2)[0]
        ext_len = struct.unpack_from('<I', bytecode, pos + 6)[0]
        real_fids.add(ext_id)
        total += 1
        pos += 10 + ext_len
    elif id16 == 0xffff:
        id16_2 = struct.unpack_from('<H', bytecode, pos + 2)[0]
        ext_len = struct.unpack_from('<I', bytecode, pos + 4)[0]
        real_fids.add(id16_2)
        total += 1
        pos += 8 + ext_len
    else:
        length = struct.unpack_from('<H', bytecode, pos + 2)[0]
        # Sanity check for garbage data
        if length > 100000 or (length == 0 and id16 > 0xF0):
            # Might be garbage, skip ahead
            pos += 2
            continue
        real_fids.add(id16)
        total += 1
        pos += 4 + length
    if total % 100 == 0:
        pass

print(f'Parsed {total} function records', file=sys.stderr)
print(f'Unique IDs: {len(real_fids)}', file=sys.stderr)
print(f'Standard IDs: {len([f for f in real_fids if f < 0x100])}', file=sys.stderr)

with open(out_path, 'wb') as f:
    f.write(bytecode)

print(f'Written {len(bytecode)} bytes to {out_path}', file=sys.stderr)
