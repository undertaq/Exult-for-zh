"""Validated, revisioned text and voice-design overrides for OmniVoice."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_LANGUAGES = {"en", "zh"}
TONE_TOKEN_RE = re.compile(r"[A-Za-z0-9ÜüVv]+")
VALID_TONE_TOKEN_RE = re.compile(r"[A-ZÜV]+[1-5]")


@dataclass(frozen=True)
class PronunciationRule:
    lang: str
    source: str
    tts: str
    expected_pinyin: str
    reason: str


@dataclass(frozen=True)
class OmniVoiceOverrides:
    revision: str
    voice_design: dict[str, dict[str, str]]
    pronunciation: tuple[PronunciationRule, ...]

    def tts_text(self, text: str, lang: str) -> str:
        """Apply literal phrase replacements for one language only."""
        result = str(text)
        for rule in self.pronunciation:
            if rule.lang == lang:
                result = result.replace(rule.source, rule.tts)
        return result

    def has_voice_design(self, design_id: str, lang: str) -> bool:
        return lang in self.voice_design.get(design_id, {})


def _required_string(item: dict[str, Any], field: str, context: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} requires non-empty {field}")
    return value.strip()


def _validate_voice_design(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        raise ValueError("voice_design must be an object")
    result: dict[str, dict[str, str]] = {}
    for design_id, entry in value.items():
        if not isinstance(design_id, str) or not design_id.strip():
            raise ValueError("voice_design requires a non-empty design id")
        if not isinstance(entry, dict):
            raise ValueError(f"voice_design {design_id} must be an object")
        result[design_id] = {
            lang: _required_string(entry, lang, f"voice_design {design_id}")
            for lang in ("en", "zh")
        }
    return result


def _validate_pronunciation(value: Any) -> tuple[PronunciationRule, ...]:
    if not isinstance(value, list):
        raise ValueError("pronunciation must be an array")
    rules: list[PronunciationRule] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(value):
        context = f"pronunciation[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{context} must be an object")
        lang = _required_string(item, "lang", context)
        if lang not in SUPPORTED_LANGUAGES:
            raise ValueError(f"{context} has unsupported lang {lang!r}")
        source = _required_string(item, "source", context)
        tts = _required_string(item, "tts", context)
        expected_pinyin = _required_string(item, "expected_pinyin", context)
        reason = _required_string(item, "reason", context)
        key = (lang, source)
        if key in seen:
            raise ValueError(f"duplicate pronunciation phrase for {lang}: {source}")
        for rule in rules:
            if rule.lang == lang and (source in rule.source or rule.source in source):
                raise ValueError(
                    f"overlapping pronunciation phrases for {lang}: {rule.source!r} and {source!r}"
                )
        tone_tokens = TONE_TOKEN_RE.findall(tts)
        if not tone_tokens or any(not VALID_TONE_TOKEN_RE.fullmatch(token) for token in tone_tokens):
            raise ValueError(f"{context} has malformed pinyin tone control in tts")
        seen.add(key)
        rules.append(PronunciationRule(lang, source, tts, expected_pinyin, reason))
    return tuple(rules)


def load_omnivoice_overrides(path: Path) -> OmniVoiceOverrides:
    """Load and strictly validate an OmniVoice override manifest."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load OmniVoice overrides from {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("OmniVoice override manifest must be an object")
    revision = _required_string(payload, "revision", "manifest")
    if "voice_design" not in payload:
        raise ValueError("manifest requires voice_design")
    if "pronunciation" not in payload:
        raise ValueError("manifest requires pronunciation")
    return OmniVoiceOverrides(
        revision=revision,
        voice_design=_validate_voice_design(payload["voice_design"]),
        pronunciation=_validate_pronunciation(payload["pronunciation"]),
    )
