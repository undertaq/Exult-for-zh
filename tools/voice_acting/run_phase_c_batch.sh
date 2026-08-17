#!/bin/bash
# Run Phase C in batches to work around process crashes
# Usage: ./run_phase_c_batch.sh [start_index] [batch_size]
set -e
cd /home/joe/project/Exult-for-zh

# Get NPC list from the module
NPC_LIST=$(python3 -c "
import sys; sys.path.insert(0, 'tools/voice_acting')
from npc_data import NPC_NUMBERS
all_npcs = sorted(NPC_NUMBERS.keys(), key=lambda x: (x.lower() if x else ''))
print('\n'.join(all_npcs))
")

mapfile -t NPC_NAMES <<< "$NPC_LIST"
TOTAL=${#NPC_NAMES[@]}
START=${1:-0}
BATCH=${2:-10}
END=$((START + BATCH))
[ $END -gt $TOTAL ] && END=$TOTAL

echo "Processing NPCs $START to $END (of $TOTAL)"
for i in $(seq $START $((END-1))); do
    NPC="${NPC_NAMES[$i]}"
    echo "=== [$((i+1))/$TOTAL] Processing NPC: $NPC ==="
    VENV=~/project/qwen3-tts/.venv/bin/python
    timeout 600 $VENV -u tools/voice_acting/generate_qwen3_voice.py \
        --phase voice --device cuda:0 --npc "$NPC"
    RC=$?
    if [ $RC -ne 0 ]; then
        echo "=== NPC $NPC FAILED with exit code $RC ==="
    fi
done
echo "=== Batch $START-$((END-1)) complete ==="