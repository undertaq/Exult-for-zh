#!/usr/bin/env python3
"""
Test VD fix for broken files (>150K):
  ZH: VD + Simplified Chinese text
  EN: VD + simplified prompts (strip character roles)
Verify with faster-whisper ASR, compare with original.
"""
import json, os, sys, gc, re, time
import unittest
from collections import defaultdict

_MISSING_DEPENDENCY = None

try:
    from zhconv import convert as tc2sc
    import torch
    import soundfile as sf
    from qwen_tts import Qwen3TTSModel
    from faster_whisper import WhisperModel
except ModuleNotFoundError as ex:
    _MISSING_DEPENDENCY = f'optional voice-design dependency missing: {ex.name}'

sys.path.insert(0, os.path.dirname(__file__))
if _MISSING_DEPENDENCY is None:
    try:
        from generate_qwen3_voice import (
            PROJECT_DIR, OUTPUT_DIR, VOICEDESIGN_MODEL, ATTN_IMPL,
            ensure_minimum_duration,
        )
    except ModuleNotFoundError as ex:
        _MISSING_DEPENDENCY = f'optional voice generation dependency missing: {ex.name}'
else:
    PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    OUTPUT_DIR = os.path.join(PROJECT_DIR, 'voice')
    VOICEDESIGN_MODEL = ''
    ATTN_IMPL = ''

if _MISSING_DEPENDENCY is not None:
    def ensure_minimum_duration(wav, sr):
        return wav


def load_tests(loader, tests, pattern):
    if _MISSING_DEPENDENCY is None:
        return tests

    class MissingOptionalDependencyTest(unittest.TestCase):
        @unittest.skip(_MISSING_DEPENDENCY)
        def test_optional_voice_design_dependencies_available(self):
            pass

    return loader.loadTestsFromTestCase(MissingOptionalDependencyTest)


def _require_dependencies():
    if _MISSING_DEPENDENCY is not None:
        raise SystemExit(_MISSING_DEPENDENCY)

FIX_OUTPUT = os.path.join(OUTPUT_DIR, 'fix_test')
MAPPING_PATH = os.path.join(os.path.dirname(__file__), 'bilingual_mapping_review.json')
REF_MAX_TOKENS = 256

TEST_CASES = [
    ('0000_1cda_0.ogg', 'Time Lord', 'zh'),
    ('0401_b4_139_1f3_0.ogg', 'Iolo', 'zh'),
    ('0417_216f_0.ogg', 'Lord British', 'zh'),
    ('0000_113c_0.ogg', 'Horance', 'en'),
    ('0000_2a40_0.ogg', 'Batlin', 'en'),
    ('0000_214c_0.ogg', 'Time Lord', 'en'),
    ('009a_7f3_0.ogg', 'Erethian', 'en'),
]


def _simplify_prompt_en(prompt):
    if not prompt:
        return ''
    parts = [p.strip() for p in prompt.split(',')]
    voice_kw = frozenset({
        'voice', 'tone', 'warm', 'friendly', 'polite', 'deep', 'calm',
        'serious', 'cheerful', 'gentle', 'confident', 'professional',
        'bright', 'welcoming', 'gruff', 'authoritative', 'dignified',
        'concerned', 'worried', 'tired', 'angry', 'slow', 'fast',
        'smooth', 'intense', 'philosophical', 'mysterious',
        'rumbling', 'resonant', 'soft', 'firm', 'strong', 'eager',
        'nervous', 'playful', 'mischievous', 'sly', 'knowing', 'weary',
        'proud', 'cracking', 'insecure', 'desperate', 'pleading',
        'pitiful', 'jovial', 'robust', 'loyal', 'brave', 'earnest',
        'emotional', 'husky', 'monotonous', 'bored', 'mechanical',
        'loud', 'crisp', 'clear', 'articulate', 'unhurried',
        'descriptive', 'mild', 'passionate', 'dramatic', 'sing-song',
        'melodic', 'cultured', 'refined', 'proper', 'no-nonsense',
        'muttering', 'murmuring', 'whisper', 'whispering',
        'sarcastic', 'wry', 'dry', 'flat', 'tight',
    })
    gender = frozenset({'male', 'female', 'neutral', 'creature', 'entity'})
    age = frozenset({'elderly', 'ancient', 'old', 'young', 'teenage', 'middle-aged', 'aged'})
    age_pat = re.compile(r'^\d+s(-\d+s)?$')
    kept = []
    for p in parts:
        pl = p.lower().strip()
        if pl in gender or pl in age or age_pat.match(pl):
            kept.append(p)
        elif any(kw in pl for kw in voice_kw):
            kept.append(p)
    return ', '.join(kept) if len(kept) >= 2 else ', '.join(parts[:2])


