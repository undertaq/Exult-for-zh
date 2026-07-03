#!/bin/bash
# One-command pipeline: regenerate bilingual_map.dat from EN and ZH usecode
# Usage: bash tools/generate_all.sh

set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

EN_USECODE="D:/Project/Ultima_7/STATIC/usecode"
ZH_USECODE="D:/Project/Ultima_7/patch/usecode.zh"
ZH_EXTRACTED="D:/Project/Ultima_7/patch/usecode_standard.bin"
MAP_OUT="D:/Project/Ultima_7/patch/voice_acting/bilingual_map.dat"

echo "=== Step 1: Extract standard usecode from ZH file ==="
python tools/extract_zh_usecode2.py

echo "=== Step 2: Disassemble EN usecode to CSV ==="
python tools/voice_acting/disassemble_usecode.py "$EN_USECODE" --all --format csv > en_voice_lines.csv

echo "=== Step 3: Disassemble ZH usecode to CSV ==="
python tools/voice_acting/disassemble_usecode.py "$ZH_EXTRACTED" --all --format csv > zh_voice_lines.csv

echo "=== Step 4: Generate offset mapping ==="
python tools/voice_acting/generate_offset_mapping.py --en en_voice_lines.csv --zh zh_voice_lines.csv -o offset_mapping.csv

echo "=== Step 5: Convert to BLMP binary ==="
python tools/csv_to_blmp.py

echo "=== Cleanup temporary files ==="
rm -f en_voice_lines.csv zh_voice_lines.csv offset_mapping.csv

echo "=== Done! ==="
ls -la "$MAP_OUT"
