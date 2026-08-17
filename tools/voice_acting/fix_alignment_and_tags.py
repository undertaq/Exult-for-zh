#!/usr/bin/env python3
"""
Fix bilingual alignment (content-based instead of sequential) and 
replace game tags (PLAYER_NAME, HONORIFIC, VAR, PRONOUN, GENDER_FLAG)
with context-appropriate TTS text.

Usage:
    python fix_alignment_and_tags.py \
        --en en_voice_lines.csv --zh zh_voice_lines.csv \
        -i bilingual_mapping_review.json \
        -o bilingual_mapping_fixed.json
"""

import argparse
import csv
import json
import re
import sys
from collections import OrderedDict, Counter

# ── Tag replacement constants ──────────────────────────────────────────

TAG_REPLACEMENTS = {
    '<PLAYER_NAME>': ('Avatar', '聖者'),
    '<HONORIFIC>': ('milord', '大人'),
    '<GENDER_FLAG>': ("man's", '男性'),
}

def get_replacement(tag, lang, context_text=''):
    if tag == '<PRONOUN>':
        # Check the 25 chars before first <PRONOUN> for verb/preposition context
        idx = context_text.find('<PRONOUN>')
        before = context_text[max(0, idx-25):idx].strip()
        last_word = before.split()[-1] if before.split() else ''
        last_word = re.sub(r'[^a-zA-Z]', '', last_word).lower()  # strip punct
        
        obj_verbs = {'show','shows','showed','shown','tell','tells','told','telling',
                     'give','gives','gave','given','giving','kill','kills','killed','killing',
                     'cut','cuts','cutting','help','helps','helped','helping',
                     'ask','asks','asked','asking','find','finds','found','finding',
                     'see','sees','saw','seen','seeing','meet','meets','met','meeting',
                     'call','calls','called','calling','make','makes','made','making',
                     'teach','teaches','taught','teaching','train','trains','trained','training',
                     'instruct','instructs','instructed','instructing',
                     'force','forces','forced','forcing','allow','allows','allowed','allowing',
                     'hear','hears','heard','hearing','watch','watches','watched','watching',
                     'like','likes','liked','liking','love','loves','loved','loving',
                     'hate','hates','hated','hating','send','sends','sent','sending',
                     'bring','brings','brought','bringing','take','takes','took','taken',
                     'leave','leaves','left','leaving','keep','keeps','kept','keeping'}
        # Object position: preceded by these prepositions
        obj_preps = {'with','to','for','from','by','at','of','about','toward','towards',
                     'upon','against','beside','beyond','through','between','among','amongst',
                     'after','before','unto','behind','beneath','under','underneath',
                     'above','over','across','along','around','during','since','until',
                     'till','up','down','off','near','past','via'}
        
        if last_word in obj_verbs or last_word in obj_preps:
            return 'him' if lang == 'en' else '他'
        return 'he' if lang == 'en' else '他'
    
    en_val, zh_val = TAG_REPLACEMENTS.get(tag, (tag, tag))
    return en_val if lang == 'en' else zh_val

# ── VAR classifier ─────────────────────────────────────────────────────