def main():
    _require_dependencies()
    os.makedirs(FIX_OUTPUT, exist_ok=True)

    # Load data
    with open(MAPPING_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    by_npc = defaultdict(list)
    for e in data:
        by_npc[e.get('npc', '') or 'UNKNOWN'].append(e)

    # Load Whisper
    print('Loading faster-whisper (medium)...')
    asr = WhisperModel('medium', device='cuda', compute_type='float16')

    # Load VD model
    print(f'Loading {VOICEDESIGN_MODEL}...')
    vd_model = Qwen3TTSModel.from_pretrained(
        VOICEDESIGN_MODEL,
        device_map='cuda',
        dtype=torch.bfloat16,
        attn_implementation=ATTN_IMPL,
    )

    results = []
    for fname, npc, lang in TEST_CASES:
        entries = by_npc.get(npc, [])
        if not entries:
            print(f'[SKIP] {npc} not found')
            continue

        # Find matching entry
        e = None
        for c in entries:
            c_fn = f"{c.get(f'{lang}_func_id','0000').lower().lstrip('0x').zfill(4)}_{c.get(f'{lang}_offset_key','0')}_{c.get(f'{lang}_segment',0)}.ogg"
            if c_fn == fname:
                e = c
                break
        if not e:
            print(f'[SKIP] {npc} {fname} not matched')
            continue

        text_key = f'{lang}_text'
        expected = e.get(text_key, '')
        prompt = e.get('voice_prompt', '')
        lang_name = 'Chinese' if lang == 'zh' else 'English'
        lang_label = lang.upper()

        # Original
        orig_path = os.path.join(OUTPUT_DIR, lang, fname)
        orig_size = os.path.getsize(orig_path) if os.path.exists(orig_path) else 0

        # Generate fix
        out_wav = os.path.join(FIX_OUTPUT, fname.replace('.ogg', '.wav'))
        if lang == 'zh':
            ref_text = tc2sc(expected, 'zh-cn')[:200]
            instruct = prompt  # full characterful
        else:
            ref_text = expected[:200]
            instruct = _simplify_prompt_en(prompt)  # stripped

        print(f'\n[{npc}] {lang_label} original={orig_size//1024}K')
        print(f'  text: {expected[:60]}...')
        print(f'  instruct: {instruct[:60]}...')
        print(f'  ref_text: {ref_text[:60]}...')

        try:
            t0 = time.time()
            wavs, sr = vd_model.generate_voice_design(
                text=ref_text,
                language=lang_name,
                instruct=instruct,
                max_new_tokens=REF_MAX_TOKENS,
            )
            wav = ensure_minimum_duration(wavs[0], sr)
            sf.write(out_wav, wav, sr)
            gen_time = time.time() - t0
            new_size = os.path.getsize(out_wav)

            # ASR verify
            t0 = time.time()
            segs, _ = asr.transcribe(out_wav, language='zh' if lang == 'zh' else 'en',
                                     beam_size=5, vad_filter=True)
            transcribed = ' '.join(s.text.strip() for s in segs)
            asr_time = time.time() - t0

            # Match score
            exp_words = set(expected.lower().split())
            trans_words = set(transcribed.lower().split())
            overlap = len(exp_words & trans_words)
            match_pct = overlap / len(exp_words) * 100 if exp_words else 0

            print(f'  VD: {new_size//1024}K ({gen_time:.1f}s) ASR: "{transcribed[:60]}" match={match_pct:.0f}%')
            results.append((npc, lang_label, orig_size//1024, new_size//1024, match_pct, transcribed[:80], expected[:80]))

        except Exception as ex:
            print(f'  ERROR: {ex}')
            results.append((npc, lang_label, orig_size//1024, 0, 0, f'ERROR: {ex}', expected[:80]))

    # Summary
    print(f'\n{"="*80}')
    print(f'{"NPC":20s} {"Lang":4s} {"Orig":>6s} {"VD":>6s} {"Match":>6s}  ASR Text')
    print('-' * 80)
    for npc, lang, orig, vd, match, trans, exp in results:
        print(f'{npc:20s} {lang:4s} {orig:5d}K {vd:5d}K {match:5.0f}%  {trans[:50]}')

    del vd_model
    gc.collect()
    torch.cuda.empty_cache()
    print('\nDone.')


if __name__ == '__main__':
    main()
