#!/usr/bin/env python3
"""Translate mapping rows that have English text but no Chinese text.

The translator is deliberately conservative: a model response is applied only
when its output preserves placeholders and dialogue structure and passes the
Traditional Chinese checks. Rejected rows remain unchanged for later review.
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
PROMPT_VERSION = "missing-zh-v1"
PLACEHOLDER_RE = re.compile(r"<[^>]+>")
_SIMPLIFIED_ONLY = set("后发里说个为这那与从来会对将还没过现让见听开问员画台关门东车云书长国实")


def select_missing_rows(rows: list[dict]) -> list[dict]:
    """Return rows eligible for translation without changing the input."""
    return [
        row
        for row in rows
        if str(row.get("en_text", "")).strip()
        and not str(row.get("zh_text", "")).strip()
    ]


def _dialogue_span_count(text: str, left: str, right: str) -> int:
    return min(text.count(left), text.count(right))


def validate_translation(source: str, translated: str) -> list[str]:
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

    source_spans = _dialogue_span_count(source, '"', '"') // 2
    translated_spans = _dialogue_span_count(translated, "「", "」")
    if source_spans != translated_spans:
        errors.append("dialogue span count")
    if translated.count("「") != translated.count("」"):
        errors.append("unbalanced corner quotes")
    if any(ch in translated for ch in _SIMPLIFIED_ONLY):
        errors.append("simplified Chinese character detected")
    return errors


def build_translation_prompt(rows: list[dict]) -> dict[str, Any]:
    payload = [{"index": row["index"], "en_text": row.get("en_text", "")} for row in rows]
    system = (
        "Translate English Ultima VII dialogue and narration into natural Traditional Chinese. "
        "Return JSON only, with a translations array containing objects with index and zh_text. "
        "Preserve every <PLACEHOLDER> exactly. Preserve narration outside dialogue. "
        "Convert each English dialogue span in double quotes to a matching Chinese 「」 span; "
        "do not invent or remove dialogue spans. Use established Ultima terminology and no commentary."
    )
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


def translation_cache_key(model: str, source: str) -> str:
    value = json.dumps(
        {"model": model, "prompt_version": PROMPT_VERSION, "source": source},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def apply_translations(rows: list[dict], accepted_by_index: dict[int, str]) -> list[dict]:
    result = copy.deepcopy(rows)
    for row in result:
        index = row.get("index")
        if index in accepted_by_index and not str(row.get("zh_text", "")).strip():
            row["zh_text"] = accepted_by_index[index]
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


def _call_ollama(url: str, model: str, rows: list[dict], timeout: int = 900) -> dict[int, str]:
    prompt = build_translation_prompt(rows)
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
        if isinstance(item, dict) and "index" in item and "zh_text" in item:
            result[int(item["index"])] = str(item["zh_text"]).strip()
    return result


def translate_rows(rows: list[dict], *, model: str, cache_path: Path, url: str, batch_size: int, timeout: int = 900) -> list[dict]:
    cache = _read_cache(cache_path)
    accepted: dict[int, str] = {}
    audit: list[dict[str, Any]] = []
    pending: list[dict] = []
    for row in rows:
        key = translation_cache_key(model, row.get("en_text", ""))
        record = cache.get(key)
        if record is not None:
            translated = record.get("translated", "")
            errors = record.get("errors", validate_translation(row.get("en_text", ""), translated))
            audit.append({"index": row["index"], "status": "accepted" if not errors else "rejected", "errors": errors})
            if not errors:
                accepted[row["index"]] = translated
        else:
            pending.append(row)

    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        translations = _call_ollama(url, model, batch, timeout=timeout)
        for row in batch:
            translated = translations.get(row["index"], "")
            errors = validate_translation(row.get("en_text", ""), translated)
            record = {
                "cache_key": translation_cache_key(model, row.get("en_text", "")),
                "model": model,
                "index": row["index"],
                "source": row.get("en_text", ""),
                "translated": translated,
                "errors": errors,
            }
            _append_cache(cache_path, record)
            audit.append({"index": row["index"], "status": "accepted" if not errors else "rejected", "errors": errors})
            if not errors:
                accepted[row["index"]] = translated
    return apply_translations(rows, accepted), audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--url", default=OLLAMA_URL)
    parser.add_argument("--cache", type=Path, default=Path("tools/voice_acting/missing_zh_translation_cache.jsonl"))
    parser.add_argument("--audit", type=Path, default=Path("tools/voice_acting/missing_zh_translation_audit.json"))
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=900, help="Ollama request timeout in seconds")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    rows = json.loads(args.mapping.read_text(encoding="utf-8"))
    selected = select_missing_rows(rows)
    print(f"selected {len(selected)} missing Chinese translations")
    if args.dry_run:
        return 0
    updated, audit = translate_rows(selected, model=args.model, cache_path=args.cache, url=args.url, batch_size=args.batch_size, timeout=args.timeout)
    accepted = {row["index"]: row["zh_text"] for row in updated if row.get("zh_text", "").strip()}
    final_rows = apply_translations(rows, accepted)
    args.mapping.write_text(json.dumps(final_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps({"model": args.model, "selected": len(selected), "rows": audit}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"accepted {sum(item['status'] == 'accepted' for item in audit)}; rejected {sum(item['status'] == 'rejected' for item in audit)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
