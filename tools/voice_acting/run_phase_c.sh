#!/bin/bash
# Reliable Phase C runner - processes NPCs in small stable batches
# Runs ZH first, then EN (separate model loads to avoid CUDA hangs)

cd /home/joe/project/Exult-for-zh
VENV=~/project/qwen3-tts/.venv/bin/python
BATCH_SIZE=5
MAX_WAIT=600

# Write pending NPC lists to temp files using Python
python3 << 'PYEOF'
import sys; sys.path.insert(0, 'tools/voice_acting')
import json, os
from npc_data import NPC_NUMBERS

with open('tools/voice_acting/bilingual_mapping_review.json') as f:
    data = json.load(f)

all_npcs = sorted(NPC_NUMBERS.keys(), key=lambda x: (x.lower() if x else ''))

for lang in ['zh', 'en']:
    pending = []
    for npc in all_npcs:
        nn = NPC_NUMBERS[npc]
        has_missing = False
        for e in data:
            if e.get('npc','') != npc: continue
            t = (e.get(f'{lang}_text','') or '').strip()
            if not t: continue
            d = f'voice/{lang}'
            fid = (e.get(f'{lang}_func_id','') or '0000')
            okv = (e.get(f'{lang}_offset_key','') or '0')
            seg = e.get(f'{lang}_segment',0) or 0
            if isinstance(fid,str) and (fid.startswith('0x') or fid.startswith('0X')): fid=fid[2:]
            fid = str(fid).lower().zfill(4)
            p = os.path.join(d, f'{fid}_{okv}_{seg}_npc{nn}.ogg')
            if not os.path.exists(p):
                has_missing = True
                break
        if has_missing:
            pending.append(npc)
    with open(f'/tmp/pending_{lang}.txt', 'w') as f:
        f.write('\n'.join(pending))
    print(f"Pending {lang}: {len(pending)} NPCs")
PYEOF

run_batches() {
    local lang=$1
    local label=$2
    
    if [ ! -s /tmp/pending_${lang}.txt ]; then
        echo "No $label NPCs to process"
        return
    fi
    
    mapfile -t NAMES < /tmp/pending_${lang}.txt
    local TOTAL=${#NAMES[@]}
    echo ""
    echo "=============================================================="
    echo "PROCESSING $label ($TOTAL NPCs)"
    echo "=============================================================="
    
    local batch_num=0
    for ((i=0; i<TOTAL; i+=BATCH_SIZE)); do
        batch_num=$((batch_num+1))
        local end=$((i+BATCH_SIZE))
        [ $end -gt $TOTAL ] && end=$TOTAL
        local batch_npcs=("${NAMES[@]:i:$((end-i))}")
        
        echo ""
        echo "--- [$batch_num/$(( (TOTAL+BATCH_SIZE-1)/BATCH_SIZE ))] $label Batch: NPCs $i-$((end-1)) ---"
        echo "  ${batch_npcs[*]}"
        
        NPC_ARG=$(IFS=,; echo "${batch_npcs[*]}")
        
        local START_TIME=$(date +%s)
        $VENV -u tools/voice_acting/generate_qwen3_voice.py \
            --phase voice --device cuda:0 --lang "$lang" --npc "$NPC_ARG" \
            > /tmp/phase_c_out.log 2>/tmp/phase_c_err.log &
        CMD_PID=$!
        
        local last_lines=0
        while true; do
            if ! kill -0 $CMD_PID 2>/dev/null; then
                wait $CMD_PID
                local RC=$?
                echo "  Done (exit $RC)"
                break
            fi
            
            local curr_lines=$(wc -l < /tmp/phase_c_out.log 2>/dev/null || echo 0)
            local elapsed=$(( $(date +%s) - START_TIME ))
            
            if [ $elapsed -gt $MAX_WAIT ] && [ $curr_lines -eq $last_lines ]; then
                echo "  TIMEOUT ($elapsed s). Killing..."
                kill -9 $CMD_PID 2>/dev/null
                sleep 2
                break
            fi
            last_lines=$curr_lines
            sleep 15
        done
        
        tail -2 /tmp/phase_c_out.log | head -1
    done
}

# === Phase 1: ZH ===
run_batches "zh" "ZH"

# === Phase 2: EN ===
run_batches "en" "EN"

echo ""
echo "=============================================================="
echo "ALL DONE"
echo "=============================================================="

# Final tally
python3 << 'PYEOF'
import sys; sys.path.insert(0, 'tools/voice_acting')
import json, os
from npc_data import NPC_NUMBERS
with open('tools/voice_acting/bilingual_mapping_review.json') as f: data=json.load(f)
zh_n=en_n=0; zh_m=en_m=0
for e in data:
    npc=e.get('npc',''); nn=NPC_NUMBERS.get(npc)
    if nn is None: continue
    for lang in ['zh','en']:
        d=f'voice/{lang}'; t=(e.get(f'{lang}_text','') or '').strip()
        if not t: continue
        fid=(e.get(f'{lang}_func_id','') or '0000'); okv=(e.get(f'{lang}_offset_key','') or '0'); seg=e.get(f'{lang}_segment',0) or 0
        if isinstance(fid,str) and (fid.startswith('0x') or fid.startswith('0X')): fid=fid[2:]
        fid=str(fid).lower().zfill(4)
        p=os.path.join(d,f'{fid}_{okv}_{seg}_npc{nn}.ogg')
        if lang=='zh':
            zh_n+=1
            if not os.path.exists(p): zh_m+=1
        else:
            en_n+=1
            if not os.path.exists(p): en_m+=1
print(f"Final: ZH {(1-zh_m/zh_n)*100:.1f}%  EN {(1-en_m/en_n)*100:.1f}%  Remaining {zh_m+en_m}")
PYEOF