def classify_var_en(text):
    """Classify what <VAR> represents in the EN text."""
    t = text.replace('<VAR>', '___VAR___').strip()
    var_count = t.count('___VAR___')
    
    # ── NUMBER patterns (PAYMENT/QUANTITY context) ──
    # "pay <VAR> gold", "hand you <VAR> arrow"
    if re.search(
        r'(?:pay(?:s|ing|ed)?|charge(?:s|d)?|cost(?:s)?|spend(?:s|ing|t)?|'
        r'bet(?:s|ting)?|wager(?:s|ing|ed)?|owe(?:s|d)?|give(?:s)?|'
        r'hand(?:s|ing|ed)?|offer(?:s|ed)?|collect(?:s|ed)?|receive(?:s|d)?|'
        r'count(?:s|ed|ing)?|gather(?:s|ed|ing)?|find(?:s|ing|found)?|'
        r'have|has|need(?:s|ed)?|want(?:s|ed)?|withdraw(?:s|ing|drew)?|'
        r'deposit(?:s|ed)?|remove(?:s|d)?|take|took|taken|buy|bought|sell|sold|'
        r'request(?:s|ed)?|demand(?:s|ed)?|charge|must\s+charge|will\s+owe)'
        r' .{0,40} ___VAR___ (?:gold|coin|coin|arrow|gem|loaf|loaves|piece|'
        r'bottle|potion|scroll|key|pound|day|week|month|year)',
        t, re.IGNORECASE):
        return 'number'
    # "___VAR___ gold/arrow/gem/coin" 
    if re.search(r'___VAR___ (?:gold|coin|arrow|gem|loaf|loaves|piece|bottle|potion)', t, re.IGNORECASE):
        return 'number'
    # "thou hast ___VAR___ in thy party" / "thou hast ___VAR___ Caddellite chunks"
    if re.search(r'(?:hast|have|has|hath|with) ___VAR___ (?:in|Caddellite)', t, re.IGNORECASE):
        return 'number'
    # "Scrumptious! ___VAR___ loaves!" 
    if re.search(r'___VAR___ loaves?', t, re.IGNORECASE):
        return 'number'
    
    # ── PLAYER NAME patterns ──
    # Greeting context
    if re.search(r'(?:well met|greetings|hail|hark|farewell|goodbye|good day|good morrow)', t, re.IGNORECASE):
        return 'player_name'
    # "traveller<VAR>"
    if re.search(r'traveller___VAR___', t, re.IGNORECASE):
        return 'player_name'
    # Vocative (set off by commas): "Within, <VAR>, thou"
    if re.search(r'[,;:] ___VAR___ [,;:]', t):
        return 'player_name'
    # "To die, <VAR>, to die!"
    if re.search(r', ___VAR___,', t):
        return 'player_name'
    # "especially <VAR>", "notably <VAR>"
    if re.search(r'(?:especially|notably|like|such as|including|namely) ___VAR___', t, re.IGNORECASE):
        return 'player_name'
    # "with thee, <VAR>", "with you, <VAR>"
    if re.search(r'with (?:thee|you|me),? ___VAR___', t, re.IGNORECASE):
        return 'player_name'
    # "for <VAR>" / "to <VAR>" / "unto <VAR>" (preposition → name)
    if re.search(r'(?:for|to|unto|upon|against|toward(?:s)?) ___VAR___', t, re.IGNORECASE):
        # Exception: payment context "pay to ___VAR___" is still NPC name
        if re.search(r'(?:pay|charge|cost|owe|give|hand|offer|send|bring|carry) .{0,20} (?:for|to|unto) ___VAR___', t, re.IGNORECASE):
            pass
        else:
            return 'player_name'
    # "search(ed) the land for <VAR>"
    if re.search(r'(?:search(?:ed|es)?|look(?:ing|ed|s)?|hunt(?:ed|ing|s)?|seek|sought|find|found|track(?:ed|ing|s)?|follow(?:ed|ing|s)?) .{0,20} (?:for|after) ___VAR___', t, re.IGNORECASE):
        return 'player_name'
    # "help <VAR>", "aid <VAR>", "assist <VAR>"
    if re.search(r'(?:help|aid|assist|save|protect|defend|guide|lead|teach|train) ___VAR___', t, re.IGNORECASE):
        return 'player_name'
    # Standalone <VAR> (just the tag alone)
    if t in ('___VAR___', '"___VAR___"', '___VAR___.', '"___VAR___."',
             '___VAR___!', '"___VAR___!"', '___VAR___?', '"___VAR___?"',
             '___VAR___,', '"___VAR___,"'):
        return 'player_name'
    # "Knave, <VAR> I have not forgotten" — vocative at sentence start
    if re.search(r'(?:knave|sir|madam|friend|fellow|stranger|traveler|traveller|'
                 r'wanderer|vagabond|scoundrel|villain|rogue|thief|fool|wretch)'
                 r' ,? ___VAR___', t, re.IGNORECASE):
        return 'player_name'
    # Leading <VAR> (at start of sentence or quote)
    if re.search(r'(?:^|")___VAR___\s', t):
        return 'player_name'
    # Trailing <VAR> (at end — often in narrative tags)
    if re.search(r'[\.!\?] ___VAR___[\.!\?\s,;:]*$', t):
        return 'player_name'
    # "<VAR>" after closing quote (narrative: "..."<VAR>)
    if re.search(r'"[^"]*"___VAR___', t):
        return 'player_name'
    # "Noble hero, it is an honor..." <VAR>
    if re.search(r'noble hero', t, re.IGNORECASE):
        return 'player_name'
    # "I travel with thee, <VAR>"
    if re.search(r'travel with (?:thee|you),? ___VAR___', t, re.IGNORECASE):
        return 'player_name'
    # "^<VAR>" prefix (training/conversation option addressing player)
    if re.search(r'\^___VAR___', t):
        return 'player_name'
    # "thou dost wish to be called." <VAR> — presenting name choice
    if re.search(r'(?:wish|wilt|wouldst|call(?:ed|s)?) .{0,20} (?:to )?be .{0,20} ___VAR___', t, re.IGNORECASE):
        return 'player_name'
    # "she says, <VAR>" — narrative addressing player
    if re.search(r'(?:says?|said) ,? ___VAR___', t, re.IGNORECASE):
        return 'player_name'
    # "<VAR>, eh." / "<VAR>, I am sure" — addressing by name
    if re.search(r'___VAR___, (?:eh|I am|I\'m)', t, re.IGNORECASE):
        return 'player_name'
    # "Hello again! <VAR>" — narrative
    if re.search(r'[\.!?]___VAR___', t):
        return 'player_name'
    # Narrative description "...<VAR>." at end
    if re.search(r'___VAR___[\.!\?]*\s*$', t):
        return 'player_name'
    
    # ── NPC NAME patterns ──
    # "was <VAR>", "were <VAR>" (identity/role)
    if re.search(r'(?:was|were) ___VAR___', t, re.IGNORECASE) and \
       not re.search(r'(?:there|it) (?:was|were) ___VAR___', t, re.IGNORECASE):
        return 'npc_name'
    # "<VAR> said/asked/replied" (speech attribution)
    if re.search(r'___VAR___ (?:says?|said|asks?|asked|repl(?:y|ied)|answered?|'
                 r'responds?|responded|calls?|called|shouts?|shouted|yells?|yelled|'
                 r'whispers?|whispered|murmurs?|murmured|mutters?|muttered|'
                 r'explains?|explained|continues?|continued|begins?|started|starts?|'
                 r'concludes?|concluded)', t, re.IGNORECASE):
        return 'npc_name'
    # "<VAR> forbade / moved / walked / came / looks / begins"
    if re.search(r'___VAR___ (?:forbade|forbid|moves?|moved|walks?|walked|went|'
                 r'comes?|came|looks?|looked|seems?|seemed|appears?|appeared|'
                 r'stands?|stood|sits?|sat|lies?|lay|begins?|started|starts?|'
                 r'opens?|opened|closed?|turns?|turned|nods?|nodded|shakes?|shook|'
                 r'smiles?|smiled|frowns?|frowned|sighs?|sighed|laughs?|laughed|'
                 r'enters?|entered|leaves?|left|arrives?|arrived|departs?|departed)'
                 r' ', t, re.IGNORECASE):
        return 'npc_name'
    # "'s <VAR>" (possessive narrative)
    if re.search(r"'s ___VAR___ ", t):
        return 'npc_name'
    # "this <VAR>" (NPC referred to as "this person")
    if re.search(r'this ___VAR___', t, re.IGNORECASE):
        return 'npc_name'
    # NPC as subject with verb (third person singular)
    if re.search(r'___VAR___\s+\w+(?:s|ed|d)\s', t):
        return 'npc_name'
    # "___VAR___ must go to Britain" — NPC giving instructions
    if re.search(r'___VAR___ must', t, re.IGNORECASE):
        return 'npc_name'
    # "Energy courses from ___VAR___ into you" — NPC channeling energy
    if re.search(r'from ___VAR___', t, re.IGNORECASE):
        return 'npc_name'
    
    # ── TITLE patterns ──
    if re.search(r'(?:a|an|the) ___VAR___', t, re.IGNORECASE) and var_count == 1:
        return 'title'
    
    # ── FALLBACK: default to player_name ──
    return 'player_name'


