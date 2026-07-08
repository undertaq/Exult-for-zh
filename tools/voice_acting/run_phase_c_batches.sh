#!/bin/bash
# Phase C production runner
# Processes NPCs in stable batches to avoid CUDA hangs
set -e
cd /home/joe/project/Exult-for-zh
VENV=~/project/qwen3-tts/.venv/bin/python

# Build NPC lists
python3 << 'PYEOF'
import json, os, sys; sys.path.insert(0, 'tools/voice_acting')
from npc_data import NPC_NUMBERS
with open('tools/voice_acting/bilingual_mapping_review.json') as f:
    data = json.load(f)
all_npcs = sorted(NPC_NUMBERS.keys(), key=lambda x: (x.lower() if x else ''))
for lang in ['zh','en']:
    pending = []
    for npc in all_npcs:
        nn = NPC_NUMBERS[npc]
        for e in data:
            if e.get('npc','') != npc: continue
            t = (e.get(f'{lang}_text','') or '').strip()
            if not t: continue
            fid=(e.get(f'{lang}_func_id','') or '0000'); okv=(e.get(f'{lang}_offset_key','') or '0'); seg=e.get(f'{lang}_segment',0) or 0
            if isinstance(fid,str) and (fid.startswith('0x') or fid.startswith('0X')): fid=fid[2:]
            fid=str(fid).lower().zfill(4)
            p=os.path.join(f'voice/{lang}',f'{fid}_{okv}_{seg}_npc{nn}.ogg')
            if not os.path.exists(p):
                pending.append(npc)
                break
    with open(f'/tmp/pending_{lang}.txt','w') as f:
        f.write('\n'.join(pending))
    print(f'{lang}: {len(pending)} NPCs pending')
PYEOF

run_phase() {
    local lang=$1 label=$2
    local list_file="/tmp/pending_${lang}.txt"
    if [ ! -s "$list_file" ]; then echo "No $label pending"; return; fi
    
    mapfile -t NPCs < "$list_file"
    local total=${#NPCs[@]}
    echo "=== $label: $total NPCs ==="
    
    for ((i=0; i<total; i+=3)); do
        end=$((i+3)); [ $end -gt $total ] && end=$total
        batch=("${NPCs[@]:i:end-i}")
        NPC_ARG=$(IFS=,; echo "${batch[*]}")
        echo "[$((i+1))-$end/$total] $label: $NPC_ARG"
        
        # Run with 10 min timeout
        timeout 600 $VENV -u tools/voice_acting/generate_qwen3_voice.py \
            --phase voice --device cuda:0 --lang "$lang" --npc "$NPC_ARG" \
            2>/dev/null | tail -3
        
        if [ ${PIPESTATUS[0]} -ne 0 ]; then
            echo "  FAILED (exit ${PIPESTATUS[0]}), trying 1-by-1..."
            for npc in "${batch[@]}"; do
                timeout 600 $VENV -u tools/voice_acting/generate_qwen3_voice.py \
                    --phase voice --device cuda:0 --lang "$lang" --npc "$npc" \
                    2>/dev/null | tail -3
            done
        fi
    done
}

run_phase zh "ZH"
run_phase en "EN"

# Final tally
python3 << 'PYEOF'
import json, os, sys; sys.path.insert(0, 'tools/voice_acting')
from npc_data import NPC_NUMBERS
with open('tools/voice_acting/bilingual_mapping_review.json') as f: data=json.load(f)
zh_n=en_n=0; zh_m=en_m=0
for e in data:
    npc=e.get('npc',''); nn=NPC_NUMBERS.get(npc); 
    if nn is None: continue
    for lang in ['zh','en']:
        d=f'voice/{lang}'; t=(e.get(f'{lang}_text','') or '').strip()
        if not t: continue
        fid=(e.get(f'{lang}_func_id','') or '0000'); okv=(e.get(f'{lang}_offset_key','') or '0'); seg=e.get(f'{lang}_segment',0) or 0
        if isinstance(fid,str) and (fid.startswith('0x') or fid.startswith('0X')): fid=fid[2:]
        fid=str(fid).lower().zfill(4)
        p=os.path.join(d,f'{fid}_{okv}_{seg}_npc{nn}.ogg')
        if lang=='zh': zh_n+=1; 
        else: en_n+=1
        if not os.path.exists(p):
            if lang=='zh': zh_m+=1
            else: en_m+=1
print(f"\nFinal: ZH {(1-zh_m/zh_n)*100:.1f}%  EN {(1-en_m/en_n)*100:.1f}%")
print(f"Remaining: ZH={zh_m}, EN={en_m}, Total={zh_m+en_m}")
print(f"Files: ZH={len(os.listdir('voice/zh'))}, EN={len(os.listdir('voice/en'))}")
PYEOF