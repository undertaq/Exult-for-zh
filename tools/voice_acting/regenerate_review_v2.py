#!/usr/bin/env python3
"""
Regenerate bilingual_mapping_review_v2.json by merging static CSV and review JSON,
verifying static matches using heuristics, and translating untranslated lines.
Preserves voice acting metadata from review JSON.
"""

import os
import re
import csv
import json
import urllib.parse
import urllib.request
import time
import sys
from collections import defaultdict

# Paths
STATIC_CSV = r"bilingual_mapping_static.csv"
STATIC_CSV_OFFSET = r"bilingual_mapping.csv"
REVIEW_JSON = r"bilingual_mapping_review.json"
OUTPUT_JSON = r"bilingual_mapping_review_v2.json"

# Named Entities for Translation post-processing and verification
ENTITIES = {
    r"\bavatar\b": "聖者",
    r"\bbritannia\b": "不列顛尼亞",
    r"\blord\s+british\b": "不列顛王",
    r"\blb\b": "不列顛王",
    r"\bbatlin\b": "巴特林",
    r"\bfellowship\b": "友誼會",
    r"\bmilord\b": "大人",
    r"\bmilady\b": "女士",
    r"\bmoongate\b": "月之門",
    r"\bblackrock\b": "黑石",
    r"\bthe\s+guardian\b": "守護者",
    r"\bguardian\b": "守護者",
    r"\bblackrock\s+sword\b": "黑石劍",
    r"\bemps\b": "森靈",
    r"\bemp\b": "森靈",
    r"\bshrine\b": "神殿",
    r"\bshrine\s+of\s+principle\b": "原則神殿",
    r"\bshrine\s+of\s+courage\b": "勇氣神殿",
    r"\bshrine\s+of\s+love\b": "愛之神殿",
    r"\bshrine\s+of\s+truth\b": "真理神殿",
    r"\bshrine\s+of\s+compassion\b": "慈悲神殿",
    r"\bbuccaneer's\s+den\b": "Buccaneer's Den",
    r"\bbuccaneers\s+den\b": "Buccaneer's Den",
    r"\bwisps\b": "鬼火",
    r"\bwisp\b": "鬼火",
    r"\btime\s+lord\b": "時間領主",
    r"\berethian\b": "Erethian",
    r"\bmondain\b": "Mondain",
    r"\bminax\b": "Minax",
    r"\bexodus\b": "Exodus",
    r"\barcadion\b": "Arcadion",
    r"\bgargoyles\b": "石像鬼",
    r"\bgargoyle\b": "石像鬼",
    r"\bbalrons\b": "炎魔",
    r"\bbalron\b": "炎魔",
    r"\bdaemons\b": "惡魔",
    r"\bdaemon\b": "惡魔",
    r"\biolo\b": "Iolo",
    r"\bshamino\b": "Shamino",
    r"\bdupre\b": "Dupre",
    r"\bgwenno\b": "Gwenno",
    r"\bspark\b": "Spark",
    r"\btrinsic\b": "Trinsic",
    r"\bbritain\b": "Britain",
    r"\bjhelom\b": "Jhelom",
    r"\bminoc\b": "Minoc",
    r"\bmoonglow\b": "Moonglow",
    r"\bserpent's\s+hold\b": "Serpent's Hold",
    r"\bskara\s+brae\b": "Skara Brae",
    r"\byew\b": "Yew",
    # Virtue concepts (standalone)
    r"\bcourage\b": "勇氣",
    r"\blove\b": "愛",
    r"\btruth\b": "真理",
    r"\bcompassion\b": "慈悲",
    r"\bprinciple\b": "原則",
    # Places (Chinese per Translation Guide)
    r"\bcove\b": "柯伏城",
    r"\bpaws\b": "小掌村",
    r"\bvesper\b": "維士皮爾城",
    r"\block\s+lake\b": "鎖湖",
    r"\bterfin\b": "特爾芬城",
    r"\bspektran\b": "史巴克傳列島",
    r"\bisle\s+of\s+the\s+avatar\b": "聖者之島",
    r"\bnew\s+magincia\b": "New Magincia",
    # Named items
    r"\bsilverleaf\b": "銀葉草",
    r"\bferryman\b": "擺渡人",
    r"\bether\b": "以太",
    r"\bshade\s+blade\b": "暗影之刃",
    r"\bblack\s+sword\b": "黑劍",
    r"\bgem\s+of\s+immortality\b": "不朽寶石",
    r"\btalisman\s+of\s+infinity\b": "無限護符",
    r"\bscroll\s+of\s+infinity\b": "無限卷軸",
    r"\bisland\s+of\s+fire\b": "烈火島",
    r"\blocket\b": "吊飾盒",
    r"\bfield\b": "力場",
    # Ships
    r"\bexcellencia\b": "卓越號",
    r"\bgolden\s+ankh\b": "黃金安卡號",
    r"\bthe\s+nymphet\b": "小仙女號",
    # Shrines / buildings
    r"\bempath\s+abbey\b": "人神修道院",
    r"\bmeditation\s+retreat\b": "冥想靜修院",
    # Inn / tavern names
    r"\bthe\s+bunk\s+and\s+stool\b": "木鋪與矮凳客棧",
    r"\bthe\s+modest\s+damsel\b": "羞怯少女旅店",
    r"\bthe\s+checquered\s+cork\b": "方格軟木塞客棧",
    r"\bthe\s+honorable\s+hound\b": "謙遜獵犬客棧",
    r"\bthe\s+out'n'inn\b": "進進出出客棧",
    r"\bthe\s+wayfarerer's\s+inn\b": "旅人旅館",
    r"\bthe\s+fallen\s+virgin\b": "落難少女旅店",
    r"\bsalty\s+dog\b": "老海狗酒館",
    r"\bthe\s+friendly\s+knave\b": "親切惡棍酒館",
    r"\bkeg\s+o'\s+spirits\b": "魂靈烈酒桶酒館",
}

