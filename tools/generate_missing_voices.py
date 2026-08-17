#!/usr/bin/env python3
"""Generate the 3 remaining missing voice files."""
import json, os, sys, pickle, torch
sys.path.insert(0, os.path.expanduser('~/project/qwen3-tts'))
import numpy as np
import soundfile as sf
from qwen_tts import Qwen3TTSModel
from zhconv import convert as tc2sc

SCRIPT_DIR = 'tools/voice_acting'
VOICE_DIR = 'voice'
MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
ATTN_IMPL = "sdpa"
MIN_DURATION_MS = 1500

data = json.load(open(f'{SCRIPT_DIR}/bilingual_mapping_review.json'))
designs = json.load(open(f'{SCRIPT_DIR}/npc_voice_designs.json'))
with open(f'{SCRIPT_DIR}/clone_prompts.pkl', 'rb') as f:
    clone_prompts = pickle.load(f)

def write_ogg_direct(filepath, wav, sr, npc='', text=''):
    import hashlib, subprocess
    title = hashlib.sha256(text.encode('utf-8')).hexdigest()[:16] if text else ''
    artist = f'qwen3:{npc}' if npc else 'qwen3'
    description = text or ''
    wav = np.asarray(wav, dtype=np.float32)
    cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
        '-f', 'f32le', '-ar', str(sr), '-ac', '1', '-i', 'pipe:0',
        '-c:a', 'libvorbis', '-q:a', '2',
    ]
    if title: cmd += ['-metadata', f'TITLE={title}']
    if artist: cmd += ['-metadata', f'ARTIST={artist}']
    if description: cmd += ['-metadata', f'DESCRIPTION={description}']
    cmd.append(str(filepath))
    raw = wav.tobytes()
    subprocess.run(cmd, input=raw, capture_output=True, check=True)

def ensure_min_dur(wav, sr, min_ms=MIN_DURATION_MS):
    needed = int(sr * min_ms / 1000)
    if len(wav) < needed:
        repeats = int(np.ceil(needed / len(wav)))
        wav = np.tile(wav, repeats)[:needed]
    return wav

# Files to generate:
jobs = [
    # EN Klog Fellowship intro
    {'lang': 'en', 'npc': 'Klog', 'text': 'The Fellowship is a society of spiritual seekers who strive to awaken the highest potential of humanity and to share this ideal unselfishly with all.', 'path': 'voice/en/091a_0_0.ogg'},
    # ZH Klog/Constance line
    {'lang': 'zh', 'npc': 'Klog', 'text': '喔。好吧，也許你下次能夠得到啟發。', 'path': 'voice/zh/091a_39b_0.ogg'},
    # EN Gargan action
    {'lang': 'en', 'npc': 'Gargan', 'text': 'Gargan coughs, clears his throat loudly, then spits.', 'path': 'voice/en/0415_6dc_1.ogg'},
]

# Check which already exist
jobs = [j for j in jobs if not os.path.exists(j['path'])]
if not jobs:
    print('All files already exist!')
    sys.exit(0)

print(f'Need to generate {len(jobs)} files')

# Build NPC -> design mapping
npc_to_did = {}
for did, d in designs['designs'].items():
    for npc_name in d['npcs']:
        npc_to_did[npc_name] = did

# Load model
print('Loading model...')
model = Qwen3TTSModel.from_pretrained(
    MODEL, device_map='cuda:0', dtype=torch.bfloat16,
    attn_implementation=ATTN_IMPL,
)

try:
    for job in jobs:
        npc_name = job['npc']
        did = npc_to_did.get(npc_name)
        if not did:
            print(f'  [{npc_name}] No voice design found, skipping')
            continue
        
        prompt_data = clone_prompts.get(did, {}).get(job['lang'])
        if prompt_data is None:
            print(f'  [{npc_name}] No clone prompt for {job["lang"]}, skipping')
            continue
        
        text = job['text']
        if job['lang'] == 'zh':
            text = tc2sc(text, 'zh-cn')
        
        print(f'  Generating {os.path.basename(job["path"])}: {text[:50]}...')
        
        wavs, sr = model.generate_voice_clone(
            text=[text],
            language=['Chinese' if job['lang'] == 'zh' else 'English'],
            voice_clone_prompt=prompt_data,
            max_new_tokens=256,
        )
        wav_out = ensure_min_dur(wavs[0], sr)
        os.makedirs(os.path.dirname(job['path']), exist_ok=True)
        write_ogg_direct(job['path'], wav_out, sr, npc_name, text)
        print(f'    Done ({len(wav_out)/sr:.1f}s, {os.path.getsize(job["path"])} bytes)')
        
        torch.cuda.empty_cache()

finally:
    del model
    torch.cuda.empty_cache()

print('\nAll missing files generated.')
