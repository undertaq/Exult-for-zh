from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable

from .catalog import CatalogEntry


GLOSSARY_PATH = Path(__file__).with_name("u6_glossary.tsv")
TRANSLATION_GUIDE_PATH = Path(__file__).parents[1] / "ucxt" / "output" / "Translation_Guide.md"
PROMPT_VERSION = "u6-zh-traditional-v1"


@dataclass(frozen=True)
class GlossaryEntry:
    en: str
    zh: str
    policy: str


def load_glossary(path: Path = GLOSSARY_PATH) -> tuple[GlossaryEntry, ...]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].split("\t") != ["en", "zh", "policy"]:
        raise ValueError("invalid U6 glossary header")
    entries: list[GlossaryEntry] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != 3 or not all(fields):
            raise ValueError("invalid U6 glossary row")
        entries.append(GlossaryEntry(*fields))
    return tuple(entries)


def glossary_sha256(path: Path = GLOSSARY_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _glossary_guidance(entries: Iterable[GlossaryEntry]) -> str:
    return "\n".join(f"- {entry.en} -> {entry.zh} ({entry.policy})" for entry in entries)


def _guide_guidance(path: Path = TRANSLATION_GUIDE_PATH) -> str:
    return path.read_text(encoding="utf-8")


def translation_system_prompt() -> str:
    return (
        "你是《創世紀 6》（Ultima VI）的繁體中文翻譯器。只翻譯提供的 U6 文本，"
        "使用自然、穩定的繁體中文；不要輸出解釋、Markdown 或 JSON 以外的內容。\n"
        "U6 詞彙表是本任務唯一的專有名詞翻譯來源；下方 U7 指南只提供繁體中文、"
        "標點、控制字元與格式規則，不得把其中未列於 U6 詞彙表的 U7 名稱自動帶入 U6。\n"
        "嚴格保留每個 protected token（例如 @...@、~、*、<PLAYER_NAME> 等）的數量、"
        "拼寫與順序；魔法咒語保持英文。NPC 對話使用全形引號「」。\n\n"
        "U6 glossary:\n"
        f"{_glossary_guidance(load_glossary())}\n\n"
        "Existing Translation_Guide.md guidance (rules only; not an additional U6 glossary):\n"
        f"{_guide_guidance()}"
    )


def review_system_prompt() -> str:
    return (
        "你是《創世紀 6》（Ultima VI）的繁體中文語意審查員。檢查候選譯文是否忠實、"
        "自然、符合 U6 詞彙表與繁體中文規則，並檢查 protected token 是否完整。"
        "審查結果僅供人工參考，不得假設可以直接覆寫候選譯文。只輸出要求的 JSON，"
        "不要輸出 Markdown 或解釋。\n\n"
        "U6 glossary:\n"
        f"{_glossary_guidance(load_glossary())}\n\n"
        "Existing Translation_Guide.md guidance (rules only; not an additional U6 glossary):\n"
        f"{_guide_guidance()}"
    )


def translation_user_payload(entries: Iterable[CatalogEntry]) -> str:
    indexed = [
        {
            "index": index,
            "key": entry.key,
            "kind": entry.kind,
            "context": entry.context,
            "source": entry.source,
            "source_sha256": entry.source_sha256,
            "protected_tokens": list(entry.protected_tokens),
        }
        for index, entry in enumerate(entries)
    ]
    return json.dumps(
        {
            "entries": indexed,
            "response_schema": [
                {"key": "...", "source_sha256": "...", "zh": "...", "status": "translated"}
            ],
            "instruction": "Return exactly one JSON array with one object per entry; preserve input keys and hashes.",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def review_user_payload(
    entries: Iterable[CatalogEntry], translations: Iterable[dict[str, str]]
) -> str:
    indexed = [
        {
            "index": index,
            "key": entry.key,
            "kind": entry.kind,
            "context": entry.context,
            "source": entry.source,
            "source_sha256": entry.source_sha256,
            "protected_tokens": list(entry.protected_tokens),
            "translation": translation["zh"],
        }
        for index, (entry, translation) in enumerate(zip(entries, translations))
    ]
    return json.dumps(
        {
            "entries": indexed,
            "response_schema": [
                {
                    "key": "...",
                    "source_sha256": "...",
                    "status": "ok|advisory",
                    "issues": ["..."],
                    "suggested_zh": "...",
                }
            ],
            "instruction": "Return exactly one JSON object with a reviews array in input order.",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
