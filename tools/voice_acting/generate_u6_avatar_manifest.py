#!/usr/bin/env python3
"""Add cloneable Avatar rows discovered in U6 usecode to the U6 manifests.

The ordinary U6 voice mapping is based on runtime-attributed NPC dialogue.
Avatar speech is not reliably attributed by that capture, because the player
has no fixed voice identity.  This adapter joins static ``show_npc_face``
attribution with the captured source catalog and reviewed translation table,
then appends only source-hash-valid, non-dynamic Avatar rows.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_USECODE = PROJECT_DIR.parent / "Ultima_7" / "mods" / "Ultima6v1.3" / "patch" / "usecode"
DEFAULT_RUNTIME_MANIFEST = PROJECT_DIR / "u6_voice" / "manifests" / "u6_voice_manifest.jsonl"
DEFAULT_TRANSLATIONS = PROJECT_DIR / "tools" / "u6_translation" / "deploy" / "mods" / "Ultima6v1.3" / "patch" / "zh_translation.tsv"
DEFAULT_MAPPING = PROJECT_DIR / "u6_voice" / "manifests" / "u6_qwen3_mapping.json"
DEFAULT_ROLE_MANIFEST = PROJECT_DIR / "u6_voice" / "manifests" / "u6_voice_roles.jsonl"

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from tools.u6_translation.voice_manifest import normalize_tts_text


def _normalize_func_id(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        raise ValueError("missing function id")
    return f"{int(text, 16):04x}"


def _normalize_offset_key(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        raise ValueError("missing offset key")
    parts = [part.removeprefix("0x") for part in text.split("_")]
    if any(not part for part in parts):
        raise ValueError("invalid offset key")
    return "_".join(parts)


def _identity(row: dict[str, Any]) -> tuple[str, str, int]:
    function_id = _normalize_func_id(row.get("func_id"))
    offset_key = _normalize_offset_key(row.get("offset_key"))
    segment = int(str(row.get("segment", "0") or "0"), 10)
    return function_id, offset_key, segment


def _runtime_key(identity: tuple[str, str, int]) -> str:
    function_id, offset_key, segment = identity
    return f"dialogue:0x{function_id}:{offset_key}:{segment}"


def _clean_tts(text: str, language: str) -> str:
    return normalize_tts_text(text, language)


def _candidate_records(
    disassembled_rows: Iterable[dict[str, Any]],
    runtime_rows: dict[str, dict[str, Any]],
    translation_rows: dict[str, dict[str, str]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    records: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen: set[tuple[str, str, int]] = set()
    for static_row in disassembled_rows:
        if str(static_row.get("speaker", "")).strip().lower() != "avatar":
            continue
        try:
            identity = _identity(static_row)
        except (TypeError, ValueError):
            continue
        function_id, offset_key, segment = identity
        if identity in seen:
            continue
        key = _runtime_key(identity)
        runtime = runtime_rows.get(key)
        translation = translation_rows.get(key)
        if runtime is None or translation is None:
            continue
        source_en = str(runtime.get("source_en") or "")
        text_zh = str(translation.get("text_zh") or "")
        if not source_en.strip() or not text_zh.strip():
            continue
        if str(runtime.get("source_sha256") or "") != str(translation.get("source_sha256") or ""):
            continue
        try:
            en_text = _clean_tts(source_en, "en")
            zh_text = _clean_tts(text_zh, "zh")
        except ValueError:
            continue
        if not en_text or not zh_text:
            continue
        seen.add(identity)
        records.append(
            (
                {
                    "npc": "Avatar",
                    "en_func_id": function_id,
                    "en_offset_key": offset_key,
                    "en_segment": segment,
                    "en_text": en_text,
                    "en_voice_desc": "Avatar",
                    "en_output_filename": f"{function_id}_{offset_key}_{segment}.ogg",
                    "zh_func_id": function_id,
                    "zh_offset_key": offset_key,
                    "zh_segment": segment,
                    "zh_text": zh_text,
                    "zh_voice_desc": "Avatar",
                    "zh_output_filename": f"{function_id}_{offset_key}_{segment}.ogg",
                },
                {
                    "key": key,
                    "function_id": int(function_id, 16),
                    "offset_key": offset_key,
                    "segment": segment,
                    "source_en": source_en,
                    "text_zh": text_zh,
                },
            )
        )
    records.sort(key=lambda pair: (pair[0]["en_func_id"], pair[0]["en_offset_key"], pair[0]["en_segment"]))
    return records


def build_avatar_entries(
    disassembled_rows: Iterable[dict[str, Any]],
    runtime_rows: dict[str, dict[str, Any]],
    translation_rows: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """Build deterministic mapping rows for cloneable Avatar identities."""

    return [mapping for mapping, _role in _candidate_records(disassembled_rows, runtime_rows, translation_rows)]


def build_avatar_roles(
    disassembled_rows: Iterable[dict[str, Any]],
    runtime_rows: dict[str, dict[str, Any]],
    translation_rows: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """Build role-source rows retaining the exact catalog markers and hashes."""

    return [role for _mapping, role in _candidate_records(disassembled_rows, runtime_rows, translation_rows)]


def load_runtime_manifest(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    # Use only the JSONL record separator.  U6 text legitimately contains
    # control codepoints such as U+0085, which ``str.splitlines`` would treat
    # as additional record boundaries.
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.strip():
            row = json.loads(line)
            rows[str(row["key"])] = row
    return rows


def load_translation_table(path: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for fields in csv.reader(handle, delimiter="\t"):
            if len(fields) < 4 or fields[0] != "dialogue":
                continue
            rows[fields[1]] = {
                "source_sha256": fields[2],
                "text_zh": fields[3],
            }
    return rows


def disassemble_avatar_source(usecode: Path) -> list[dict[str, str]]:
    command = [
        sys.executable,
        str(Path(__file__).with_name("disassemble_usecode.py")),
        str(usecode),
        "--all",
        "--format",
        "csv",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return list(csv.DictReader(io.StringIO(result.stdout)))


def _merge_json_mapping(path: Path, additions: list[dict[str, Any]]) -> int:
    existing = json.loads(path.read_text(encoding="utf-8"))
    existing_keys = {
        (
            str(row.get("npc") or "").strip().lower(),
            _normalize_func_id(row.get("en_func_id")),
            _normalize_offset_key(row.get("en_offset_key")),
            int(row.get("en_segment", 0)),
        )
        for row in existing
    }
    new_rows = [
        row
        for row in additions
        if (
            str(row.get("npc") or "").strip().lower(),
            row["en_func_id"],
            row["en_offset_key"],
            row["en_segment"],
        ) not in existing_keys
    ]
    if new_rows:
        path.write_text(json.dumps(existing + new_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(new_rows)


def _merge_role_manifest(path: Path, additions: list[dict[str, Any]]) -> int:
    existing_lines = [line for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
    existing = [json.loads(line) for line in existing_lines]
    existing_keys = {
        (
            _normalize_func_id(row.get("function_id")),
            _normalize_offset_key(row.get("offset_key")),
            int(row.get("segment", 0)),
        )
        for row in existing
    }
    new_rows = [
        row
        for row in additions
        if (
            _normalize_func_id(row["function_id"]),
            _normalize_offset_key(row["offset_key"]),
            int(row["segment"]),
        ) not in existing_keys
    ]
    if new_rows:
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in existing + new_rows),
            encoding="utf-8",
        )
    return len(new_rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usecode", type=Path, default=DEFAULT_USECODE)
    parser.add_argument("--runtime-manifest", type=Path, default=DEFAULT_RUNTIME_MANIFEST)
    parser.add_argument("--translations", type=Path, default=DEFAULT_TRANSLATIONS)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--role-manifest", type=Path, default=DEFAULT_ROLE_MANIFEST)
    args = parser.parse_args(argv)

    static_rows = disassemble_avatar_source(args.usecode)
    runtime_rows = load_runtime_manifest(args.runtime_manifest)
    translation_rows = load_translation_table(args.translations)
    mappings = build_avatar_entries(static_rows, runtime_rows, translation_rows)
    roles = build_avatar_roles(static_rows, runtime_rows, translation_rows)
    mapping_added = _merge_json_mapping(args.mapping, mappings)
    roles_added = _merge_role_manifest(args.role_manifest, roles)
    print(
        f"Avatar static_rows={sum(str(row.get('speaker', '')).strip().lower() == 'avatar' for row in static_rows)} "
        f"candidate_rows={len(mappings)} mapping_added={mapping_added} roles_added={roles_added}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
