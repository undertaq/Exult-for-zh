#!/bin/bash
# Fast Phase C runner — processes ALL NPCs per language, restarting on hang
cd /home/joe/project/Exult-for-zh
VENV=~/project/qwen3-tts/.venv/bin/python

count_pending() {
    local lang=$1
    python3 -c "
import json, os, sys; sys.path.insert(0, 'tools/voice_acting')
from npc_data import NPC_NUMBERS
with open('tools/voice_acting/bilingual_mapping_review.json') as f: data=json.load(f)
n=en=0; m=0; L='$lang'
for e in data:
    if (e.get('voice_generation') or '').strip() == 'skip': continue
    npc=e.get('npc',''); nn=NPC_NUMBERS.get(npc)
    if nn is None: continue
    t=(e.get(L+'_text','') or '').strip()
    if not t: continue
    n+=1
    fid=(e.get(L+'_func_id','') or '0000'); okv=(e.get(L+'_offset_key','') or '0'); seg=e.get(L+'_segment',0) or 0
    if isinstance(fid,str) and (fid.startswith('0x') or fid.startswith('0X')): fid=fid[2:]
    fid=str(fid).lower().zfill(4)
    p=os.path.join('voice/'+L,fid+'_'+okv+'_'+str(seg)+'_npc'+str(nn)+'.ogg')
    if not os.path.exists(p): m+=1
print(f'{m}/{n}')
"
}

for lang in zh en; do
    echo "=============================================="
    echo "Processing $lang"
    echo "=============================================="
    
    round=0
    while true; do
        pending=$(count_pending $lang)
        pending_num=${pending%%/*}
        total_num=${pending#*/}
        [ "$pending_num" = "0" ] && break
        [ "$pending_num" = "" ] && break
        
        round=$((round+1))
        echo ""
        echo "--- [$lang] Round $round — $pending files remaining ---"
        
        timeout 900 $VENV -u tools/voice_acting/generate_qwen3_voice.py \
            --phase voice --device cuda:0 --lang $lang \
            > /tmp/fast_${lang}.log 2>/dev/null
        
        exit_code=$?
        echo "  exit=$exit_code"
        
        # Show last NPC processed
        grep -oP '\[\w+\]' /tmp/fast_${lang}.log | tail -1
        # Show Gen/Skip for last NPC
        tail -5 /tmp/fast_${lang}.log | grep "Gen:" | tail -1
        
        sleep 3
    done
    
    echo "$lang complete!"
done

echo ""
echo "=== ALL DONE ==="
python3 -c "
import json, os, sys; sys.path.insert(0, 'tools/voice_acting')
from npc_data import NPC_NUMBERS
with open('tools/voice_acting/bilingual_mapping_review.json') as f: data=json.load(f)
zh_n=en_n=0; zh_m=en_m=0
for e in data:
    if (e.get('voice_generation') or '').strip() == 'skip': continue
    npc=e.get('npc',''); nn=NPC_NUMBERS.get(npc)
    if nn is None: continue
    for lang in ['zh','en']:
        d=f'voice/{lang}'; t=(e.get(f'{lang}_text','') or '').strip()
        if not t: continue
        fid=(e.get(f'{lang}_func_id','') or '0000'); okv=(e.get(f'{lang}_offset_key','') or '0'); seg=e.get(f'{lang}_segment',0) or 0
        if isinstance(fid,str) and (fid.startswith('0x') or fid.startswith('0X')): fid=fid[2:]
        fid=str(fid).lower().zfill(4)
        p=os.path.join(d,f'{fid}_{okv}_{seg}_npc{nn}.ogg')
        if lang=='zh': zh_n+=1
        else: en_n+=1
        if not os.path.exists(p):
            if lang=='zh': zh_m+=1
            else: en_m+=1
pct_zh = (1-zh_m/zh_n)*100 if zh_n else 0
pct_en = (1-en_m/en_n)*100 if en_n else 0
print(f'ZH: {pct_zh:.1f}% ({zh_n-zh_m}/{zh_n})')
print(f'EN: {pct_en:.1f}% ({en_n-en_m}/{en_n})')
print(f'Remaining: {zh_m+en_m}')
"