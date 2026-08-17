# Voice Packing System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a packing tool and game engine integration to pack ~13K .ogg voice files per language into a single .pak + .idx archive pair, with development-mode fallback to separate files.

**Architecture:** Two independent halves sharing the same binary format: a Python CLI tool (`pack_voice.py`) for packing/unpacking/verifying archives, and C++ changes to `VoiceActingManager` for loading archive data at game runtime. The .pak is a simple concatenation of .ogg files sorted by filename; the .idx is a sorted binary index mapping filename → offset + size.

**Tech Stack:** Python 3 (struct, pathlib), C++17 (std::ifstream, std::lower_bound)

---

### Task 1: Packing Tool — Core Index/Entry Types

**Files:**
- Create: `tools/voice_acting/pack_voice.py`

- [ ] **Step 1: Write and verify the struct definitions**

```python
import struct
import json
from pathlib import Path
from typing import Optional

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


def read_idx(path: Path) -> list[IndexEntry]:
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


def write_idx(path: Path, entries: list[IndexEntry]):
    buf = bytearray()
    buf += IDX_MAGIC
    buf += struct.pack('<II', IDX_VERSION, len(entries))
    for e in entries:
        buf += e.to_bytes()
    path.write_bytes(bytes(buf))
```

Add these at the top of the script and run a quick sanity check:
```bash
cd tools/voice_acting && python3 -c "
import pack_voice
e = pack_voice.IndexEntry('009a_12df_0_npc286', 1024, 65536)
data = e.to_bytes()
e2, _ = pack_voice.IndexEntry.from_bytes(data, 0)
assert e.name == e2.name
assert e.offset == e2.offset
assert e.size == e2.size
print('IndexEntry round-trip OK')
"
```
Expected: `IndexEntry round-trip OK`

- [ ] **Step 2: Commit**

```bash
git add tools/voice_acting/pack_voice.py
git commit -m "feat(voice): add voice packing tool with IndexEntry and idx read/write"
```

---

### Task 2: Packing Tool — Pack Mode

**Files:**
- Modify: `tools/voice_acting/pack_voice.py`

- [ ] **Step 1: Add `cmd_pack` function**

```python
import os
import sys

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
            name = ogg_path.stem  # filename without .ogg
            entries.append(IndexEntry(name, offset, len(data)))
            pak.write(data)
            offset += len(data)

    # Validate: no duplicate names
    names = [e.name for e in entries]
    if len(names) != len(set(names)):
        dupes = [n for n in names if names.count(n) > 1]
        raise ValueError(f'Duplicate filenames in {lang}: {sorted(set(dupes))}')

    # Validate: offset chain is contiguous
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
```

- [ ] **Step 2: Add CLI arg parsing**

```python
def main():
    import argparse
    parser = argparse.ArgumentParser(description='Voice packer for Exult')
    parser.add_argument('mode', choices=['pack', 'unpack', 'verify'])
    parser.add_argument('--lang', choices=['en', 'zh', 'all'], default='all')
    parser.add_argument('--source-dir', type=Path, default=None)
    parser.add_argument('--output-dir', type=Path, default=None)
    args = parser.parse_args()

    langs = ['en', 'zh'] if args.lang == 'all' else [args.lang]

    for lang in langs:
        source_dir = args.source_dir or Path(__file__).resolve().parent.parent.parent / 'voice' / lang
        output_dir = args.output_dir or Path(__file__).resolve().parent.parent.parent / 'voice'
        if args.mode == 'pack':
            cmd_pack(lang, source_dir, output_dir)
        elif args.mode == 'unpack':
            cmd_unpack(lang, output_dir, source_dir)
        elif args.mode == 'verify':
            cmd_verify(lang, output_dir)


if __name__ == '__main__':
    main()
```

- [ ] **Step 3: Test pack mode on a subset**

