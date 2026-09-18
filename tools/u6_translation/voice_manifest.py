from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from collections.abc import Mapping
from typing import Any, Iterable

from .catalog import CatalogEntry
from .runtime_table import RuntimeRow


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


@dataclass(frozen=True)
class VoiceAssignment:
    speaker: str
    speaker_id: int
    voice_id_en: str
    voice_id_zh: str
    voice_desc: str
    status: str


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
    by_key: dict[str, list[VoiceManifestRow]] = {}
    for row in rows:
        by_key.setdefault(row.key, []).append(row)

    return [
        {
            "key": key,
            "source_sha256": sorted({row.source_sha256 for row in key_rows}),
            "row_count": len(key_rows),
        }
        for key, key_rows in sorted(by_key.items())
        if len(key_rows) > 1
    ]


def load_voice_assignments(path: Path) -> list[VoiceAssignment]:
    """Load U7-compatible or U6 bilingual voice assignments deterministically."""

    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or ())
        u6_fields = {"speaker", "speaker_id", "en_voice_id", "zh_voice_id", "voice_desc", "status"}
        u7_fields = {"npc_name", "voice_id", "voice_name"}
        if not (u6_fields <= fields or u7_fields <= fields):
            raise ValueError("unsupported voice assignment CSV schema")
        assignments: list[VoiceAssignment] = []
        for row in reader:
            if u6_fields <= fields:
                raw_id = (row.get("speaker_id") or "").strip()
                try:
                    speaker_id = int(raw_id, 10) if raw_id else 0
                except ValueError as error:
                    raise ValueError(f"invalid speaker_id: {raw_id!r}") from error
                assignments.append(
                    VoiceAssignment(
                        speaker=(row.get("speaker") or "").strip(),
                        speaker_id=speaker_id,
                        voice_id_en=(row.get("en_voice_id") or "").strip(),
                        voice_id_zh=(row.get("zh_voice_id") or "").strip(),
                        voice_desc=(row.get("voice_desc") or "").strip(),
                        status=(row.get("status") or "needs-review").strip(),
                    )
                )
            else:
                voice_id = (row.get("voice_id") or "").strip()
                assignments.append(
                    VoiceAssignment(
                        speaker=(row.get("npc_name") or "").strip(),
                        speaker_id=0,
                        voice_id_en=voice_id,
                        voice_id_zh=voice_id,
                        voice_desc=(row.get("voice_name") or "").strip(),
                        status="approved",
                    )
                )
    return sorted(
        assignments,
        key=lambda assignment: (
            assignment.speaker,
            assignment.speaker_id,
            assignment.voice_id_en,
            assignment.voice_id_zh,
            assignment.voice_desc,
            assignment.status,
        ),
    )


def _speaker_id(speaker: str) -> int:
    match = re.fullmatch(r"Unresolved · NPC ([0-9]+)", speaker)
    return int(match.group(1), 10) if match else 0


def _assignment_for(
    speaker: str, speaker_id: int, assignments: list[VoiceAssignment]
) -> VoiceAssignment | None:
    by_name = [assignment for assignment in assignments if speaker and assignment.speaker == speaker]
    candidates = by_name or [
        assignment
        for assignment in assignments
        if speaker_id and assignment.speaker_id == speaker_id
    ]
    return candidates[0] if len(candidates) == 1 else None


