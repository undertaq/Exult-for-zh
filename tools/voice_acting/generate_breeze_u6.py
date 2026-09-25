#!/usr/bin/env python3
"""Generate the complete U6 bilingual dialogue set with Breeze TTS 2 Clone.

The role manifest is authoritative for narrator/speaker boundaries. Mixed lines
are rendered one part at a time so a narrator reference cannot bleed into a
speaker segment, and narrator gender follows the active speaker gender.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import multiprocessing as mp
import os
import queue
import re
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
try:
    import soundfile as sf
except ModuleNotFoundError:  # Routing tests do not need the audio dependency.
    sf = None

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent

MODEL = Path("/home/joe/project/breeze-tts/models/Breeze-TTS-2")
REFERENCE_REVIEW = ROOT / "u6_voice/breeze_tts2_reference_review"
REFERENCE_METADATA = REFERENCE_REVIEW / "metadata.json"
MAPPING = ROOT / "u6_voice/manifests/u6_qwen3_mapping.json"
ROLE_MANIFEST = ROOT / "u6_voice/manifests/u6_voice_roles.jsonl"
RUNTIME_OVERRIDES = ROOT / "u6_voice/manifests/u6_runtime_speaker_overrides.json"
U7_MANIFEST = SCRIPT_DIR / "reference_import_manifest.json"
CATALOG = ROOT / "u6_voice/u6_npc_voice_designs.json"
GENDER_OVERRIDES = ROOT / "u6_voice/manifests/u6_voice_gender_overrides.json"
REFS = ROOT / "u6_voice/refs"
OUTPUT = ROOT / "u6_voice/breeze_tts2_voice"
REVIEW = ROOT / "u6_voice/breeze_tts2_voice_review"
DYNAMIC_MANIFEST = ROOT / "u6_voice/manifests/u6_dynamic_voice_templates.jsonl"
DYNAMIC_OUTPUT = ROOT / "u6_voice/breeze_tts2_dynamic_voice"
DYNAMIC_REVIEW = ROOT / "u6_voice/dynamic_voice_review"
PORTRAIT_MAP = REFERENCE_REVIEW / "portrait_map.json"
ROUTE_REVISION = "u6-breeze-role-routing-v2-gender-volume"
SAMPLE_RATE = 24000
MIX_CROSSFADE_SECONDS = 0.02
MIX_GAP_SECONDS = 0.03


@dataclass(frozen=True)
class Reference:
    reference_id: str
    audio: Path
    text: str
    gender: str


@dataclass(frozen=True)
class VoicePart:
    role: str
    text: str
    reference: Reference


@dataclass(frozen=True)
class BreezeCloneJob:
    key: str
    npc: str
    target_npc: str
    lang: str
    text: str
    func_id: str
    offset_key: str
    segment: int
    output: Path
    parts: tuple[VoicePart, ...]
    active_gender: str
    avatar_gender: str | None
    cross_speaker_target: str | None
    source_en: str
    source_zh: str
    dynamic_template_key: str | None = None
    role_span_index: int | None = None
    role_span_identity: str = ""
    player_gender: str | None = None
    dynamic_slots: tuple[dict[str, Any], ...] = ()
    source_template_en: str = ""
    source_template_zh: str = ""
    canonical_en: str = ""
    canonical_zh: str = ""
    source_parts: tuple[dict[str, Any], ...] = ()
    role_span_start_char: int | None = None
    role_span_end_char: int | None = None

    @property
    def route_mode(self) -> str:
        roles = {part.role for part in self.parts}
        if roles == {"speaker"}:
            return "speaker"
        if roles == {"narrator"}:
            return "narrator"
        return "mixed"

    @property
    def template_key(self) -> str:
        return self.dynamic_template_key or ""

    @property
    def is_dynamic(self) -> bool:
        return self.dynamic_template_key is not None


def _normalize_role_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def role_key(function_id: str, offset_key: str, segment: str) -> tuple[str, str, str]:
    value = str(function_id).strip().lower()
    number = int(value, 16) if value.startswith("0x") or (value.startswith("0") and len(value) == 4) else int(value)
    offset = str(offset_key).strip().lower().removeprefix("0x").lstrip("0") or "0"
    return f"{number:04x}", offset, str(int(str(segment).strip() or "0"))


def load_role_manifest(path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        result[role_key(row["function_id"], row["offset_key"], row["segment"])] = {
            "source_en": _normalize_role_text(row["source_en"]),
            "text_zh": _normalize_role_text(row["text_zh"]),
        }
    return result


def load_runtime_speaker_overrides(path: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    payload = load_json(path)
    result: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in payload if isinstance(payload, list) else payload.get("variants", []):
        lang = str(item.get("lang") or "").strip().lower()
        base = Path(str(item.get("base_output") or "").strip()).name
        variant = {"speaker": str(item.get("speaker") or "").strip(), "speaker_npc": int(item["speaker_npc"])}
        if lang and base and variant["speaker"] and variant["speaker_npc"]:
            if variant not in result.setdefault((lang, base), []):
                result[(lang, base)].append(variant)
    cross_tsv = payload.get("cross_speaker_tsv") if isinstance(payload, dict) else None
    if cross_tsv:
        with (path.parent / str(cross_tsv)).open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream, delimiter="\t"):
                base = Path(str(row.get("base_output") or "").strip()).name
                variant = {"speaker": str(row.get("speaker") or "").strip(), "speaker_npc": int(row["speaker_npc"])}
                if base and variant["speaker"] and variant["speaker_npc"]:
                    for lang in ("en", "zh"):
                        if variant not in result.setdefault((lang, base), []):
                            result[(lang, base)].append(variant)
    return result


def _clean_voice_part(text: str) -> str:
    normalized = _normalize_role_text(text).replace("@", "")
    while normalized.endswith("*"):
        normalized = normalized[:-1].rstrip()
    if re.fullmatch(r"[「」『』“”‘’\"'＂]+", normalized):
        return ""
    return normalized


def _marker_role_parts(text: str) -> list[tuple[str, str]]:
    while text.startswith("@@"):
        text = text[1:]
    parts = []
    cursor = 0
    for marker in re.finditer(r"@([^@]*)@", text):
        narrator = _clean_voice_part(text[cursor:marker.start()])
        speaker = _clean_voice_part(marker.group(1))
        if narrator:
            parts.append(("narrator", narrator))
        if speaker:
            parts.append(("speaker", speaker))
        cursor = marker.end()
    narrator = _clean_voice_part(text[cursor:])
    if narrator:
        parts.append(("narrator", narrator))
    return parts


def _unbalanced_marker_role_parts(text: str) -> list[tuple[str, str]]:
    positions = [match.start() for match in re.finditer("@", text)]
    if not positions:
        value = _clean_voice_part(text)
        return [("narrator", value)] if value else []
    parts = []
    role = "narrator" if positions[0] == 0 else "speaker"
    cursor = 0
    for position in positions:
        value = _clean_voice_part(text[cursor:position])
        if value:
            if parts and parts[-1][0] == role:
                parts[-1] = (role, f"{parts[-1][1]} {value}".strip())
            else:
                parts.append((role, value))
        role = "speaker" if role == "narrator" else "narrator"
        cursor = position + 1
    value = _clean_voice_part(text[cursor:])
    if value:
        parts.append((role, value))
    return parts


def parse_role_parts(source_en: str, translated_text: str, lang: str) -> list[tuple[str, str]]:
    has_marker = "@" in source_en
    has_pair = bool(re.search(r"@[^@]*@", source_en))
    if lang == "en":
        if has_pair:
            return _marker_role_parts(source_en)
        if has_marker:
            return _unbalanced_marker_role_parts(source_en)
        value = _clean_voice_part(source_en)
        return [("narrator", value)] if value else []
    if not has_marker:
        value = _clean_voice_part(translated_text)
        return [("narrator", value)] if value else []
    if re.search(r"@[^@]*@", translated_text):
        return _marker_role_parts(translated_text)
    if "@" in translated_text:
        return _unbalanced_marker_role_parts(translated_text)
    value = _clean_voice_part(translated_text)
    return [("speaker", value)] if value else []


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def narrator_reference_id(gender: str) -> str:
    return "npc_narrator_male" if gender == "male" else "npc_unknown"


def avatar_genders_for_route(npc: str, routed: bool) -> tuple[str | None, ...]:
    if npc.casefold() == "avatar" and routed:
        return ("male", "female")
    return (None,)


def route_voice_parts(source_en: str, text_zh: str, lang: str) -> list[tuple[str, str]]:
    return parse_role_parts(source_en, text_zh, lang)


def _catalog_gender(description: str, fallback: str = "female") -> str:
    primary = description.split(" If ", 1)[0].split(" if ", 1)[0].lower()
    if re.search(r"\b(man|male|gentleman|boy|king|he|him|his)\b", primary):
        return "male"
    if re.search(r"\b(woman|female|lady|girl|queen|she|her)\b", primary):
        return "female"
    return fallback


def _load_gender_overrides(path: Path = GENDER_OVERRIDES) -> dict[str, str]:
    data = load_json(path)
    values = data.get("genders", {}) if isinstance(data, dict) else {}
    return {
        str(npc).casefold(): str(gender).strip().lower()
        for npc, gender in values.items()
        if str(gender).strip().lower() in {"male", "female"}
    }


def _load_reference_catalog() -> tuple[dict[tuple[str, str], Reference], dict[str, str]]:
    data = load_json(REFERENCE_METADATA)
    refs: dict[tuple[str, str], Reference] = {}
    genders: dict[str, str] = {}
    metadata_genders: dict[str, str] = {}
    for row in data.get("rows", []):
        npc = str(row["npc"])
        lang = str(row["lang"])
        category = str(row.get("category") or "")
        gender = category.split(",", 1)[0].strip().lower()
        if gender in {"male", "female"}:
            metadata_genders[npc.casefold()] = gender
        refs[(npc.casefold(), lang)] = Reference(
            reference_id=str(row["voice_id"]),
            audio=Path(row["breeze_audio"]),
            text=str(row["text"]),
            gender=gender,
        )
    designs = load_json(CATALOG).get("designs", {})
    overrides = _load_gender_overrides()
    for design in designs.values():
        description = str(design.get("u6_description") or "")
        casting_gender = str((design.get("casting_inference") or {}).get("gender") or "").strip().lower()
        for npc in design.get("npcs") or [design.get("npc")]:
            if npc:
                key = str(npc).casefold()
                fallback = metadata_genders.get(key, "female")
                inferred = overrides.get(key)
                if inferred is None and key in metadata_genders:
                    inferred = metadata_genders[key]
                if inferred is None and casting_gender in {"male", "female"}:
                    inferred = casting_gender
                if inferred is None:
                    inferred = _catalog_gender(description, fallback)
                genders[key] = inferred
    for key, gender in metadata_genders.items():
        genders.setdefault(key, gender)
    for key, gender in overrides.items():
        genders.setdefault(key, gender)
    for (npc, lang), reference in list(refs.items()):
        gender = genders.get(npc)
        if gender in {"male", "female"} and reference.gender != gender:
            refs[(npc, lang)] = Reference(
                reference.reference_id,
                reference.audio,
                reference.text,
                gender,
            )
    return refs, genders


def _load_u7_references() -> tuple[dict[tuple[str, str], Reference], dict[str, Reference]]:
    by_design: dict[tuple[str, str], Reference] = {}
    by_npc: dict[str, Reference] = {}
    manifest = load_json(U7_MANIFEST)
    for item in manifest.get("items", []):
        language = str(item.get("language", "")).lower()
        lang = "en" if language.startswith("english") else "zh" if language.startswith("chinese") else ""
        design_id = str(item.get("design_id") or "").strip()
        npc = str(item.get("npc") or "").strip()
        destination = Path(str(item.get("destination") or "")).name
        if not lang or not design_id or not destination:
            continue
        path = next(
            (candidate for candidate in (REFS / destination, ROOT / "voice/refs" / destination) if candidate.is_file()),
            REFS / destination,
        )
        if not path.is_file():
            continue
        gender = "female" if design_id == "npc_unknown" else "male"
        ref = Reference(design_id, path, str(item.get("reference_text") or "").strip(), gender)
        by_design[(design_id, lang)] = ref
        if npc:
            by_npc[(npc.casefold(), lang)] = ref
    return by_design, by_npc


def _reference_for_npc(
    npc: str,
    lang: str,
    avatar_gender: str | None,
    breeze_refs: dict[tuple[str, str], Reference],
    u7_design_refs: dict[tuple[str, str], Reference],
    u7_npc_refs: dict[tuple[str, str], Reference],
) -> Reference:
    if npc.casefold() == "avatar":
        ref = u7_design_refs.get((f"npc_avatar_{avatar_gender}", lang))
        if ref:
            return ref
    ref = breeze_refs.get((npc.casefold(), lang))
    if ref:
        return ref
    ref = u7_npc_refs.get((npc.casefold(), lang))
    if ref:
        return ref
    fallback = REFS / f"npc_{_slug(npc)}_{lang}_ref.ogg"
    if fallback.is_file():
        return Reference(f"npc_{_slug(npc)}", fallback, "", "female")
    raise FileNotFoundError(f"no Breeze/U7 reference for {npc} ({lang})")


def _narrator_reference(
    gender: str,
    lang: str,
    u7_design_refs: dict[tuple[str, str], Reference],
) -> Reference:
    reference_id = narrator_reference_id(gender)
    try:
        return u7_design_refs[(reference_id, lang)]
    except KeyError as error:
        raise FileNotFoundError(f"missing narrator reference {reference_id}/{lang}") from error


def _output_name(entry: dict[str, Any], lang: str, avatar_gender: str | None, speaker_npc: int | None) -> str:
    base = str(entry.get(f"{lang}_output_filename") or f"{entry.get('en_func_id')}_{entry.get('en_offset_key')}_{entry.get('en_segment', 0)}.ogg")
    stem = base[:-4] if base.lower().endswith(".ogg") else base
    if avatar_gender:
        return f"{stem}_avatar_{avatar_gender}.ogg"
    if speaker_npc is not None:
        return f"{stem}_npc{speaker_npc}.ogg"
    return f"{stem}.ogg"


def build_breeze_jobs(
    mapping_path: Path = MAPPING,
    output_dir: Path = OUTPUT,
) -> list[BreezeCloneJob]:
    breeze_refs, genders = _load_reference_catalog()
    u7_design_refs, u7_npc_refs = _load_u7_references()
    roles = load_role_manifest(ROLE_MANIFEST)
    cross_variants = load_runtime_speaker_overrides(RUNTIME_OVERRIDES)
    jobs: dict[str, BreezeCloneJob] = {}
    for entry in load_json(mapping_path):
        if entry.get("voice_generation") == "skip":
            continue
        npc = str(entry.get("npc") or "").strip()
        if not npc:
            continue
        for lang in ("en", "zh"):
            text = str(entry.get(f"{lang}_text") or "").strip()
            if not text:
                continue
            func_id = str(entry.get(f"{lang}_func_id") or entry.get("en_func_id") or "")
            offset_key = str(entry.get(f"{lang}_offset_key") or entry.get("en_offset_key") or "")
            segment = int(entry.get(f"{lang}_segment", 0) or 0)
            role_source = roles.get(role_key(func_id, offset_key, str(segment)))
            routed = role_source is not None
            source_en = str(role_source["source_en"] if role_source else entry.get("en_text") or "")
            source_zh = str(role_source["text_zh"] if role_source else entry.get("zh_text") or "")
            base_name = Path(str(entry.get(f"{lang}_output_filename") or "")).name
            targets: list[tuple[str, str | None, int | None]] = []
            for avatar_gender in avatar_genders_for_route(npc, routed):
                targets.append((npc, avatar_gender, None))
            for variant in cross_variants.get((lang, base_name), []):
                targets.append((str(variant["speaker"]), None, int(variant["speaker_npc"])))
            for target_npc, avatar_gender, speaker_npc in targets:
                if avatar_gender:
                    active_gender = avatar_gender
                else:
                    try:
                        active_gender = genders[target_npc.casefold()]
                    except KeyError as error:
                        raise KeyError(f"missing authoritative gender for NPC {target_npc!r}") from error
                parts = route_voice_parts(source_en, source_zh, lang) if routed else [("speaker", text)]
                if not parts:
                    parts = [("narrator", text)]
                voice_parts: list[VoicePart] = []
                for role, part_text in parts:
                    if not part_text:
                        continue
                    reference = (
                        _narrator_reference(active_gender, lang, u7_design_refs)
                        if role == "narrator"
                        else _reference_for_npc(target_npc, lang, avatar_gender, breeze_refs, u7_design_refs, u7_npc_refs)
                    )
                    voice_parts.append(VoicePart(role, part_text, reference))
                if not voice_parts:
                    continue
                output = output_dir / lang / _output_name(entry, lang, avatar_gender, speaker_npc)
                key = f"{lang}:{output.name}"
                jobs[key] = BreezeCloneJob(
                    key=key,
                    npc=npc,
                    target_npc=target_npc,
                    lang=lang,
                    text=text,
                    func_id=func_id,
                    offset_key=offset_key,
                    segment=segment,
                    output=output,
                    parts=tuple(voice_parts),
                    active_gender=active_gender,
                    avatar_gender=avatar_gender,
                    cross_speaker_target=target_npc if target_npc.casefold() != npc.casefold() else None,
                    source_en=source_en,
                    source_zh=source_zh,
                )
    return list(jobs.values())


def load_dynamic_voice_manifest(path: Path) -> list[dict[str, Any]]:
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid dynamic manifest JSON at {path}:{line_number}") from error
        if record.get("schema") != "u6-dynamic-voice-template-v1":
            raise ValueError(f"unsupported dynamic manifest schema at {path}:{line_number}")
        if not re.fullmatch(r"dyn_[0-9a-f]{64}", str(record.get("key") or "")):
            raise ValueError(f"missing stable dynamic key at {path}:{line_number}")
        records.append(record)
    return records


def _dynamic_output_name(record: dict[str, Any], span: dict[str, Any],
                         target_npc: str,
                         role: str, player_gender: str | None,
                         active_gender: str) -> str:
    function_id = int(record["function_id"])
    offset = re.sub(r"[^0-9a-f_]+", "", str(record.get("offset_key") or "0").lower().removeprefix("0x")) or "0"
    player = player_gender or "any"
    return (
        f"{function_id:04x}_{offset}_s{int(record['segment'])}_"
        f"{record['key']}_r{int(span['index'])}_{role}_t{_slug(target_npc)}_"
        f"p{player}_v{active_gender}.ogg"
    )


def build_dynamic_breeze_jobs(
    manifest_path: Path = DYNAMIC_MANIFEST,
    output_dir: Path = DYNAMIC_OUTPUT,
) -> list[BreezeCloneJob]:
    """Create one full canonical role-span job per language/gender route."""
    breeze_refs, genders = _load_reference_catalog()
    u7_design_refs, u7_npc_refs = _load_u7_references()
    jobs: dict[str, BreezeCloneJob] = {}
    for record in load_dynamic_voice_manifest(Path(manifest_path)):
        npc = str(record.get("npc") or "").strip()
        speaker_source = str(
            record.get("speaker") or npc or record.get("caller_guess") or "").strip()
        target_npcs = list(dict.fromkeys(
            candidate.strip()
            for candidate in speaker_source.split("|")
            if candidate.strip()
        ))
        if not target_npcs:
            raise ValueError(f"{record.get('line_id', record.get('key'))}: missing active speaker")
        variants = record.get("player_gender_variants") or [None]
        for target_npc in target_npcs:
            if target_npc.casefold() != "avatar" and target_npc.casefold() not in genders:
                raise KeyError(
                    f"missing authoritative gender for dynamic speaker {target_npc!r} "
                    f"at {record.get('line_id', record.get('key'))}")
            for player_gender in variants:
                if player_gender not in (None, "male", "female"):
                    raise ValueError(f"invalid player-gender variant: {player_gender!r}")
                transcript_key = player_gender or "default"
                active_genders = (
                    [player_gender] if target_npc.casefold() == "avatar" and player_gender
                    else ["male", "female"] if target_npc.casefold() == "avatar"
                    else [genders[target_npc.casefold()]]
                )
                for lang in ("en", "zh"):
                    for span in record.get("role_spans") or []:
                        if not span.get("requires_audio", True):
                            continue
                        role = str(span.get("role") or "").strip().lower()
                        if role not in {"speaker", "narrator"}:
                            raise ValueError(
                                f"{record.get('line_id', record.get('key'))}: "
                                f"ambiguous role span {span.get('index')}: {role!r}")
                        transcript = (span.get("transcripts") or {}).get(transcript_key)
                        if not isinstance(transcript, dict) or not transcript.get(lang):
                            raise ValueError(
                                f"{record.get('line_id', record.get('key'))}: missing "
                                f"{lang}/{transcript_key} transcript for role span {span.get('index')}")
                        text = str(transcript[lang]).strip()
                        if not text or re.search(r"<VAR[^>]*>|<(?:PLAYER_NAME|HONORIFIC|PRONOUN|GENDER_FLAG)>", text):
                            raise ValueError(
                                f"{record.get('line_id', record.get('key'))}: invalid canonical "
                                f"transcript for {lang}/{transcript_key}/span {span.get('index')}")

                        for active_gender in active_genders:
                            avatar_gender = active_gender if target_npc.casefold() == "avatar" else None
                            if role == "narrator":
                                reference = _narrator_reference(
                                    active_gender, lang, u7_design_refs)
                            else:
                                reference = _reference_for_npc(
                                    target_npc, lang, avatar_gender, breeze_refs,
                                    u7_design_refs, u7_npc_refs)
                            filename = _dynamic_output_name(
                                record, span, target_npc, role, player_gender, active_gender)
                            output = Path(output_dir) / lang / filename
                            role_identity = (
                                f"{int(span['index'])}:{role}:"
                                f"{int(span['start_char'])}-{int(span['end_char'])}")
                            job_key = f"{lang}:{filename}"
                            job = BreezeCloneJob(
                                key=job_key,
                                npc=npc or target_npc,
                                target_npc=target_npc,
                                lang=lang,
                                text=text,
                                func_id=f"0x{int(record['function_id']):04X}",
                                offset_key=str(record.get("offset_key") or ""),
                                segment=int(record["segment"]),
                                output=output,
                                parts=(VoicePart(role, text, reference),),
                                active_gender=active_gender,
                                avatar_gender=avatar_gender,
                                cross_speaker_target=(
                                    target_npc if npc and target_npc.casefold() != npc.casefold()
                                    else None),
                                source_en=str(record.get("source_template_en") or ""),
                                source_zh=str(record.get("source_template_zh") or ""),
                                dynamic_template_key=str(record["key"]),
                                role_span_index=int(span["index"]),
                                role_span_identity=role_identity,
                                player_gender=player_gender,
                                dynamic_slots=tuple(dict(slot) for slot in record.get("slots", [])),
                                source_template_en=str(record.get("source_template_en") or ""),
                                source_template_zh=str(record.get("source_template_zh") or ""),
                                canonical_en=str(transcript.get("en") or ""),
                                canonical_zh=str(transcript.get("zh") or ""),
                                source_parts=tuple(dict(part) for part in record.get("source_parts", [])),
                                role_span_start_char=int(span["start_char"]),
                                role_span_end_char=int(span["end_char"]),
                            )
                            previous = jobs.get(job_key)
                            if previous is not None and previous != job:
                                raise ValueError(f"conflicting dynamic jobs target {output}")
                            jobs[job_key] = job
    return list(jobs.values())


def validate_dynamic_output_paths(output_dir: Path, review_dir: Path) -> bool:
    """Prevent dynamic-only runs from overlapping existing U6 voice assets."""
    output = Path(output_dir).resolve()
    review = Path(review_dir).resolve()

    def overlaps(left: Path, right: Path) -> bool:
        return left == right or left in right.parents or right in left.parents

    if overlaps(output, review):
        raise ValueError("dynamic audio and review directories must not overlap")

    voice_root = ROOT / "u6_voice"
    protected_existing = [
        OUTPUT,
        REFS,
        REVIEW,
        DYNAMIC_REVIEW,
        REFERENCE_REVIEW,
        voice_root / "omnivoice",
        voice_root / "omnivoice_trial",
        voice_root / "omnivoice_review",
        voice_root / "omnivoice_reference_review",
        voice_root / "omnivoice_pronunciation_review",
        voice_root / "omnivoice_refs",
        voice_root / "packaged",
        voice_root / "review",
        voice_root / "review_lines",
    ]
    protected_reviews = protected_existing + [DYNAMIC_OUTPUT]
    for protected in protected_existing:
        if overlaps(output, protected.resolve()):
            raise ValueError(
                f"dynamic output overlaps protected existing voice/review path: {protected}")
    for protected in protected_reviews:
        if overlaps(review, protected.resolve()):
            raise ValueError(
                f"dynamic review overlaps protected existing voice/review path: {protected}")
    return True


def audit_breeze_jobs(jobs: list[BreezeCloneJob]) -> dict[str, Any]:
    counts = {"speaker": 0, "narrator": 0, "mixed": 0, "cross_speaker": 0, "avatar_male": 0, "avatar_female": 0}
    mismatches = []
    for job in jobs:
        counts[job.route_mode] += 1
        if job.cross_speaker_target:
            counts["cross_speaker"] += 1
        if job.avatar_gender:
            counts[f"avatar_{job.avatar_gender}"] += 1
        expected = narrator_reference_id(job.active_gender)
        for part in job.parts:
            if part.role == "narrator" and part.reference.reference_id != expected:
                mismatches.append({"key": job.key, "expected": expected, "actual": part.reference.reference_id})
    return {"counts": counts, "narrator_gender_mismatches": mismatches, "total": len(jobs)}


def _usable_output(path: Path, metadata_path: Path) -> bool:
    if sf is None:
        return False
    if not path.is_file() or path.stat().st_size < 1000 or not metadata_path.is_file():
        return False
    try:
        info = sf.info(path)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (RuntimeError, OSError, json.JSONDecodeError):
        return False
    return info.samplerate == SAMPLE_RATE and info.channels == 1 and info.frames > 100 and metadata.get("status") == "generated"


def _metadata_path(path: Path) -> Path:
    return path.with_suffix(".json")


def dynamic_job_signature(job: BreezeCloneJob) -> str:
    """Fingerprint all source and routing inputs that make a dynamic clip."""
    references = []
    for part in job.parts:
        audio = part.reference.audio
        references.append({
            "role": part.role,
            "reference_id": part.reference.reference_id,
            "reference_audio": str(audio),
            "reference_sha256": sha256_file(audio) if audio.is_file() else "",
            "reference_text": part.reference.text,
            "reference_gender": part.reference.gender,
        })
    identity = {
        "template_key": job.dynamic_template_key,
        "role_span_index": job.role_span_index,
        "role_span_identity": job.role_span_identity,
        "source_template_en": job.source_template_en,
        "source_template_zh": job.source_template_zh,
        "source_parts": job.source_parts,
        "slots": job.dynamic_slots,
        "lang": job.lang,
        "player_gender": job.player_gender,
        "active_gender": job.active_gender,
        "target_npc": job.target_npc,
        "text": job.text,
        "references": references,
    }
    payload = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _usable_output_for_job(job: BreezeCloneJob) -> bool:
    if not _usable_output(job.output, _metadata_path(job.output)):
        return False
    if not job.is_dynamic:
        return True
    try:
        metadata = json.loads(_metadata_path(job.output).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return metadata.get("dynamic_job_signature") == dynamic_job_signature(job)


def _write_json_atomic(path: Path, data: Any) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.partial")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _join_audio(parts: list[np.ndarray], sample_rate: int) -> np.ndarray:
    if len(parts) == 1:
        return parts[0]
    gap = np.zeros(round(sample_rate * MIX_GAP_SECONDS), dtype=np.float32)
    overlap = max(1, round(sample_rate * MIX_CROSSFADE_SECONDS))
    result = parts[0].astype(np.float32, copy=False)
    for part in parts[1:]:
        part = part.astype(np.float32, copy=False)
        result = np.concatenate((result, gap))
        n = min(overlap, len(result), len(part))
        if n:
            fade_out = np.linspace(1.0, 0.0, n, dtype=np.float32)
            fade_in = 1.0 - fade_out
            result[-n:] = result[-n:] * fade_out + part[:n] * fade_in
            result = np.concatenate((result, part[n:]))
        else:
            result = np.concatenate((result, part))
    return result


def normalize_audio_for_job(job: BreezeCloneJob, audio: np.ndarray) -> np.ndarray:
    """Bring the known-quiet Beh Lem EN route to the review-set peak level."""
    if job.target_npc.casefold() != "beh lem" or job.lang != "en":
        return audio
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak <= 1e-9:
        return audio
    target_peak = 10 ** (-1.0 / 20.0)
    return np.clip(audio.astype(np.float32, copy=False) * (target_peak / peak), -1.0, 1.0)


def _load_runtime(gpu: int):
    # This must happen before importing torch.  Each spawned worker gets its
    # own logical CUDA device, so worker 0 maps to the 5060 Ti and worker 1
    # maps to the 3060 without either process accidentally selecting GPU 0.
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu)
    import torch
    from breeze_infer.runtime import load_runtime, set_all_seeds, update_generation_config_for_breeze
    from breeze_infer.templates import get_template, prepare_inputs
    from models.fast_streaming import FastBreezeStreamingRuntime, FastStreamingConfig

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    tokenizer, model, audio_tokenizer = load_runtime(MODEL, device=device, attn_implementation="eager")
    update_generation_config_for_breeze(model)
    runtime = FastBreezeStreamingRuntime(
        model,
        audio_tokenizer,
        # Breeze's CUDA-graph stages are safe for one request at a time and
        # substantially faster than the eager path.  Native multi-request
        # generation is intentionally not used: its stochastic codec path
        # currently asserts for batched inputs and its codec decoder is still
        # documented as unbatched.
        FastStreamingConfig(
            max_new_tokens=1500,
            max_seq_len=2048,
            fast_all=True,
            repetition_penalty=1.1,
        ),
        tokenizer=tokenizer,
    )
    return tokenizer, model, audio_tokenizer, runtime, get_template("ref_clone_tata"), prepare_inputs, set_all_seeds


def _render_part(part: VoicePart, job: BreezeCloneJob, index: int, runtime_bundle: tuple[Any, ...]) -> np.ndarray:
    tokenizer, model, audio_tokenizer, runtime, template, prepare_inputs, set_all_seeds = runtime_bundle
    request = {
        "id": f"{job.key}-part{index}",
        "text": part.text,
        "speaker": "S0",
        "ref_audio_path": str(part.reference.audio),
        "ref_text": part.reference.text,
    }
    seed = int.from_bytes(hashlib.sha256(f"{job.key}:{index}".encode()).digest()[:4], "big")
    set_all_seeds(seed)
    inputs = prepare_inputs(
        tokenizer, audio_tokenizer, model, [request], template,
        guidance_scale=1.0, guidance_scale_ref=None, guidance_scale_ins=None,
    )
    chunks = []
    for chunk in runtime.iter_audio_chunks(inputs, request_id=request["id"], seed=seed):
        chunks.append(np.asarray(chunk.audio, dtype=np.float32).reshape(-1))
    if not chunks:
        raise RuntimeError(f"Breeze returned no audio for {job.key} part {index}")
    return np.concatenate(chunks)


def _publish(job: BreezeCloneJob, audio: np.ndarray, runtime_bundle: tuple[Any, ...], gpu: int) -> None:
    if sf is None:
        raise RuntimeError("soundfile is required for Breeze audio rendering")
    job.output.parent.mkdir(parents=True, exist_ok=True)
    partial = job.output.with_name(f".{job.output.stem}.{os.getpid()}.partial.ogg")
    metadata_path = _metadata_path(job.output)
    audio = normalize_audio_for_job(job, audio)
    try:
        sf.write(partial, audio, SAMPLE_RATE, format="OGG", subtype="VORBIS")
        os.replace(partial, job.output)
        metadata = {
            "status": "generated",
            "model": "BreezeBlue/Breeze-TTS-2",
            "route_revision": ROUTE_REVISION,
            "gpu": gpu,
            "npc": job.npc,
            "target_npc": job.target_npc,
            "lang": job.lang,
            "text": job.text,
            "func_id": job.func_id,
            "offset_key": job.offset_key,
            "segment": job.segment,
            "route_mode": job.route_mode,
            "active_gender": job.active_gender,
            "avatar_gender": job.avatar_gender,
            "cross_speaker_target": job.cross_speaker_target,
            "same_sex_narrator": all(
                part.role != "narrator" or part.reference.reference_id == narrator_reference_id(job.active_gender)
                for part in job.parts
            ),
            "source_en": job.source_en,
            "source_zh": job.source_zh,
            "dynamic_template_key": job.dynamic_template_key,
            "role_span_index": job.role_span_index,
            "role_span_identity": job.role_span_identity,
            "player_gender": job.player_gender,
            "dynamic_slots": list(job.dynamic_slots),
            "source_template_en": job.source_template_en,
            "source_template_zh": job.source_template_zh,
            "canonical_en": job.canonical_en,
            "canonical_zh": job.canonical_zh,
            "source_parts": list(job.source_parts),
            "dynamic_job_signature": dynamic_job_signature(job) if job.is_dynamic else None,
            "role_span_start_char": job.role_span_start_char,
            "role_span_end_char": job.role_span_end_char,
            "parts": [
                {
                    "role": part.role,
                    "text": part.text,
                    "reference_id": part.reference.reference_id,
                    "reference_audio": str(part.reference.audio),
                    "reference_text": part.reference.text,
                    "reference_gender": part.reference.gender,
                }
                for part in job.parts
            ],
            "sample_rate": SAMPLE_RATE,
            "duration_seconds": round(len(audio) / SAMPLE_RATE, 3),
            "sha256": sha256_file(job.output),
        }
        _write_json_atomic(metadata_path, metadata)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _worker(jobs: list[BreezeCloneJob], gpu: int, events: mp.Queue, resume: bool) -> None:
    try:
        pending = [job for job in jobs if not (resume and _usable_output_for_job(job))]
        runtime_bundle = _load_runtime(gpu) if pending else None
        for index, job in enumerate(jobs):
            if resume and _usable_output_for_job(job):
                events.put({"kind": "done", "key": job.key, "status": "exists", "gpu": gpu})
                continue
            assert runtime_bundle is not None
            audio_parts = [_render_part(part, job, part_index, runtime_bundle) for part_index, part in enumerate(job.parts)]
            _publish(job, _join_audio(audio_parts, SAMPLE_RATE), runtime_bundle, gpu)
            events.put({"kind": "done", "key": job.key, "status": "saved", "gpu": gpu})
        events.put({"kind": "worker_done", "gpu": gpu})
    except BaseException:
        events.put({"kind": "error", "gpu": gpu, "error": traceback.format_exc()})


def _job_record(job: BreezeCloneJob) -> dict[str, Any]:
    return {
        "key": job.key,
        "npc": job.npc,
        "target_npc": job.target_npc,
        "lang": job.lang,
        "text": job.text,
        "func_id": job.func_id,
        "offset_key": job.offset_key,
        "segment": job.segment,
        "output": str(job.output),
        "route_mode": job.route_mode,
        "active_gender": job.active_gender,
        "avatar_gender": job.avatar_gender,
        "cross_speaker_target": job.cross_speaker_target,
        "dynamic_template_key": job.dynamic_template_key,
        "role_span_index": job.role_span_index,
        "role_span_identity": job.role_span_identity,
        "player_gender": job.player_gender,
        "dynamic_slots": list(job.dynamic_slots),
        "source_template_en": job.source_template_en,
        "source_template_zh": job.source_template_zh,
        "canonical_en": job.canonical_en,
        "canonical_zh": job.canonical_zh,
        "parts": [
            {"role": part.role, "text": part.text, "reference_id": part.reference.reference_id}
            for part in job.parts
        ],
    }


def write_review(
    jobs: list[BreezeCloneJob],
    completed: int,
    review_dir: Path = REVIEW,
    voice_dir: Path = OUTPUT,
    mapping_path: Path = MAPPING,
) -> None:
    review_dir.mkdir(parents=True, exist_ok=True)
    audit = audit_breeze_jobs(jobs)
    sys.path.insert(0, str(SCRIPT_DIR))
    from generate_voice_review_html import rows_from_full_voice, write_report

    rows = rows_from_full_voice(voice_dir, mapping_path)
    write_report(
        rows,
        review_dir,
        "U6 Breeze TTS 2 Clone Review",
        review_id=f"{ROUTE_REVISION}:{time.time_ns()}",
        extra_payload={
            "model": "BreezeBlue/Breeze-TTS-2",
            "route_revision": ROUTE_REVISION,
            "same_sex_narrator_rule": "Narrator reference gender equals active speaker/avatar gender.",
            "completed": completed,
            "total": len(jobs),
            "audit": audit,
        },
    )


def _portrait_for_npc(npc: str, portrait_map: Path = PORTRAIT_MAP) -> str:
    if not portrait_map.is_file():
        return ""
    try:
        matched = load_json(portrait_map).get("matched", {})
    except (OSError, json.JSONDecodeError):
        return ""
    for value in matched.values():
        if str(value.get("npc") or "").casefold() == npc.casefold():
            image = REFERENCE_REVIEW / str(value.get("file") or "")
            return str(image.resolve()) if image.is_file() else ""
    return ""


def dynamic_review_rows(jobs: list[BreezeCloneJob]) -> list[dict[str, Any]]:
    rows = []
    for job in jobs:
        reference = job.parts[0].reference if job.parts else None
        slot_lines = [
            f"VAR{slot.get('ordinal')}: {slot.get('semantic_type')}"
            + (f" ({slot.get('pronoun_form')})" if slot.get("pronoun_form") else "")
            for slot in job.dynamic_slots
        ]
        note = "\n".join((
            f"Template: {job.dynamic_template_key}",
            f"Source EN: {job.source_template_en}",
            f"Source zh-Hant: {job.source_template_zh}",
            "Slots: " + (", ".join(slot_lines) if slot_lines else "none"),
            f"Role span: {job.role_span_identity}",
            f"Active speaker: {job.target_npc} ({job.active_gender})",
            f"Player-gender text variant: {job.player_gender or 'gender-neutral'}",
            f"Canonical EN: {job.canonical_en}",
            f"Canonical zh-Hant: {job.canonical_zh}",
            f"Source provenance parts: {len(job.source_parts)}",
        ))
        rows.append({
            "kind": "dynamic-generated",
            "status": "generated" if _usable_output_for_job(job) else "missing",
            "character": job.npc,
            "npc": job.npc,
            "speaker": job.target_npc,
            "portrait": _portrait_for_npc(job.npc or job.target_npc),
            "lang": job.lang,
            "mood": job.route_mode,
            "text": job.text,
            "audio": str(job.output) if job.output.is_file() else "",
            "ref_audio": str(reference.audio) if reference else "",
            "ref_text": reference.text if reference else "",
            "filename": job.output.name,
            "note": note,
            "template_key": job.dynamic_template_key,
            "role_span_index": job.role_span_index,
            "role_span_identity": job.role_span_identity,
            "active_gender": job.active_gender,
            "player_gender": job.player_gender,
            "canonical_en": job.canonical_en,
            "canonical_zh": job.canonical_zh,
            "source_template_en": job.source_template_en,
            "source_template_zh": job.source_template_zh,
            "dynamic_slots": list(job.dynamic_slots),
            "source_parts": list(job.source_parts),
        })
    return rows


def write_dynamic_review(
    jobs: list[BreezeCloneJob],
    completed: int,
    review_dir: Path = DYNAMIC_REVIEW,
) -> None:
    review_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(SCRIPT_DIR))
    from generate_voice_review_html import write_report

    write_report(
        dynamic_review_rows(jobs),
        review_dir,
        "U6 Dynamic Breeze TTS 2 Review",
        review_id=f"u6-dynamic-breeze:{time.time_ns()}",
        extra_payload={
            "model": "BreezeBlue/Breeze-TTS-2",
            "dynamic_only": True,
            "route_revision": ROUTE_REVISION,
            "same_sex_narrator_rule": "Narrator reference gender equals active speaker gender.",
            "completed": completed,
            "total": len(jobs),
            "audit": audit_breeze_jobs(jobs),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpu-count", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--review-interval", type=float, default=120.0)
    parser.add_argument("--max-jobs", type=int)
    parser.add_argument("--dynamic-only", action="store_true",
                        help="generate reviewed dynamic full-line spans only")
    parser.add_argument("--dynamic-manifest", type=Path, default=DYNAMIC_MANIFEST)
    parser.add_argument("--output-dir", type=Path,
                        help="override output root (dynamic default is isolated)")
    parser.add_argument("--review-dir", type=Path,
                        help="override review root (dynamic default is isolated)")
    args = parser.parse_args()
    if args.gpu_count < 1:
        parser.error("--gpu-count must be at least 1")
    if args.review_interval <= 0:
        parser.error("--review-interval must be positive")
    if args.max_jobs is not None and args.max_jobs < 0:
        parser.error("--max-jobs must be non-negative")
    if args.dynamic_only:
        output_dir = args.output_dir or DYNAMIC_OUTPUT
        review_dir = args.review_dir or DYNAMIC_REVIEW
        try:
            validate_dynamic_output_paths(output_dir, review_dir)
        except ValueError as error:
            parser.error(str(error))
        jobs = build_dynamic_breeze_jobs(args.dynamic_manifest, output_dir)
    else:
        output_dir = args.output_dir or OUTPUT
        review_dir = args.review_dir or REVIEW
        jobs = build_breeze_jobs(output_dir=output_dir)
    if args.max_jobs is not None:
        jobs = jobs[:args.max_jobs]
    audit = audit_breeze_jobs(jobs)
    print(json.dumps(audit, ensure_ascii=False), flush=True)
    completed = (
        sum(_usable_output_for_job(job) for job in jobs)
        if args.resume
        else 0
    )
    if args.dynamic_only:
        write_dynamic_review(jobs, completed, review_dir)
    else:
        write_review(jobs, completed, review_dir, output_dir)
    ctx = mp.get_context("spawn")
    events = ctx.Queue()
    shards = [jobs[index::args.gpu_count] for index in range(args.gpu_count)]
    workers = [ctx.Process(target=_worker, args=(shard, index, events, args.resume), daemon=False) for index, shard in enumerate(shards)]
    for worker in workers:
        worker.start()
    processed = 0
    finished = 0
    last_review = time.monotonic()
    try:
        while finished < len(workers):
            try:
                event = events.get(timeout=30)
            except queue.Empty:
                print("waiting for Breeze workers...", flush=True)
                if time.monotonic() - last_review >= args.review_interval:
                    if args.dynamic_only:
                        write_dynamic_review(jobs, completed, review_dir)
                    else:
                        write_review(jobs, completed, review_dir, output_dir)
                    last_review = time.monotonic()
                continue
            if event["kind"] == "done":
                processed += 1
                if event["status"] == "saved":
                    completed += 1
                print(f"[{processed}/{len(jobs)}] gpu={event['gpu']} {event['status']} {event['key']}", flush=True)
                if time.monotonic() - last_review >= args.review_interval:
                    if args.dynamic_only:
                        write_dynamic_review(jobs, completed, review_dir)
                    else:
                        write_review(jobs, completed, review_dir, output_dir)
                    last_review = time.monotonic()
            elif event["kind"] == "worker_done":
                finished += 1
                print(f"GPU {event['gpu']} worker complete", flush=True)
            elif event["kind"] == "error":
                raise RuntimeError(f"Breeze GPU {event['gpu']} worker failed:\n{event['error']}")
    except BaseException:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
        raise
    finally:
        for worker in workers:
            worker.join()
    if args.dynamic_only:
        write_dynamic_review(jobs, completed, review_dir)
    else:
        write_review(jobs, completed, review_dir, output_dir)
    print(f"complete: {completed}/{len(jobs)}; review: {review_dir / 'index.html'}", flush=True)
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