```bash
mkdir -p /tmp/voice_test/en /tmp/voice_test/zh
# create dummy ogg files (minimal valid ogg is fine, or just empty files for testing)
touch /tmp/voice_test/en/0001_0_0.ogg /tmp/voice_test/en/0002_0_0_npc1.ogg
touch /tmp/voice_test/zh/0001_0_0.ogg /tmp/voice_test/zh/0002_0_0_npc1.ogg

cd tools/voice_acting && python3 pack_voice.py pack --lang all --source-dir /tmp/voice_test/en --output-dir /tmp/voice_test
```
Expected: packs 2 files each and writes .pak + .idx

- [ ] **Step 4: Commit**

```bash
git add tools/voice_acting/pack_voice.py
git commit -m "feat(voice): add pack subcommand to voice packer"
```

---

### Task 3: Packing Tool — Unpack Mode

**Files:**
- Modify: `tools/voice_acting/pack_voice.py`

- [ ] **Step 1: Add `cmd_unpack` function**

```python
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
```

- [ ] **Step 2: Test unpack**

```bash
mkdir -p /tmp/voice_test/en_out
cd tools/voice_acting && python3 pack_voice.py unpack --lang en --source-dir /tmp/voice_test --output-dir /tmp/voice_test/en_out
ls /tmp/voice_test/en_out/
```
Expected: `0001_0_0.ogg 0002_0_0_npc1.ogg`

- [ ] **Step 3: Verify round-trip integrity**

```bash
cd tools/voice_acting && python3 -c "
import pack_voice
en = pack_voice.read_idx(Path('/tmp/voice_test/en_voices.idx'))
assert len(en) == 2
en2 = pack_voice.read_idx(Path('/tmp/voice_test/en_voices.idx'))
# unpack again to ensure it's idempotent
import subprocess
subprocess.run(['python3', 'pack_voice.py', 'unpack', '--lang', 'en', '--source-dir', '/tmp/voice_test', '--output-dir', '/tmp/voice_test/en_out2'], check=True)
print('Round-trip OK')
"
```

- [ ] **Step 4: Commit**

```bash
git add tools/voice_acting/pack_voice.py
git commit -m "feat(voice): add unpack subcommand to voice packer"
```

---

### Task 4: Packing Tool — Verify Mode

**Files:**
- Modify: `tools/voice_acting/pack_voice.py`

- [ ] **Step 1: Add `cmd_verify` function**

```python
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
        # Check for OGG magic bytes
        if not data.startswith(b'OggS'):
            print(f'WARNING [{i}]: {e.name} missing OGG magic ({data[:8].hex()})')
            errors += 1

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
    exit_code = 0

    for lang in langs:
        source_dir = args.source_dir or (base / 'voice')
        output_dir = args.output_dir or (base / 'voice' / lang)
        if args.mode == 'pack':
            cmd_pack(lang, args.source_dir or base / 'voice' / lang, args.output_dir or base / 'voice')
        elif args.mode == 'unpack':
            cmd_unpack(lang, args.source_dir or base / 'voice', args.output_dir or base / 'voice' / lang)
        elif args.mode == 'verify':
            ec = cmd_verify(lang, args.source_dir or base / 'voice')
            if ec:
                exit_code = ec

    sys.exit(exit_code)
```

- [ ] **Step 2: Test verify on dummy data**

```bash
cd tools/voice_acting && python3 pack_voice.py verify --lang en --source-dir /tmp/voice_test
```
Expected: `Verified en: 2 entries, 0 bytes — all OK`

- [ ] **Step 3: Test verify on actual voice files** (if real .ogg files exist)

```bash
cd tools/voice_acting && python3 pack_voice.py pack --lang en
cd tools/voice_acting && python3 pack_voice.py verify --lang en
```
Expected: Packs the real en voices and verifies them.

- [ ] **Step 4: Commit**

```bash
git add tools/voice_acting/pack_voice.py
git commit -m "feat(voice): add verify subcommand to voice packer"
```

---

### Task 5: Game Engine — Header Updates

