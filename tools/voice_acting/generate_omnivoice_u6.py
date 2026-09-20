#!/usr/bin/env python3
"""Generate the U6 reference voices and bilingual dialogue with OmniVoice.

The Qwen3 output is intentionally left untouched.  This worker writes a
resumable comparison tree under ``u6_voice/omnivoice_refs`` and
``u6_voice/omnivoice``.  U7 reference overrides continue to come from the
approved ``voice/refs`` clips and use the transcript recorded in the U7
reference-import manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from .omnivoice_overrides import OmniVoiceOverrides, load_omnivoice_overrides
except ImportError:  # Direct script execution.
    from omnivoice_overrides import OmniVoiceOverrides, load_omnivoice_overrides


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DESIGNS = PROJECT_DIR / "u6_voice" / "u6_npc_voice_designs.json"
DEFAULT_MAPPING = PROJECT_DIR / "u6_voice" / "manifests" / "u6_qwen3_mapping.json"
DEFAULT_ROLE_MANIFEST = PROJECT_DIR / "u6_voice" / "manifests" / "u6_voice_roles.jsonl"
DEFAULT_U7_MANIFEST = SCRIPT_DIR / "reference_import_manifest.json"
DEFAULT_OVERRIDES = PROJECT_DIR / "u6_voice" / "manifests" / "omnivoice_overrides.json"
DEFAULT_REFS_DIR = PROJECT_DIR / "u6_voice" / "refs"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "u6_voice" / "omnivoice"
DEFAULT_REVIEW_DIR = PROJECT_DIR / "u6_voice" / "omnivoice_review"
DEFAULT_REFERENCE_REVIEW_DIR = PROJECT_DIR / "u6_voice" / "omnivoice_reference_review"
MODEL_ID = "k2-fsa/OmniVoice"
LANGUAGE_NAMES = {"en": "English", "zh": "Chinese"}
ROUTED_REFERENCE_REVISION = "u6-omnivoice-role-routing-v1"
SPECIAL_REFERENCE_IDS = frozenset({
    "npc_avatar_female",
    "npc_avatar_male",
    "npc_unknown",
    "npc_narrator_male",
})

# Task 3 can replace or extend these values with a revisioned manifest at the
# omnivoice_instruction() call boundary without changing pitch heuristics.
DESIGN_INSTRUCTION_OVERRIDES = {
    "u6_aaron_324a17d2": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
    "u6_amanda_161b5245": {"en": "female, moderate pitch, American accent", "zh": "女, 中音调"},
    "u6_arty_762c615c": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
    "u6_budo_4b6e65fd": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
    "u6_dezana_6642c6a6": {"en": "female, moderate pitch, American accent", "zh": "女, 中音调"},
    "u6_dunbar_d41e3d0c": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
    "u6_kenneth_ca70c45c": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
    "u6_leonna_c563a3bc": {"en": "female, moderate pitch, American accent", "zh": "女, 中音调"},
    "u6_marney_b33f933c": {"en": "female, low pitch, American accent", "zh": "女, 低音调"},
    "u6_sandy_e42e5767": {"en": "male, low pitch, American accent", "zh": "男, 低音调"},
    "u6_shawn_66e52fa9": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
    "u6_timothy_f787b4f6": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
    "u6_trenton_bell_50adc94b": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
    "u6_wilbur_63606e9b": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
    "u6_zoltan_5aadd2f1": {"en": "male, moderate pitch, American accent", "zh": "男, 中音调"},
}


@dataclass(frozen=True)
class ReferenceJob:
    design_id: str
    npc: str
    lang: str
    text: str
    instruct: str
    output: Path
    source: str
    ref_audio: Path | None
    ref_text: str
    tts_text: str = ""
    override_revision: str | None = None


@dataclass(frozen=True)
class VoicePart:
    role: str
    text: str
    reference_path: Path
    reference_text: str
    reference_id: str
    reference_sha256: str = ""

    def record(self) -> dict[str, str]:
        return {
            "role": self.role,
            "text": self.text,
            "reference_path": str(self.reference_path),
            "reference_text": self.reference_text,
            "reference_id": self.reference_id,
            "reference_sha256": self.reference_sha256,
        }


@dataclass(frozen=True)
class CloneJob:
    design_id: str
    npc: str
    lang: str
    text: str
    ref_audio: Path
    ref_text: str
    output: Path
    func_id: str
    offset_key: str
    segment: int
    tts_text: str = ""
    override_revision: str | None = None
    reference_role: str | None = None
    reference_revision: str | None = None
    reference_sha256: str = ""
    voice_parts: tuple[VoicePart, ...] = field(default_factory=tuple)
    avatar_gender: str | None = None
    variant: str | None = None


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _normalize_role_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def role_key(function_id: str, offset_key: str, segment: str) -> tuple[str, str, str]:
    """Return a stable U6 role-source key across numeric and hex manifests."""
    function_text = str(function_id).strip().lower()
    if function_text.startswith("0x"):
        function_value = int(function_text, 16)
    elif function_text.startswith("0") and len(function_text) == 4:
        function_value = int(function_text, 16)
    else:
        function_value = int(function_text, 10)
    offset_text = str(offset_key).strip().lower().removeprefix("0x")
    offset_text = offset_text.lstrip("0") or "0"
    return (f"{function_value:04x}", offset_text, str(int(str(segment).strip() or "0")))


def load_role_manifest(path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    """Load valid JSONL role sources, reporting malformed rows to stderr."""
    result: dict[tuple[str, str, str], dict[str, str]] = {}
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("row is not an object")
            source_en = row["source_en"]
            text_zh = row["text_zh"]
            if not isinstance(source_en, str) or not isinstance(text_zh, str):
                raise ValueError("role text is not a string")
            key = role_key(row["function_id"], row["offset_key"], row["segment"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            print(f"Skipping malformed role manifest row {line_number}: {error}", file=sys.stderr)
            continue
        result[key] = {
            "source_en": _normalize_role_text(source_en),
            "text_zh": _normalize_role_text(text_zh),
        }
    return result


def _clean_voice_part(text: str) -> str:
    normalized = _normalize_role_text(text).replace("@", "")
    while normalized.endswith("*"):
        normalized = normalized[:-1].rstrip()
    return normalized


def _marker_role_parts(text: str) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = []
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


def parse_role_parts(source_en: str, translated_text: str, lang: str) -> list[tuple[str, str]]:
    """Split dialogue by English-authoritative speaker markers for one language."""
    if lang not in LANGUAGE_NAMES:
        raise ValueError(f"unsupported language: {lang}")
    english_has_speaker = bool(re.search(r"@[^@]*@", source_en))
    if lang == "en":
        return _marker_role_parts(source_en) if english_has_speaker else [("narrator", _clean_voice_part(source_en))]
    if not english_has_speaker:
        text = _clean_voice_part(translated_text)
        return [("narrator", text)] if text else []
    if re.search(r"@[^@]*@", translated_text):
        return _marker_role_parts(translated_text)
    text = _clean_voice_part(translated_text)
    return [("speaker", text)] if text else []


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_seed(*parts: object) -> int:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")


def _designs_by_npc(designs: dict[str, dict[str, Any]]) -> dict[str, tuple[str, dict[str, Any]]]:
    result: dict[str, tuple[str, dict[str, Any]]] = {}
    for design_id, design in designs.items():
        names = design.get("npcs") or [design.get("npc") or design_id]
        for npc in names:
            result[str(npc).strip().lower()] = (design_id, design)
    return result


def load_reference_overrides(manifest_path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Load the approved U7 audio and its exact transcript by NPC/language."""
    manifest = load_json(manifest_path)
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for item in manifest.get("items", []):
        language = str(item.get("language", "")).lower()
        lang = "en" if language.startswith("english") else "zh" if language.startswith("chinese") else ""
        npc = str(item.get("npc", "")).strip().lower()
        destination = str(item.get("destination", "")).strip()
        if not lang or not npc or not destination:
            continue
        path = PROJECT_DIR / "voice" / "refs" / destination
        result[(npc, lang)] = {
            "path": path,
            "ref_text": str(item.get("reference_text", "")).strip(),
            "destination": destination,
            "design_id": str(item.get("design_id", "")).strip(),
            "reference_id": str(item.get("design_id", "")).strip(),
            "sha256": str(item.get("sha256", "")).strip(),
            "candidate_index": item.get("candidate_index"),
        }
    return result