def var_replacement_en(cls):
    """Get English replacement for a VAR classification."""
    return {
        'number': 'some',
        'player_name': 'Avatar',
        'npc_name': 'this person',
        'title': 'woodsman',
    }.get(cls, 'Avatar')


def var_replacement_zh(cls):
    """Get Chinese replacement for a VAR classification."""
    return {
        'number': '一些',
        'player_name': '聖者',
        'npc_name': '那個人',
        'title': '遊俠',
    }.get(cls, '聖者')


# ── Alignment matching ─────────────────────────────────────────────────

_LATIN_RE = re.compile(r"[A-Za-z']+")

def group_similarity(en_text, zh_text):
    """Compute content similarity between EN and ZH text groups."""
    if not en_text or not zh_text:
        return 0.0

    en_len = len(en_text)
    zh_len = len(zh_text)
    expected_zh = en_len / 2.8
    len_score = 1.0 - min(abs(expected_zh - zh_len) / max(expected_zh, zh_len, 1), 1.0)

    en_words = {w for w in _LATIN_RE.findall(en_text) if len(w) > 1}
    zh_words = {w for w in _LATIN_RE.findall(zh_text) if len(w) > 1}
    shared = en_words & zh_words
    union = en_words | zh_words
    latin_score = len(shared) / max(len(union), 1) if union else 0.0

    en_var = '<' in en_text
    zh_var = '<' in zh_text
    var_score = 1.0 if en_var == zh_var else 0.0

    en_q = en_text.strip().startswith(('"', '\u201c'))
    zh_q = any(zh_text.strip().startswith(q)
               for q in ('"', '\u201c', '\u300c', '\u300e', '\u300a'))
    quote_score = 1.0 if en_q == zh_q else 0.0

    return len_score * 0.20 + latin_score * 0.45 + var_score * 0.20 + quote_score * 0.15