def build_voice_rows(
    catalog: Iterable[CatalogEntry],
    translations: Iterable[RuntimeRow],
    speakers: Mapping[str, str],
    assignments: Iterable[VoiceAssignment],
) -> list[VoiceManifestRow]:
    """Join U6 dialogue only, retaining incomplete lines for human review."""

    translations_by_identity: dict[tuple[str, str, str], list[RuntimeRow]] = {}
    for translation in translations:
        if translation.kind == "dialogue":
            translations_by_identity.setdefault(
                (translation.kind, translation.key, translation.source_sha256), []
            ).append(translation)
    ordered_assignments = sorted(assignments, key=lambda assignment: (
        assignment.speaker, assignment.speaker_id, assignment.voice_id_en,
        assignment.voice_id_zh, assignment.voice_desc, assignment.status,
    ))
    rows: list[VoiceManifestRow] = []
    for entry in sorted(catalog, key=lambda value: (value.key, value.source_sha256)):
        if entry.kind != "dialogue":
            continue
        function_id, offset_key, segment = parse_voice_key(entry.key)
        translation_matches = translations_by_identity.get(
            (entry.kind, entry.key, entry.source_sha256), []
        )
        translation_values = {match.zh for match in translation_matches if match.zh.strip()}
        text_zh = sorted(translation_values)[0] if len(translation_values) == 1 else ""
        speaker = speakers.get(entry.key, "").strip()
        speaker_id = _speaker_id(speaker)
        assignment = _assignment_for(speaker, speaker_id, ordered_assignments)
        reasons: list[str] = []
        if not text_zh:
            reasons.append("translation missing or ambiguous")
        if not speaker or speaker.startswith(("Ambiguous ·", "Unresolved ·")):
            reasons.append("speaker missing or ambiguous")
        if assignment is None:
            reasons.append("casting missing or ambiguous")
        elif assignment.status != "approved":
            reasons.append("casting not approved")
        elif not assignment.voice_id_en or not assignment.voice_id_zh:
            reasons.append("casting missing voice id")
        tts_en = ""
        tts_zh = ""
        if not reasons:
            try:
                tts_en = normalize_tts_text(entry.source, "en")
                tts_zh = normalize_tts_text(text_zh, "zh")
            except ValueError as error:
                reasons.append(str(error))
        rows.append(
            VoiceManifestRow(
                key=entry.key,
                function_id=function_id,
                offset_key=offset_key,
                segment=segment,
                source_en=entry.source,
                source_sha256=entry.source_sha256,
                text_zh=text_zh,
                tts_en=tts_en,
                tts_zh=tts_zh,
                speaker_id=speaker_id,
                speaker=speaker if not speaker.startswith(("Ambiguous ·", "Unresolved ·")) else "",
                voice_id_en=assignment.voice_id_en if assignment else "",
                voice_id_zh=assignment.voice_id_zh if assignment else "",
                voice_desc=assignment.voice_desc if assignment else "",
                status="approved" if not reasons else "needs-review",
                skip_reason="; ".join(reasons),
            )
        )
    return rows


_PROVIDER_FIELDS = (
    "filename", "func_id", "offset_key", "segment", "speaker", "speaker_source",
    "npc_num", "voice_id", "voice_desc", "prev_text", "next_text", "text",
)


def _provider_row(row: VoiceManifestRow, voice_id: str, text: str) -> dict[str, object]:
    return {
        "filename": voice_filename(row.function_id, row.offset_key, row.segment),
        "func_id": f"{row.function_id:04x}",
        "offset_key": row.offset_key,
        "segment": row.segment,
        "speaker": row.speaker,
        "speaker_source": "runtime-capture" if row.speaker else "static-catalog",
        "npc_num": row.speaker_id,
        "voice_id": voice_id,
        "voice_desc": row.voice_desc,
        "prev_text": "",
        "next_text": "",
        "text": text,
    }


def write_generation_manifests(output_dir: Path, rows: Iterable[VoiceManifestRow]) -> None:
    """Write all rows for review plus paired provider manifests for approved rows."""

    output_dir.mkdir(parents=True, exist_ok=True)
    ordered_rows = sorted(rows, key=lambda row: (row.key, row.source_sha256))
    (output_dir / "u6_voice_manifest.jsonl").write_text(
        "".join(json.dumps(asdict(row), ensure_ascii=False, separators=(",", ":")) + "\n" for row in ordered_rows),
        encoding="utf-8",
    )
    approved_rows = [row for row in ordered_rows if row.status == "approved"]
    for language, voice_attr, text_attr in (
        ("en", "voice_id_en", "tts_en"),
        ("zh", "voice_id_zh", "tts_zh"),
    ):
        with (output_dir / f"{language}_manifest.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_PROVIDER_FIELDS, lineterminator="\n")
            writer.writeheader()
            for row in approved_rows:
                writer.writerow(_provider_row(row, getattr(row, voice_attr), getattr(row, text_attr)))
