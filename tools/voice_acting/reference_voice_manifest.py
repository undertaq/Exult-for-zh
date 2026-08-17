#!/usr/bin/env python3
"""Build individual NPC voice designs from selected reference candidates."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any


SPECIAL_DESIGN_IDS = {
    "avatar_male": "npc_avatar_male",
    "avatar_female": "npc_avatar_female",
    "narrator_male": "npc_narrator_male",
    "narrator_female": "npc_unknown",
}

SPECIAL_NPC_NAMES = {
    "avatar_male": "Avatar male",
    "avatar_female": "Avatar female",
    "narrator_male": "Narrator male",
    "narrator_female": "UNKNOWN",
}


class ManifestError(ValueError):
    """Raised when the selected-reference manifest is incomplete or invalid."""


@dataclass(frozen=True)
class SelectedVoice:
    """A selected bilingual reference pair with validated candidate metadata."""

    npc: str
    slug: str
    design_id: str
    english_wav: Path
    chinese_wav: Path
    english_index: int
    chinese_index: int
    english_seed: int | None
    chinese_seed: int | None
    english_metadata: dict[str, Any]
    chinese_metadata: dict[str, Any]
    selection_method: str | None
    standalone: bool


def slugify_npc(name: str) -> str:
    """Return the normalized identifier used by the candidate artifacts."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
    return slug