def fix_encoding(text):
    """Fix double-encoded UTF-8: read as UTF-8, re-interpret bytes as Latin-1, decode as UTF-8."""
    if not text:
        return text
    try:
        return text.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def normalize_func_id(value):
    value = str(value or '').strip().lower()
    if value.startswith('0x'):
        value = value[2:]
    return value.zfill(4)


def normalize_offset_key(value):
    parts = str(value or '0').strip().split('_')
    normalized = []
    for part in parts:
        part = part.strip().lower()
        if part.startswith('0x'):
            part = part[2:]
        normalized.append(part or '0')
    return '_'.join(normalized)


def runtime_key(func_id, offset_key, segment):
    return (
        normalize_func_id(func_id),
        normalize_offset_key(offset_key),
        int(segment or 0),
    )


def build_groups(csv_path):
    """Group voice lines by func_id then offset_key."""
    funcs = OrderedDict()
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get('offset_key', '').strip().replace('0x', '').strip()
            if not key:
                continue
            fid = row.get('func_id', '').strip()
            seg_str = row.get('segment', '0').strip()
            seg = int(seg_str) if seg_str else 0
            text = fix_encoding(row.get('text', ''))
            npc = row.get('npc', '') or row.get('speaker', '') or ''

            if fid not in funcs:
                funcs[fid] = []
            groups = funcs[fid]
            grp = next((g for g in groups if g['offset_key'] == key), None)
            if grp is None:
                grp = {
                    'func_id': fid,
                    'offset_key': key,
                    'segs': [],
                    'texts': [],
                    'npc': npc,
                }
                groups.append(grp)
            grp['segs'].append(seg)
            grp['texts'].append(text)
    return funcs


def build_runtime_key_index(csv_path):
    """Return runtime keys present in a source CSV plus duplicate text diagnostics."""
    keys = set()
    text_keys = Counter()
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            keys.add(runtime_key(row.get('func_id', ''), row.get('offset_key', ''), row.get('segment', 0)))
            text_key = (
                re.sub(r'\s+', ' ', fix_encoding(row.get('text', '')).strip()),
                row.get('npc', '') or '',
                row.get('speaker', '') or '',
                row.get('caller_guess', '') or '',
            )
            text_keys[text_key] += 1
    ambiguous = sum(1 for count in text_keys.values() if count > 1)
    return keys, ambiguous


def validate_output_runtime_keys(output, en_csv, zh_csv):
    """Fail fast if output runtime identity fields do not point at source CSV rows."""
    en_keys, en_ambiguous = build_runtime_key_index(en_csv)
    zh_keys, zh_ambiguous = build_runtime_key_index(zh_csv)
    if en_ambiguous or zh_ambiguous:
        print(
            f"  Duplicate source text keys: EN={en_ambiguous}, ZH={zh_ambiguous}",
            file=sys.stderr,
        )

    mismatches = []
    for row in output:
        idx = row.get('index', '?')
        if row.get('en_text', '').strip():
            key = runtime_key(row.get('en_func_id', ''), row.get('en_offset_key', ''), row.get('en_segment', 0))
            if key not in en_keys:
                mismatches.append((idx, 'en', row.get('en_func_id', ''), row.get('en_offset_key', ''), row.get('en_segment', 0)))
        if row.get('zh_text', '').strip():
            key = runtime_key(row.get('zh_func_id', ''), row.get('zh_offset_key', ''), row.get('zh_segment', 0))
            if key not in zh_keys:
                mismatches.append((idx, 'zh', row.get('zh_func_id', ''), row.get('zh_offset_key', ''), row.get('zh_segment', 0)))

    if mismatches:
        print("ERROR: output contains runtime keys not found in source CSVs:", file=sys.stderr)
        for mismatch in mismatches[:20]:
            idx, lang, func_id, offset_key, segment = mismatch
            print(f"  row {idx} {lang}: {func_id} {offset_key} segment {segment}", file=sys.stderr)
        if len(mismatches) > 20:
            print(f"  ... {len(mismatches) - 20} more", file=sys.stderr)
        raise SystemExit(1)


