#!/usr/bin/env python3
"""
Fast Phase C runner — processes ALL NPCs per language, restarting if the process
hangs or times out. Each run processes as many NPCs as possible before the
model's CUDA kernel eventually stalls.
"""
import json, os, subprocess, sys, time

sys.path.insert(0, 'tools/voice_acting')
from npc_data import NPC_NUMBERS

BASE_DIR = '/home/joe/project/Exult-for-zh'
VENV_PYTHON = os.path.expanduser('~/project/qwen3-tts/.venv/bin/python')
JSON_PATH = 'tools/voice_acting/bilingual_mapping_review.json'

def count_pending(lang):
    """Return (pending, total) — uses Phase C's _build_base_name logic."""
    with open(os.path.join(BASE_DIR, JSON_PATH)) as f:
        data = json.load(f)
    total = 0
    pending = 0
    for e in data:
        npc = e.get('npc', '')
        nn = NPC_NUMBERS.get(npc)
        if nn is None:
            continue
        text = (e.get(f'{lang}_text', '') or '').strip()
        if not text:
            continue
        total += 1
        # Match generate_qwen3_voice's _build_base_name exactly
        fid_key = f'{lang}_func_id'
        fid = (e.get(fid_key, '') or e.get('zh_func_id', '') or e.get('en_func_id', '') or '0000')
        ok = (e.get(f'{lang}_offset_key', '') or '0')
        seg = e.get(f'{lang}_segment', 0) or 0
        if isinstance(fid, str) and (fid.startswith('0x') or fid.startswith('0X')):
            fid = fid[2:]
        fid = str(fid).lower().zfill(4)
        filename = f'{fid}_{ok}_{seg}_npc{nn}.ogg'
        path = os.path.join(BASE_DIR, f'voice/{lang}', filename)
        if not os.path.exists(path):
            pending += 1
    return pending, total

def run_round(lang, round_num, pending):
    """Run one Phase C round. Returns exit code."""
    log_file = os.path.join('/tmp', f'fast_{lang}.log')
    cmd = [
        'timeout', '900',
        VENV_PYTHON, '-u', 'tools/voice_acting/generate_qwen3_voice.py',
        '--phase', 'voice', '--device', 'cuda:0', '--lang', lang,
    ]
    print(f"\n--- [{lang}] Round {round_num} — {pending[0]}/{pending[1]} files remaining ---")
    sys.stdout.flush()
    
    with open(log_file, 'w') as out_f:
        result = subprocess.run(cmd, cwd=BASE_DIR, stdout=out_f, stderr=subprocess.DEVNULL)
    
    return result.returncode

def main():
    os.chdir(BASE_DIR)
    
    for lang in ['zh', 'en']:
        print(f"\n{'='*50}")
        print(f"Processing {lang}")
        print(f"{'='*50}")
        sys.stdout.flush()
        
        round_num = 0
        while True:
            pending = count_pending(lang)
            if pending[0] == 0:
                break
            
            round_num += 1
            rc = run_round(lang, round_num, pending)
            print(f"  exit={rc}", flush=True)
            
            # Show last progress
            log_file = f'/tmp/fast_{lang}.log'
            try:
                with open(log_file) as f:
                    lines = f.readlines()
                for line in reversed(lines[-20:]):
                    if '[' in line and '] Gen:' in line:
                        print(f"  last: {line.strip()}")
                        break
            except (FileNotFoundError, IndexError):
                pass
            
            time.sleep(3)
        
        print(f"{lang} complete!", flush=True)
    
    # Final tally
    zh_p, zh_t = count_pending('zh')
    en_p, en_t = count_pending('en')
    zh_files = len(os.listdir('voice/zh'))
    en_files = len(os.listdir('voice/en'))
    print(f"\n{'='*50}")
    print(f"ALL DONE")
    print(f"{'='*50}")
    print(f"ZH: {(1-zh_p/zh_t)*100:.1f}% ({zh_t-zh_p}/{zh_t})")
    print(f"EN: {(1-en_p/en_t)*100:.1f}% ({en_t-en_p}/{en_t})")
    print(f"Remaining: {zh_p+en_p}")
    print(f"Files: ZH={zh_files} EN={en_files}")

if __name__ == '__main__':
    main()
