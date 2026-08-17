#!/usr/bin/env python3
"""Audit bilingual_mapping_review.json for session completeness.

Checks: entry count, sequential indices, text completeness, raw text,
tag replacement, delimiter balance, NPC field, VAR consistency,
and specific checkpoints.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fix_alignment_and_tags import var_replacement_en, var_replacement_zh

MAPPING = Path(__file__).parent / 'bilingual_mapping_review.json'
BACKUP = Path(__file__).parent / 'bilingual_mapping_review.json.pre_translate'

errors = []
warnings = []


def err(msg, idx=None):
    tag = f"  [{idx}] " if idx is not None else "  "
    errors.append(f"{tag}{msg}")


def warn(msg, idx=None):
    tag = f"  [{idx}] " if idx is not None else "  "
    warnings.append(f"{tag}{msg}")


def audit():
    with open(MAPPING) as f:
        data = json.load(f)
    by_idx = {e['index']: e for e in data}

    print("=" * 72)
    print("  AUDIT: bilingual_mapping_review.json — Session Completeness")
    print("=" * 72)

    # 1. Basic Integrity
    print("\n1. Basic Integrity")
    print("-" * 40)

    if len(data) == 8905:
        print(f"   ✓ Entry count: {len(data)}")
    else:
        err(f"Expected 8905 entries, got {len(data)}")

    indices = sorted(e['index'] for e in data)
    if indices == list(range(len(data))):
        print(f"   ✓ Indices sequential 0–{len(data)-1}")
    else:
        missing = set(range(len(data))) - set(indices)
        extra = set(indices) - set(range(len(data)))
        if missing: err(f"Missing indices: {sorted(missing)[:10]}")
        if extra: err(f"Extra indices: {sorted(extra)[:10]}")

    dup_indices = [i for i, count in
                   __import__('collections').Counter(e['index'] for e in data).items()
                   if count > 1]
    if dup_indices:
        err(f"Duplicate indices: {dup_indices}")
    else:
        print(f"   ✓ No duplicate indices")

    non_dict = sum(1 for e in data if not isinstance(e, dict))
    if non_dict:
        err(f"Non-dict entries: {non_dict}")
    else:
        print(f"   ✓ All entries are dicts")

    # 2. Text completeness
    print("\n2. Text Completeness")
    print("-" * 40)
    missing_zh = [e for e in data if not e.get('zh_text', '').strip()]
    missing_en = [e for e in data if not e.get('en_text', '').strip()]
    print(f"   Missing zh_text: {len(missing_zh)}  ", end="")
    print("✗" if missing_zh else "✓")
    print(f"   Missing en_text: {len(missing_en)}  ", end="")
    print("✗" if missing_en else "✓")

    # 3. Raw text fields
    print("\n3. Raw Text Fields")
    print("-" * 40)
    for fname in ['en_raw', 'zh_raw']:
        missing = [e for e in data if fname not in e or not e.get(fname, '').strip()]
        print(f"   Empty {fname}: {len(missing)}  ", end="")
        if missing:
            err(f"{len(missing)} entries with empty {fname}", missing[0]['index'])
            print("✗")
        else:
            print("✓")

    # 4. Tag replacement
    print("\n4. Tag Replacement")
    print("-" * 40)
    tag_pat = re.compile(r'<[^>]+>')
    tags_in_zh = [(e['index'], e['zh_text']) for e in data
                  if tag_pat.search(e.get('zh_text', ''))]
    tags_in_en = [(e['index'], e['en_text']) for e in data
                  if tag_pat.search(e.get('en_text', ''))]
    print(f"   Tags in zh_text: {len(tags_in_zh)}  ", end="")
    if tags_in_zh:
        for idx, txt in tags_in_zh[:3]:
            found = tag_pat.findall(txt)
            err(f"Tags {found} remaining", idx)
        print("✗")
    else:
        print("✓")
    print(f"   Tags in en_text: {len(tags_in_en)}  ", end="")
    if tags_in_en:
        for idx, txt in tags_in_en[:3]:
            found = tag_pat.findall(txt)
            err(f"Tags {found} remaining", idx)
        print("✗")
    else:
        print("✓")

    # 5. Delimiter balance
    print("\n5. Delimiter Balance")
    print("-" * 40)
    zh_unbal = [(e['index'], e['zh_text']) for e in data
                if e.get('zh_text', '').count('「') != e.get('zh_text', '').count('」')]
    en_unbal = [(e['index'], e['en_text']) for e in data
                if e.get('en_text', '').count('"') % 2 != 0]
    print(f"   ZH 「」 unbalanced: {len(zh_unbal)}  ", end="")
    print("✗" if zh_unbal else "✓")
    print(f"   EN \"\" unbalanced:  {len(en_unbal)}  ", end="")
    print("✗" if en_unbal else "✓")

    # 6. NPC field
    print("\n6. NPC Field")
    print("-" * 40)
    empty_npc = [e for e in data if not e.get('npc', '').strip()]
    unknown_npc = [e for e in data if e.get('npc', '').strip().upper() == 'UNKNOWN']
    print(f"   Empty npc: {len(empty_npc)}  ", end="")
    print("✗" if empty_npc else "✓")
    print(f"   NPC='UNKNOWN': {len(unknown_npc)}")

    # Compare with backup
    if BACKUP.exists():
        with open(BACKUP) as f:
            backup = json.load(f)
        backup_unknown = [e for e in backup if e.get('npc', '').strip().upper() == 'UNKNOWN']
        print(f"   Backup had: {len(backup_unknown)} UNKNOWN")
        if len(unknown_npc) <= len(backup_unknown):
            print(f"   ✓ UNKNOWN count reduced by {len(backup_unknown) - len(unknown_npc)}")
        else:
            warn(f"UNKNOWN count increased from {len(backup_unknown)} to {len(unknown_npc)}")

    # 7. VAR class consistency
    print("\n7. VAR Class Consistency")
    print("-" * 40)
    with_var_class = [e for e in data if e.get('var_class')]
    print(f"   Entries with var_class: {len(with_var_class)}")
    mismatch = 0
    for e in data:
        vc = e.get('var_class', '')
        if '<VAR>' not in e.get('en_raw', '') and '<VAR>' not in e.get('zh_raw', ''):
            continue
        if not vc:
            continue
        en_text = e.get('en_text', '')
        zh_text = e.get('zh_text', '')
        expected_en = var_replacement_en(vc)
        expected_zh = var_replacement_zh(vc)
        if not en_text or not zh_text:
            continue
        for other_class in ['player_name', 'npc_name', 'title', 'number']:
            if other_class == vc:
                continue
            other_zh = var_replacement_zh(other_class)
            if en_text == expected_en and other_zh in zh_text and expected_zh not in zh_text:
                mismatch += 1
                if mismatch <= 5:
                    err(f"EN uses {vc} class but ZH uses {other_class} class", e['index'])
    if mismatch:
        print(f"   ⚠ {mismatch} potential class mismatches")
    else:
        print("   ✓ All consistent")

    # 8. Checkpoints
    print("\n8. Checkpoints")
    print("-" * 40)
    checks = [
        (731, "If you would like", "如果你願意"),
        (7223, "Be most careful", "務必小心"),
        (8553, "It is most fortunate", "跌倒在我們避難所"),
        (7723, "do you find the price acceptable", "你覺得這個價格可以接受嗎"),
        (6431, "you should come to my shoppe", "請你在我們營業時再來"),
        (83, "Here we are", "我們到了"),
        (84, "Arcadion's voice whispers", "Arcadion的聲音"),
        (143, "Dracothraxus sniffs", "Dracothraxus"),
        (197, "Then I have a mission", "任務交給你"),
        (307, "Ancient text translation", "古文譯本"),
    ]
    all_ok = True
    for idx, en_exp, zh_exp in checks:
        if idx not in by_idx:
            err(f"Checkpoint {idx} missing", idx)
            all_ok = False
            continue
        e = by_idx[idx]
        en_ok = en_exp in e.get('en_text', '') or en_exp.lower() in e.get('en_text', '').lower()
        zh_ok = zh_exp in e.get('zh_text', '')
        if en_ok and zh_ok:
            print(f"   ✓ idx={idx}")
        else:
            problems = []
            if not en_ok: problems.append(f"EN")
            if not zh_ok: problems.append(f"ZH")
            err(f"Checkpoint {idx} failed: {', '.join(problems)}", idx)
            all_ok = False

    # Summary
    print("\n" + "=" * 72)
    print(f"  RESULTS: {len(errors)} errors, {len(warnings)} warnings")
    print("=" * 72)
    if errors:
        print("\n  ERRORS:")
        for e in errors:
            print(f"    ✗ {e}")
    if warnings:
        print("\n  WARNINGS:")
        for w in warnings:
            print(f"    ⚠ {w}")
    if not errors and not warnings:
        print("\n  ✓ ALL CHECKS PASSED")
    return len(errors) + len(warnings)


if __name__ == '__main__':
    sys.exit(audit())
