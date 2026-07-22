#!/usr/bin/env python3
"""Translate mapping rows that have text in one language but not the other.

Supports both directions (en2zh and zh2en). The translator is deliberately
conservative: a model response is applied only when its output preserves
placeholders and dialogue structure and passes language-specific checks.
Rejected rows remain unchanged for later review.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any


OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_MODEL = "qwen3.6:35b"
PROMPT_VERSION = "missing-text-v2"
PLACEHOLDER_RE = re.compile(r"<[^>]+>")
_SIMPLIFIED_ONLY = set("后发里说个为这那与从来会对将还没过现让见听开问员画台关门东车云书长国实")


def direction_config(direction: str) -> dict:
    """Return field names and validation rules for the given direction."""
    if direction == "en2zh":
        return {
            "source_field": "en_text",
            "target_field": "zh_text",
            "response_key": "zh_text",
            "cache_suffix": "en2zh",
            "validate_for": "zh",
            "system_prompt": (
                "Translate English Ultima VII dialogue and narration into natural Traditional Chinese. "
                "Return JSON only, with a translations array containing objects with index and zh_text. "
                "Preserve every <PLACEHOLDER> exactly. Preserve narration outside dialogue. "
                "Convert each English dialogue span in double quotes to a matching Chinese 「」 span; "
                "do not invent or remove dialogue spans. Use established Ultima terminology and no commentary."
            ),
        }
    else:
        return {
            "source_field": "zh_text",
            "target_field": "en_text",
            "response_key": "en_text",
            "cache_suffix": "zh2en",
            "validate_for": "en",
            "system_prompt": (
                "Translate Traditional Chinese Ultima VII dialogue and narration into natural English. "
                "Return JSON only, with a translations array containing objects with index and en_text. "
                "Preserve every <PLACEHOLDER> exactly. Preserve narration outside dialogue. "
                "Convert each Chinese dialogue span in 「」 to matching English double-quote spans; "
                "do not invent or remove dialogue spans. Use established Ultima terminology and no commentary."
            ),
        }


def select_missing_rows(rows: list[dict], direction: str = "en2zh") -> list[dict]:
    """Return rows eligible for translation without changing the input."""
    cfg = direction_config(direction)
    source = cfg["source_field"]
    target = cfg["target_field"]
    return [
        row
        for row in rows
        if str(row.get(source, "")).strip()
        and not str(row.get(target, "")).strip()
    ]


def _dialogue_span_count(text: str, left: str, right: str) -> int:
    return min(text.count(left), text.count(right))


def validate_translation(source: str, translated: str, direction: str = "en2zh") -> list[str]:
    """Return validation errors; an empty list means the translation is safe."""
    errors: list[str] = []
    source = str(source or "")
    translated = str(translated or "").strip()
    if not translated:
        return ["empty translation"]
    if translated.startswith("```") or "Here is the translation" in translated:
        errors.append("model commentary")

    source_placeholders = sorted(PLACEHOLDER_RE.findall(source))
    translated_placeholders = sorted(PLACEHOLDER_RE.findall(translated))
    if source_placeholders != translated_placeholders:
        errors.append("placeholder mismatch")

    if direction == "en2zh":
        source_spans = _dialogue_span_count(source, '"', '"') // 2
        translated_spans = _dialogue_span_count(translated, "「", "」")
        if source_spans != translated_spans:
            errors.append("dialogue span count")
        if translated.count("「") != translated.count("」"):
            errors.append("unbalanced corner quotes")
        if any(ch in translated for ch in _SIMPLIFIED_ONLY):
            errors.append("simplified Chinese character detected")
    else:
        source_spans = _dialogue_span_count(source, "「", "」")
        translated_spans = _dialogue_span_count(translated, '"', '"') // 2
        if source_spans != translated_spans:
            errors.append("dialogue span count")
        if translated.count('"') % 2 != 0:
            errors.append("unbalanced double quotes")
    return errors


def build_translation_prompt(rows: list[dict], direction: str = "en2zh") -> dict[str, Any]:
    cfg = direction_config(direction)
    source = cfg["source_field"]
    response_key = cfg["response_key"]
    payload = [{"index": row["index"], source: row.get(source, "")} for row in rows]
    system = cfg["system_prompt"]
    return {
        "model": DEFAULT_MODEL,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    }


def translation_cache_key(model: str, source: str, direction: str = "en2zh") -> str:
    value = json.dumps(
        {"model": model, "prompt_version": PROMPT_VERSION, "direction": direction, "source": source},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def apply_translations(rows: list[dict], accepted_by_index: dict[int, str], direction: str = "en2zh") -> list[dict]:
    cfg = direction_config(direction)
    target = cfg["target_field"]
    result = copy.deepcopy(rows)
    for row in result:
        index = row.get("index")
        if index in accepted_by_index and not str(row.get(target, "")).strip():
            row[target] = accepted_by_index[index]
    return result


def _read_cache(path: Path) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return cache
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                cache[record["cache_key"]] = record
    return cache


def _append_cache(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _call_ollama(url: str, model: str, rows: list[dict], direction: str = "en2zh", timeout: int = 900) -> dict[int, str]:
    cfg = direction_config(direction)
    response_key = cfg["response_key"]
    prompt = build_translation_prompt(rows, direction=direction)
    prompt["model"] = model
    request = urllib.request.Request(
        url,
        data=json.dumps(prompt, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body.get("message", {}).get("content", body.get("response", body))
    if isinstance(content, str):
        content = json.loads(content)
    if isinstance(content, dict):
        content = content.get("translations", content.get("results", []))
    result = {}
    for item in content or []:
        if isinstance(item, dict) and "index" in item and response_key in item:
            result[int(item["index"])] = str(item[response_key]).strip()
    return result


def translate_rows(rows: list[dict], *, model: str, cache_path: Path, url: str, batch_size: int, timeout: int = 900, direction: str = "en2zh") -> list[dict]:
    cfg = direction_config(direction)
    source_field = cfg["source_field"]
    cache = _read_cache(cache_path)
    accepted: dict[int, str] = {}
    audit: list[dict[str, Any]] = []
    pending: list[dict] = []
    for row in rows:
        key = translation_cache_key(model, row.get(source_field, ""), direction=direction)
        record = cache.get(key)
        if record is not None:
            translated = record.get("translated", "")
            errors = record.get("errors", validate_translation(row.get(source_field, ""), translated, direction=direction))
            audit.append({"index": row["index"], "status": "accepted" if not errors else "rejected", "errors": errors})
            if not errors:
                accepted[row["index"]] = translated
        else:
            pending.append(row)

    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        translations = _call_ollama(url, model, batch, direction=direction, timeout=timeout)
        for row in batch:
            translated = translations.get(row["index"], "")
            errors = validate_translation(row.get(source_field, ""), translated, direction=direction)
            record = {
                "cache_key": translation_cache_key(model, row.get(source_field, ""), direction=direction),
                "model": model,
                "index": row["index"],
                "source": row.get(source_field, ""),
                "translated": translated,
                "errors": errors,
            }
            _append_cache(cache_path, record)
            audit.append({"index": row["index"], "status": "accepted" if not errors else "rejected", "errors": errors})
            if not errors:
                accepted[row["index"]] = translated
    return apply_translations(rows, accepted, direction=direction), audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--direction", choices=("en2zh", "zh2en"), default="en2zh")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--url", default=OLLAMA_URL)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=900, help="Ollama request timeout in seconds")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    direction = args.direction
    cfg = direction_config(direction)
    if args.cache is None:
        args.cache = Path(f"tools/voice_acting/missing_{cfg['cache_suffix']}_translation_cache.jsonl")
    if args.audit is None:
        args.audit = Path(f"tools/voice_acting/missing_{cfg['cache_suffix']}_translation_audit.json")
    rows = json.loads(args.mapping.read_text(encoding="utf-8"))
    selected = select_missing_rows(rows, direction=direction)
    target_field = cfg["target_field"]
    print(f"selected {len(selected)} missing {target_field} translations")
    if args.dry_run:
        return 0
    updated, audit = translate_rows(selected, model=args.model, cache_path=args.cache, url=args.url, batch_size=args.batch_size, timeout=args.timeout, direction=direction)
    accepted = {row["index"]: row[target_field] for row in updated if row.get(target_field, "").strip()}
    final_rows = apply_translations(rows, accepted, direction=direction)
    args.mapping.write_text(json.dumps(final_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps({"model": args.model, "direction": direction, "selected": len(selected), "rows": audit}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"accepted {sum(item['status'] == 'accepted' for item in audit)}; rejected {sum(item['status'] == 'rejected' for item in audit)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
