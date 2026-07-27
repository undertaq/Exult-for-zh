import struct
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
