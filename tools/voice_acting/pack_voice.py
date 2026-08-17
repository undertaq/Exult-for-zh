import struct
import sys
from pathlib import Path
from typing import List

IDX_MAGIC = b'VAIX'
IDX_VERSION = 1

class IndexEntry:
    __slots__ = ('name', 'offset', 'size')
    def __init__(self, name: str, offset: int = 0, size: int = 0):
        self.name = name       # filename without ".ogg", e.g. "009a_12df_0_npc286"
        self.offset = offset   # byte offset in .pak file
        self.size = size       # byte size of .ogg data

    @classmethod
    def from_bytes(cls, data: bytes, pos: int) -> tuple['IndexEntry', int]:
        name_len = struct.unpack_from('<H', data, pos)[0]
        pos += 2
        name = data[pos:pos + name_len].decode('ascii')
        pos += name_len
        offset, size = struct.unpack_from('<QI', data, pos)
        pos += 12  # 8 + 4
        return cls(name, offset, size), pos

    def to_bytes(self) -> bytes:
        name_bytes = self.name.encode('ascii')
        return (struct.pack('<H', len(name_bytes)) +
                name_bytes +
                struct.pack('<QI', self.offset, self.size))


def read_idx(path: Path) -> List[IndexEntry]:
    data = path.read_bytes()
    if data[:4] != IDX_MAGIC:
        raise ValueError(f'Bad magic in {path}')
    ver, count = struct.unpack_from('<II', data, 4)
    if ver != IDX_VERSION:
        raise ValueError(f'Unknown index version {ver}')
    entries = []
    pos = 12  # 4 + 4 + 4
    for _ in range(count):
        entry, pos = IndexEntry.from_bytes(data, pos)
        entries.append(entry)
    return entries


def write_idx(path: Path, entries: List[IndexEntry]):
    buf = bytearray()
    buf += IDX_MAGIC
    buf += struct.pack('<II', IDX_VERSION, len(entries))
    for e in entries:
        buf += e.to_bytes()
    path.write_bytes(bytes(buf))


def cmd_pack(lang: str, source_dir: Path, output_dir: Path):
    ogg_files = sorted(source_dir.glob('*.ogg'))
    if not ogg_files:
        print(f'No .ogg files found in {source_dir}')
        return

    entries = []
    offset = 0
    with (output_dir / f'{lang}_voices.pak').open('wb') as pak:
        for ogg_path in ogg_files:
            data = ogg_path.read_bytes()
            name = ogg_path.stem
            entries.append(IndexEntry(name, offset, len(data)))
            pak.write(data)
            offset += len(data)

    names = [e.name for e in entries]
    if len(names) != len(set(names)):
        dupes = [n for n in names if names.count(n) > 1]
        raise ValueError(f'Duplicate filenames in {lang}: {sorted(set(dupes))}')

    expected = 0
    for e in entries:
        assert e.offset == expected, f'Offset mismatch for {e.name}: expected {expected}, got {e.offset}'
        expected += e.size
    assert expected == offset, f'Pak size mismatch: {expected} vs {offset}'

    idx_path = output_dir / f'{lang}_voices.idx'
    write_idx(idx_path, entries)
    print(f'Packed {len(entries)} files into {output_dir}/{lang}_voices.pak and {idx_path.name}')
    print(f'  Pak size: {offset:,} bytes ({offset/1024/1024:.1f} MB)')
    print(f'  Index size: {idx_path.stat().st_size:,} bytes')


def cmd_unpack(lang: str, source_dir: Path, output_dir: Path):
    idx_path = source_dir / f'{lang}_voices.idx'
    pak_path = source_dir / f'{lang}_voices.pak'

    if not idx_path.exists() or not pak_path.exists():
        print(f'Missing {lang}_voices.idx or {lang}_voices.pak in {source_dir}')
        return

    entries = read_idx(idx_path)
    pak_data = pak_path.read_bytes()
    output_dir.mkdir(parents=True, exist_ok=True)

    for e in entries:
        data = pak_data[e.offset:e.offset + e.size]
        out_path = output_dir / f'{e.name}.ogg'
        out_path.write_bytes(data)

    print(f'Extracted {len(entries)} files to {output_dir}')


def cmd_verify(lang: str, data_dir: Path):
    idx_path = data_dir / f'{lang}_voices.idx'
    pak_path = data_dir / f'{lang}_voices.pak'

    if not idx_path.exists() or not pak_path.exists():
        print(f'Missing {lang}_voices.idx or {lang}_voices.pak in {data_dir}')
        return 1

    entries = read_idx(idx_path)
    pak_data = pak_path.read_bytes()
    errors = 0

    for i, e in enumerate(entries):
        if e.offset + e.size > len(pak_data):
            print(f'ERROR [{i}]: {e.name} overflows pak (offset={e.offset}, size={e.size}, pak_len={len(pak_data)})')
            errors += 1
            continue
        data = pak_data[e.offset:e.offset + e.size]
        if len(data) != e.size:
            print(f'ERROR [{i}]: {e.name} size mismatch (expected {e.size}, got {len(data)})')
            errors += 1
            continue
        if not data.startswith(b'OggS'):
            print(f'WARNING [{i}]: {e.name} missing OGG magic ({data[:8].hex()})')

    total_pak = len(pak_data)
    computed = sum(e.size for e in entries)
    if total_pak != computed:
        print(f'ERROR: pak size {total_pak} != sum of entries {computed}')
        errors += 1

    if errors == 0:
        print(f'Verified {lang}: {len(entries)} entries, {total_pak:,} bytes — all OK')
    else:
        print(f'Verified {lang}: {len(entries)} entries, {errors} error(s)')
    return errors


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Voice packer for Exult')
    parser.add_argument('mode', choices=['pack', 'unpack', 'verify'])
    parser.add_argument('--lang', choices=['en', 'zh', 'all'], default='all')
    parser.add_argument('--source-dir', type=Path, default=None)
    parser.add_argument('--output-dir', type=Path, default=None)
    args = parser.parse_args()

    base = Path(__file__).resolve().parent.parent.parent
    langs = ['en', 'zh'] if args.lang == 'all' else [args.lang]

    base_voice = base / 'voice'
    exit_code = 0
    for lang in langs:
        if args.mode == 'pack':
            src = args.source_dir or base_voice / lang
            out = args.output_dir or base_voice
            cmd_pack(lang, src, out)
        elif args.mode == 'unpack':
            src = args.source_dir or base_voice
            out = args.output_dir or base_voice / lang
            cmd_unpack(lang, src, out)
        elif args.mode == 'verify':
            src = args.source_dir or base_voice
            if cmd_verify(lang, src):
                exit_code = 1

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