**Files:**
- Modify: `audio/VoiceActingManager.h`
- Modify: `audio/VoiceActingManager.cc`

The `VoiceActingManager` is entirely **static**. Packed archive data needs static members and a static helper.

- [ ] **Step 1: Add includes and struct to the header**

After `#include <fstream>` and `#include <string>`, add:
```cpp
#include <cstdint>
#include <vector>
```

In the class, in the `private:` section, add:

```cpp
struct VoicePackedEntry {
    std::string name;     // filename without ".ogg", e.g. "009a_12df_0_npc286"
    uint64_t    offset;   // byte offset in .pak
    uint32_t    size;     // byte count
};

static bool         use_packed;
static std::string  pak_path;
static std::string  idx_path;
static std::vector<VoicePackedEntry> index;
static std::ifstream pak_stream;

static void load_packed_index();
static bool find_in_pak(const std::string& name, std::vector<char>& out_data);
```

Add to the static member declarations at line 79-84 (after the existing static members):

```cpp
static bool         use_packed;
static std::string  pak_path;
static std::string  idx_path;
static std::vector<VoiceActingManager::VoicePackedEntry> index;
static std::ifstream pak_stream;
```

- [ ] **Step 2: Commit**

```bash
git add audio/VoiceActingManager.h
git commit -m "feat(voice): add packed archive static members to VoiceActingManager"
```

---

### Task 6: Game Engine — Static Members Definition

**Files:**
- Modify: `audio/VoiceActingManager.cc`

- [ ] **Step 1: Add static member definitions**

After the existing static member definitions at line 39-46:

```cpp
// Packed voice archive static members.
bool                                         VoiceActingManager::use_packed = false;
std::string                                  VoiceActingManager::pak_path;
std::string                                  VoiceActingManager::idx_path;
std::vector<VoiceActingManager::VoicePackedEntry> VoiceActingManager::index;
std::ifstream                                VoiceActingManager::pak_stream;
```

- [ ] **Step 2: Commit**

```bash
git add audio/VoiceActingManager.cc
git commit -m "feat(voice): define static members for packed archive"
```

---

### Task 7: Game Engine — Index Loading and Init Logic

**Files:**
- Modify: `audio/VoiceActingManager.cc`

- [ ] **Step 1: Add `load_packed_index` implementation**

