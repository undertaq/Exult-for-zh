#!/usr/bin/env python3
"""Add zh_raw/en_raw fields, replace tags in zh_text with TTS text,
fix archaic contractions in en_text for TTS pronunciation,
and balance dialogue delimiters across segments."""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# Import tag replacement logic from fix_alignment_and_tags
sys.path.insert(0, str(Path(__file__).parent))
import fix_alignment_and_tags as fixmod

# ── Usecode variable resolution ──────────────────────────────────────
# Lazily loaded to avoid overhead when --usecode-en is not provided
_usecode_var_lookup = None

def remove_0x_prefix(s: str) -> str:
    """Remove leading 0x prefix from a hex string, handling 0x0 correctly."""
    s = s.lower()
    if s.startswith('0x'):
        s = s[2:]
    return s if s else '0'


def _load_usecode_var_lookup(usecode_en_path):
    """Load EN usecode and build a lookup from (func_id, offset_key, segment)
    to (list_of_en_values, list_of_zh_values) for per-VAR resolution.

    Each list has one element per <VAR> in the say-line, in the order
    the variables appear in the template.
    """
    import struct
    from disassemble_usecode import (
        parse_function, disassemble_function, extract_say_lines,
        trace_variable_sources, skip_symbol_table,
    )

    with open(usecode_en_path, 'rb') as f:
        data = f.read()

    offset = skip_symbol_table(data, 0)
    functions = {}
    while offset < len(data):
        try:
            func_id, func_data, extended, next_offset = parse_function(data, offset)
            functions[func_id] = (func_data, extended)
            offset = next_offset
        except (struct.error, IndexError):
            break

    lookup = {}
    for func_id, (fdata, extended) in functions.items():
        try:
            func = disassemble_function(func_id, fdata, extended)
        except (struct.error, IndexError, ValueError):
            continue

        var_sources = trace_variable_sources(func)
        say_lines = extract_say_lines(func)

        for line in say_lines:
            var_info = line.get('var_info', [])
            if not var_info:
                continue
            en_values = [v['en'] for v in var_info]
            zh_values = [v['zh'] for v in var_info]
            # Normalize offset_key to match JSON storage (strip 0x)
            raw_key = line['offset_key']
            normalized_key = '_'.join(
                remove_0x_prefix(p) for p in raw_key.split('_')
            )
            key = (func_id, normalized_key, line['segment'])
            lookup[key] = (en_values, zh_values)

    return lookup

def get_var_resolutions(entry, usecode_var_lookup):
    """Return (en_replacements, zh_replacements) for a mapping entry,
    or (None, None) if no per-VAR info is available."""
    func_id_str = entry.get('en_func_id', '')
    if not func_id_str:
        return None, None

    func_id = int(func_id_str, 16) if func_id_str.startswith('0x') else int(func_id_str)
    offset_key = entry.get('en_offset_key', '')
    segment = entry.get('en_segment', 0)

    key = (func_id, offset_key, segment)
    val = usecode_var_lookup.get(key)
    return val if val else (None, None)

# ── Archaic contraction replacements (pronunciation-affecting only) ──

# Order matters: longer matches first to avoid partial replacement
ARCHAIC_CONTRACTIONS_EN = [
    # 'T... forms — the apostrophe makes TTS say "t" instead of "It"
    (r"'Tisn't", "It is not"),
    (r"'Tis", "It is"),
    (r"'Twasn't", "It was not"),
    (r"'Twas", "It was"),
    (r"'Twouldn't", "It would not"),
    (r"'Twould", "It would"),
    (r"'Twilln't", "It will not"),
    (r"'Twill", "It will"),
    (r"'Twere", "It were"),
    # Other contractions that affect pronunciation
    (r"'em\b", "them"),        # "give 'em" → "give them"
    (r"ne'er\b", "never"),     # "ne'er" → "never"
    (r"e'er\b", "ever"),       # "e'er" → "ever"
    (r"o'er\b", "over"),       # "o'er" → "over"
    (r"e'en\b", "even"),       # "e'en" → "even"
    (r"'til\b", "until"),      # "'til" → "until"
    (r"ma'am\b", "madam"),     # "ma'am" → "madam" (more natural TTS)
]