def nw_align(en_grps, zh_grps, gap_penalty=-0.5):
    """
    Needleman-Wunsch alignment for EN↔ZH groups within a function.
    Preserves sequential order, allows gaps for extra/missing groups.
    Returns (paired, en_unpaired, zh_unpaired).
    """
    n, m = len(en_grps), len(zh_grps)
    
    # Precompute similarity matrix
    sim_mat = [[0.0] * m for _ in range(n)]
    for i in range(n):
        en_txt = ' '.join(en_grps[i]['texts'])
        for j in range(m):
            zh_txt = ' '.join(zh_grps[j]['texts'])
            sim_mat[i][j] = group_similarity(en_txt, zh_txt)
    
    # DP table: (score, backtrace)
    dp = [[(0.0, '') for _ in range(m + 1)] for _ in range(n + 1)]
    
    # Initialize first row/col with gap penalties
    for i in range(1, n + 1):
        dp[i][0] = (gap_penalty * i, 'up')
    for j in range(1, m + 1):
        dp[0][j] = (gap_penalty * j, 'left')
    
    # Fill DP
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            match = dp[i-1][j-1][0] + sim_mat[i-1][j-1]
            gap_en = dp[i-1][j][0] + gap_penalty
            gap_zh = dp[i][j-1][0] + gap_penalty
            best = max((match, 'diag'), (gap_en, 'up'), (gap_zh, 'left'))
            dp[i][j] = best
    
    # Backtrace
    paired = []
    en_unpaired_idx = set(range(n))
    zh_unpaired_idx = set(range(m))
    
    i, j = n, m
    while i > 0 or j > 0:
        _, direction = dp[i][j]
        if direction == 'diag':
            i -= 1
            j -= 1
            paired.append((en_grps[i], zh_grps[j], sim_mat[i][j]))
            en_unpaired_idx.discard(i)
            zh_unpaired_idx.discard(j)
        elif direction == 'up':
            i -= 1
        else:  # 'left'
            j -= 1
    
    paired.reverse()
    en_unpaired = [en_grps[i] for i in sorted(en_unpaired_idx)]
    zh_unpaired = [zh_grps[i] for i in sorted(zh_unpaired_idx)]
    
    return paired, en_unpaired, zh_unpaired


# ── Tag replacement in text ────────────────────────────────────────────

def replace_tags_in_text(text, lang, var_class=None, var_replacements=None):
    """Replace all game tags with TTS-appropriate text, strip control chars.

    If var_replacements is a list of strings (one per <VAR> occurrence),
    each <VAR> is replaced individually with the corresponding value
    (per-VAR resolution from usecode tracing).
    """
    if not text:
        return text
    
    result = text
    
    # Strip game control characters: ^
    result = result.replace('^', '')
    
    # Replace deterministic tags (handling each occurrence for PRONOUN)
    for tag in ['<PLAYER_NAME>', '<HONORIFIC>', '<GENDER_FLAG>']:
        if tag in result:
            result = result.replace(tag, get_replacement(tag, lang, context_text=text))
    
    # Handle <PRONOUN> per occurrence (3 cases: he/him/his)
    while '<PRONOUN>' in result:
        repl = get_replacement('<PRONOUN>', lang, context_text=result)
        result = result.replace('<PRONOUN>', repl, 1)
    
    # Replace <VAR> using per-VAR resolution or classification
    if '<VAR>' in result:
        if var_replacements is not None:
            # Per-VAR resolution from usecode tracing
            # Each <VAR> gets its own replacement value
            parts = result.split('<VAR>')
            new_parts = [parts[0]]
            for i in range(1, len(parts)):
                if i - 1 < len(var_replacements):
                    new_parts.append(var_replacements[i - 1])
                else:
                    # Fallback for extra VARs (shouldn't happen)
                    if var_class is None:
                        var_class = classify_var_en(text)
                    repl = var_replacement_en(var_class) if lang == 'en' else var_replacement_zh(var_class)
                    new_parts.append(repl)
                new_parts.append(parts[i])
            result = ''.join(new_parts)
        else:
            if var_class is None:
                var_class = classify_var_en(text)
            repl = var_replacement_en(var_class) if lang == 'en' else var_replacement_zh(var_class)
            
            # Handle multiple VARs intelligently
            var_count = result.count('<VAR>')
            if var_count == 1:
                result = result.replace('<VAR>', repl)
            else:
                parts = result.split('<VAR>')
                new_parts = []
                for i, p in enumerate(parts):
                    if i > 0:
                        prev_seg = parts[i-1] if i-1 >= 0 else ''
                        cur_seg = p if i < len(parts) else ''
                        
                        if prev_seg and prev_seg[-1].isalpha():
                            pass  # skip this VAR
                        elif cur_seg and cur_seg[0].isalpha() and cur_seg[0].isascii():
                            pass  # skip this VAR
                        else:
                            new_parts.append(repl)
                    new_parts.append(p)
                result = ''.join(new_parts)
            result = re.sub(r'  +', ' ', result)
    
    return result


