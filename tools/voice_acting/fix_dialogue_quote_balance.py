#!/usr/bin/env python3
"""Fix unbalanced dialogue quote delimiters in voice text manifests."""

import argparse
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MAPPING = PROJECT_DIR / "tools" / "voice_acting" / "bilingual_mapping_review.json"
DEFAULT_EN_CSV = PROJECT_DIR / "tools" / "voice_acting" / "en_voice_lines.csv"
DEFAULT_ZH_CSV = PROJECT_DIR / "tools" / "voice_acting" / "zh_voice_lines.csv"
DEFAULT_OUT_JSON = PROJECT_DIR / "voice" / "review_samples" / "full_generated_review" / "dialogue_quote_balance_fixes.json"
DEFAULT_OUT_CSV = PROJECT_DIR / "voice" / "review_samples" / "full_generated_review" / "dialogue_quote_balance_fixes.csv"
BACKUP_DIR = PROJECT_DIR / "voice_backup"


def fix_english_quotes(text):
    if not text:
        return text, ""
    
    # Strip accidental leading or trailing double quotes if it balances the count
    if text.startswith('""'):
        fixed = text[1:]
        if fixed.count('"') % 2 == 0:
            return fixed, "remove_double_open_quote"
    if text.endswith('""'):
        fixed = text[:-1]
        if fixed.count('"') % 2 == 0:
            return fixed, "remove_double_close_quote"

    count = text.count('"')
    if count % 2 == 0:
        return text, ""

    first = text.find('"')
    last = text.rfind('"')
    if first == -1:
        return text, ""

    def looks_like_open_quote(index):
        prev = text[index - 1] if index > 0 else ""
        nxt = text[index + 1] if index + 1 < len(text) else ""
        return (
            index == 0
            or prev.isspace()
            or prev in ",:([{-"
        ) and bool(nxt and not nxt.isspace())

    def looks_like_close_quote(index):
        prev = text[index - 1] if index > 0 else ""
        nxt = text[index + 1] if index + 1 < len(text) else ""
        return bool(prev and not prev.isspace()) and (
            index == len(text) - 1
            or nxt.isspace()
            or nxt in ".,;:!?)]}-"
        )

    if (looks_like_open_quote(last) or not looks_like_close_quote(last)) and not text.endswith('"'):
        return text + '"', "append_english_quote"
    if not text.startswith('"'):
        return '"' + text, "prepend_english_quote"
    return text, ""



def fix_chinese_corner_quotes(text):
    if not text:
        return text, ""
    left = text.count("「")
    right = text.count("」")
    if left == right:
        return text, ""
    fixed = text
    actions = []
    while left > right:
        fixed += "」"
        right += 1
        actions.append("append_chinese_quote")
    while right > left:
        if fixed.startswith("」「"):
            fixed = fixed[1:]
            right -= 1
            actions.append("remove_extra_leading_chinese_close")
        elif fixed.startswith("「") and fixed.endswith("」") and right == left + 1:
            fixed = fixed[:-1]
            right -= 1
            actions.append("remove_extra_trailing_chinese_close")
        elif left == 0 and right >= 2:
            wrong_open = fixed.find("」")
            fixed = fixed[:wrong_open] + "「" + fixed[wrong_open + 1:]
            right -= 1
            left += 1
            actions.append("replace_chinese_close_with_open")
        else:
            fixed = "「" + fixed
            left += 1
            actions.append("prepend_chinese_quote")
    return fixed, "+".join(actions)


def _is_chinese_speech(text):
    """True if 'text' looks like speech (ends with 。？！，) and is not a short term."""
    if not text:
        return False
    text = text.strip()
    if not text:
        return False
    last = text[-1]
    return last in '\u3002\uff1f\uff01\uff0c' and len(text) > 2


def fix_chinese_speech_vs_narration(zh_text, en_text):
    """Fix 「『speech』」→「speech」(redundant outer 「」) and
    「『speech』narration『speech』」→「speech」narration「speech」

    Detects outer 「」 wrapping 『』 where 『』 marks actual speech
    (ending in 。？！，) not titles/terms. Requires EN to have double
    quotes (speech marker). Skips emphasis-only cases (Xorinia style).
    """
    if not zh_text or not en_text:
        return zh_text, ""
    zh = zh_text.strip()
    if not (zh.startswith('\u300c\u300e') and zh.endswith('\u300d')):
        return zh_text, ""

    if '"' not in en_text and '\u201c' not in en_text:
        return zh_text, ""

    inner = zh[1:-1]

    pairs = []
    pos = 0
    while pos < len(inner):
        lidx = inner.find('\u300e', pos)
        if lidx == -1:
            break
        ridx = inner.find('\u300f', lidx)
        if ridx == -1:
            break
        content = inner[lidx + 1:ridx]
        pairs.append((lidx, ridx, content))
        pos = ridx + 1

    if not pairs:
        return zh_text, ""

    has_narration_between = any(
        inner[pairs[i][1] + 1:pairs[i + 1][0]].strip()
        for i in range(len(pairs) - 1)
    )

    if len(pairs) >= 2 and has_narration_between:
        must_have_speech = any(_is_chinese_speech(c) for _, _, c in pairs)
        if not must_have_speech:
            return zh_text, ""

    else:
        if not _is_chinese_speech(pairs[0][2]):
            return zh_text, ""

    result = list(inner)
    for lidx, ridx, _ in reversed(pairs):
        result[lidx] = '\u300c'
        result[ridx] = '\u300d'

    return ''.join(result), 'fix_speech_vs_narration'