# Archaic verbs — only those where the archaic form would sound wrong
# Keeping thou/thee/thy/thine/thyself as-is (user confirmed they don't affect pronunciation)
# But verb forms like "doth" → "does" matter for grammar in TTS
ARCHAIC_VERBS = [
    (r'\bdoth\b', 'does'),
    (r'\bdost\b', 'do'),
    (r'\bhath\b', 'has'),
    (r'\bhast\b', 'have'),
    (r'\bcanst\b', 'can'),
    (r'\bcouldst\b', 'could'),
    (r'\bwouldst\b', 'would'),
    (r'\bshouldst\b', 'should'),
    (r'\bmayest\b', 'may'),
    (r'\bmightst\b', 'might'),
    (r'\bwilt\b', 'will'),
    (r'\bshalt\b', 'shall'),
    (r'\bthou\s+art\b', 'you are'),
]

# Archaic pronouns — replace with modern equivalents for TTS
# These affect naturalness (TTS would pronounce them correctly but sound dated)
ARCHAIC_PRONOUNS = [
    (r'\bthou\b', 'you'),
    (r'\bthee\b', 'you'),
    (r'\bthy\b', 'your'),
    # "thine eyes" → "your eyes" (determiner before vowel)
    (r'\bthine (?=[a-zA-Z])', 'your '),
    # "it is thine" → "it is yours" (possessive pronoun)
    (r'\bthine\b', 'yours'),
    (r'\bthyself\b', 'yourself'),
    (r'\bye\b', 'you'),
]

def fix_archaic_contractions(text: str) -> str:
    """Replace archaic contractions that affect TTS pronunciation."""
    if not text:
        return text
    result = text
    for pattern, replacement in ARCHAIC_CONTRACTIONS_EN:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result

def fix_archaic_verbs(text: str) -> str:
    """Replace archaic verb forms that would sound wrong in TTS."""
    if not text:
        return text
    result = text
    for pattern, replacement in ARCHAIC_VERBS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result

def fix_archaic_pronouns(text: str) -> str:
    """Modernize archaic pronouns for TTS naturalness."""
    if not text:
        return text
    result = text
    for pattern, replacement in ARCHAIC_PRONOUNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


# ── Punctuation for Chinese whitespace normalization ──
ZH_CLOSING_PUNCT = r'。，！？」、；：，．）】】》\u201d\uff09'
ZH_OPENING_PUNCT = r'「「（【【《\u201c\uff08'

def normalize_zh_whitespace(text: str) -> str:
    """Remove unnecessary spaces in Chinese text for natural TTS."""
    if not text:
        return text
    result = text
    # Remove spaces before closing punctuation
    result = re.sub(r'\s+([' + ZH_CLOSING_PUNCT + r'])', r'\1', result)
    # Remove spaces after opening punctuation
    result = re.sub(r'([' + ZH_OPENING_PUNCT + r'])\s+', r'\1', result)
    # Remove spaces between two CJK characters (caused by tag replacement)
    result = re.sub(r'([\u4e00-\u9fff])\s+([\u4e00-\u9fff])', r'\1\2', result)
    # Remove spaces between CJK and opening/closing punct
    result = re.sub(r'([\u4e00-\u9fff])\s+(' + ZH_CLOSING_PUNCT + r')', r'\1\2', result)
    result = re.sub(r'(' + ZH_OPENING_PUNCT + r')\s+([\u4e00-\u9fff])', r'\1\2', result)
    return result

def normalize_en_whitespace(text: str) -> str:
    """Normalize English whitespace for TTS."""
    if not text:
        return text
    result = text
    # Remove space before punctuation (not quotes — distinguish opening/closing is complex)
    result = re.sub(r'\s+([.,!?;:])', r'\1', result)
    # Remove space after opening bracket
    result = re.sub(r'([(])\s+', r'\1', result)
    # Collapse double+ spaces (from removed tags etc.)
    result = re.sub(r'  +', ' ', result)
    # Fix redundant determiner from tag replacement
    result = re.sub(r'\bthis this person\b', 'this person', result, flags=re.IGNORECASE)
    # Fix spacing: tag replacement words merged with preceding word
    # e.g., "travellerAvatar" → "traveller Avatar", "AvatarAvatar" → "Avatar Avatar"
    # Use lookbehind (doesn't consume overlapping matches) 
    for word in ['Avatar', 'this person', 'some', 'woodsman']:
        result = re.sub(rf'(?<=[a-zA-Z]){re.escape(word)}', rf' {word}', result)
    return result


