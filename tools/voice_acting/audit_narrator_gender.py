#!/usr/bin/env python3
"""Audit narrator gender routing for voice generation."""

import argparse
import json
import re
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_qwen3_voice as voice_gen  # noqa: E402


FEMALE_NOISE_PATTERNS = [
    r'not(?:\s+\w+){0,4}\s+feminine',
    r'not\s+feminine',
    r'don[’\']?t(?:\s+\w+){0,4}\s+feminine',
    r'do\s+not(?:\s+\w+){0,4}\s+feminine',
    r'不要女性化',
    r'不女性化',
    r'非女性',
    r'female\s+roles?',
    r'woman[’\']?s\s+wig',
    r'in\s+drag',
    r'[飾饰][演演]女性(?:角色)?',
    r'女性角色',
]


def strip_negated_female_terms(text):
    cleaned = text
    for pattern in FEMALE_NOISE_PATTERNS:
        cleaned = re.sub(pattern, ' ', cleaned, flags=re.IGNORECASE)
    return cleaned


def gender_from_text(text):
    """Infer a gender marker from names or prompt descriptions."""
    text = (text or '').strip()
    if not text:
        return None
    lowered = text.lower()
    cleaned = strip_negated_female_terms(lowered)

    female = (
        re.search(r'(^|[^a-z])female([^a-z]|$)', cleaned)
        or re.search(r'(^|[^a-z])feminine([^a-z]|$)', cleaned)
        or '女性' in cleaned
        or '女聲' in cleaned
        or '女中音' in cleaned
        or re.search(r'(^|[^a-z])woman([^a-z]|$)', cleaned)
        or re.search(r'(^|[^a-z])girl([^a-z]|$)', cleaned)
    )
    male = (
        re.search(r'(^|[^a-z])male([^a-z]|$)', lowered)
        or re.search(r'(^|[^a-z])masculine([^a-z]|$)', lowered)
        or '男性' in lowered
        or '男聲' in lowered
        or '男中音' in lowered
        or re.search(r'(^|[^a-z])man([^a-z]|$)', lowered)
        or re.search(r'(^|[^a-z])boy([^a-z]|$)', lowered)
    )

    if female and male:
        return 'conflict'
    if female:
        return 'female'
    if male:
        return 'male'
    return None


def prompt_gender_for_design(design):
    analysis = design.get('_portrait_voice_analysis') or {}
    blob = ' '.join([
        str(design.get('voice_desc_en', '') or ''),
        str(design.get('voice_desc_zh', '') or ''),
        str(analysis.get('gender_presentation', '') or ''),
        str(analysis.get('previous_voice_desc_en', '') or ''),
        str(analysis.get('previous_voice_desc_zh', '') or ''),
    ])
    return gender_from_text(blob)


def name_gender_for_npc(design_id, design, npc_name):
    blob = ' '.join([
        str(npc_name or ''),
        str(design_id or ''),
        str(design.get('npc', '') or ''),
    ])
    return gender_from_text(blob)


def narrator_gender_from_design_id(design_id):
    if design_id == voice_gen.NARRATOR_MALE_DESIGN_ID:
        return 'male'
    if design_id == voice_gen.NARRATOR_FEMALE_DESIGN_ID:
        return 'female'
    return gender_from_text(design_id)


def audit_designs(designs):
    npc_to_design = voice_gen.build_npc_to_design_map(designs)
    rows = []
    issues = []

    for npc_name in sorted(npc_to_design):
        design_id = npc_to_design[npc_name]
        design = designs.get('designs', {}).get(design_id, {})
        prompt_gender = prompt_gender_for_design(design)
        name_gender = name_gender_for_npc(design_id, design, npc_name)
        generator_gender = voice_gen.voice_gender_for_npc(designs, npc_to_design, npc_name)
        narrator_id = voice_gen.narrator_design_id_for_npc(designs, npc_to_design, npc_name)
        narrator_gender = narrator_gender_from_design_id(narrator_id)

        expected_gender = None
        reason = None
        if prompt_gender in ('female', 'male'):
            expected_gender = prompt_gender
            reason = 'prompt'
        elif name_gender in ('female', 'male'):
            expected_gender = name_gender
            reason = 'speaker_name'
        elif generator_gender in ('female', 'male'):
            expected_gender = generator_gender
            reason = 'generator'

        row = {
            'npc': npc_name,
            'design_id': design_id,
            'prompt_gender': prompt_gender,
            'name_gender': name_gender,
            'generator_gender': generator_gender,
            'expected_gender': expected_gender,
            'expected_reason': reason,
            'narrator_id': narrator_id,
            'narrator_gender': narrator_gender,
            'voice_desc_en': design.get('voice_desc_en', ''),
            'voice_desc_zh': design.get('voice_desc_zh', ''),
        }
        row_issues = []
        if prompt_gender == 'conflict':
            row_issues.append('prompt_gender_conflict')
        if name_gender == 'conflict':
            row_issues.append('speaker_name_gender_conflict')
        if (
            prompt_gender in ('female', 'male')
            and name_gender in ('female', 'male')
            and prompt_gender != name_gender
        ):
            row_issues.append('prompt_name_gender_disagree')
        if (
            expected_gender in ('female', 'male')
            and generator_gender in ('female', 'male')
            and expected_gender != generator_gender
        ):
            row_issues.append('generator_gender_disagrees')
        if (
            expected_gender in ('female', 'male')
            and narrator_gender in ('female', 'male')
            and expected_gender != narrator_gender
        ):
            row_issues.append('narrator_gender_disagrees')
        if row_issues:
            row['issues'] = row_issues
            issues.append(row)
        rows.append(row)

    return rows, issues


def print_text_report(rows, issues, limit):
    counts = {}
    for row in rows:
        key = (row['expected_gender'] or 'unknown', row['narrator_gender'] or 'unknown')
        counts[key] = counts.get(key, 0) + 1

    print(f'Audited NPC voices: {len(rows)}')
    print(f'Issues: {len(issues)}')
    print('Expected gender -> narrator gender:')
    for (expected, narrator), count in sorted(counts.items()):
        print(f'  {expected:7s} -> {narrator:7s}: {count}')

    if not issues:
        return

    print()
    print(f'Issues (showing {min(limit, len(issues))} of {len(issues)}):')
    for row in issues[:limit]:
        print(
            f"- {row['npc']} [{row['design_id']}]: "
            f"prompt={row['prompt_gender']} name={row['name_gender']} "
            f"generator={row['generator_gender']} narrator={row['narrator_id']} "
            f"({row['narrator_gender']}) issues={','.join(row['issues'])}"
        )


def main():
    parser = argparse.ArgumentParser(description='Audit narrator gender routing.')
    parser.add_argument(
        '--designs',
        default=str(SCRIPT_DIR / 'npc_voice_designs.json'),
        help='Path to npc_voice_designs.json',
    )
    parser.add_argument('--json-out', help='Write detailed audit JSON to this path')
    parser.add_argument('--format', choices=('text', 'json'), default='text')
    parser.add_argument('--limit', type=int, default=50)
    parser.add_argument('--fail-on-issues', action='store_true')
    args = parser.parse_args()

    with open(args.designs, 'r', encoding='utf-8') as f:
        designs = json.load(f)
    rows, issues = audit_designs(designs)

    payload = {
        'summary': {
            'rows': len(rows),
            'issues': len(issues),
        },
        'issues': issues,
        'rows': rows,
    }
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

    if args.format == 'json':
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_text_report(rows, issues, args.limit)

    if args.fail_on_issues and issues:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
