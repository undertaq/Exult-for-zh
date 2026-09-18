from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable


@dataclass(frozen=True)
class VoiceManifestRow:
    key: str
    function_id: int
    offset_key: str
    segment: int
    source_en: str
    source_sha256: str
    text_zh: str
    tts_en: str
    tts_zh: str
    speaker_id: int
    speaker: str
    voice_id_en: str
    voice_id_zh: str
    voice_desc: str
    status: str
    skip_reason: str


_VOICE_KEY = re.compile(r"dialogue:0x([0-9a-fA-F]+):([^:]+):([0-9]+)\Z")
_PLACEHOLDER = re.compile(r"<[^>]+>")


def parse_voice_key(key: str) -> tuple[int, str, int]:
    match = _VOICE_KEY.fullmatch(key)
    if match is None:
        raise ValueError(f"invalid dialogue key: {key!r}")
    return int(match.group(1), 16), match.group(2), int(match.group(3), 10)


def voice_filename(function_id: int, offset_key: str, segment: int) -> str:
    return f"{function_id:04x}_{offset_key}_{segment}.ogg"


def normalize_tts_text(text: str, language: str) -> str:
    if language not in {"en", "zh"}:
        raise ValueError(f"unsupported TTS language: {language!r}")

    normalized = text.replace("@", "").replace("*", "").strip()
    normalized = normalized.replace(
        "<PLAYER_NAME>", "Avatar" if language == "en" else "你"
    )
    unresolved = _PLACEHOLDER.search(normalized)
    if unresolved is not None:
        raise ValueError(f"unresolved placeholder: {unresolved.group(0)}")
    return " ".join(normalized.split())


def voice_key_collisions(rows: Iterable[VoiceManifestRow]) -> list[dict[str, Any]]:
    by_key: dict[str, set[str]] = {}
    for row in rows:
        by_key.setdefault(row.key, set()).add(row.source_sha256)

    return [
        {"key": key, "source_sha256": sorted(source_hashes)}
        for key, source_hashes in sorted(by_key.items())
        if len(source_hashes) > 1
    ]