def stage_u7_special_references(
    manifest_path: Path,
    source_refs_dir: Path,
    refs_dir: Path,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Verify and copy the U7 Avatar/narrator reference families for U6 routing."""
    staged: dict[tuple[str, str], dict[str, Any]] = {}
    for item in load_json(manifest_path).get("items", []):
        reference_id = str(item.get("design_id", "")).strip()
        if reference_id not in SPECIAL_REFERENCE_IDS:
            continue
        language = str(item.get("language", "")).lower()
        lang = "en" if language.startswith("english") else "zh" if language.startswith("chinese") else ""
        destination_name = str(item.get("destination", "")).strip()
        transcript = str(item.get("reference_text", "")).strip()
        if not lang or not destination_name or not transcript:
            raise ValueError(f"invalid special U7 reference entry: {item!r}")
        source = Path(source_refs_dir) / destination_name
        if not source.is_file():
            raise FileNotFoundError(f"missing U7 special reference: {source}")
        source_hash = sha256_file(source)
        destination = Path(refs_dir) / destination_name
        if not destination.is_file() or sha256_file(destination) != source_hash:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        if sha256_file(destination) != source_hash:
            raise ValueError(f"staged U7 special reference hash mismatch: {destination}")
        staged[(reference_id, lang)] = {
            "path": destination,
            "ref_text": transcript,
            "reference_id": reference_id,
            "sha256": source_hash,
            "source": source,
        }
    expected_count = len(SPECIAL_REFERENCE_IDS) * len(LANGUAGE_NAMES)
    if len(staged) != expected_count:
        raise ValueError(f"expected {expected_count} special U7 references, staged {len(staged)}")
    return staged


def _design_gender(design: dict[str, Any]) -> str:
    gender = str((design.get("casting_inference") or {}).get("gender", "")).lower()
    return gender if gender in {"male", "female"} else "female"


def _reference_from_override(override: dict[str, Any], fallback_id: str) -> dict[str, Any]:
    path = Path(override["path"])
    return {
        "path": path,
        "ref_text": str(override.get("ref_text") or "").strip(),
        "reference_id": str(override.get("reference_id") or override.get("design_id") or fallback_id),
        "sha256": sha256_file(path) if path.is_file() else str(override.get("sha256") or ""),
    }


def _speaker_reference(
    design_id: str,
    design: dict[str, Any],
    npc: str,
    lang: str,
    refs_dir: Path,
    overrides: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    override = overrides.get((npc.lower(), lang))
    if override:
        return _reference_from_override(override, design_id)
    return {
        "path": refs_dir / _reference_filename(design_id, lang),
        "ref_text": str(design.get(f"ref_{lang}_text") or "").strip(),
        "reference_id": design_id,
        "sha256": "",
    }


def _narrator_reference(
    gender: str,
    lang: str,
    reference_routes: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    reference_id = "npc_narrator_male" if gender == "male" else "npc_unknown"
    try:
        return reference_routes[(reference_id, lang)]
    except KeyError as error:
        raise ValueError(f"missing routed narrator reference {reference_id}/{lang}") from error


def _avatar_filename(entry: dict[str, Any], lang: str, gender: str) -> str:
    filename = str(entry.get(f"{lang}_output_filename") or "").strip()
    if not filename:
        return f"{_runtime_output_stem(entry, lang)}_avatar_{gender}.ogg"
    stem = filename[:-4] if filename.lower().endswith(".ogg") else filename
    return f"{stem}_avatar_{gender}.ogg"


def _pitch_tag(design: dict[str, Any], lang: str) -> str:
    casting = design.get("casting_inference") or {}
    age = str(casting.get("age", "")).lower()
    gender = str(casting.get("gender", "")).lower()
    description = str(design.get("voice_desc_en", "")).lower()
    if gender == "non-human" or age == "elderly" or any(
        word in description for word in ("deep", "weathered", "authoritative", "guarded")
    ):
        value = "very low pitch" if gender == "non-human" else "low pitch"
    elif age == "young" or "youthful" in description:
        value = "high pitch"
    else:
        value = "moderate pitch"
    if lang == "zh":
        return {
            "very low pitch": "极低音调",
            "low pitch": "低音调",
            "moderate pitch": "中音调",
            "high pitch": "高音调",
        }[value]
    return value


def omnivoice_instruction(
    design: dict[str, Any],
    lang: str,
    design_id: str | None = None,
    instruction_overrides: dict[str, dict[str, str]] | None = None,
) -> str:
    """Convert the U6 casting bible into OmniVoice's validated tag syntax."""
    if design_id:
        overrides = {
            **DESIGN_INSTRUCTION_OVERRIDES.get(design_id, {}),
            **(instruction_overrides or {}).get(design_id, {}),
        }
        if instruction := overrides.get(lang):
            return instruction
    casting = design.get("casting_inference") or {}
    gender = str(casting.get("gender", "")).lower()
    age = str(casting.get("age", "")).lower()
    if lang == "zh":
        tags = {"male": "男", "female": "女", "child": "儿童", "young": "青年", "elderly": "老年"}
        result = []
        if gender in tags:
            result.append(tags[gender])
        if age in tags:
            result.append(tags[age])
        result.append(_pitch_tag(design, lang))
        return ", ".join(result)

    result = []
    if gender in {"male", "female"}:
        result.append(gender)
    if age == "young":
        result.append("young adult")
    elif age == "elderly":
        result.append("elderly")
    result.append(_pitch_tag(design, lang))
    result.append("American accent")
    return ", ".join(result)


def _reference_filename(design_id: str, lang: str) -> str:
    return f"{design_id}_{lang}_ref.ogg"


def build_reference_jobs(
    designs: dict[str, dict[str, Any]],
    refs_dir: Path,
    overrides: dict[tuple[str, str], dict[str, Any]],
    generation_overrides: OmniVoiceOverrides | None = None,
) -> list[ReferenceJob]:
    jobs: list[ReferenceJob] = []
    for design_id, design in sorted(designs.items()):
        npc = str(design.get("npc") or design_id)
        for lang in ("en", "zh"):
            text = str(design.get(f"ref_{lang}_text") or "").strip()
            if not text:
                continue
            override = overrides.get((npc.lower(), lang))
            if override:
                jobs.append(ReferenceJob(
                    design_id=design_id,
                    npc=npc,
                    lang=lang,
                    text=text,
                    instruct="",
                    output=refs_dir / _reference_filename(design_id, lang),
                    source="u7",
                    ref_audio=Path(override["path"]),
                    ref_text=str(override.get("ref_text") or text),
                    tts_text=text,
                ))
            else:
                tts_text = generation_overrides.tts_text(text, lang) if generation_overrides else text
                affected = bool(
                    generation_overrides
                    and (
                        tts_text != text
                        or generation_overrides.has_voice_design(design_id, lang)
                    )
                )
                jobs.append(ReferenceJob(
                    design_id=design_id,
                    npc=npc,
                    lang=lang,
                    text=text,
                    instruct=omnivoice_instruction(
                        design,
                        lang,
                        design_id,
                        generation_overrides.voice_design if generation_overrides else None,
                    ),
                    output=refs_dir / _reference_filename(design_id, lang),
                    source="omnivoice_design",
                    ref_audio=None,
                    ref_text=text,
                    tts_text=tts_text,
                    override_revision=generation_overrides.revision if affected else None,
                ))
    return jobs


def _mapping_filename(entry: dict[str, Any], lang: str) -> str:
    value = str(entry.get(f"{lang}_output_filename") or "").strip()
    if value:
        return value
    return f"{_runtime_output_stem(entry, lang)}_0.ogg"


def _runtime_output_stem(entry: dict[str, Any], lang: str) -> str:
    fid = str(entry.get(f"{lang}_func_id") or "0000").lower().removeprefix("0x").zfill(4)
    offset = str(entry.get(f"{lang}_offset_key") or "0")
    segment = entry.get(f"{lang}_segment", 0) or 0
    return f"{fid}_{offset}_{segment}"


def _reference_sha256(reference: dict[str, Any]) -> str:
    path = Path(reference["path"])
    return sha256_file(path) if path.is_file() else str(reference.get("sha256") or "")


def _reference_revision(parts: list[VoicePart]) -> str:
    identity = [
        {
            "role": part.role,
            "reference_id": part.reference_id,
            "reference_sha256": part.reference_sha256,
        }
        for part in parts
    ]
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"{ROUTED_REFERENCE_REVISION}:{digest}"


def build_clone_jobs(
    mapping_path: Path,
    designs: dict[str, dict[str, Any]],
    refs_dir: Path,
    output_dir: Path,
    overrides: dict[tuple[str, str], dict[str, Any]],
    generation_overrides: OmniVoiceOverrides | None = None,
    role_sources: dict[tuple[str, str, str], dict[str, str]] | None = None,
    reference_routes: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> list[CloneJob]:
    by_npc = _designs_by_npc(designs)
    jobs: list[CloneJob] = []
    for entry in load_json(mapping_path):
        if entry.get("voice_generation") == "skip":
            continue
        npc = str(entry.get("npc") or "").strip()
        if not npc:
            continue
        is_avatar = npc.lower() == "avatar"
        if is_avatar:
            design_id, design = "", {}
        else:
            design_id, design = by_npc[npc.lower()]
        for lang in ("en", "zh"):
            text = str(entry.get(f"{lang}_text") or "").strip()
            if not text:
                continue
            func_id = str(entry.get(f"{lang}_func_id") or entry.get("en_func_id") or entry.get("zh_func_id") or "")
            offset_key = str(entry.get(f"{lang}_offset_key") or entry.get("en_offset_key") or entry.get("zh_offset_key") or "")
            segment = int(entry.get(f"{lang}_segment", 0) or 0)
            route_source = role_sources.get(role_key(func_id, offset_key, str(segment))) if role_sources else None
            routed = route_source is not None and reference_routes is not None
            variants = ("male", "female") if is_avatar and routed else (None,)
            for avatar_gender in variants:
                current_design_id = f"npc_avatar_{avatar_gender}" if avatar_gender else design_id
                current_design = design
                if is_avatar:
                    current_design = {"casting_inference": {"gender": avatar_gender}}
                speaker = (
                    reference_routes[(current_design_id, lang)]
                    if is_avatar and reference_routes is not None
                    else _speaker_reference(
                        current_design_id,
                        current_design,
                        npc,
                        lang,
                        refs_dir,
                        overrides,
                    )
                )
                tts_text = generation_overrides.tts_text(text, lang) if generation_overrides else text
                affected = bool(
                    generation_overrides
                    and (
                        tts_text != text
                        or (
                            not overrides.get((npc.lower(), lang))
                            and not is_avatar
                            and generation_overrides.has_voice_design(current_design_id, lang)
                        )
                    )
                )
                voice_parts: tuple[VoicePart, ...] = ()
                reference_role: str | None = None
                reference_revision: str | None = None
                ref = speaker
                if routed:
                    source_text = str(route_source["source_en"])
                    translated_text = str(route_source.get("text_zh") or text)
                    parts = parse_role_parts(source_text, translated_text, lang)
                    if not parts:
                        parts = [("narrator", text)]
                    gender = avatar_gender or _design_gender(current_design)
                    routed_parts = []
                    for role, part_text in parts:
                        part_reference = speaker if role == "speaker" else _narrator_reference(
                            gender, lang, reference_routes
                        )
                        routed_parts.append(VoicePart(
                            role=role,
                            text=part_text,
                            reference_path=Path(part_reference["path"]),
                            reference_text=str(part_reference["ref_text"]),
                            reference_id=str(part_reference["reference_id"]),
                            reference_sha256=_reference_sha256(part_reference),
                        ))
                    ref = {
                        "path": routed_parts[0].reference_path,
                        "ref_text": routed_parts[0].reference_text,
                    }
                    reference_revision = _reference_revision(routed_parts)
                    reference_sha256 = routed_parts[0].reference_sha256
                    if len(routed_parts) > 1:
                        voice_parts = tuple(routed_parts)
                        reference_role = "mixed"
                    elif routed_parts[0].role == "speaker":
                        reference_role = f"avatar_{gender}" if avatar_gender else "speaker"
                    else:
                        reference_role = f"narrator_{gender}"
                jobs.append(CloneJob(
                    design_id=current_design_id,
                    npc=npc,
                    lang=lang,
                    text=text,
                    ref_audio=Path(ref["path"]),
                    ref_text=str(ref["ref_text"]),
                    output=output_dir / lang / (
                        _avatar_filename(entry, lang, avatar_gender)
                        if avatar_gender else _mapping_filename(entry, lang)
                    ),
                    func_id=func_id,
                    offset_key=offset_key,
                    segment=segment,
                    tts_text=tts_text,
                    override_revision=generation_overrides.revision if affected else None,
                    reference_role=reference_role,
                    reference_revision=reference_revision,
                    reference_sha256=reference_sha256 if routed else "",
                    voice_parts=voice_parts,
                    avatar_gender=avatar_gender,
                    variant=f"avatar_{avatar_gender}" if avatar_gender else None,
                ))
    return jobs


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def _write_ogg_atomic(path: Path, audio: Any, sample_rate: int) -> None:
    import numpy as np
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    array = np.asarray(audio, dtype=np.float32).squeeze()
    if array.size == 0:
        raise ValueError("cannot write empty audio")
    if array.ndim != 1:
        raise ValueError(f"expected mono audio, got shape {array.shape}")
    with tempfile.NamedTemporaryFile(suffix=".ogg", prefix=f".{path.stem}.", dir=path.parent, delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        sf.write(str(temp_path), array, int(sample_rate), format="OGG", subtype="VORBIS")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _metadata_path(audio_path: Path) -> Path:
    return audio_path.with_suffix(".json")


def _read_metadata(audio_path: Path) -> dict[str, Any]:
    path = _metadata_path(audio_path)
    try:
        value = load_json(path)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _job_tts_text(job: ReferenceJob | CloneJob) -> str:
    return job.tts_text or job.text


def _job_seed(job: ReferenceJob | CloneJob) -> int:
    routing_identity = ""
    if isinstance(job, CloneJob):
        routing_identity = json.dumps({
            "reference_role": job.reference_role,
            "reference_revision": job.reference_revision,
            "reference_sha256": job.reference_sha256,
            "voice_parts": [part.record() for part in job.voice_parts],
            "avatar_gender": job.avatar_gender,
            "variant": job.variant,
        }, ensure_ascii=False, sort_keys=True)
    return stable_seed(
        job.design_id,
        job.npc,
        job.lang,
        job.text,
        _job_tts_text(job),
        job.override_revision or "",
        routing_identity,
        job.output,
    )


def _completion_expected(job: ReferenceJob | CloneJob) -> dict[str, Any]:
    expected = {
        "status": "generated",
        "design_id": job.design_id,
        "lang": job.lang,
        "text": job.text,
    }
    if job.override_revision:
        expected.update({
            "tts_text": _job_tts_text(job),
            "override_revision": job.override_revision,
        })
    if isinstance(job, CloneJob) and job.reference_revision:
        expected.update({
            "reference_role": job.reference_role,
            "reference_revision": job.reference_revision,
            "reference_sha256": job.reference_sha256,
            "voice_parts": [part.record() for part in job.voice_parts],
            "avatar_gender": job.avatar_gender,
            "variant": job.variant,
        })
    return expected


def _complete(
    audio_path: Path,
    expected: dict[str, Any] | ReferenceJob | CloneJob,
) -> bool:
    if not audio_path.is_file():
        return False
    job = expected if isinstance(expected, (ReferenceJob, CloneJob)) else None
    if job:
        expected = _completion_expected(job)
    metadata = _read_metadata(audio_path)
    if (
        job
        and job.override_revision is None
        and metadata.get("override_revision") is not None
    ):
        return False
    if (
        job
        and isinstance(job, CloneJob)
        and job.reference_revision is None
        and metadata.get("reference_revision") is not None
    ):
        return False
    try:
        duration = float(metadata.get("duration_seconds") or 0)
    except (TypeError, ValueError):
        return False
    return (
        metadata.get("status") == "generated"
        and duration > 0
        and all(
        metadata.get(key) == value for key, value in expected.items()
        )
    )


def _normalize_target(value: object) -> str:
    return str(value).strip().replace("\\", "/").lower()


def _target_values(values: list[str] | None) -> set[str]:
    result = set()
    for value in values or []:
        result.update(
            _normalize_target(part)
            for part in str(value).split(",")
            if part.strip()
        )
    return result


def _job_output_keys(job: ReferenceJob | CloneJob) -> set[str]:
    path = job.output
    keys = {
        path.name,
        path.stem,
        path.as_posix(),
        f"{job.lang}/{path.name}",
        f"{job.lang}/{path.stem}",
    }
    try:
        keys.add(path.relative_to(PROJECT_DIR).as_posix())
    except ValueError:
        pass
    if isinstance(job, ReferenceJob):
        keys.update({
            f"{job.design_id}:{job.lang}",
            f"{job.design_id}_{job.lang}_ref",
            f"{job.design_id}_{job.lang}_ref.ogg",
        })
    else:
        output_key = f"{job.func_id}_{job.offset_key}_{job.segment}"
        keys.update({
            output_key,
            f"{output_key}.ogg",
            f"{job.lang}/{output_key}",
            f"{job.lang}/{output_key}.ogg",
            f"{job.func_id}:{job.offset_key}:{job.segment}",
        })
    return {_normalize_target(key) for key in keys}


def _job_is_stale(job: ReferenceJob | CloneJob) -> bool:
    if isinstance(job, ReferenceJob) and job.source == "u7":
        return not (job.ref_audio and job.ref_audio.is_file())
    return not _complete(job.output, job)


def select_target_jobs(
    jobs: list[ReferenceJob | CloneJob],
    *,
    npcs: list[str] | None = None,
    design_ids: list[str] | None = None,
    output_keys: list[str] | None = None,
    lang: str = "both",
    stale_only: bool = False,
) -> list[ReferenceJob | CloneJob]:
    """Select only requested jobs, optionally limiting the result to stale work."""
    if lang not in (*LANGUAGE_NAMES, "both"):
        raise ValueError(f"unsupported language selector: {lang}")
    npc_targets = _target_values(npcs)
    design_targets = _target_values(design_ids)
    output_targets = _target_values(output_keys)
    has_targets = bool(npc_targets or design_targets or output_targets)
    selected = []
    for job in jobs:
        if lang != "both" and job.lang != lang:
            continue
        matches_target = (
            not has_targets
            or _normalize_target(job.npc) in npc_targets
            or _normalize_target(job.design_id) in design_targets
            or bool(_job_output_keys(job) & output_targets)
        )
        if matches_target and (not stale_only or _job_is_stale(job)):
            selected.append(job)
    return selected


def _print_target_counts(label: str, jobs: list[ReferenceJob | CloneJob]) -> None:
    stale = sum(_job_is_stale(job) for job in jobs)
    complete = len(jobs) - stale
    print(
        f"Target {label}: {len(jobs)} matched; {stale} stale; {complete} already complete",
        flush=True,
    )


def _print_route_counts(jobs: list[CloneJob]) -> None:
    ordinary = sum(job.reference_role == "speaker" for job in jobs)
    narrator_only = sum(
        bool(job.reference_role and job.reference_role.startswith("narrator_"))
        for job in jobs
    )
    mixed = sum(bool(job.voice_parts) for job in jobs)
    avatar_male = sum(job.avatar_gender == "male" for job in jobs)
    avatar_female = sum(job.avatar_gender == "female" for job in jobs)
    print(
        "Route counts "
        f"ordinary={ordinary} narrator_only={narrator_only} mixed={mixed} "
        f"avatar_male={avatar_male} avatar_female={avatar_female}",
        flush=True,
    )


def _seed_torch(seed: int) -> None:
    import torch

    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def load_model(gpu: int, model_id: str = MODEL_ID):
    import torch
    from omnivoice.models.omnivoice import OmniVoice

    device = f"cuda:{gpu}" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device.startswith("cuda:") else torch.float32
    print(f"Loading {model_id} on {device} with {dtype}", flush=True)
    model = OmniVoice.from_pretrained(model_id, device_map=device, dtype=dtype)
    print(f"Loaded OmniVoice on {device}; sampling rate={model.sampling_rate}", flush=True)
    return model


def fallback_texts(text: str, lang: str):
    """Yield safe text variants for OmniVoice's short/punctuation edge cases."""
    original = str(text)
    yield original
    stripped = original.lstrip(" \t.,!?;:'\"…，。！？、；：")
    if stripped and stripped != original:
        yield stripped
    collapsed = re.sub(r"([.!?。！？])\1+$", r"\1", stripped)
    if collapsed and collapsed != stripped:
        yield collapsed
    bare = collapsed.rstrip(".!?。！？…")
    if bare and bare != collapsed:
        yield bare
    if not stripped:
        if lang == "en":
            if "!" in original:
                yield "Ah!"
            elif "?" in original:
                yield "What?"
            else:
                yield "Hmm."
        else:
            if "！" in original or "!" in original:
                yield "啊！"
            elif "？" in original or "?" in original:
                yield "什麼？"
            else:
                yield "嗯。"


def _audio_length(audio: Any) -> int:
    try:
        return len(audio)
    except TypeError:
        return 0


def _audio_from_model(
    model,
    job: ReferenceJob | CloneJob,
    prompt_cache: dict[str, Any] | None = None,
    *,
    seed_offset: int = 0,
    text_override: str | None = None,
):
    import torch

    target_text = _job_tts_text(job) if text_override is None else text_override
    seed = _job_seed(job) + seed_offset
    _seed_torch(seed)
    kwargs = {
        "num_step": 32,
        "guidance_scale": 2.0,
        "speed": 1.0,
        "postprocess_output": True,
    }
    if isinstance(job, ReferenceJob):
        audios = model.generate(
            text=target_text,
            language=LANGUAGE_NAMES[job.lang],
            instruct=job.instruct,
            **kwargs,
        )
    else:
        key = f"{job.ref_audio.resolve()}\n{job.ref_text}"
        prompt = prompt_cache.get(key) if prompt_cache is not None else None
        if prompt is None:
            prompt = model.create_voice_clone_prompt(
                ref_audio=str(job.ref_audio),
                ref_text=job.ref_text,
            )
            if prompt_cache is not None:
                prompt_cache[key] = prompt
        audios = model.generate(
            text=target_text,
            language=LANGUAGE_NAMES[job.lang],
            voice_clone_prompt=prompt,
            **kwargs,
        )
    if not audios:
        raise RuntimeError("OmniVoice returned no audio")
    audio = audios[0]
    if _audio_length(audio) == 0:
        raise RuntimeError("OmniVoice returned empty audio")
    return audio, int(model.sampling_rate), seed


def _render_with_fallbacks(
    model,
    job: ReferenceJob | CloneJob,
    prompt_cache: dict[str, Any] | None = None,
):
    """Retry failed/empty renders with deterministic seeds and safe text."""
    last_error: Exception | None = None
    for text_override in fallback_texts(_job_tts_text(job), job.lang):
        for seed_offset in range(4):
            try:
                result = _audio_from_model(
                    model,
                    job,
                    prompt_cache,
                    seed_offset=seed_offset,
                    text_override=text_override,
                )
                return result, text_override
            except Exception as error:
                last_error = error
    raise RuntimeError(
        f"OmniVoice failed for {job.npc} {job.lang} after fallback retries: {last_error}"
    )


def _reference_records(jobs: list[ReferenceJob]) -> list[dict[str, Any]]:
    records = []
    for job in jobs:
        if job.source == "u7":
            audio = job.ref_audio if job.ref_audio and job.ref_audio.exists() else None
            status = "reused_u7" if audio else "missing_u7"
            metadata = {}
        else:
            audio = job.output if job.output.exists() else None
            metadata = _read_metadata(job.output)
            status = "generated" if _complete(job.output, job) else "missing"
        records.append({
            "design_id": job.design_id,
            "npc": job.npc,
            "lang": job.lang,
            "text": job.text,
            "ref_text": job.ref_text,
            "instruct": job.instruct,
            "source": job.source,
            "status": status,
            "audio": str(audio.resolve()) if audio else "",
            "filename": audio.name if audio else job.output.name,
            "metadata": metadata,
        })
    return records


def write_reference_review(jobs: list[ReferenceJob], review_dir: Path, title: str = "U6 OmniVoice Reference Review") -> None:
    records = _reference_records(jobs)
    review_dir.mkdir(parents=True, exist_ok=True)
    data = {"title": title, "model": MODEL_ID, "records": records}
    _write_json_atomic(review_dir / "reference_review_data.json", data)
    rows = []
    for record in records:
        audio = Path(record["audio"]) if record["audio"] else None
        source = os.path.relpath(audio, review_dir).replace(os.sep, "/") if audio else ""
        audio_html = (
            f'<audio controls preload="none" src="{html.escape(source, quote=True)}"></audio>'
            if source else '<span class="missing">missing</span>'
        )
        rows.append(
            f'<tr data-status="{html.escape(record["status"])}" data-lang="{record["lang"]}">'
            f'<td>{html.escape(record["npc"])}</td><td>{record["lang"]}</td>'
            f'<td>{html.escape(record["source"])}</td><td>{html.escape(record["status"])}</td>'
            f'<td>{audio_html}</td><td class="text">{html.escape(record["text"])}</td>'
            f'<td class="text">{html.escape(record["instruct"])}</td></tr>'
        )
    page = f'''<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body {{ font:14px system-ui,sans-serif; margin:0; color:#202124; background:#f7f9fc; }}
header {{ position:sticky; top:0; background:white; border-bottom:1px solid #d9dee7; padding:14px 18px; z-index:2; }}
h1 {{ margin:0 0 10px; font-size:20px; }} input,select {{ padding:7px; font:inherit; margin-right:8px; }}
main {{ padding:16px 18px; }} table {{ width:100%; border-collapse:collapse; background:white; }}
th,td {{ border:1px solid #d9dee7; padding:7px; text-align:left; vertical-align:top; }} th {{ background:#eef2f6; }}
audio {{ width:220px; }} .text {{ max-width:560px; white-space:pre-wrap; }} .missing {{ color:#a50e0e; }}
</style>
<header><h1>{html.escape(title)}</h1><div><input id="q" placeholder="Search NPC or prompt"><select id="status"><option value="all">All status</option><option>generated</option><option>reused_u7</option><option>missing</option></select><select id="lang"><option value="all">All languages</option><option value="en">English</option><option value="zh">Chinese</option></select> <span id="count"></span></div></header>
<main><table><thead><tr><th>NPC</th><th>Lang</th><th>Source</th><th>Status</th><th>Audio</th><th>Reference text</th><th>OmniVoice instruction</th></tr></thead><tbody>{''.join(rows)}</tbody></table></main>
<script>
const rows=[...document.querySelectorAll('tbody tr')], q=document.querySelector('#q'), s=document.querySelector('#status'), l=document.querySelector('#lang');
function update() {{ const query=q.value.toLowerCase(), status=s.value, lang=l.value; let n=0; rows.forEach(r=>{{ const ok=(!query||r.textContent.toLowerCase().includes(query))&&(status==='all'||r.dataset.status===status)&&(lang==='all'||r.dataset.lang===lang); r.hidden=!ok; if(ok)n++; }}); document.querySelector('#count').textContent=n+' / '+rows.length; }}
q.oninput=s.onchange=l.onchange=update; update();
</script>'''
    (review_dir / "index.html").write_text(page, encoding="utf-8")


def write_clone_review(output_dir: Path, mapping_path: Path, review_dir: Path, title: str) -> None:
    sys.path.insert(0, str(SCRIPT_DIR))
    from generate_voice_review_html import rows_from_full_voice, write_report

    rows = rows_from_full_voice(output_dir, mapping_path)
    write_report(rows, review_dir, title, review_id=str(time.time()))
    print(f"Review HTML updated: {review_dir / 'index.html'} ({len(rows)} rows)", flush=True)


def chunked(items: list[Any], size: int):
    """Yield ordered, non-empty batches without dropping a tail batch."""
    if size < 1:
        raise ValueError("batch size must be at least 1")
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _worker_jobs[T](jobs: list[T], worker_index: int, worker_count: int) -> list[T]:
    if worker_count < 1 or not 0 <= worker_index < worker_count:
        raise ValueError("worker index/count must satisfy 0 <= index < count and count >= 1")
    return [job for index, job in enumerate(jobs) if index % worker_count == worker_index]


def _audio_batch_from_model(model, jobs: list[ReferenceJob | CloneJob], prompt_cache: dict[str, Any] | None = None):
    """Generate one homogeneous batch, returning one audio tuple per job."""
    if not jobs:
        return []
    import torch

    _seed_torch(stable_seed(*(_job_seed(job) for job in jobs)))
    kwargs = {
        "num_step": 32,
        "guidance_scale": 2.0,
        "speed": 1.0,
        "postprocess_output": True,
    }
    if isinstance(jobs[0], ReferenceJob):
        if not all(isinstance(job, ReferenceJob) for job in jobs):
            raise TypeError("reference and clone jobs cannot share a batch")
        audios = model.generate(
            text=[_job_tts_text(job) for job in jobs],
            language=[LANGUAGE_NAMES[job.lang] for job in jobs],
            instruct=[job.instruct for job in jobs],
            **kwargs,
        )
    else:
        if not all(isinstance(job, CloneJob) for job in jobs):
            raise TypeError("reference and clone jobs cannot share a batch")
        prompts = []
        for job in jobs:
            key = f"{job.ref_audio.resolve()}\n{job.ref_text}"
            prompt = prompt_cache.get(key) if prompt_cache is not None else None
            if prompt is None:
                prompt = model.create_voice_clone_prompt(
                    ref_audio=str(job.ref_audio),
                    ref_text=job.ref_text,
                )
                if prompt_cache is not None:
                    prompt_cache[key] = prompt
            prompts.append(prompt)
        audios = model.generate(
            text=[_job_tts_text(job) for job in jobs],
            language=[LANGUAGE_NAMES[job.lang] for job in jobs],
            voice_clone_prompt=prompts,
            **kwargs,
        )
    if len(audios) != len(jobs):
        raise RuntimeError(f"OmniVoice returned {len(audios)} outputs for {len(jobs)} jobs")
    return [(audio, int(model.sampling_rate), _job_seed(job))
            for job, audio in zip(jobs, audios)]


def _publish_reference(
    job: ReferenceJob,
    audio: Any,
    sample_rate: int,
    seed: int,
    args: argparse.Namespace,
    rendered_text: str | None = None,
) -> None:
    if _audio_length(audio) == 0:
        raise ValueError("cannot publish empty reference audio")
    _write_ogg_atomic(job.output, audio, sample_rate)
    _write_json_atomic(_metadata_path(job.output), {
        "status": "generated",
        "design_id": job.design_id,
        "lang": job.lang,
        "text": job.text,
        "tts_text": _job_tts_text(job),
        "override_revision": job.override_revision,
        "rendered_text": rendered_text or _job_tts_text(job),
        "fallback_used": (rendered_text or _job_tts_text(job)) != _job_tts_text(job),
        "npc": job.npc,
        "source": job.source,
        "instruct": job.instruct,
        "ref_text": job.ref_text,
        "model": args.model,
        "gpu": args.gpu,
        "seed": seed,
        "sample_rate": sample_rate,
        "duration_seconds": round(len(audio) / sample_rate, 3),
        "sha256": sha256_file(job.output),
    })


def _publish_clone(
    job: CloneJob,
    audio: Any,
    sample_rate: int,
    seed: int,
    args: argparse.Namespace,
    rendered_text: str | None = None,
) -> None:
    if _audio_length(audio) == 0:
        raise ValueError("cannot publish empty clone audio")
    _write_ogg_atomic(job.output, audio, sample_rate)
    metadata = {
        "status": "generated",
        "design_id": job.design_id,
        "lang": job.lang,
        "text": job.text,
        "tts_text": _job_tts_text(job),
        "override_revision": job.override_revision,
        "rendered_text": rendered_text or _job_tts_text(job),
        "fallback_used": (rendered_text or _job_tts_text(job)) != _job_tts_text(job),
        "npc": job.npc,
        "ref_audio": str(job.ref_audio),
        "ref_text": job.ref_text,
        "model": args.model,
        "gpu": args.gpu,
        "seed": seed,
        "sample_rate": sample_rate,
        "duration_seconds": round(len(audio) / sample_rate, 3),
        "sha256": sha256_file(job.output),
        "func_id": job.func_id,
        "offset_key": job.offset_key,
        "segment": job.segment,
    }
    if job.reference_revision:
        metadata.update({
            "reference_role": job.reference_role,
            "reference_revision": job.reference_revision,
            "reference_sha256": job.reference_sha256,
            "voice_parts": [part.record() for part in job.voice_parts],
            "avatar_gender": job.avatar_gender,
            "variant": job.variant,
        })
    _write_json_atomic(_metadata_path(job.output), metadata)


def process_references(
    args: argparse.Namespace,
    all_jobs: list[ReferenceJob],
    review_jobs: list[ReferenceJob] | None = None,
) -> None:
    review_jobs = review_jobs or all_jobs
    jobs = _worker_jobs(all_jobs, args.worker_index, args.worker_count)
    generated_jobs = [job for job in jobs if job.source == "omnivoice_design"]
    print(
        f"Reference worker {args.worker_index}/{args.worker_count}: {len(jobs)} assigned, "
        f"{len(generated_jobs)} OmniVoice designs, {len(jobs) - len(generated_jobs)} U7 reuses",
        flush=True,
    )
    pending = []
    for index, job in enumerate(jobs, 1):
        if job.source == "u7":
            print(f"[ref {index}/{len(jobs)}] reuse {job.npc} {job.lang}: {job.ref_audio}", flush=True)
            continue
        if _complete(job.output, job):
            print(f"[ref {index}/{len(jobs)}] resume {job.npc} {job.lang}", flush=True)
            continue
        pending.append(job)
    model = load_model(args.gpu, args.model) if pending else None
    for batch_index, batch in enumerate(chunked(pending, args.batch_size), 1):
        try:
            results = _audio_batch_from_model(model, batch)
        except Exception as error:
            if len(batch) > 1:
                print(f"[ref batch {batch_index}] batch failed ({error}); retrying individually", flush=True)
                try:
                    import torch
                    torch.cuda.empty_cache()
                except Exception:
                    pass
                results = []
                for job in batch:
                    try:
                        results.extend([_audio_from_model(model, job)])
                    except Exception as individual_error:
                        print(f"[ref] ERROR {job.npc} {job.lang}: {individual_error}", flush=True)
                        results.append(None)
            else:
                print(f"[ref] ERROR {batch[0].npc} {batch[0].lang}: {error}", flush=True)
                results = [None]
        for job, result in zip(batch, results):
            rendered_text = _job_tts_text(job)
            if result is None or _audio_length(result[0]) == 0:
                try:
                    result, rendered_text = _render_with_fallbacks(model, job)
                    print(f"[ref] fallback {job.npc} {job.lang}: {rendered_text!r}", flush=True)
                except Exception as error:
                    print(f"[ref] ERROR {job.npc} {job.lang}: {error}", flush=True)
                    continue
            audio, sample_rate, seed = result
            try:
                _publish_reference(job, audio, sample_rate, seed, args, rendered_text)
                print(f"[ref] OK {job.npc} {job.lang}", flush=True)
            except Exception as error:
                print(f"[ref] ERROR writing {job.npc} {job.lang}: {error}", flush=True)
        if args.worker_index == 0 and time.time() - args.last_review >= args.review_interval:
            write_reference_review(review_jobs, args.reference_review_dir)
            args.last_review = time.time()
    # Every worker refreshes on exit.  With split workers, the last worker to
    # finish publishes the complete reference tree rather than leaving a
    # stale page from whichever language happened to finish first.
    write_reference_review(review_jobs, args.reference_review_dir)


def process_voice(args: argparse.Namespace, all_jobs: list[CloneJob]) -> None:
    selected = [job for job in all_jobs if args.lang == "both" or job.lang == args.lang]
    jobs = _worker_jobs(selected, args.worker_index, args.worker_count)
    print(f"Voice worker {args.worker_index}/{args.worker_count}: {len(jobs)} assigned", flush=True)
    pending = []
    for index, job in enumerate(jobs, 1):
        if _complete(job.output, job):
            print(f"[voice {index}/{len(jobs)}] resume {job.npc} {job.lang} {job.output.name}", flush=True)
            continue
        if not job.ref_audio.is_file():
            print(f"[voice {index}/{len(jobs)}] ERROR missing ref {job.ref_audio}", flush=True)
            continue
        pending.append(job)
    model = load_model(args.gpu, args.model) if pending else None
    prompt_cache: dict[str, Any] = {}
    for batch_index, batch in enumerate(chunked(pending, args.batch_size), 1):
        try:
            results = _audio_batch_from_model(model, batch, prompt_cache)
        except Exception as error:
            if len(batch) > 1:
                print(f"[voice batch {batch_index}] batch failed ({error}); retrying individually", flush=True)
                try:
                    import torch
                    torch.cuda.empty_cache()
                except Exception:
                    pass
                results = []
                for job in batch:
                    try:
                        results.extend([_audio_from_model(model, job, prompt_cache)])
                    except Exception as individual_error:
                        print(f"[voice] ERROR {job.npc} {job.lang} {job.output.name}: {individual_error}", flush=True)
                        results.append(None)
            else:
                print(f"[voice] ERROR {batch[0].npc} {batch[0].lang} {batch[0].output.name}: {error}", flush=True)
                results = [None]
        for job, result in zip(batch, results):
            rendered_text = _job_tts_text(job)
            if result is None or _audio_length(result[0]) == 0:
                try:
                    result, rendered_text = _render_with_fallbacks(model, job, prompt_cache)
                    print(f"[voice] fallback {job.npc} {job.lang}: {rendered_text!r}", flush=True)
                except Exception as error:
                    print(f"[voice] ERROR {job.npc} {job.lang} {job.output.name}: {error}", flush=True)
                    continue
            audio, sample_rate, seed = result
            try:
                _publish_clone(job, audio, sample_rate, seed, args, rendered_text)
                print(f"[voice] OK {job.npc} {job.lang} {job.output.name}", flush=True)
            except Exception as error:
                print(f"[voice] ERROR writing {job.npc} {job.lang} {job.output.name}: {error}", flush=True)
        if args.worker_index == 0 and time.time() - args.last_review >= args.review_interval:
            write_clone_review(args.output_dir, args.mapping, args.review_dir, "U6 OmniVoice Clone Review")
            args.last_review = time.time()
    if args.worker_index == 0:
        write_clone_review(args.output_dir, args.mapping, args.review_dir, "U6 OmniVoice Clone Review")


def write_manifest(args: argparse.Namespace, refs: list[ReferenceJob], clones: list[CloneJob]) -> None:
    ref_records = _reference_records(refs)
    clone_records = []
    for job in clones:
        metadata = _read_metadata(job.output)
        clone_records.append({
            "design_id": job.design_id,
            "npc": job.npc,
            "lang": job.lang,
            "text": job.text,
            "tts_text": _job_tts_text(job),
            "override_revision": job.override_revision,
            "ref_audio": str(job.ref_audio),
            "ref_text": job.ref_text,
            "reference_role": job.reference_role,
            "reference_revision": job.reference_revision,
            "reference_sha256": job.reference_sha256,
            "voice_parts": [part.record() for part in job.voice_parts],
            "avatar_gender": job.avatar_gender,
            "variant": job.variant,
            "output": str(job.output),
            "status": "generated" if _complete(job.output, job) else "missing",
            "metadata": metadata,
        })
    _write_json_atomic(args.manifest_path, {
        "model": args.model,
        "reference_manifest": str(args.reference_review_dir / "reference_review_data.json"),
        "reference_records": ref_records,
        "clone_records": clone_records,
    })
    print(f"Wrote {args.manifest_path}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("refs", "voice", "all", "finalize"), default="all")
    parser.add_argument("--lang", choices=("en", "zh", "both"), default="both")
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--worker-index", type=int, default=0)
    parser.add_argument("--worker-count", type=int, default=1)
    parser.add_argument("--model", default=MODEL_ID)
    parser.add_argument("--designs", type=Path, default=DEFAULT_DESIGNS)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--role-manifest", type=Path, default=DEFAULT_ROLE_MANIFEST)
    parser.add_argument("--u7-manifest", type=Path, default=DEFAULT_U7_MANIFEST)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    parser.add_argument("--refs-dir", type=Path, default=DEFAULT_REFS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--review-dir", type=Path, default=DEFAULT_REVIEW_DIR)
    parser.add_argument("--reference-review-dir", type=Path, default=DEFAULT_REFERENCE_REVIEW_DIR)
    parser.add_argument("--manifest-path", type=Path, default=PROJECT_DIR / "u6_voice" / "omnivoice_manifest.json")
    parser.add_argument("--batch-size", type=int, default=4, help="OmniVoice inference batch size; falls back to single jobs on failure")
    parser.add_argument("--review-interval", type=float, default=120.0)
    parser.add_argument(
        "--npc-id",
        "--npc",
        dest="target_npcs",
        action="append",
        default=[],
        help="Target an NPC name; repeat or comma-separate values",
    )
    parser.add_argument(
        "--design-id",
        dest="target_design_ids",
        action="append",
        default=[],
        help="Target a voice-design ID; repeat or comma-separate values",
    )
    parser.add_argument(
        "--output-key",
        dest="target_output_keys",
        action="append",
        default=[],
        help="Target an output filename/key; repeat or comma-separate values",
    )
    parser.add_argument(
        "--stale-only",
        action="store_true",
        help="Exclude selected jobs whose current audio and metadata are complete",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report selected and stale job counts without loading the model or writing audio",
    )
    args = parser.parse_args()
    args.last_review = 0.0
    return args


def main() -> int:
    args = parse_args()
    designs = load_json(args.designs).get("designs", {})
    overrides = load_reference_overrides(args.u7_manifest)
    generation_overrides = load_omnivoice_overrides(args.overrides)
    role_sources = load_role_manifest(args.role_manifest)
    reference_routes = stage_u7_special_references(
        args.u7_manifest,
        PROJECT_DIR / "voice" / "refs",
        args.refs_dir,
    )
    refs = build_reference_jobs(designs, args.refs_dir, overrides, generation_overrides)
    clones = build_clone_jobs(
        args.mapping,
        designs,
        args.refs_dir,
        args.output_dir,
        overrides,
        generation_overrides,
        role_sources,
        reference_routes,
    )
    print(f"U6 designs={len(designs)} refs={len(refs)} clones={len(clones)}", flush=True)
    _print_route_counts(clones)

    selected_refs = select_target_jobs(
        refs,
        npcs=args.target_npcs,
        design_ids=args.target_design_ids,
        output_keys=args.target_output_keys,
        lang=args.lang,
        stale_only=args.stale_only,
    )
    selected_clones = select_target_jobs(
        clones,
        npcs=args.target_npcs,
        design_ids=args.target_design_ids,
        output_keys=args.target_output_keys,
        lang=args.lang,
        stale_only=args.stale_only,
    )
    _print_target_counts("references", selected_refs)
    _print_target_counts("clones", selected_clones)
    if args.dry_run:
        return 0

    if args.phase in {"refs", "all"}:
        process_references(args, selected_refs, refs)
    if args.phase in {"voice", "all"}:
        process_voice(args, selected_clones)
    if args.phase == "finalize":
        write_reference_review(refs, args.reference_review_dir)
        write_clone_review(args.output_dir, args.mapping, args.review_dir, "U6 OmniVoice Clone Review")
        write_manifest(args, refs, clones)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
