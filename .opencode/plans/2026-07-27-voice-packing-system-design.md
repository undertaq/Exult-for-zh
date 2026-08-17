# Voice Packing System

## Problem

~13K `.ogg` voice files per language = ~26K inodes and filesystem overhead. Distribution, installation, and file I/O are slower with thousands of small files. Game needs a packed archive format for release builds while keeping development workflows unchanged.

## Design

Two packed archives per language placed in `<PATCH>/voice_acting/`:

| Language | Packed file | Index file |
|----------|------------|------------|
| English  | `en_voices.pak` | `en_voices.idx` |
| Chinese  | `zh_voices.pak` | `zh_voices.idx` |

- **Development**: separate `.ogg` files in `voice/en/` and `voice/zh/` (unchanged)
- **Release**: `.pak` + `.idx` files at `voice/` level; game falls back to separate files if packed not found
- **No mixed mode**: the game either uses the packed archive or separate files — never both simultaneously

### Packed Archive Format (`.pak`)

Simple byte-level concatenation of all `.ogg` files sorted by filename ascending (case-insensitive). No headers, no alignment padding, no compression (OGG is already compressed).

```
[pak file]
+-------------------+
| .ogg file #1      |  ← sorted by filename, e.g. "0001_0_0.ogg"
+-------------------+
| .ogg file #2      |  ← e.g. "0001_0_0_npc1.ogg"
+-------------------+
| ...               |
+-------------------+
| .ogg file #N      |
+-------------------+
```

Offset of each file = cumulative byte position from start of file.

### Index File Format (`.idx`)

Binary, sorted, loaded at game startup:

```
[idx file header]
+----------------------------+
| magic: "VAIX" (4 bytes)    |
| version: uint32 LE (1)     |
| entry_count: uint32 LE     |
+----------------------------+
| entry[0]:                   |
|   name_len: uint16 LE      |  filename excluding ".ogg" extension
|   name: char[name_len]     |  e.g. "009a_12df_0_npc286"
|   offset: uint64 LE        |  byte offset in .pak
|   size: uint32 LE          |  byte size of .ogg data
+----------------------------+
| entry[1]: ...              |
+----------------------------+
```

- Entries are sorted by `name` (matching `.pak` order) for O(log N) binary search
- Approximate size: 13K entries × ~34 bytes avg = ~450KB
- Multi-byte values are little-endian

### Tool: `tools/voice_acting/pack_voice.py`

Three subcommands:

**`pack`** — scans a voice directory, produces `.pak` + `.idx`:
```
python pack_voice.py pack --lang en
python pack_voice.py pack --lang zh
```
- Reads all `*.ogg` files from `voice/{lang}/`
- Sorts by filename ascending
- Writes `voice/{lang}_voices.pak` and `voice/{lang}_voices.idx`
- Validates: every file in source directory has a matching index entry; total bytes match

**`unpack`** — extracts `.pak` back into individual files:
```
python pack_voice.py unpack --lang en
```
- Reads `.idx`, extracts each entry from `.pak`
- Writes to `voice/{lang}/` (overwriting)
- Validates every file extracts correctly

**`verify`** — checks integrity of a `.pak` + `.idx` pair:
```
python pack_voice.py verify --lang en
```
- Reads `.idx`, seeks+reads each entry from `.pak`
- Confirms valid OGG headers for each entry
- Reports count, total size, any errors

Common options:
- `--lang {en,zh,all}` — target language (default: `all`)
- `--source-dir` — override voice source directory (default: `voice/{lang}/`)
- `--output-dir` — override output directory (default: `voice/`)

### Game Engine Integration (C++)

In `VoiceActingManager.cc`, add packed-archive loading as an alternative to file-exists lookups.

**New members in `VoiceActingManager`:**

```cpp
struct VoicePackedEntry {
    std::string name;     // filename without ".ogg", e.g. "009a_12df_0_npc286"
    uint64_t offset;      // byte offset in .pak
    uint32_t size;        // byte size in .pak
};

bool    use_packed_;
std::string pak_path_;    // full path to en_voices.pak or zh_voices.pak
std::string idx_path_;    // full path to en_voices.idx or zh_voices.idx
std::vector<VoicePackedEntry> index_;
std::ifstream pak_stream_;  // kept open for seeks
```

**Init flow** (called once during language/voice init):
1. Construct `pak_path_` = `<PATCH>/voice_acting/<lang>_voices.pak`
2. Construct `idx_path_` = `<PATCH>/voice_acting/<lang>_voices.idx`
3. If both files exist:
   a. Parse `.idx` into `index_` vector
   b. Open `.pak` file handle for random-access reads
   c. Set `use_packed_ = true`
4. If either file missing → `use_packed_ = false`

**Voice play flow** (modified voice resolution):
1. Compute `base_name` as current code: `<funcID>_<offsetKey>_<segment>[_npc<N>]`
2. If `use_packed_`:
   a. Binary search `index_` for `base_name`
   b. If found → seek+read from `.pak`
   c. If not found → fall through to separate-file loading
3. If `!use_packed_` or packed lookup failed → original behavior

### Changes to Existing Files

| File | Changes |
|------|---------|
| `tools/voice_acting/pack_voice.py` | **New file** — the packing/unpacking/verify tool |
| `audio/VoiceActingManager.h` | Add `use_packed_`, `pak_path_`, `idx_path_`, `index_`, `pak_stream_` members |
| `audio/VoiceActingManager.cc` | Add init logic for loading `.idx`, modify voice play to try packed first |

### What Does NOT Change

- Filename computation logic
- NPC number mapping
- Bilingual fallback (try configured language → fall back to other)
- `voice/en/` and `voice/zh/` directory structure for development
- Audio decoding (still decodes OGG)

### Integrity Guarantees

- Pack tool validates: every source file has an index entry
- Pack tool validates: `.pak` byte count matches sum of all entry sizes
- Pack tool validates: index entries are sorted correctly
- Verify command validates: each entry reads valid OGG data
- Game skips packed mode quietly if files are missing (graceful degradation)