# ── Known runtime-variable resolutions (from usecode analysis) ──
# Some entries have <VAR> that are runtime string variables, not player names.
# These offsets + the raw tag pattern identify which entries need special handling.
KNOWN_VAR_RESOLUTIONS_RAW = {
    # func 0x04E5 (Budo), offset 261_1f2_1f2_1f2:
    # Three <VAR> = var0005 + var0006 + var0007 concatenated at runtime
    # EN: "thou shouldst come to my shoppe when " + "it is open! I would be so pleased to " + "help thee then."
    # ZH: "請你在" + "我們營業時再來！我將" + "非常樂意在那時幫助你。"
    6431: (
        "you should come to my shoppe when it is open! I would be so pleased to help you then.",
        "請你在我們營業時再來！我將非常樂意在那時幫助你。",
    ),
    # func 0x0876 (Denton), offset 122_125:
    # Single <VAR> at sentence start followed by period — VAR is a generic
    # npc_name placeholder ("this person"/"那個人") that reads awkwardly.
    # Better to omit entirely.
    7723: ("remove_leading_var", "remove_leading_var"),
}

# Replacement words that can be duplicated from consecutive tag replacements
EN_REPLACEMENT_WORDS = ['Avatar', 'this person', 'some', 'woodsman']
ZH_REPLACEMENT_WORDS = ['聖者', '那個人', '一些', '遊俠']


def fix_known_var_entries(entry: dict) -> tuple[str, str]:
    """Replace tag-generated duplicate text with resolved variable text
    for entries where we know the runtime variable values."""
    idx = entry.get('index')
    if idx not in KNOWN_VAR_RESOLUTIONS_RAW:
        return entry.get('en_text', ''), entry.get('zh_text', '')

    en_fix, zh_fix = KNOWN_VAR_RESOLUTIONS_RAW[idx]

    en_text = entry.get('en_text', '') or ''
    zh_text = entry.get('zh_text', '') or ''

    if en_fix == 'remove_leading_var':
        # Remove leading generic placeholder (e.g. "this person. " / "那個人。")
        # from the start of the text — the VAR at sentence start reads awkwardly.
        import re
        en_text = re.sub(r'^"[^a-z]*this person\.\s*', '"', en_text)
        en_text = re.sub(r'^[^a-z]*this person\.\s*', '', en_text)
        zh_text = re.sub(r'^「那個人。', '「', zh_text)
        zh_text = re.sub(r'^那個人。', '', zh_text)
        return en_text, zh_text

    # EN: find the duplicate-Avatar part and replace with resolved text
    for old in ['Avatar Avatar Avatar', 'Avatar Avatar']:
        if old in en_text:
            en_text = en_text.replace(old, en_fix, 1)
            break

    # ZH: find the duplicate-聖者 part
    for old in ['聖者聖者聖者', '聖者聖者']:
        if old in zh_text:
            zh_text = zh_text.replace(old, zh_fix, 1)
            break

    return en_text, zh_text


def collapse_dup(text: str, words: list[str], lang: str = 'en') -> str:
    """Collapse consecutive duplicate replacement words.
    EN: "Avatar Avatar" → "Avatar"  (spaces between)
    ZH: "聖者聖者" → "聖者"  (no spaces)"""
    if not text:
        return text
    result = text
    for word in words:
        if lang == 'zh':
            while word * 2 in result:
                result = result.replace(word * 2, word)
        else:
            # Collapse any number of consecutive "Word Word" → "Word"
            pattern = rf'\b{re.escape(word)}(?:\s+{re.escape(word)}\b)+'
            result = re.sub(pattern, word, result)
    return result


def load_en_csv(path: Path) -> dict[str, str]:
    """Load EN CSV into a dict keyed by func_id_offset_key_segment.
    Normalizes keys by stripping 0x prefix for matching with JSON."""
    mapping = {}
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            func = row['func_id'].lower().replace('0x', '')
            offset = row['offset_key'].lower()
            # Handle multi-keys like "0x79_0x7c"
            if '_' in offset:
                parts = offset.split('_')
                offset = '_'.join(p.lstrip('0x') for p in parts)
            else:
                offset = offset.lstrip('0x')
            seg = row['segment']
            key = f"{func}_{offset}_{seg}"
            mapping[key] = row['text']
    return mapping