def backup_file(path):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"{path.stem}_before_quote_balance_{stamp}{path.suffix}"
    shutil.copy2(path, backup_path)
    return backup_path


def fix_mapping(mapping_path):
    with open(mapping_path, encoding="utf-8") as f:
        rows = json.load(f)
    fixes = []
    for index, row in enumerate(rows):
        for lang, key, fixer in (
            ("en", "en_text", fix_english_quotes),
            ("zh", "zh_text", fix_chinese_corner_quotes),
        ):
            old = row.get(key, "")
            new, action = fixer(old)
            if action:
                row[key] = new
                fixes.append({
                    "file": str(mapping_path),
                    "row_index": index,
                    "lang": lang,
                    "action": action,
                    "npc": row.get("npc", ""),
                    "func_id": row.get(f"{lang}_func_id", ""),
                    "offset_key": row.get(f"{lang}_offset_key", ""),
                    "segment": row.get(f"{lang}_segment", ""),
                    "old_text": old,
                    "new_text": new,
                })

        old_zh = row.get("zh_text", "")
        en_text = row.get("en_text", "")
        new_zh, action = fix_chinese_speech_vs_narration(old_zh, en_text)
        if action:
            row["zh_text"] = new_zh
            fixes.append({
                "file": str(mapping_path),
                "row_index": index,
                "lang": "zh",
                "action": action,
                "npc": row.get("npc", ""),
                "func_id": row.get("zh_func_id", ""),
                "offset_key": row.get("zh_offset_key", ""),
                "segment": row.get("zh_segment", ""),
                "old_text": old_zh,
                "new_text": new_zh,
            })
    return rows, fixes


def fix_en_csv(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames
    fixes = []
    for index, row in enumerate(rows):
        old = row.get("text", "")
        new, action = fix_english_quotes(old)
        if action:
            row["text"] = new
            fixes.append({
                "file": str(csv_path),
                "row_index": index,
                "lang": "en",
                "action": action,
                "npc": row.get("npc", ""),
                "speaker": row.get("speaker", ""),
                "func_id": row.get("func_id", ""),
                "offset_key": row.get("offset_key", ""),
                "segment": row.get("segment", ""),
                "old_text": old,
                "new_text": new,
            })
    return fieldnames, rows, fixes


def decode_mojibake_utf8(text):
    try:
        return text.encode("latin1").decode("utf-8")
    except UnicodeError:
        return text


def fix_zh_csv(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames
    fixes = []
    for index, row in enumerate(rows):
        old = row.get("text", "")
        decoded = decode_mojibake_utf8(old)
        new, action = fix_chinese_corner_quotes(decoded)
        row["text"] = new
        if action:
            fixes.append({
                "file": str(csv_path),
                "row_index": index,
                "lang": "zh",
                "action": action,
                "npc": row.get("npc", ""),
                "speaker": row.get("speaker", ""),
                "func_id": row.get("func_id", ""),
                "offset_key": row.get("offset_key", ""),
                "segment": row.get("segment", ""),
                "old_text": decoded,
                "new_text": new,
            })
    return fieldnames, rows, fixes


def write_mapping(path, rows):
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_fix_reports(fixes, output_json, output_csv):
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps({"fixes": fixes}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "file", "row_index", "lang", "action", "npc", "speaker",
            "func_id", "offset_key", "segment", "old_text", "new_text",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(fixes)


def main():
    parser = argparse.ArgumentParser(description="Fix unbalanced dialogue quote delimiters.")
    parser.add_argument("--mapping", default=str(DEFAULT_MAPPING))
    parser.add_argument("--en-csv", default=str(DEFAULT_EN_CSV))
    parser.add_argument("--zh-csv", default=str(DEFAULT_ZH_CSV))
    parser.add_argument("--output-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--output-csv", default=str(DEFAULT_OUT_CSV))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    mapping_path = Path(args.mapping)
    en_csv_path = Path(args.en_csv)
    zh_csv_path = Path(args.zh_csv)
    mapping_rows, mapping_fixes = fix_mapping(mapping_path)
    en_fields, en_rows, en_fixes = fix_en_csv(en_csv_path)
    zh_fields, zh_rows, zh_fixes = fix_zh_csv(zh_csv_path)
    fixes = mapping_fixes + en_fixes + zh_fixes
    write_fix_reports(fixes, Path(args.output_json), Path(args.output_csv))

    backups = []
    if not args.dry_run and fixes:
        if mapping_fixes:
            backups.append(str(backup_file(mapping_path)))
            write_mapping(mapping_path, mapping_rows)
        if en_fixes:
            backups.append(str(backup_file(en_csv_path)))
            write_csv(en_csv_path, en_fields, en_rows)
        if zh_rows:
            backups.append(str(backup_file(zh_csv_path)))
            write_csv(zh_csv_path, zh_fields, zh_rows)

    print(json.dumps({
        "mapping_fixes": len(mapping_fixes),
        "en_csv_fixes": len(en_fixes),
        "zh_csv_fixes": len(zh_fixes),
        "total_fixes": len(fixes),
        "backups": backups,
        "output_json": str(args.output_json),
        "output_csv": str(args.output_csv),
        "dry_run": args.dry_run,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
