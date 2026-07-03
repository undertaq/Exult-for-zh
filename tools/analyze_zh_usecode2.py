with open('D:/Project/Ultima_7/patch/usecode.zh', 'rb') as f:
    data = f.read()

# Parse ALL function table entries
pos = 16  # After header
entries = []
while pos + 4 <= len(data) and data[pos:pos+4] == b'Func':
    str_start = pos + 4
    null_pos = data.index(b'\0', str_start)
    func_id_str = data[str_start:null_pos].decode('ascii', errors='replace')
    func_id = int(func_id_str, 16)
    entry_end = null_pos + 11  # 1 (null) + 1 (flag) + 1 (pad?) + 4 (id1) + 4 (id2)
    entries.append((pos, func_id))
    pos = entry_end

print(f'Total entries parsed: {len(entries)}')
print(f'Table end at offset: 0x{pos:x} ({pos})')

print(f'\nSample entries:')
for i, (epos, fid) in enumerate(entries[:5]):
    print(f'  [{i}] at 0x{epos:x}: func 0x{fid:04X}')
print(f'  ...')
for i, (epos, fid) in enumerate(entries[-5:], len(entries)-5):
    print(f'  [{i}] at 0x{epos:x}: func 0x{fid:04X}')

print(f'\nFirst 32 bytes after table:')
chunk = data[pos:pos+32]
print(f'  {chunk.hex()}')
print(f'ASCII: ', end='')
for b in chunk:
    print(chr(b) if 32 <= b < 127 else '.', end='')
print()

# Look for the actual usecode data
if pos < len(data):
    v1 = int.from_bytes(data[pos:pos+4], 'little')
    v2 = int.from_bytes(data[pos+4:pos+8], 'little')
    print(f'\nFirst 4 bytes as int32: {v1} (0x{v1:x})')
    print(f'Bytes 4-8 as int32: {v2} (0x{v2:x})')
