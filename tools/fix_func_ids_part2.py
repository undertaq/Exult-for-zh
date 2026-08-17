"""
Second pass: fix remaining entries with wrong func_ids that weren't matched
by the first pass (offset_mapping.csv pairing differs from JSON pairing).
Uses en_voice_lines.csv and zh_voice_lines.csv directly to look up
func_ids by matching text.
"""
import csv
import json
import os
import shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR   = os.path.dirname(SCRIPT_DIR)

EN_CSV_PATH = os.path.join(SCRIPT_DIR, 'voice_acting', 'en_voice_lines.csv')
ZH_CSV_PATH = os.path.join(SCRIPT_DIR, 'voice_acting', 'zh_voice_lines.csv')
JSON_PATH   = os.path.join(SCRIPT_DIR, 'voice_acting', 'bilingual_mapping_review.json')
VOICE_DIR   = os.path.join(REPO_DIR, 'voice')

# ── 1. Build text→func_id lookups from CSVs ──────────────────────────
# CSV has: func_id, npc, speaker, caller_guess, offset_key, segment, total_segments, has_var, text
en_text_lookup = {}  # normalized text → (func_id, offset_key, segment)
with open(EN_CSV_PATH, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        text = row['text'].strip()
        fid  = row['func_id'].strip()
        ok   = row['offset_key'].replace('0x', '').strip()
        seg  = int(row['segment'].strip()) if row['segment'].strip() else 0
        if text and fid:
            # Normalize: strip quotes, whitespace
            norm = text.strip(' "\u201c\u201d')
            if norm not in en_text_lookup:
                en_text_lookup[norm] = (fid, ok, seg)

zh_text_lookup = {}
with open(ZH_CSV_PATH, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        text = row['text'].strip()
        fid  = row['func_id'].strip()
        ok   = row['offset_key'].replace('0x', '').strip()
        seg  = int(row['segment'].strip()) if row['segment'].strip() else 0
        if text and fid:
            norm = text.strip(' "\u201c\u201d\u300c\u300d')
            if norm not in zh_text_lookup:
                zh_text_lookup[norm] = (fid, ok, seg)

print(f'EN text→func_id lookups: {len(en_text_lookup)}')
print(f'ZH text→func_id lookups: {len(zh_text_lookup)}')

# ── 2. Process unmatched JSON entries ────────────────────────────────
data = json.load(open(JSON_PATH, encoding='utf-8'))

fixed_en = 0
fixed_zh = 0
renamed_en = 0
renamed_zh = 0
skipped = 0

def make_name(fid, ok, seg):
    fid_s = fid.replace('0x', '').replace('0X', '').lower().zfill(4) if fid else '0000'
    return f'{fid_s}_{ok}_{seg}.ogg'

for entry in data:
    en_fid_old = entry.get('en_func_id', '')
    zh_fid_old = entry.get('zh_func_id', '')
    en_ok      = entry.get('en_offset_key', '')
    zh_ok      = entry.get('zh_offset_key', '')
    en_seg     = entry.get('en_segment', 0)
    zh_seg     = entry.get('zh_segment', 0)
    en_text    = entry.get('en_text', '').strip()
    zh_text    = entry.get('zh_text', '').strip()

    en_fixed = False
    zh_fixed = False

    # Fix EN func_id
    if en_text:
        en_norm = en_text.strip(' "\u201c\u201d')
        if en_norm in en_text_lookup:
            correct_fid, correct_ok, correct_seg = en_text_lookup[en_norm]
            if correct_fid != en_fid_old:
                # Update JSON
                entry['en_func_id'] = correct_fid
                entry['en_offset_key'] = correct_ok
                entry['en_segment'] = correct_seg
                en_fixed = True
                fixed_en += 1

                # Rename file
                old_name = make_name(en_fid_old, en_ok, en_seg)
                new_name = make_name(correct_fid, correct_ok, correct_seg)
                old_path = os.path.join(VOICE_DIR, 'en', old_name)
                new_path = os.path.join(VOICE_DIR, 'en', new_name)
                if os.path.exists(old_path) and not os.path.exists(new_path):
                    shutil.move(old_path, new_path)
                    renamed_en += 1
                elif os.path.exists(old_path) and os.path.exists(new_path):
                    os.remove(old_path)
                    renamed_en += 1  # still counted as handled

    # Fix ZH func_id
    if zh_text:
        zh_norm = zh_text.strip(' "\u201c\u201d\u300c\u300d')
        if zh_norm in zh_text_lookup:
            correct_fid, correct_ok, correct_seg = zh_text_lookup[zh_norm]
            if correct_fid != zh_fid_old:
                entry['zh_func_id'] = correct_fid
                entry['zh_offset_key'] = correct_ok
                entry['zh_segment'] = correct_seg
                zh_fixed = True
                fixed_zh += 1

                old_name = make_name(zh_fid_old, zh_ok, zh_seg)
                new_name = make_name(correct_fid, correct_ok, correct_seg)
                old_path = os.path.join(VOICE_DIR, 'zh', old_name)
                new_path = os.path.join(VOICE_DIR, 'zh', new_name)
                if os.path.exists(old_path) and not os.path.exists(new_path):
                    shutil.move(old_path, new_path)
                    renamed_zh += 1
                elif os.path.exists(old_path) and os.path.exists(new_path):
                    os.remove(old_path)
                    renamed_zh += 1

print(f'EN func_id fixed: {fixed_en}, files renamed: {renamed_en}')
print(f'ZH func_id fixed: {fixed_zh}, files renamed: {renamed_zh}')

# ── 3. Save ──────────────────────────────────────────────────────────
json.dump(data, open(JSON_PATH, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
print(f'\nUpdated {JSON_PATH}')
