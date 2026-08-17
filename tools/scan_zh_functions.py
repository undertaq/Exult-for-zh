"""
Scan the ZH usecode file for valid function records after the YSCU header.
"""
import struct

with open('D:/Project/Ultima_7/patch/usecode.zh', 'rb') as f:
    data = f.read()

total_size = len(data)

# Start after YSCU table at 0x26E9
pos = 0x26E9
real_fids = set()
too_large = 0
total_found = 0
garbage = 0

while pos + 4 <= total_size:
    id16 = struct.unpack_from('<H', data, pos)[0]
    if id16 == 0:
        pos += 1
        continue
    if id16 == 0xfffe:
        ext_id = struct.unpack_from('<i', data, pos + 2)[0]
        ext_len = struct.unpack_from('<I', data, pos + 6)[0]
        real_fids.add(ext_id)
        total_found += 1
        pos += 10 + ext_len
    elif id16 == 0xffff:
        id16_2 = struct.unpack_from('<H', data, pos + 2)[0]
        ext_len = struct.unpack_from('<I', data, pos + 4)[0]
        real_fids.add(id16_2)
        total_found += 1
        pos += 8 + ext_len
    else:
        length = struct.unpack_from('<H', data, pos + 2)[0]
        if length >= 50000:
            garbage += 1
            pos += 2
            continue
        real_fids.add(id16)
        total_found += 1
        pos += 4 + length

print(f'Total positions parsed: {total_found}')
print(f'Garbage (len>=50000) skipped: {garbage}')
print(f'Unique function IDs: {len(real_fids)}')
print()
print('IDs < 0x100 (standard functions):')
standard = sorted(f for f in real_fids if f < 0x100)
print(f'  Count: {len(standard)}')
print(f'  Range: 0x{min(standard):04X} - 0x{max(standard):04X}')
print()
print('IDs 0x100-0xFFF (common):')
common = sorted(f for f in real_fids if 0x100 <= f < 0x1000)
print(f'  Count: {len(common)}')
if common:
    print(f'  Range: 0x{min(common):04X} - 0x{max(common):04X}')

print()
print('IDs >= 0x1000 (extended/large):')
large = sorted(f for f in real_fids if f >= 0x1000)
print(f'  Count: {len(large)}')
if large:
    print(f'  Range: 0x{min(large):04X} - 0x{max(large):04X}')
    print(f'  Sample: {[hex(f) for f in large[:10]]}')

print()
# Compare with English usecode
print('Reading English usecode function IDs...')
with open('D:/Project/Ultima_7/STATIC/usecode', 'rb') as f:
    en_data = f.read()

en_fids = set()
pos = 0
while pos + 4 <= len(en_data):
    id16 = struct.unpack_from('<H', en_data, pos)[0]
    if id16 == 0:
        pos += 1
        continue
    if id16 == 0xfffe:
        ext_id = struct.unpack_from('<i', en_data, pos + 2)[0]
        ext_len = struct.unpack_from('<I', en_data, pos + 6)[0]
        en_fids.add(ext_id)
        pos += 10 + ext_len
    elif id16 == 0xffff:
        id16_2 = struct.unpack_from('<H', en_data, pos + 2)[0]
        ext_len = struct.unpack_from('<I', en_data, pos + 4)[0]
        en_fids.add(id16_2)
        pos += 8 + ext_len
    else:
        length = struct.unpack_from('<H', en_data, pos + 2)[0]
        if length >= 50000:
            pos += 2
            continue
        en_fids.add(id16)
        pos += 4 + length

print(f'EN functions: {len(en_fids)}')
common_ids = real_fids & en_fids
zh_only = real_fids - en_fids
en_only = en_fids - real_fids
print(f'Common functions: {len(common_ids)}')
print(f'ZH-only IDs: {len(zh_only)}')
if zh_only:
    print(f'  Sample: {sorted(zh_only)[:10]}')
print(f'EN-only IDs: {len(en_only)} (expected if ZH has subset)')