def classify_var_in_entry(en_text_with_tags: str) -> str:
    """Classify <VAR> in the raw EN text using the existing classifier."""
    if not en_text_with_tags:
        return 'player_name'
    return fixmod.classify_var_en(en_text_with_tags)


# Mapping from EN per-VAR values (from usecode tracing) to ZH equivalents.
# Only meaningful values are mapped; usecode false positives (verbs, pronouns,
# fragments) are NOT included — they fall back to the generic class placeholder.
_EN_VAR_TO_ZH = {
    'valiant warrior': '英勇的戰士',
    'Elizabeth': '伊莉莎白',
    'Paulette': 'Paulette',
    'the mage Erethian': '法師 Erethian',
    'The barkeep': '酒館老闆',
    'the blade': '這把劍',
    'the barmaid, Paulette': '酒吧女侍 Paulette',
    'If thou wouldst like, I would be happy to give thee a dozen of my special arrows. Art thou interested?':
        '如果你願意，我很樂意給你一打我特製的箭。你有興趣嗎？',
    'Be most careful. Who knows what may be lurking amongst the trees...':
        '務必小心。誰知道樹林間潛伏著什麼……',
    'It is most fortunate that thou fell so near our shelter. Thou must have a protector watching over thee.@':
        '你跌倒在我們避難所附近真是太幸運了。你必定有守護者在看顧著你。',
}

def en_var_to_zh(en_value: str, var_class: str) -> str:
    """Translate an EN per-VAR replacement value to ZH.

    Falls back to the generic class-based placeholder when the EN value
    is not in the known translation table (handles usecode false positives).
    """
    if en_value in _EN_VAR_TO_ZH:
        return _EN_VAR_TO_ZH[en_value]
    return fixmod.var_replacement_zh(var_class)


def replace_zh_tags(zh_text: str, var_class: str = None, var_replacements: list[str] = None) -> str:
    """Replace all ZH tags with TTS-friendly text.

    Uses per-VAR replacement list when provided, otherwise falls back
    to single-class replacement.
    """
    if not zh_text:
        return zh_text
    # Use per-VAR resolution if available
    result = fixmod.replace_tags_in_text(
        zh_text, 'zh',
        var_class=var_class,
        var_replacements=var_replacements,
    )
    # Post-processing: fix 「這那個人」→「這個人」 (demonstrative clash)
    result = result.replace('這那個人', '這個人')
    return result


def check_delimiter_balance(text: str, lang: str) -> tuple[bool, str]:
    """Check if dialogue delimiters are balanced in a text entry.
    Returns (is_balanced, issue_description)."""
    if not text:
        return True, ""
    if lang == 'zh':
        opens = text.count('「')
        closes = text.count('」')
        if opens != closes:
            return False, f"「」unbalanced: {opens} open vs {closes} close"
        # Check for colon before opening quote (should use 「 not ：「)
        if re.search(r'[：:]「', text):
            return True, ""  # This is acceptable typography
        return True, ""
    else:
        # EN uses ""
        opens = text.count('"')
        if opens % 2 != 0:
            return False, f"\" unbalanced: {opens} total"
        return True, ""


