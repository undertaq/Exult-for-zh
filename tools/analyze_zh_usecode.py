import struct

with open('D:/Project/Ultima_7/patch/usecode.zh', 'rb') as f:
    data = f.read()

print('Size:', len(data))
print()
print('Full header (first 80 bytes):')
for i in range(0, 80, 16):
    chunk = data[i:i+16]
    hex_str = ' '.join(f'{b:02x}' for b in chunk)
    ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
    print(f'  {i:04x}: {hex_str:48s} {ascii_str}')

print()
print('Looking for Func markers...')
pos = 0
count = 0
while True:
    idx = data.find(b'Func', pos)
    if idx == -1:
        break
    print(f'  Func at 0x{idx:x} ({idx})')
    chunk = data[idx:idx+24]
    hex_str = ' '.join(f'{b:02x}' for b in chunk)
    ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
    print(f'    {hex_str:72s} {ascii_str}')
    pos = idx + 4
    count += 1
    if count >= 10:
        break

print(f'\nTotal Func markers found: {data.count(b"Func")}')