# ── Main ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Fix alignment and replace tags in bilingual mapping')
    parser.add_argument('--en', required=True, help='English voice lines CSV')
    parser.add_argument('--zh', required=True, help='Chinese voice lines CSV')
    parser.add_argument('-i', '--input', required=True,
                        help='Input bilingual_mapping_review.json')
    parser.add_argument('-o', '--output', required=True,
                        help='Output JSON')
    parser.add_argument('--keep-confidence', action='store_true',
                        help='Keep existing confidence instead of recomputing')
    parser.add_argument('--no-tag-replace', action='store_true',
                        help='Skip tag replacement (fix alignment only)')
    args = parser.parse_args()

    # ── Regenerate alignment from source CSVs ──
    print("Rebuilding alignment from source CSVs...", file=sys.stderr)
    en_funcs = build_groups(args.en)
    zh_funcs = build_groups(args.zh)
    
    all_fids = sorted(set(en_funcs.keys()) | set(zh_funcs.keys()))
    en_only = sorted(set(en_funcs.keys()) - set(zh_funcs.keys()))
    zh_only = sorted(set(zh_funcs.keys()) - set(en_funcs.keys()))
    common = sorted(set(en_funcs.keys()) & set(zh_funcs.keys()))
    print(f"  Common functions: {len(common)}, EN only: {len(en_only)}, ZH only: {len(zh_only)}", file=sys.stderr)
    
    # Redo matching for all functions
    all_entries = []
    match_stats = Counter()
    same_count = 0
    diff_count = 0
    
    # Process common functions
    for fid in common + en_only + zh_only:
        en_grps = en_funcs.get(fid, [])
        zh_grps = zh_funcs.get(fid, [])
        npc = (en_grps[0]['npc'] if en_grps else zh_grps[0]['npc']) if (en_grps or zh_grps) else ''
        
        if len(en_grps) == 0:
            # ZH-only function
            for zg in zh_grps:
                for j, txt in enumerate(zg['texts']):
                    all_entries.append({
                        'zh_offset_key': zg['offset_key'], 'zh_segment': zg['segs'][j],
                        'zh_text': txt, 'en_offset_key': '', 'en_segment': 0, 'en_text': '',
                        'confidence': 'unpaired_zh', 'npc': npc, 'func_id': fid,
                        'zh_func_id': zg['func_id'], 'en_func_id': '',
                    })
                    match_stats['unpaired_zh'] += 1
            continue
        elif len(zh_grps) == 0:
            # EN-only function
            for eg in en_grps:
                for j, txt in enumerate(eg['texts']):
                    all_entries.append({
                        'zh_offset_key': '', 'zh_segment': 0, 'zh_text': '',
                        'en_offset_key': eg['offset_key'], 'en_segment': eg['segs'][j],
                        'en_text': txt, 'confidence': 'unpaired_en', 'npc': npc, 'func_id': fid,
                        'zh_func_id': '', 'en_func_id': eg['func_id'],
                    })
                    match_stats['unpaired_en'] += 1
            continue
        en_grps = en_funcs[fid]
        zh_grps = zh_funcs[fid]
        npc = en_grps[0]['npc'] if en_grps else ''
        
        counts_match = (len(en_grps) == len(zh_grps))
        same_count += counts_match
        diff_count += not counts_match
        
        if counts_match:
            # Sequential pairing — correct for same-count functions
            paired = [(en_grps[i], zh_grps[i], 1.0) for i in range(len(en_grps))]
            en_unpaired = []
            zh_unpaired = []
        else:
            # Needleman-Wunsch alignment for mismatched counts
            paired, en_unpaired, zh_unpaired = nw_align(en_grps, zh_grps)
        
        for eg, zg, sim in paired:
            if counts_match:
                conf = 'order_based'
            elif sim > 0.40:
                conf = 'high'
            elif sim > 0.12:
                conf = 'medium'
            else:
                conf = 'low'
            match_stats[conf] += 1
            
            seg_count = min(len(eg['segs']), len(zg['segs']))
            emitted_en = set()
            emitted_zh = set()
            for j in range(seg_count):
                en_seg = eg['segs'][j]
                zh_seg = zg['segs'][j]
                emitted_en.add((eg['offset_key'], en_seg))
                emitted_zh.add((zg['offset_key'], zh_seg))
                all_entries.append({
                    'zh_offset_key': zg['offset_key'],
                    'zh_segment': zh_seg,
                    'zh_text': zg['texts'][j] if j < len(zg['texts']) else '',
                    'en_offset_key': eg['offset_key'],
                    'en_segment': en_seg,
                    'en_text': eg['texts'][j] if j < len(eg['texts']) else '',
                    'confidence': conf,
                    'npc': npc,
                    'func_id': fid,
                    'zh_func_id': zg['func_id'],
                    'en_func_id': eg['func_id'],
                })
            # A matched group can still have extra segments on one side (the
            # ZH localization often merges several EN lines into one segment).
            # Emit the overflow as unpaired rows rather than silently dropping
            # them (e.g. Iolo's func 0x0401 "Lo and behold!" line, EN seg 2/3).
            # Skip segments already emitted so duplicate source rows (same
            # offset_key+segment, identical text) do not become duplicate keys.
            for j in range(seg_count, len(eg['segs'])):
                en_seg = eg['segs'][j]
                if (eg['offset_key'], en_seg) in emitted_en:
                    continue
                emitted_en.add((eg['offset_key'], en_seg))
                all_entries.append({
                    'zh_offset_key': '', 'zh_segment': 0, 'zh_text': '',
                    'en_offset_key': eg['offset_key'],
                    'en_segment': en_seg,
                    'en_text': eg['texts'][j],
                    'confidence': 'unpaired_en',
                    'npc': npc,
                    'func_id': fid,
                    'zh_func_id': '',
                    'en_func_id': eg['func_id'],
                })
                match_stats['unpaired_en'] += 1
            for j in range(seg_count, len(zg['segs'])):
                zh_seg = zg['segs'][j]
                if (zg['offset_key'], zh_seg) in emitted_zh:
                    continue
                emitted_zh.add((zg['offset_key'], zh_seg))
                all_entries.append({
                    'zh_offset_key': zg['offset_key'],
                    'zh_segment': zh_seg,
                    'zh_text': zg['texts'][j],
                    'en_offset_key': '', 'en_segment': 0, 'en_text': '',
                    'confidence': 'unpaired_zh',
                    'npc': npc,
                    'func_id': fid,
                    'zh_func_id': zg['func_id'],
                    'en_func_id': '',
                })
                match_stats['unpaired_zh'] += 1
        
        for eg in en_unpaired:
            for j, txt in enumerate(eg['texts']):
                all_entries.append({
                    'zh_offset_key': '', 'zh_segment': 0, 'zh_text': '',
                    'en_offset_key': eg['offset_key'],
                    'en_segment': eg['segs'][j],
                    'en_text': txt,
                    'confidence': 'unpaired_en',
                    'npc': npc,
                    'func_id': fid,
                    'zh_func_id': '',
                    'en_func_id': eg['func_id'],
                })
                match_stats['unpaired_en'] += 1
        
        for zg in zh_unpaired:
            for j, txt in enumerate(zg['texts']):
                all_entries.append({
                    'zh_offset_key': zg['offset_key'],
                    'zh_segment': zg['segs'][j],
                    'zh_text': txt,
                    'en_offset_key': '', 'en_segment': 0, 'en_text': '',
                    'confidence': 'unpaired_zh',
                    'npc': npc,
                    'func_id': fid,
                    'zh_func_id': zg['func_id'],
                    'en_func_id': '',
                })
                match_stats['unpaired_zh'] += 1
    
    print(f"  Alignment results: {dict(match_stats)}", file=sys.stderr)
    
    # Load existing review data to preserve review fields
    print("Loading existing review data...", file=sys.stderr)
    with open(args.input, encoding='utf-8') as f:
        review_data = json.load(f)
    
    # Build index of existing entries by (npc, zh_offset_key, zh_segment, en_offset_key, en_segment, zh_func_id, en_func_id)
    # to preserve voice_gender, voice_age, voice_prompt, tone, etc.
    # Includes func_id to prevent collisions when different dialogue functions share the same offset keys.
    existing_index = {}
    for e in review_data:
        key = (e.get('npc', ''), e.get('zh_offset_key', ''), e.get('zh_segment', 0),
               e.get('en_offset_key', ''), e.get('en_segment', 0),
               e.get('zh_func_id', ''), e.get('en_func_id', ''))
        existing_index[key] = e
    
    # ── Match review fields to realigned entries ──
    def find_existing_entry(npc, zh_off, en_off, zh_seg=0, en_seg=0, zh_func='', en_func=''):
        """Find matching entry in existing review data."""
        # Exact match (now includes segment and func_id)
        key = (npc, zh_off, zh_seg, en_off, en_seg, zh_func, en_func)
        if key in existing_index:
            return existing_index[key]
        # Fallback: same en_offset_key and en_segment (prefer same func_id)
        candidate = None
        for k, v in existing_index.items():
            if k[0] == npc and k[3] == en_off and k[4] == en_seg:
                if k[5] == zh_func and k[6] == en_func:
                    return v
                if candidate is None:
                    candidate = v
        if candidate:
            return candidate
        # Fallback: same zh_offset_key and zh_segment (prefer same func_id)
        candidate = None
        for k, v in existing_index.items():
            if k[0] == npc and k[1] == zh_off and k[2] == zh_seg:
                if k[5] == zh_func and k[6] == en_func:
                    return v
                if candidate is None:
                    candidate = v
        if candidate:
            return candidate
        return None
    
    # ── Build output ──
    output = []
    for i, entry in enumerate(all_entries):
        npc = entry['npc']
        zh_off = entry['zh_offset_key']
        en_off = entry['en_offset_key']
        
        # Try to preserve review fields
        existing = find_existing_entry(npc, zh_off, en_off, entry.get('zh_segment', 0), entry.get('en_segment', 0),
                                        entry.get('zh_func_id', ''), entry.get('en_func_id', ''))
        if existing:
            new_entry = dict(existing)
            # Update text from realigned data
            new_entry['npc'] = npc
            new_entry['zh_offset_key'] = zh_off
            new_entry['zh_segment'] = entry['zh_segment']
            new_entry['zh_text'] = entry['zh_text']
            new_entry['en_offset_key'] = en_off
            new_entry['en_segment'] = entry['en_segment']
            new_entry['en_text'] = entry['en_text']
            new_entry['zh_func_id'] = entry.get('zh_func_id', '')
            new_entry['en_func_id'] = entry.get('en_func_id', '')
            if not args.keep_confidence:
                new_entry['confidence'] = entry['confidence']
            new_entry['index'] = i
        else:
            # Create new entry from alignment data
            new_entry = {
                'index': i,
                'npc': npc,
                'zh_offset_key': zh_off,
                'zh_segment': entry['zh_segment'],
                'zh_text': entry['zh_text'],
                'en_offset_key': en_off,
                'en_segment': entry['en_segment'],
                'en_text': entry['en_text'],
                'confidence': entry['confidence'],
                'voice_gender': '',
                'voice_age': '',
                'voice_prompt': '',
                'voice_lang': 'en',
                'tone': 'neutral',
                'tone_instruct': '',
                'zh_func_id': entry.get('zh_func_id', ''),
                'en_func_id': entry.get('en_func_id', ''),
            }
        
        # ── Tag replacement ──
        if not args.no_tag_replace:
            orig_zh = new_entry['zh_text']
            orig_en = new_entry['en_text']
            
            has_tags = any(t in (orig_zh + orig_en) for t in 
                          ['<PLAYER_NAME>', '<HONORIFIC>', '<VAR>', '<PRONOUN>', '<GENDER_FLAG>'])
            
            if has_tags:
                var_cls = classify_var_en(orig_en) if '<VAR>' in (orig_zh + orig_en) else None
                new_entry['zh_text_raw'] = orig_zh.replace('^', '')
                new_entry['en_text_raw'] = orig_en.replace('^', '')
                new_entry['zh_text'] = replace_tags_in_text(orig_zh, 'zh', var_cls)
                new_entry['en_text'] = replace_tags_in_text(orig_en, 'en', var_cls)
                if var_cls:
                    new_entry['var_class'] = var_cls
            else:
                # No tags — clear any stale raw fields inherited from wrong existing entry
                new_entry.pop('en_text_raw', None)
                new_entry.pop('zh_text_raw', None)
                new_entry.pop('var_class', None)
        
        output.append(new_entry)
    
    validate_output_runtime_keys(output, args.en, args.zh)

    # ── Write output ──
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    # Stats
    total = len(output)
    tagged = sum(1 for e in output if any(t in e.get('en_text_raw', e.get('en_text', ''))
                 for t in ['<PLAYER_NAME>', '<HONORIFIC>', '<VAR>', '<PRONOUN>', '<GENDER_FLAG>']))
    var_classes = Counter(e.get('var_class', 'none') for e in output if 'var_class' in e)
    
    print(f"\nFile written: {args.output}", file=sys.stderr)
    print(f"  Total entries: {total}", file=sys.stderr)
    print(f"  Entries with tags: {tagged}", file=sys.stderr)
    print(f"  VAR classifications: {dict(var_classes)}", file=sys.stderr)
    print(f"  Unpaired EN: {match_stats.get('unpaired_en', 0)}", file=sys.stderr)
    print(f"  Unpaired ZH: {match_stats.get('unpaired_zh', 0)}", file=sys.stderr)
    
    # Show some samples
    print("\nSamples:", file=sys.stderr)
    tag_entries = [e for e in output if 'var_class' in e and e['var_class'] != 'none']
    for cls in ['number', 'player_name', 'npc_name', 'title']:
        examples = [e for e in tag_entries if e.get('var_class') == cls][:2]
        if examples:
            print(f"\n  {cls}:", file=sys.stderr)
            for ex in examples:
                print(f"    EN raw: {ex.get('en_text_raw', ex['en_text'])[:80]}", file=sys.stderr)
                print(f"    EN tts: {ex['en_text'][:80]}", file=sys.stderr)
                print(f"    ZH raw: {ex.get('zh_text_raw', ex['zh_text'])[:80]}", file=sys.stderr)
                print(f"    ZH tts: {ex['zh_text'][:80]}", file=sys.stderr)


if __name__ == '__main__':
    main()
