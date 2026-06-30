#!/usr/bin/env bash
# Process each NPC individually with timeout, so one hung NPC won't block
# the entire batch. Run from the project root.
set -e

SCRIPT="/home/joe/project/Exult-for-zh/tools/voice_acting/generate_qwen3_voice.py"
MAPPING="/home/joe/project/Exult-for-zh/tools/voice_acting/bilingual_mapping_review.json"
VENV="/home/joe/project/qwen3-tts/.venv/bin/python"
TIMEOUT=600  # 10 minutes per NPC
LOG="/home/joe/project/Exult-for-zh/voice/generation.log"

# Get NPC list from the JSON
NPCS=$("$VENV" -c "
import json
from collections import defaultdict
data = json.load(open('$MAPPING'))
by_npc = defaultdict(list)
for e in data:
    npc = e.get('npc', '') or 'UNKNOWN'
    by_npc[npc].append(e)
for n in sorted(by_npc.keys()):
    print(f'{n} ({len(by_npc[n])})')
" 2>/dev/null)

TOTAL=$(echo "$NPCS" | wc -l)
DONE=0
FAILED=0

echo "Processing $TOTAL NPCs one at a time..."
echo "Started: $(date)" | tee -a "$LOG"
echo "========================================"

for NPC in $NPCS; do
    DONE=$((DONE + 1))
    echo "[$DONE/$TOTAL] NPC: '$NPC'"
    echo "[$(date)] [$DONE/$TOTAL] Starting NPC: '$NPC'" >> "$LOG"

    if PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True PYTHONUNBUFFERED=1 timeout "$TIMEOUT" \
        "$VENV" -u "$SCRIPT" --npc "$NPC" --resume >> "$LOG" 2>&1; then
        echo "  OK" | tee -a "$LOG"
    else
        EXIT_CODE=$?
        echo "  FAILED (exit=$EXIT_CODE)" | tee -a "$LOG"
        FAILED=$((FAILED + 1))
    fi

    echo "  ---" >> "$LOG"
done

echo "========================================"
echo "Finished: $(date)"
echo "OK: $((TOTAL - FAILED))/$TOTAL, Failed: $FAILED"