def balance_segment_delimiters(text: str, lang: str) -> str:
    """Fix unbalanced delimiters in a single segment.
    For multi-segment entries, each segment should be self-balanced for TTS."""
    if not text:
        return text
    if lang == 'zh':
        opens = text.count('「')
        closes = text.count('」')
        if opens > closes:
            text += '」' * (opens - closes)
        elif closes > opens:
            text = '「' * (closes - opens) + text
    return text


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Prepare TTS fields in bilingual mapping")
    parser.add_argument("--usecode-en", type=str, default=None,
                        help="Path to EN usecode binary for per-VAR resolution")
    parser.add_argument("--mapping", type=str,
                        default="tools/voice_acting/bilingual_mapping_review.json",
                        help="Path to bilingual mapping JSON")
    parser.add_argument("--en-csv", type=str, default="tools/voice_acting/_live/en.csv",
                        help="Path to EN voice lines CSV")
    args = parser.parse_args()

    mapping_path = Path(args.mapping)
    en_csv_path = Path(args.en_csv)
    
    print("Loading JSON mapping...")
    with open(mapping_path, encoding='utf-8') as f:
        data = json.load(f)
    
    # Load usecode for per-VAR resolution if requested
    var_lookup = None
    if args.usecode_en:
        usecode_path = Path(args.usecode_en)
        if usecode_path.exists():
            print(f"Loading usecode from {usecode_path} for per-VAR resolution...")
            var_lookup = _load_usecode_var_lookup(str(usecode_path))
            print(f"  Loaded {len(var_lookup)} say-lines with variable info")
        else:
            print(f"Warning: usecode.en not found at {usecode_path}", file=sys.stderr)
    
    print("Loading EN CSV for raw text...")
    en_raw_map = load_en_csv(en_csv_path)
    
    # Track stats
    stats = {
        'en_raw_set': 0,
        'en_raw_missing': 0,
        'zh_raw_set': 0,
        'zh_tags_replaced': 0,
        'en_contractions_fixed': 0,
        'en_verbs_fixed': 0,
        'en_pronouns_fixed': 0,
        'zh_whitespace_fixed': 0,
        'en_whitespace_fixed': 0,
        'var_entries_fixed': 0,
        'en_dup_collapsed': 0,
        'zh_dup_collapsed': 0,
        'zh_delim_fixed': 0,
        'en_delim_fixed': 0,
        'var_classified': {'number': 0, 'player_name': 0, 'npc_name': 0, 'title': 0},
    }
    
    # Build segment groups for delimiter balancing
    zh_groups = defaultdict(list)
    for idx, entry in enumerate(data):
        if entry.get('zh_func_id') and entry.get('zh_offset_key') and entry.get('zh_segment') is not None:
            key = (entry['zh_func_id'], entry['zh_offset_key'])
            zh_groups[key].append(idx)
    
    print(f"Processing {len(data)} entries...")
    
    for entry in data:
        idx = entry['index']
        
        # ── Step 1: Set en_raw from EN CSV (only if not already set) ──
        if 'en_raw' not in entry:
            en_func = entry.get('en_func_id', '').lower().replace('0x', '')
            en_off = entry.get('en_offset_key', '')
            en_key = f"{en_func}_{en_off}_{entry.get('en_segment', 0)}"
            raw_en = en_raw_map.get(en_key)
            if raw_en:
                entry['en_raw'] = raw_en
                stats['en_raw_set'] += 1
            else:
                # Fallback: use current en_text as raw
                entry['en_raw'] = entry.get('en_text', '')
                stats['en_raw_missing'] += 1
        
        # ── Step 2: Set zh_raw from zh_text + zh_raw (only if not already set) ──
        if 'zh_raw' not in entry:
            entry['zh_raw'] = entry.get('zh_text', '')
            stats['zh_raw_set'] += 1
        
        # ── Step 3: Replace tags in zh_text (use existing single-class approach) ──
        source = entry.get('zh_raw', entry.get('zh_text', ''))
        if re.search(r'<[^>]+>', source):
            var_class = classify_var_in_entry(entry.get('en_raw', ''))
            stats['var_classified'][var_class] = stats['var_classified'].get(var_class, 0) + 1
            new_zh = replace_zh_tags(source, var_class=var_class)
            entry['zh_text'] = new_zh
            stats['zh_tags_replaced'] += 1

        # ── Step 3b: Replace tags using per-VAR resolution from usecode ──
        if var_lookup is not None and '<VAR>' in entry.get('en_raw', ''):
            # Skip per-VAR override for number-classified VARs: the usecode
            # tracer often resolves these to player_name (e.g. "pays you
            # <VAR> gold coins" → Avatar), but context demands "some"/数字.
            existing_class = entry.get('var_class')
            if existing_class == 'number':
                stats['var_entries_fixed'] += 1  # count as resolved (correctly)
            else:
                en_repls, zh_repls = get_var_resolutions(entry, var_lookup)
                if en_repls is not None:
                    entry['en_text'] = fixmod.replace_tags_in_text(
                        entry.get('en_raw', ''), 'en',
                        var_replacements=en_repls,
                    )
                    stats['var_entries_fixed'] += 1
                    # Also apply per-VAR resolution to ZH text, using the
                    # usecode's ZH values directly (from game data). When
                    # the usecode ZH value is empty or a class fallback,
                    # translate from the EN value via en_var_to_zh().
                    # Use zh_text_raw (authoritative tag source) in preference
                    # to zh_raw (which may have been set from already-replaced text).
                    zh_source = entry.get('zh_text_raw') or entry.get('zh_raw') or ''
                    if '<VAR>' in zh_source and zh_repls:
                        zh_repls_resolved = []
                        for i, v in enumerate(en_repls):
                            z = zh_repls[i] if i < len(zh_repls) else ''
                            if z:
                                zh_repls_resolved.append(z)
                            else:
                                zh_repls_resolved.append(
                                    en_var_to_zh(v, existing_class or 'player_name'))
                        entry['zh_text'] = fixmod.replace_tags_in_text(
                            zh_source, 'zh',
                            var_replacements=zh_repls_resolved,
                        )
        
        # ── Step 3c: Clean up tag-replacement artifacts ──
        en_text = entry.get('en_text', '')
        # "the Avatar, Avatar!" (inverted — raw "the Avatar, <PLAYER_NAME>!")
        new_en = re.sub(r'the Avatar, Avatar\b', 'the Avatar', en_text)
        # "Avatar, the Avatar" → "the Avatar" (raw "<PLAYER_NAME>, the Avatar")
        new_en = re.sub(r'Avatar, the Avatar\b', 'the Avatar', new_en)
        # "Avatar.Avatar" — missing space from "<PLAYER_NAME>.<VAR>"
        new_en = re.sub(r'Avatar\.(?=[A-Z])', 'Avatar. ', new_en)
        # Capitalize "milord" at sentence start (from <HONORIFIC> after period)
        new_en = re.sub(r'([.!?][\'"]?\s+)milord\b', lambda m: m.group(1) + 'Milord', new_en)
        new_en = re.sub(r'^milord\b', 'Milord', new_en)
        new_en = re.sub(r'\"milord\b', '"Milord', new_en)
        if new_en != en_text:
            entry['en_text'] = new_en
        zh_text = entry.get('zh_text', '')
        new_zh = re.sub(r'聖者，[是]?聖者', '聖者', zh_text)
        if new_zh != zh_text:
            entry['zh_text'] = new_zh
        
        # ── Step 4: Fix archaic contractions in en_text ──
        en_text = entry.get('en_text', '')
        fixed_en = fix_archaic_contractions(en_text)
        if fixed_en != en_text:
            entry['en_text'] = fixed_en
            stats['en_contractions_fixed'] += 1
        
        fixed_en2 = fix_archaic_verbs(entry.get('en_text', ''))
        if fixed_en2 != entry.get('en_text', ''):
            entry['en_text'] = fixed_en2
            stats['en_verbs_fixed'] += 1

        fixed_en3 = fix_archaic_pronouns(entry.get('en_text', ''))
        if fixed_en3 != entry.get('en_text', ''):
            entry['en_text'] = fixed_en3
            stats['en_pronouns_fixed'] += 1
    
    # ── Step 5: Normalize whitespace (after tag replacement) ──
    for entry in data:
        new_zh = normalize_zh_whitespace(entry.get('zh_text', ''))
        if new_zh != entry.get('zh_text', ''):
            entry['zh_text'] = new_zh
            stats['zh_whitespace_fixed'] += 1
        new_en = normalize_en_whitespace(entry.get('en_text', ''))
        if new_en != entry.get('en_text', ''):
            entry['en_text'] = new_en
            stats['en_whitespace_fixed'] += 1
    
    # ── Step 5b: Fix ZH counter-word collision with 一些 (number VAR after whitespace norm) ──
    # EN "some gold" → ZH should be "一些金幣", not "一些枚金幣".
    for entry in data:
        zh_text = entry.get('zh_text', '')
        new_zh = re.sub(r'一些[枚個支]', '一些', zh_text)
        new_zh = re.sub(r'一些個人', '一些人', new_zh)
        if new_zh != zh_text:
            entry['zh_text'] = new_zh
    
    # ── Step 6: Fix known VAR entries and collapse duplicate replacements ──
    for entry in data:
        old_en = entry.get('en_text', '') or ''
        old_zh = entry.get('zh_text', '') or ''

        # Resolve known runtime-variable entries
        new_en, new_zh = fix_known_var_entries(entry)
        if new_en != old_en or new_zh != old_zh:
            entry['en_text'] = new_en
            entry['zh_text'] = new_zh
            stats['var_entries_fixed'] += 1

        # Collapse consecutive duplicates from tag replacement
        new_en = collapse_dup(entry.get('en_text', ''), EN_REPLACEMENT_WORDS, 'en')
        if new_en != entry.get('en_text', ''):
            entry['en_text'] = new_en
            stats['en_dup_collapsed'] += 1
        new_zh = collapse_dup(entry.get('zh_text', ''), ZH_REPLACEMENT_WORDS, 'zh')
        if new_zh != entry.get('zh_text', ''):
            entry['zh_text'] = new_zh
            stats['zh_dup_collapsed'] += 1
    
    # ── Step 7: Balance delimiters ──
    # Balance every entry's delimiters for TTS (each segment spoken independently)
    for entry in data:
        zh_text = entry.get('zh_text', '')
        balanced, issue = check_delimiter_balance(zh_text, 'zh')
        if not balanced:
            entry['zh_text'] = balance_segment_delimiters(zh_text, 'zh')
            stats['zh_delim_fixed'] += 1
    
    # EN delimiter balance (simpler: just balance each entry)
    for entry in data:
        en_text = entry.get('en_text', '')
        if en_text and en_text.count('"') % 2 != 0:
            # Add closing quote
            entry['en_text'] = en_text + '"'
            stats['en_delim_fixed'] += 1
    
    # ── Save ──
    print(f"  en_raw set: {stats['en_raw_set']} (missing: {stats['en_raw_missing']})")
    print(f"  zh_raw set: {stats['zh_raw_set']}")
    print(f"  zh tags replaced: {stats['zh_tags_replaced']}")
    print(f"  VAR classified: {stats['var_classified']}")
    print(f"  en archaic contractions fixed: {stats['en_contractions_fixed']}")
    print(f"  en archaic verbs fixed: {stats['en_verbs_fixed']}")
    print(f"  en archaic pronouns fixed: {stats['en_pronouns_fixed']}")
    print(f"  zh whitespace normalized: {stats['zh_whitespace_fixed']}")
    print(f"  en whitespace normalized: {stats['en_whitespace_fixed']}")
    print(f"  known var entries fixed: {stats['var_entries_fixed']}")
    print(f"  en dup collapsed: {stats['en_dup_collapsed']}")
    print(f"  zh dup collapsed: {stats['zh_dup_collapsed']}")
    print(f"  zh delimiter fixes: {stats['zh_delim_fixed']}")
    print(f"  en delimiter fixes: {stats['en_delim_fixed']}")
    
    with open(mapping_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f"Wrote {mapping_path}")
    
    # ── Final verification ──
    tag_re = re.compile(r'<[^>]+>')
    zh_tags_remaining = sum(1 for e in data if tag_re.search(e.get('zh_text', '') or ''))
    en_tags_remaining = sum(1 for e in data if tag_re.search(e.get('en_text', '') or ''))
    zh_delim_unbal = 0
    en_delim_unbal = 0
    for e in data:
        if not check_delimiter_balance(e.get('zh_text', ''), 'zh')[0]:
            zh_delim_unbal += 1
        if e.get('en_text', '') and e['en_text'].count('"') % 2 != 0:
            en_delim_unbal += 1
    
    print()
    print("=== VERIFICATION ===")
    print(f"  Tags remaining in zh_text: {zh_tags_remaining}")
    print(f"  Tags remaining in en_text: {en_tags_remaining}")
    print(f"  ZH delimiter imbalance:    {zh_delim_unbal}")
    print(f"  EN delimiter imbalance:    {en_delim_unbal}")
    
    # Check that en_raw has tags (proving it came from CSV)
    en_raw_with_tags = sum(1 for e in data if tag_re.search(e.get('en_raw', '') or ''))
    print(f"  en_raw entries with tags:  {en_raw_with_tags}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
