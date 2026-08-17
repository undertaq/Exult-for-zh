#!/bin/bash
# One-command pipeline: regenerate bilingual_map.dat from reviewed mappings
# Usage: bash tools/generate_all.sh

set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

REVIEW_JSON="${REVIEW_JSON:-tools/voice_acting/bilingual_mapping_review.json}"
LOCAL_MAP="${LOCAL_MAP:-voice/bilingual_map.dat}"
MAP_OUT="${MAP_OUT:-/home/joe/project/Ultima_7/patch/voice_acting/bilingual_map.dat}"
PYTHON="${PYTHON:-python3}"

echo "=== Generate canonical BLMP from reviewed mapping JSON ==="
"$PYTHON" tools/voice_acting/generate_bilingual_map.py \
    --input "$REVIEW_JSON" \
    --output "$LOCAL_MAP"

echo "=== Copy BLMP to patch voice_acting directory ==="
mkdir -p "$(dirname "$MAP_OUT")"
cp -p "$LOCAL_MAP" "$MAP_OUT"

echo "=== Done! ==="
ls -la "$MAP_OUT"