def design_id_for_selection(slug: str) -> str:
    """Map a selected artifact slug to the stable runtime design identifier."""
    normalized = slugify_npc(slug)
    return SPECIAL_DESIGN_IDS.get(normalized, f"npc_{normalized}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def selected_reference_text(candidate_metadata: dict[str, Any]) -> str:
    """Return the exact text spoken by a selected candidate."""
    text = str(candidate_metadata.get("sample_text", "")).strip()
    if not text:
        raise ManifestError("selected candidate has no sample_text")
    return text


def _load_candidate(
    *,
    candidate_root: Path,
    slug: str,
    selection: dict[str, Any],
    language: str,
) -> tuple[Path, int, int | None, dict[str, Any]]:
    language_key = language.lower()
    wav_value = selection.get(f"{language_key}_wav")
    index = selection.get(f"{language_key}_index")
    if not wav_value:
        raise ManifestError(f"{slug}: missing {language} candidate path")
    if not isinstance(index, int):
        raise ManifestError(f"{slug}: missing {language} candidate index")

    wav_path = candidate_root / str(wav_value)
    if not wav_path.is_file():
        raise ManifestError(f"{slug}: missing {language} candidate audio: {wav_path}")
    metadata_path = wav_path.with_suffix(".json")
    if not metadata_path.is_file():
        raise ManifestError(f"{slug}: missing {language} candidate metadata: {metadata_path}")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{slug}: invalid {language} candidate metadata") from exc

    if metadata.get("slug") != slug:
        raise ManifestError(f"{slug}: {language} candidate metadata slug mismatch")
    if metadata.get("language") != language:
        raise ManifestError(f"{slug}: {language} candidate metadata language mismatch")
    if metadata.get("index") != index:
        raise ManifestError(f"{slug}: {language} candidate metadata index mismatch")
    expected_hash = str(metadata.get("sha256", "")).lower()
    if not expected_hash:
        raise ManifestError(f"{slug}: {language} candidate metadata has no sha256")
    if sha256_file(wav_path) != expected_hash:
        raise ManifestError(f"{slug}: {language} candidate sha256 mismatch")
    selected_reference_text(metadata)

    seed = selection.get(f"{language_key}_seed")
    if seed is not None and metadata.get("seed") != seed:
        raise ManifestError(f"{slug}: {language} candidate seed mismatch")
    return wav_path, index, seed, metadata


def load_selection_data(
    data: dict[str, Any], candidate_root: Path, voice_bibles_dir: Path | None = None
) -> dict[str, SelectedVoice]:
    """Validate a decoded selection payload and return records keyed by slug."""
    selected = data.get("selected")
    if not isinstance(selected, dict) or not selected:
        raise ManifestError("selection has no selected records")

    result: dict[str, SelectedVoice] = {}
    seen_npcs: set[str] = set()
    for key, record in sorted(selected.items()):
        if not isinstance(record, dict):
            raise ManifestError(f"{key}: selected record is not an object")
        slug = slugify_npc(record.get("slug", key))
        if not slug:
            raise ManifestError(f"{key}: selected record has no slug")
        if slug in result:
            raise ManifestError(f"{slug}: duplicate selected slug")
        npc = str(record.get("npc", "")).strip()
        if not npc:
            raise ManifestError(f"{slug}: selected record has no NPC")
        if npc in seen_npcs:
            raise ManifestError(f"{slug}: duplicate NPC: {npc}")
        seen_npcs.add(npc)

        if voice_bibles_dir is not None and not (voice_bibles_dir / f"{slug}.json").is_file():
            raise ManifestError(f"{slug}: missing voice bible")
        english_wav, english_index, english_seed, english_metadata = _load_candidate(
            candidate_root=candidate_root, slug=slug, selection=record, language="English"
        )
        chinese_wav, chinese_index, chinese_seed, chinese_metadata = _load_candidate(
            candidate_root=candidate_root, slug=slug, selection=record, language="Chinese"
        )
        result[slug] = SelectedVoice(
            npc=npc,
            slug=slug,
            design_id=design_id_for_selection(slug),
            english_wav=english_wav,
            chinese_wav=chinese_wav,
            english_index=english_index,
            chinese_index=chinese_index,
            english_seed=english_seed,
            chinese_seed=chinese_seed,
            english_metadata=english_metadata,
            chinese_metadata=chinese_metadata,
            selection_method=record.get("selection_method"),
            standalone=bool(record.get("standalone", False)),
        )
    return result


def load_selection(path: Path) -> dict[str, SelectedVoice]:
    """Load a selection file whose candidate paths are rooted at its grandparent."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid selection JSON: {path}") from exc
    return load_selection_data(data, path.parent.parent)


def _load_voice_bible(voice_bibles_dir: Path, slug: str) -> tuple[str, str]:
    path = voice_bibles_dir / f"{slug}.json"
    try:
        bible = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"{slug}: missing voice bible") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{slug}: invalid voice bible") from exc
    english = str(
        bible.get("voice_prompt_enriched", bible.get("voice_description_en", ""))
    ).strip()
    chinese = str(
        bible.get("voice_prompt_enriched_zh", bible.get("voice_description_zh", ""))
    ).strip()
    if not english:
        raise ManifestError(f"{slug}: voice bible has no English prompt")
    if not chinese:
        raise ManifestError(f"{slug}: voice bible has no Chinese prompt")
    return english, chinese


def _existing_designs_by_npc(current: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for design in current.get("designs", {}).values():
        for npc in design.get("npcs", []):
            result[str(npc)] = design
    return result


def _canonical_npc_name(selected: SelectedVoice, current: dict[str, Any]) -> str:
    special_name = SPECIAL_NPC_NAMES.get(selected.slug)
    if special_name:
        return special_name
    return selected.npc


def build_individual_designs(
    current: dict[str, Any],
    selection: dict[str, SelectedVoice],
    voice_bibles_dir: Path,
    candidate_root: Path,
) -> dict[str, Any]:
    """Convert selected references into exactly one design per selected NPC."""
    del candidate_root  # Candidate paths and hashes are validated during selection loading.
    previous_by_npc = _existing_designs_by_npc(current)
    designs: dict[str, dict[str, Any]] = {}

    for slug, selected in sorted(selection.items()):
        design_id = selected.design_id
        if design_id in designs:
            raise ManifestError(f"{slug}: duplicate design ID: {design_id}")
        npc_name = _canonical_npc_name(selected, current)
        previous = current.get("designs", {}).get(design_id) or previous_by_npc.get(npc_name, {})
        voice_desc_en, voice_desc_zh = _load_voice_bible(voice_bibles_dir, slug)
        design = {
            "npc": npc_name,
            "type": "narrator" if design_id in {"npc_narrator_male", "npc_unknown"} else "individual",
            "npcs": [npc_name],
            "voice_desc_en": voice_desc_en,
            "voice_desc_zh": voice_desc_zh,
            "ref_zh_text": selected_reference_text(selected.chinese_metadata),
            "ref_en_text": selected_reference_text(selected.english_metadata),
        }
        if "_portrait_voice_analysis" in previous:
            design["_portrait_voice_analysis"] = previous["_portrait_voice_analysis"]
        designs[design_id] = design

    meta = dict(current.get("_meta", {}))
    meta.update(
        {
            "total_npcs": len(designs),
            "total_designs": len(designs),
            "unique_designs": len(designs),
            "narrator_designs": sum(
                design["type"] == "narrator" for design in designs.values()
            ),
            "group_designs": 0,
            "group_count": 0,
        }
    )
    return {"_meta": meta, "designs": designs}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-designs")
    build.add_argument("--selection", type=Path, required=True)
    build.add_argument("--voice-bibles", type=Path, required=True)
    build.add_argument("--candidate-root", type=Path, required=True)
    build.add_argument("--current-designs", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "build-designs":
        try:
            selection_data = json.loads(args.selection.read_text(encoding="utf-8"))
            current = json.loads(args.current_designs.read_text(encoding="utf-8"))
            selection = load_selection_data(
                selection_data, args.candidate_root, args.voice_bibles
            )
            designs = build_individual_designs(
                current, selection, args.voice_bibles, args.candidate_root
            )
        except (OSError, ManifestError, json.JSONDecodeError) as exc:
            parser.error(str(exc))
        args.output.write_text(
            json.dumps(designs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Wrote {len(designs['designs'])} individual designs to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