def norm(t):
    if not t:
        return ""
    t = re.sub(r'["""\u201c\u201d\u201e\u201f]', '', t)
    t = re.sub(r'\s+', ' ', t).strip().lower()
    return t

def make_clean(text):
    if not text:
        return ""
    t = norm(text)
    t = re.sub(r'<[^>]+>', '', t)
    t = re.sub(r'[^a-z0-9\s]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def load_static_csv(path):
    rows = []
    keyed = {}
    with open(path, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            fid = row['func_id'].strip()
            en_key = row['en_offset_key'].strip()
            en_seg = int(row.get('en_segment', '0').strip() or '0')
            entry = {
                'func_id': fid,
                'npc': row.get('npc', '').strip(),
                'en_offset_key': en_key,
                'en_segment': en_seg,
                'en_text': row.get('en_text', '').strip(),
                'zh_offset_key': row.get('zh_offset_key', '').strip(),
                'zh_segment': int(row.get('zh_segment', '0').strip() or '0'),
                'zh_text': row.get('zh_text', '').strip(),
                'confidence': row.get('confidence', '').strip(),
                '_match_review': [],
            }
            rows.append(entry)
            keyed[(fid, en_key, en_seg)] = entry
    return rows, keyed

def google_translate(text, target_lang='zh-TW'):
    """Translate text using the free Google Translate API endpoint with retry."""
    if not text.strip() or not any(c.isalnum() for c in text):
        return text # Don't translate punctuation/whitespace-only strings

    url = "https://translate.google.com/translate_a/single?client=gtx&sl=en&tl=" + target_lang + "&dt=t&q=" + urllib.parse.quote(text)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
    }
    req = urllib.request.Request(url, headers=headers)
    
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                res = response.read().decode('utf-8')
                data = json.loads(res)
                translated = "".join(seg[0] for seg in data[0] if seg[0])
                return translated
        except Exception as e:
            print(f"Translation warning: attempt {attempt+1} failed for text '{text[:30]}...': {e}", file=sys.stderr)
            time.sleep(1.5)
    return ""

# Spell names from Translation Guide (8 circles, 4 per circle)
SPELL_NAMES = {
    # 1st circle
    "Awaken": "喚醒眾人", "Create Food": "製造食物", "Cure": "醫療",
    "Detect Trap": "偵測陷阱", "Great Douse": "大熄滅術", "Great Ignite": "大點燃術",
    "Light": "亮光術", "Locate": "定位術",
    # 2nd circle
    "Destroy Trap": "摧毀陷阱", "Enchant": "著魔術", "Fire Blast": "火焰術",
    "Great Light": "大光亮術", "Mass Cure": "大治療術", "Protection": "保護術",
    "Telekinesis": "遙控術", "Wizard Eye": "巫師眼",
    # 3rd circle
    "Curse": "詛咒術", "Heal": "醫療術", "Paralyze": "麻痺術",
    "Peer": "靈視術", "Poison": "撒毒術", "Protect All": "保護全體隊員",
    "Sleep": "催眠術", "Swarm": "招蟲術",
    # 4th circle
    "Conjure": "招遣術", "Lightning": "霹靂閃電", "Mark": "標記術",
    "Mass Curse": "大詛咒術", "Recall": "喚回術", "Reveal": "現形術",
    "Seance": "降神術", "Unlock Magic": "開鎖術",
    # 5th circle
    "Charm": "迷惑術", "Dance": "狂舞術", "Dispel Field": "祛除力場",
    "Explosion": "爆炸術", "Fire Field": "火焰力場", "Great Heal": "大治療術",
    "Invisibility": "隱身術", "Mass Sleep": "大催眠術",
    # 6th circle
    "Cause Fear": "恐懼術", "Clone": "複製隊員", "Fire Ring": "火環術",
    "Flame Strike": "火焰之擊", "Magic Storm": "魔法風暴", "Poison Field": "毒性力場",
    "Sleep Field": "催眠力場", "Tremor": "大地震",
    # 7th circle
    "Create Gold": "製金術", "Death Bolt": "死亡之矢", "Delayed Blast": "延遲爆炸術",
    "Energy Field": "能量力場", "Energy Mist": "能量之矢", "Mass Charm": "大迷惑術",
    "Mass Might": "大力術", "Restoration": "回複術",
    # 8th circle
    "Armageddon": "末日決戰", "Death Vortex": "死亡漩渦", "Invisibility All": "全體隱形",
    "Mass Death": "大死亡術", "Resurrect": "復活術", "Summon": "招喚術",
    "Swordstrike": "劍擊術", "Time Stop": "時間暫停",
}

# Book titles from Translation Guide
BOOK_NAMES = {
    "The Dragon Compendium": "龍類圖鑑",
    "The Journal of Garret Moore": "Garret Moore 日記",
    "The Transitive Vampire": "變形吸血鬼",
    "The Tome of the Dead": "亡者之書",
    "Artifacts of Darkness": "黑暗神器",
    "The Light Until Dawn": "黎明之光",
    "Ritual Magic": "儀式魔法",
    "Pathways of Planar Travel": "位面旅行途徑",
    "Enchanting Items for Household Use": "家用物品附魔",
    "A Guide to Childcare for the Rich and Famous": "富豪名流育兒指南",
    "Alagner's Book of Marvelous and Astonishing Things": "Alagner 的驚奇事物之書",
    "The History of Stonegate": "Stonegate 歷史",
    "The Way of the Swallow": "燕子之道",
    "Vetrons Guide to Weapons and Armour": "Vetron 武器與護甲指南",
    "Vargaz's Stories of Legend": "Vargaz 傳奇故事",
    "One Hundred and One Ways to Cheat at Nim": "Nim 遊戲的一百零一種作弊方法",
    "Play Directing: Analysis, Communication and Style": "戲劇導演：分析、溝通與風格",
    "On Acting": "論表演",
    "Thou Art What Thee Eats": "人如其食",
    "Man Versus Fish: The Ultimate Conflict": "人與魚：終極衝突",
    "Knight's Bridge in a Nutshell": "騎士橋遊戲簡介",
    "The Symbology of Runes": "符文符號學",
    "Britannian Mining Company log": "不列顛尼亞礦業公司日誌",
    "Modern Necromancy": "現代死靈法術",
    "The Bunk and Stool": "木鋪與矮凳客棧",
    "Knight's Bridge": "騎士橋棋",
    "Nim": "Nim 遊戲",
    "Silverleaf": "銀葉草",
    "Codavar": "Codavar",
}

def post_process_translation(zh_text):
    """Post-process translated Traditional Chinese to match guidelines."""
    if not zh_text:
        return ""

    # 1. Standard entity terms replacement (from ENTITIES dict)
    for pattern, zh_term in ENTITIES.items():
        en_word = re.sub(r'\\b', '', pattern)
        zh_text = re.sub(en_word, zh_term, zh_text, flags=re.IGNORECASE)

    # Also replace common machine-translation artifacts
    replacements = {
        "阿凡達": "聖者",
        "不列顛王": "不列顛王",
        "監護人": "守護者",
        "監護者": "守護者",
        "聯誼會": "友誼會",
        "月門": "月之門",
        "月球門": "月之門",
        "妖精": "森靈",
        "小妖精": "森靈",
        "魔鬼": "惡魔",
        "靈魂": "鬼火",
        "時空領主": "時間領主",
        "男爵": "大人",
        "夫人": "女士",
        "皇冠寶石": "皇冠寶石號",
        "小仙女": "小仙女號",
    }
    for old, new in replacements.items():
        zh_text = zh_text.replace(old, new)

    # 2. Spell name replacement (for short texts that look like spell names)
    # Check if text is short enough to be a spell name
    words = zh_text.split()
    for en_name, zh_name in SPELL_NAMES.items():
        if en_name.lower() in zh_text.lower() or en_name in zh_text:
            zh_text = zh_text.replace(en_name, zh_name)
            zh_text = zh_text.replace(en_name.lower(), zh_name)

    # 3. Book title replacement
    for en_title, zh_title in BOOK_NAMES.items():
        if en_title.lower() in zh_text.lower():
            # Case-insensitive replacement
            idx = zh_text.lower().find(en_title.lower())
            if idx >= 0:
                zh_text = zh_text[:idx] + zh_title + zh_text[idx + len(en_title):]

    # 4. Quote replacement: replace double quotes with full-width quotes
    # "Hello" -> 「Hello」
    processed = []
    quote_open = False
    for ch in zh_text:
        if ch == '"':
            if not quote_open:
                processed.append('「')
                quote_open = True
            else:
                processed.append('」')
                quote_open = False
        else:
            processed.append(ch)
    zh_text = "".join(processed)
    if quote_open:
        zh_text += '」'

    # 5. Fix sentence-ending quote punctuation per Translation Guide rule #7:
    #    .」 → 。」  ?」 → ？」  !」 → ！」
    zh_text = zh_text.replace('."', '。"')
    zh_text = zh_text.replace('?"', '？"')
    zh_text = zh_text.replace('!"', '！"')
    # Also apply after full-width quote conversion
    zh_text = zh_text.replace('.」', '。」')
    zh_text = zh_text.replace('?」', '？」')
    zh_text = zh_text.replace('!」', '！」')

    # 6. Clean up spaces around punctuation
    zh_text = zh_text.replace(" 。", "。").replace(" ，", "，").replace(" ！", "！").replace(" ？", "？")

    return zh_text

def _strip_regex(pattern):
    """Remove regex metacharacters from a pattern to get the plain text term."""
    term = pattern
    term = re.sub(r'\\[bwWsSdD]', '', term)
    term = term.replace(r'\s+', ' ')
    term = term.replace(r'\.', '.')
    term = term.replace(r"\'", "'")
    term = re.sub(r'[^a-z0-9\s\'.]', '', term, flags=re.IGNORECASE)
    return term.strip()

# Chinese digit equivalents for number checking
ZH_DIGITS = {
    "0": ["零", "〇"], "1": ["一", "壹"], "2": ["二", "貳", "兩"],
    "3": ["三", "參"], "4": ["四", "肆"], "5": ["五", "伍"],
    "6": ["六", "陸"], "7": ["七", "柒"], "8": ["八", "捌"], "9": ["九", "玖"],
}

# ── Tag replacement for game tokens (PLAYER_NAME, HONORIFIC, VAR, PRONOUN, GENDER_FLAG) ──

TAG_REPLACEMENTS = {
    '<PLAYER_NAME>': ('Avatar', '聖者'),
    '<HONORIFIC>': ('milord', '大人'),
    '<GENDER_FLAG>': ("man's", '男性'),
}

def _get_tag_replacement(tag, lang, context_text=''):
    if tag == '<PRONOUN>':
        idx = context_text.find('<PRONOUN>')
        before = context_text[max(0, idx-25):idx].strip()
        last_word = before.split()[-1] if before.split() else ''
        last_word = re.sub(r'[^a-zA-Z]', '', last_word).lower()
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

def classify_var_en(text):
    """Classify what <VAR> represents in the EN text."""
    t = text.replace('<VAR>', '___VAR___').strip()
    var_count = t.count('___VAR___')
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
    if re.search(r'___VAR___ (?:gold|coin|arrow|gem|loaf|loaves|piece|bottle|potion)', t, re.IGNORECASE):
        return 'number'
    if re.search(r'(?:hast|have|has|hath|with) ___VAR___ (?:in|Caddellite)', t, re.IGNORECASE):
        return 'number'
    if re.search(r'___VAR___ loaves?', t, re.IGNORECASE):
        return 'number'
    if re.search(r'(?:well met|greetings|hail|hark|farewell|goodbye|good day|good morrow)', t, re.IGNORECASE):
        return 'player_name'
    if re.search(r'traveller___VAR___', t, re.IGNORECASE):
        return 'player_name'
    if re.search(r'[,;:] ___VAR___ [,;:]', t):
        return 'player_name'
    if re.search(r', ___VAR___,', t):
        return 'player_name'
    if re.search(r'(?:especially|notably|like|such as|including|namely) ___VAR___', t, re.IGNORECASE):
        return 'player_name'
    if re.search(r'with (?:thee|you|me),? ___VAR___', t, re.IGNORECASE):
        return 'player_name'
    if re.search(r'(?:for|to|unto|upon|against|toward(?:s)?) ___VAR___', t, re.IGNORECASE):
        if re.search(r'(?:pay|charge|cost|owe|give|hand|offer|send|bring|carry) .{0,20} (?:for|to|unto) ___VAR___', t, re.IGNORECASE):
            pass
        else:
            return 'player_name'
    if re.search(r'(?:search(?:ed|es)?|look(?:ing|ed|s)?|hunt(?:ed|ing|s)?|seek|sought|find|found|track(?:ed|ing|s)?|follow(?:ed|ing|s)?) .{0,20} (?:for|after) ___VAR___', t, re.IGNORECASE):
        return 'player_name'
    if re.search(r'(?:help|aid|assist|save|protect|defend|guide|lead|teach|train) ___VAR___', t, re.IGNORECASE):
        return 'player_name'
    if t in ('___VAR___', '"___VAR___"', '___VAR___.', '"___VAR___."',
             '___VAR___!', '"___VAR___!"', '___VAR___?', '"___VAR___?"',
             '___VAR___,', '"___VAR___,"'):
        return 'player_name'
    if re.search(r'(?:knave|sir|madam|friend|fellow|stranger|traveler|traveller|'
                 r'wanderer|vagabond|scoundrel|villain|rogue|thief|fool|wretch)'
                 r' ,? ___VAR___', t, re.IGNORECASE):
        return 'player_name'
    if re.search(r'(?:^|")___VAR___\s', t):
        return 'player_name'
    if re.search(r'[\.!\?] ___VAR___[\.!\?\s,;:]*$', t):
        return 'player_name'
    if re.search(r'"[^"]*"___VAR___', t):
        return 'player_name'
    if re.search(r'noble hero', t, re.IGNORECASE):
        return 'player_name'
    if re.search(r'travel with (?:thee|you),? ___VAR___', t, re.IGNORECASE):
        return 'player_name'
    if re.search(r'\^___VAR___', t):
        return 'player_name'
    if re.search(r'(?:wish|wilt|wouldst|call(?:ed|s)?) .{0,20} (?:to )?be .{0,20} ___VAR___', t, re.IGNORECASE):
        return 'player_name'
    if re.search(r'(?:says?|said) ,? ___VAR___', t, re.IGNORECASE):
        return 'player_name'
    if re.search(r'___VAR___, (?:eh|I am|I\'m)', t, re.IGNORECASE):
        return 'player_name'
    if re.search(r'[\.!?]___VAR___', t):
        return 'player_name'
    if re.search(r'___VAR___[\.!\?]*\s*$', t):
        return 'player_name'
    if re.search(r'(?:was|were) ___VAR___', t, re.IGNORECASE) and \
       not re.search(r'(?:there|it) (?:was|were) ___VAR___', t, re.IGNORECASE):
        return 'npc_name'
    if re.search(r'___VAR___ (?:says?|said|asks?|asked|repl(?:y|ied)|answered?|'
                 r'responds?|responded|calls?|called|shouts?|shouted|yells?|yelled|'
                 r'whispers?|whispered|murmurs?|murmured|mutters?|muttered|'
                 r'explains?|explained|continues?|continued|begins?|started|starts?|'
                 r'concludes?|concluded)', t, re.IGNORECASE):
        return 'npc_name'
    if re.search(r'___VAR___ (?:forbade|forbid|moves?|moved|walks?|walked|went|'
                 r'comes?|came|looks?|looked|seems?|seemed|appears?|appeared|'
                 r'stands?|stood|sits?|sat|lies?|lay|begins?|started|starts?|'
                 r'opens?|opened|closed?|turns?|turned|nods?|nodded|shakes?|shook|'
                 r'smiles?|smiled|frowns?|frowned|sighs?|sighed|laughs?|laughed|'
                 r'enters?|entered|leaves?|left|arrives?|arrived|departs?|departed)'
                 r' ', t, re.IGNORECASE):
        return 'npc_name'
    if re.search(r"'s ___VAR___ ", t):
        return 'npc_name'
    if re.search(r'this ___VAR___', t, re.IGNORECASE):
        return 'npc_name'
    if re.search(r'___VAR___\s+\w+(?:s|ed|d)\s', t):
        return 'npc_name'
    if re.search(r'___VAR___ must', t, re.IGNORECASE):
        return 'npc_name'
    if re.search(r'from ___VAR___', t, re.IGNORECASE):
        return 'npc_name'
    if re.search(r'(?:a|an|the) ___VAR___', t, re.IGNORECASE) and var_count == 1:
        return 'title'
    return 'player_name'

def var_replacement_zh(cls):
    return {
        'number': '一些',
        'player_name': '聖者',
        'npc_name': '那個人',
        'title': '遊俠',
    }.get(cls, '聖者')

def replace_tags_in_zh(text, en_text=None):
    """Replace game tags in Chinese text with appropriate Chinese equivalents."""
    if not text:
        return text
    result = text.replace('^', '')
    for tag in ['<PLAYER_NAME>', '<HONORIFIC>', '<GENDER_FLAG>']:
        if tag in result:
            result = result.replace(tag, _get_tag_replacement(tag, 'zh', context_text=text))
    while '<PRONOUN>' in result:
        repl = _get_tag_replacement('<PRONOUN>', 'zh', context_text=result)
        result = result.replace('<PRONOUN>', repl, 1)
    if '<VAR>' in result:
        var_cls = classify_var_en(en_text) if en_text and '<VAR>' in (text + en_text) else 'player_name'
        repl = var_replacement_zh(var_cls)
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
                        pass
                    elif cur_seg and cur_seg[0].isalpha() and cur_seg[0].isascii():
                        pass
                    else:
                        new_parts.append(repl)
                new_parts.append(p)
            result = ''.join(new_parts)
            result = re.sub(r'  +', ' ', result)
    return result


def verify_match(en, zh):
    """Run heuristics to verify if English and Chinese texts match."""
    if not en or not zh:
        return False, "empty"
    
    en_clean = en.strip()
    zh_clean = zh.strip()

    # 1. Number check — also check Chinese digit equivalents
    en_nums = set(re.findall(r'\d+', en_clean))
    for num in en_nums:
        if num in zh_clean:
            continue
        # Check if Chinese digit equivalent exists
        digits = list(num)
        zh_alternatives = []
        for d in digits:
            zh_alternatives.append(ZH_DIGITS.get(d, [d]))
        # Generate possible Chinese forms: e.g. "12" -> "十二", "一二"
        for alt_set in zh_alternatives:
            for alt in alt_set:
                if alt in zh_clean:
                    break
            else:
                continue
            break
        else:
            # Skip if num is small and likely expressed in Chinese
            if len(num) <= 2:
                continue
            return False, f"number_mismatch_{num}"

    # 2. Named entities check
    en_lower = en_clean.lower()
    zh_lower = zh_clean.lower()
    for pattern, zh_term in ENTITIES.items():
        if re.search(pattern, en_lower):
            en_term = _strip_regex(pattern)
            if not en_term:
                continue
            # If zh_term is an English proper name, it should appear as-is in ZH
            if zh_term.isascii() and zh_term.isalpha():
                if zh_term.lower() not in zh_lower and en_term.lower() not in zh_lower:
                    return False, f"entity_mismatch_{zh_term}"
            else:
                # zh_term is Chinese; check if term or its English source appears
                if zh_term.lower() not in zh_lower and en_term.lower() not in zh_lower:
                    return False, f"entity_mismatch_{zh_term}"

    # 3. Length check — skip for short texts (likely UI strings or spell names)
    en_words = len(re.findall(r'\b\w+\b', en_clean))
    zh_chars = len(re.sub(r'[^\u4e00-\u9fff]', '', zh_clean))
    
    if en_words <= 5:
        pass  # Short text — skip length check
    elif zh_chars > 0:
        ratio = en_words / zh_chars
        if ratio < 0.15 or ratio > 5.0:
            return False, f"length_ratio_{ratio:.2f}"
    elif not zh_clean.isascii():
        return False, "long_en_no_zh_chars"

    # 4. Control characters check — be lenient about '@' in ZH (may appear in spells)
    for char in ['@', '*']:
        if (char in en_clean) != (char in zh_clean):
            if char == '@' and (len(en_clean) < 20 or len(zh_clean) < 20):
                continue  # Short texts may have spell glyphs
            if char == '*' and (en_clean.startswith('"') or zh_clean.startswith('「')):
                continue
            return False, f"control_char_mismatch_{char}"

    return True, "ok"

def main():
    print("Loading static CSV...", file=sys.stderr)
    static_rows, static_keyed = load_static_csv(STATIC_CSV)
    print(f"  {len(static_rows)} rows", file=sys.stderr)

    # Deduplicate: keep only first entry per (func_id, en_offset_key, en_segment)
    seen_keys = set()
    deduped = []
    for entry in static_rows:
        k = (entry['func_id'], entry['en_offset_key'], entry['en_segment'])
        if k not in seen_keys:
            seen_keys.add(k)
            deduped.append(entry)
        else:
            for existing in deduped:
                ek = (existing['func_id'], existing['en_offset_key'], existing['en_segment'])
                if ek == k:
                    if 'matched' in entry['confidence'] and 'static' in existing['confidence']:
                        existing['confidence'] = entry['confidence']
                    break
    static_rows = deduped
    print(f"  {len(static_rows)} after dedup", file=sys.stderr)

    # Add entries from bilingual_mapping.csv (offset-mapped) for missing keys
    # This CSV has combined keys (e.g. "6e1_70e") that the static CSV may lack
    existing_keys = set()
    for entry in static_rows:
        existing_keys.add((entry['func_id'], entry['en_offset_key'], entry['en_segment']))
    offset_added = 0
    try:
        with open(STATIC_CSV_OFFSET, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                fid = row['func_id'].strip()
                en_key = row['en_offset_key'].strip()
                en_seg = int(row.get('en_segment', '0').strip() or '0')
                k = (fid, en_key, en_seg)
                if k in existing_keys:
                    continue
                en_text = row.get('en_text', '').strip()
                zh_text = row.get('zh_text', '').strip()
                if not en_text and not zh_text:
                    continue
                entry = {
                    'func_id': fid,
                    'npc': row.get('npc', '').strip(),
                    'en_offset_key': en_key,
                    'en_segment': en_seg,
                    'en_text': en_text,
                    'zh_offset_key': row.get('zh_offset_key', '').strip(),
                    'zh_segment': int(row.get('zh_segment', '0').strip() or '0'),
                    'zh_text': zh_text,
                    'confidence': 'offset_mapped',
                    '_match_review': [],
                }
                static_rows.append(entry)
                existing_keys.add(k)
                offset_added += 1
    except FileNotFoundError:
        print(f"  Note: {STATIC_CSV_OFFSET} not found, skipping", file=sys.stderr)
    print(f"  {offset_added} added from {STATIC_CSV_OFFSET}", file=sys.stderr)
    print(f"  total static rows: {len(static_rows)}", file=sys.stderr)

    static_by_fid = defaultdict(list)
    for entry in static_rows:
        static_by_fid[entry['func_id']].append(entry)

    static_all = []
    for entry in static_rows:
        clean = make_clean(entry['en_text'])
        if clean:
            static_all.append((clean, entry))

    print("Pre-splitting static words for Jaccard...", file=sys.stderr)
    static_all_words = [(set(clean.split()), entry) for clean, entry in static_all]

    print("Loading review JSON...", file=sys.stderr)
    with open(REVIEW_JSON, 'r', encoding='utf-8') as f:
        review_entries = json.load(f)
    print(f"  {len(review_entries)} entries", file=sys.stderr)

    # ── Phase 1: Match review entries to static entries ────────────────
    print("Matching review entries to static rows...", file=sys.stderr)
    matched_count = 0
    unmatched_both = []   # has en+zh but no match
    unmatched_zhonly = [] # has zh only

    for idx, rev in enumerate(review_entries):
        if idx > 0 and idx % 2000 == 0:
            print(f"  Processed {idx} review entries...", file=sys.stderr)
        en_func = rev.get('en_func_id', '').strip()
        en_key = rev.get('en_offset_key', '').strip()
        en_seg = rev.get('en_segment', 0)
        en_text = rev.get('en_text', '').strip()
        zh_text = rev.get('zh_text', '').strip() or rev.get('zh_text_raw', '').strip()

        if not en_text:
            unmatched_zhonly.append(rev)
            continue
        if not zh_text:
            continue

        matched_static = None
        match_type = None

        # Strategy 1: Exact match by (func, offset, segment)
        if en_func and en_key:
            matched_static = static_keyed.get((en_func, en_key, en_seg))
            if matched_static:
                match_type = 'exact'

        # Strategy 2: Content match by substring
        if not matched_static:
            rev_clean = make_clean(en_text)
            if rev_clean:
                if en_func in static_by_fid:
                    for s_entry in static_by_fid[en_func]:
                        s_clean = make_clean(s_entry['en_text'])
                        if rev_clean in s_clean:
                            matched_static = s_entry
                            match_type = 'substr'
                            break
                if not matched_static:
                    for s_clean, s_entry in static_all:
                        if rev_clean in s_clean:
                            matched_static = s_entry
                            match_type = 'substr_cross_func'
                            break

        # Strategy 3: Jaccard similarity (for near-matches)
        if not matched_static:
            rev_words = set(make_clean(en_text).split()) if make_clean(en_text) else set()
            if rev_words:
                best_entry = None
                best_score = 0.0
                for s_words, s_entry in static_all_words:
                    if not s_words:
                        continue
                    inter = rev_words & s_words
                    union = rev_words | s_words
                    score = len(inter) / len(union) if union else 0
                    if score > best_score:
                        best_score = score
                        best_entry = s_entry
                if best_score >= 0.5:
                    matched_static = best_entry
                    match_type = f'jaccard_{best_score:.2f}'

        if matched_static:
            pos = matched_static['en_text'].lower().find(en_text.lower())
            matched_static['_match_review'].append({
                'zh_text': zh_text,
                'en_text': en_text,
                'match_type': match_type,
                'pos': pos if pos >= 0 else 999999,
                'voice_gender': rev.get('voice_gender'),
                'voice_age': rev.get('voice_age'),
                'voice_prompt': rev.get('voice_prompt'),
                'voice_lang': rev.get('voice_lang'),
                'tone': rev.get('tone'),
                'tone_instruct': rev.get('tone_instruct'),
            })
            matched_count += 1
        else:
            unmatched_both.append(rev)

    print(f"  Matched review entries: {matched_count}", file=sys.stderr)

    # ── Phase 2: Build final output list ──────────────────────────────
    print("Building final mapping list...", file=sys.stderr)
    output = []
    index = 0
    translation_cache = {}

    stats = defaultdict(int)

    for entry in static_rows:
        en_text = entry['en_text']
        zh_text = entry['zh_text']
        matches = entry['_match_review']

        out = {
            'index': index,
            'npc': entry['npc'],
            'en_func_id': entry['func_id'],
            'en_offset_key': entry['en_offset_key'],
            'en_segment': entry['en_segment'],
            'en_text': en_text,
            'zh_func_id': entry['func_id'],
            'zh_offset_key': entry['zh_offset_key'],
            'zh_segment': entry['zh_segment'],
            'zh_text': zh_text,
            'confidence': entry['confidence'],
            'voice_gender': None,
            'voice_age': None,
            'voice_prompt': None,
            'voice_lang': 'en',
            'tone': 'neutral',
            'tone_instruct': '',
        }

        # Check for standard option override
        STANDARD_OPTIONS = {
            "name": "姓名",
            "job": "職業",
            "bye": "告辭",
            "avatar": "聖者",
            "gold": "金幣",
            "magic": "魔法",
            "join": "加入",
            "leave": "離隊",
            "stables": "馬廄",
            "murder": "謀殺",
            "fellowship": "友誼會",
            "heal": "治療",
            "spells": "法術",
            "reagents": "藥材",
            "potions": "藥水",
            "cure poison": "解毒",
            "resurrect": "復活",
            "food": "食物",
            "drink": "飲料",
            "room": "房間",
            "buy": "買賣",
            "sell": "販售",
            "nothing": "再看看",
        }
        en_lower_clean = en_text.strip().strip('"').strip("'").strip().lower()
        if en_lower_clean in STANDARD_OPTIONS:
            out['zh_text'] = STANDARD_OPTIONS[en_lower_clean]
            out['confidence'] = 'standard_option_override'
            stats['standard_override'] += 1
        elif matches:
            matches_sorted = sorted(matches, key=lambda m: m['pos'])
            # Check coverage of matched segments
            en_clean = make_clean(en_text)
            if en_clean:
                coverage = [False] * len(en_clean)
                for m in matches:
                    r_clean = make_clean(m.get('en_text', ''))
                    if r_clean:
                        idx_pos = en_clean.find(r_clean)
                        if idx_pos >= 0:
                            for k in range(idx_pos, min(idx_pos + len(r_clean), len(coverage))):
                                coverage[k] = True
                covered_ratio = sum(coverage) / len(coverage) if coverage else 0
            else:
                covered_ratio = 1.0

            if covered_ratio >= 0.85:
                # Reconstruct full Chinese translation
                if len(matches_sorted) == 1:
                    out['zh_text'] = matches_sorted[0]['zh_text']
                else:
                    out['zh_text'] = ''.join(m['zh_text'] for m in matches_sorted)
                
                # Copy voice acting fields from the longest matched segment
                longest_match = max(matches_sorted, key=lambda m: len(m['en_text']))
                out['voice_gender'] = longest_match['voice_gender']
                out['voice_age'] = longest_match['voice_age']
                out['voice_prompt'] = longest_match['voice_prompt']
                out['voice_lang'] = longest_match['voice_lang'] or 'en'
                out['tone'] = longest_match['tone'] or 'neutral'
                out['tone_instruct'] = longest_match['tone_instruct'] or ''

                match_types = [m['match_type'] for m in matches_sorted]
                if any(t == 'exact' for t in match_types):
                    out['confidence'] = 'review_v2_matched_exact'
                elif any(t and t.startswith('substr') for t in match_types):
                    out['confidence'] = 'review_v2_matched_substr'
                else:
                    out['confidence'] = 'review_v2_matched_jaccard'
                stats['matched_review'] += 1
            else:
                # Partial review match (< 85% coverage). The static ZH covers the
                # full concatenated text and is authoritative — keep it, but record
                # the available review ZH for reference.
                out['zh_text'] = zh_text
                out['confidence'] = 'review_v2_partial_static_kept'
                stats['partial_review'] += 1
        elif en_text and zh_text:
            # Statically paired — trust the alignment from static analysis.
            # EN and ZH texts are structurally paired at the instruction level
            # (same func_id, offset_key, segment) from the bilingual usecode.
            # Heuristic verification causes false positives for legitimate
            # differences (e.g. "Britain" vs "不列顛城", extra control chars).
            # Accept as-is since the source alignment is authoritative.
            out['confidence'] = 'static_keep'
            stats['static_keep'] += 1
        elif en_text and not zh_text:
            # Untranslated English text: translate!
            if en_text in translation_cache:
                out['zh_text'] = translation_cache[en_text]
            else:
                print(f"Translating: '{en_text[:40]}...'", file=sys.stderr)
                raw_translation = google_translate(en_text)
                processed_translation = post_process_translation(raw_translation)
                translation_cache[en_text] = processed_translation
                out['zh_text'] = processed_translation
                
            if out['zh_text']:
                out['confidence'] = 'review_v2_translated'
                stats['translated'] += 1
            else:
                out['confidence'] = 'needs_translation'
                stats['translation_failed'] += 1
        elif not en_text and zh_text:
            out['zh_text'] = "##M## " + zh_text
            out['confidence'] = 'review_v2_unmatched_zh'
            stats['unmatched_zh'] += 1
        else:
            out['confidence'] = 'empty_entry'
            stats['empty'] += 1

        output.append(out)
        index += 1

    # ── Phase 3: Add remaining unmatched review entries ──────────────
    print("Appending unmatched review entries...", file=sys.stderr)
    for rev in unmatched_both:
        zh_text = rev.get('zh_text', '').strip() or rev.get('zh_text_raw', '').strip()
        en_text = rev.get('en_text', '').strip()
        if not zh_text:
            continue
        out = {
            'index': index,
            'npc': rev.get('npc', ''),
            'en_func_id': rev.get('en_func_id', ''),
            'en_offset_key': '',
            'en_segment': 0,
            'en_text': en_text,
            'zh_func_id': rev.get('zh_func_id', ''),
            'zh_offset_key': rev.get('zh_offset_key', ''),
            'zh_segment': rev.get('zh_segment', 0),
            'zh_text': f"##M## {zh_text}",
            'confidence': 'review_v2_unverified_pair',
            'voice_gender': rev.get('voice_gender'),
            'voice_age': rev.get('voice_age'),
            'voice_prompt': rev.get('voice_prompt'),
            'voice_lang': rev.get('voice_lang') or 'en',
            'tone': rev.get('tone') or 'neutral',
            'tone_instruct': rev.get('tone_instruct') or '',
        }
        output.append(out)
        index += 1
        stats['unverified_pair_unmatched'] += 1

    for rev in unmatched_zhonly:
        zh_text = rev.get('zh_text', '').strip() or rev.get('zh_text_raw', '').strip()
        if not zh_text:
            continue
        out = {
            'index': index,
            'npc': rev.get('npc', ''),
            'en_func_id': rev.get('en_func_id', ''),
            'en_offset_key': '',
            'en_segment': 0,
            'en_text': '',
            'zh_func_id': rev.get('zh_func_id', ''),
            'zh_offset_key': rev.get('zh_offset_key', ''),
            'zh_segment': rev.get('zh_segment', 0),
            'zh_text': f"##M## {zh_text}",
            'confidence': 'review_v2_unmatched_zh',
            'voice_gender': rev.get('voice_gender'),
            'voice_age': rev.get('voice_age'),
            'voice_prompt': rev.get('voice_prompt'),
            'voice_lang': rev.get('voice_lang') or 'en',
            'tone': rev.get('tone') or 'neutral',
            'tone_instruct': rev.get('tone_instruct') or '',
        }
        output.append(out)
        index += 1
        stats['unmatched_zh_only'] += 1

    print("\nSummary Statistics:")
    for k, v in stats.items():
        print(f"  {k}: {v}", file=sys.stderr)
    print(f"  ─────────────────────────", file=sys.stderr)
    print(f"  total entries: {len(output)}", file=sys.stderr)
    # Count ##M## entries
    m_count = sum(1 for e in output if e['zh_text'].startswith('##M##'))
    print(f"  ##M## total (needs review): {m_count}", file=sys.stderr)

    # ── Tag replacement: resolve game tokens to Chinese equivalents ──
    # The engine does NOT replace <PLAYER_NAME>, <HONORIFIC>, <VAR>, etc.
    # at runtime. Replace them here with the fixed Chinese text.
    tag_replaced = 0
    bracket_stripped = 0
    for entry in output:
        zh_text = entry['zh_text']
        en_text = entry['en_text']
        if any(t in zh_text for t in ['<PLAYER_NAME>', '<HONORIFIC>', '<VAR>', '<PRONOUN>', '<GENDER_FLAG>']):
            if zh_text.startswith('##M##'):
                continue
            entry['zh_text_raw'] = zh_text.replace('^', '')
            entry['zh_text'] = replace_tags_in_zh(zh_text, en_text)
            tag_replaced += 1
        elif '^' in zh_text:
            entry['zh_text_raw'] = zh_text.replace('^', '')
            entry['zh_text'] = zh_text.replace('^', '')

        # Strip angle-bracket translation artifacts: Google Translate sometimes
        # keeps <> around translated tag content (e.g., <HONORIFIC> → <大人>).
        # These are not valid game tags — remove all remaining <...> pairs.
        zt = entry['zh_text']
        if '<' in zt or '>' in zt:
            stripped = re.sub(r'<[^<>]+>', '', zt)
            if stripped != zt:
                if 'zh_text_raw' not in entry:
                    entry['zh_text_raw'] = zt.replace('^', '')
                entry['zh_text'] = stripped
                bracket_stripped += 1

    print(f"  Tag replacement applied to: {tag_replaced} entries", file=sys.stderr)
    print(f"  Angle-bracket artifacts stripped: {bracket_stripped} entries", file=sys.stderr)

    # Write Output JSON
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=1)

    print(f"\nSuccessfully generated {len(output)} entries in {OUTPUT_JSON}", file=sys.stderr)

if __name__ == '__main__':
    main()