Add this free function (since all members are static, it doesn't need to be a method — but we declared it as a static method, so implement it as such). Place it after the `find_voice_file` function:

```cpp
/*
 *  Load the packed voice archive index for the given language.
 *  Called once during init. Returns true if .idx + .pak were loaded.
 */
void VoiceActingManager::load_packed_index() {
    const std::string& lang   = get_voice_language();
    const std::string  base   = get_system_path("<PATCH>/voice_acting/");
    pak_path = base + lang + "_voices.pak";
    idx_path = base + lang + "_voices.idx";

    // Check both files exist
    std::ifstream idx_file(idx_path, std::ios::binary);
    if (!idx_file.is_open()) {
        return;
    }
    std::ifstream pak_test(pak_path, std::ios::binary);
    if (!pak_test.is_open()) {
        idx_file.close();
        return;
    }
    pak_stream.open(pak_path, std::ios::binary);
    if (!pak_stream.is_open()) {
        idx_file.close();
        return;
    }

    // Read entire .idx into memory
    idx_file.seekg(0, std::ios::end);
    std::streamsize idx_size = idx_file.tellg();
    idx_file.seekg(0, std::ios::beg);
    std::vector<char> idx_buf(static_cast<size_t>(idx_size));
    if (!idx_file.read(idx_buf.data(), idx_size)) {
        idx_file.close();
        pak_stream.close();
        return;
    }
    idx_file.close();

    // Parse header: magic(4) + version(4) + count(4)
    const char* p = idx_buf.data();
    if (idx_size < 12 || std::memcmp(p, "VAIX", 4) != 0) {
        pak_stream.close();
        return;
    }
    uint32_t version;
    uint32_t count;
    std::memcpy(&version, p + 4, 4);
    std::memcpy(&count, p + 8, 4);
    // Note: little-endian format; on big-endian platforms, byte-swap.
    if (version != 1) {
        pak_stream.close();
        return;
    }

    // Parse entries
    index.clear();
    index.reserve(count);
    size_t pos = 12;
    for (uint32_t i = 0; i < count; i++) {
        if (pos + 2 > static_cast<size_t>(idx_size)) break;
        uint16_t name_len;
        std::memcpy(&name_len, p + pos, 2);
        pos += 2;
        if (pos + name_len + 12 > static_cast<size_t>(idx_size)) break;
        std::string name(p + pos, name_len);
        pos += name_len;
        VoicePackedEntry entry;
        entry.name = std::move(name);
        std::memcpy(&entry.offset, p + pos, 8);
        std::memcpy(&entry.size, p + pos + 8, 4);
        pos += 12;
        index.push_back(std::move(entry));
    }

    use_packed = true;
}
```

- [ ] **Step 2: Call `load_packed_index` from `init()`**

Modify `VoiceActingManager::init()` to load the index after reading config:

```cpp
void VoiceActingManager::init() {
    string s;
    config->value("config/audio/speech/voice/enabled", s, "yes");
    voice_enabled = (s != "no");
    config->set("config/audio/speech/voice/enabled", voice_enabled ? "yes" : "no", false);

    config->value("config/audio/speech/voice/language", voice_language, "");
    if (voice_language.empty()) {
        config->value("config/gameplay/language", voice_language, "zh");
    }
    config->set("config/audio/speech/voice/language", voice_language, false);

    // Try loading packed voice archive.
    load_packed_index();
    if (use_packed) {
        pout << "[VoiceActing] Loaded packed archive: " << pak_path
             << " (" << index.size() << " entries)" << std::endl;
    } else {
        pout << "[VoiceActing] No packed archive found, using separate files"
             << std::endl;
    }
}
```

- [ ] **Step 3: Commit**

```bash
git add audio/VoiceActingManager.cc
git commit -m "feat(voice): add load_packed_index and integrate into init"
```

---

### Task 8: Game Engine — Integrate Packed Lookup into play_for_conversation

**Files:**
- Modify: `audio/VoiceActingManager.cc`

The current flow in `play_for_conversation` (lines 280-385):
1. Build `base` = `<funcID>_<offsetKey>_<segment>`
2. Try avatar-specific filename → `find_voice_file` → `try_play(path)`
3. Try NPC-specific filename → `find_voice_file` → `try_play(path)`
4. Try generic filename → `find_voice_file` → `try_play(path)`
5. Log entry

In packed mode, we need to intercept at each level: try packed first, and only fall through to `find_voice_file` if packed lookup fails.

- [ ] **Step 1: Add `find_in_pak` implementation**

Place this after `load_packed_index`:

```cpp
/*
 *  Look up a voice file by name in the packed archive.
 *  Returns true and fills out_data if found.
 */
bool VoiceActingManager::find_in_pak(
        const std::string& name, std::vector<char>& out_data) {
    // Binary search on sorted index
    auto it = std::lower_bound(index.begin(), index.end(), name,
        [](const VoicePackedEntry& e, const std::string& n) {
            return e.name < n;
        });
    if (it == index.end() || it->name != name) {
        return false;
    }

    // Seek and read from the open pak stream
    pak_stream.seekg(static_cast<std::streamoff>(it->offset), std::ios::beg);
    if (!pak_stream) {
        return false;
    }
    out_data.resize(it->size);
    pak_stream.read(out_data.data(), static_cast<std::streamsize>(it->size));
    if (!pak_stream) {
        return false;
    }
    return true;
}
```

- [ ] **Step 2: Add `try_play_data` — play voice from in-memory data**

Since the current `try_play` takes a file path and `audio->play_voice_file` also takes a path, we need to write the packed data to a temp file and play it. Add this helper:

```cpp
/*
 *  Play voice from a packed archive entry.
 *  Extracts data to a temp file and plays it, so we don't need
 *  to modify the Audio API. The temp file is created in the
 *  voice directory and removed after playback.
 */
static bool try_play_packed(const std::string& name, const std::vector<char>& data) {
    const std::string& lang = VoiceActingManager::get_voice_language();
    std::string temp_path = get_system_path(
        "<PATCH>/voice_acting/" + lang + "/." + name + ".ogg");
    // Ensure parent directory exists
    std::string dir = temp_path.substr(0, temp_path.find_last_of("/\\"));
    std::string cmd = "mkdir -p " + dir;
    // Use U7mkdir or equivalent if available; for now use get_system_path
    // and write directly
    std::ofstream out(temp_path, std::ios::binary);
    if (!out.is_open()) {
        return false;
    }
    out.write(data.data(), static_cast<std::streamsize>(data.size()));
    out.close();

    bool played = VoiceActingManager::try_play(temp_path);
    std::remove(temp_path.c_str());
    return played;
}
```

- [ ] **Step 3: Modify `play_for_conversation` to try packed first**

Replace the existing avatar/NPC/generic try blocks. The key change: at each candidate level, try `find_in_pak` before `find_voice_file`.

In the `play_for_conversation` function, after the cross-language lookup block (after line 323), add a packed-mode early path:

```cpp
    // ---- TRY PACKED ARCHIVE FIRST ----
    // Build all candidate names and try the packed archive before
    // falling back to separate files.
    if (use_packed) {
        std::vector<std::string> candidates;
        if (avatar_speaker) {
            candidates.push_back(base + get_avatar_voice_suffix());
        }
        if (speaker_npc != 0) {
            char npc_suffix[16];
            std::snprintf(npc_suffix, sizeof(npc_suffix), "_npc%d", speaker_abs);
            candidates.push_back(base + npc_suffix);
        }
        candidates.push_back(base);  // generic fallback

        for (const auto& candidate : candidates) {
            std::vector<char> pak_data;
            if (find_in_pak(candidate, pak_data)) {
                bool played = try_play_packed(candidate, pak_data);
                string status;
                if (played) {
                    status = "played";
                } else {
                    status = "error";
                }
                // Log with the candidate name (without extension for consistency)
                log_entry(candidate + ".ogg", pak_path, function_id,
                          offset_key, segment, text, status,
                          speaker_npc, caller_npc);
                return played;
            }
        }
        // Packed lookup failed for all candidates — fall through to file search
    }
    // ---- END PACKED ARCHIVE PATH ----
```

This block goes right before the existing `// Try NPC-specific file first` section (line 325).

- [ ] **Step 4: Commit**

```bash
git add audio/VoiceActingManager.cc
git commit -m "feat(voice): integrate packed lookup into play_for_conversation"
```

### Task 9: Pack Real Voice Files

**Files:**
- Run: pack voice files for both languages

- [ ] **Step 1: Pack English voice files**

```bash
cd tools/voice_acting && python3 pack_voice.py pack --lang en --source-dir ../../voice/en --output-dir ../../voice
```

Expected: `voice/en_voices.pak` + `voice/en_voices.idx` created

- [ ] **Step 2: Pack Chinese voice files**

```bash
cd tools/voice_acting && python3 pack_voice.py pack --lang zh --source-dir ../../voice/zh --output-dir ../../voice
```

Expected: `voice/zh_voices.pak` + `voice/zh_voices.idx` created

- [ ] **Step 3: Verify both archives**

```bash
cd tools/voice_acting && python3 pack_voice.py verify --lang all
```

Expected: "Verified en: X entries, Y bytes — all OK" + "Verified zh: X entries, Y bytes — all OK"

- [ ] **Step 4: Commit**

```bash
git add voice/en_voices.pak voice/en_voices.idx voice/zh_voices.pak voice/zh_voices.idx
git commit -m "feat(voice): add packed voice archives for en and zh"
```
