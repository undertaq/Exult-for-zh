#!/usr/bin/env python3
"""Generate resumable Qwen3 VoiceDesign reference candidates outside voice/refs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
PROJECT_DIR = Path(__file__).resolve().parents[2]
CANONICAL_FEMALE_NARRATOR_SLUG = "narrator_female"
SAMPLE_TEXT = {
    "English": "Greetings, traveler. What brings you to these lands this day?",
    "Chinese": "旅人，你好。今天過得如何？",
}
LANGUAGE_SPECS = (
    ("Chinese", "voice_desc_zh", "voice_prompt_enriched_zh", "用標準的普通話朗讀"),
    ("English", "voice_desc_en", "voice_prompt_enriched", "Neutral clear speaking voice, natural and pleasant"),
)


@dataclass(frozen=True)
class CandidateJob:
    npc: str
    slug: str
    index: int
    language: str
    text: str
    instruct: str
    output: Path


def slugify(name: str) -> str:
    ascii_name = name.lower().encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_name).strip("_") or "npc"
    if slug in {"unknown", "npc_unknown"}:
        return CANONICAL_FEMALE_NARRATOR_SLUG
    return slug


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_voice_bibles(voice_bibles: Path) -> dict[str, Any]:
    """Adapt per-NPC bible JSON into the normalized design shape used by jobs."""
    normalized: dict[str, Any] = {"designs": {}}
    for path in sorted(voice_bibles.glob("*.json")):
        bible = json.loads(path.read_text(encoding="utf-8"))
        npc = str(bible.get("npc") or path.stem)
        slug = str(bible.get("slug") or slugify(npc))
        en = bible.get("voice_prompt_enriched") or bible.get("voice_prompt_original")
        zh = bible.get("voice_prompt_enriched_zh") or en
        if not en and not zh:
            continue
        normalized["designs"][f"npc_{slug}"] = {
            "npc": npc,
            "npcs": [npc],
            "voice_desc_en": en or "",
            "voice_desc_zh": zh or "",
        }
    return normalized


def load_designs_or_voice_bibles(designs_path: Path | None, voice_bibles: Path | None) -> dict[str, Any]:
    """Load normalized designs, optionally overlaying direct per-NPC voice bibles."""
    designs: dict[str, Any] = {"designs": {}}
    if designs_path is not None:
        designs = json.loads(designs_path.read_text(encoding="utf-8"))
        designs.setdefault("designs", {})
    if voice_bibles is not None:
        bible_designs = normalize_voice_bibles(voice_bibles)["designs"]
        overridden_npcs = {
            str(design["npc"])
            for design in bible_designs.values()
        }
        for design_id, design in list(designs["designs"].items()):
            members = [str(npc) for npc in (design.get("npcs") or [design.get("npc") or design_id])]
            retained_members = [npc for npc in members if npc not in overridden_npcs]
            if len(retained_members) == len(members):
                continue
            if retained_members:
                designs["designs"][design_id] = {**design, "npcs": retained_members}
            else:
                del designs["designs"][design_id]
        designs["designs"].update(bible_designs)
    if not designs["designs"]:
        raise ValueError("provide --designs and/or --voice-bibles with at least one usable voice design")
    return designs


def build_candidate_jobs(designs: dict, output_dir: Path, candidates: int) -> list[CandidateJob]:
    if candidates < 1:
        raise ValueError("candidates must be at least 1")
    _validate_candidate_output_dir(output_dir)
    jobs: list[CandidateJob] = []
    for design_id, design in sorted(designs.get("designs", {}).items()):
        npcs = design.get("npcs") or [design.get("npc") or design_id]
        for npc_name in npcs:
            npc = str(npc_name)
            slug = slugify(npc)
            for language, design_field, bible_field, default_instruct in LANGUAGE_SPECS:
                instruct = str(design.get(design_field) or design.get(bible_field) or default_instruct).strip()
                if not instruct:
                    continue
                for index in range(candidates):
                    jobs.append(CandidateJob(
                        npc=npc,
                        slug=slug,
                        index=index,
                        language=language,
                        text=SAMPLE_TEXT[language],
                        instruct=instruct,
                        output=output_dir / slug / f"candidate_{language}_{index}.ogg",
                    ))
    return jobs


def _validate_candidate_output_dir(output_dir: Path) -> None:
    """Reject the approved-reference tree even when the path is symlinked."""
    refs_dir = (PROJECT_DIR / "voice" / "refs").resolve(strict=False)
    candidates = [output_dir.expanduser().resolve(strict=False)]
    if not output_dir.is_absolute():
        candidates.append((PROJECT_DIR / output_dir).resolve(strict=False))
    if any(path == refs_dir or refs_dir in path.parents for path in candidates):
        raise ValueError("candidate output directory must not be voice/refs or a descendant")


def _set_seed(seed: int) -> None:
    try:
        import torch
        torch.manual_seed(seed)
    except ImportError:
        pass


def _is_oom(error: Exception) -> bool:
    return "out of memory" in str(error).lower()


def _generate_batch(model, jobs: list[CandidateJob], seed: int):
    _set_seed(seed)
    try:
        wavs, sample_rate = model.generate_voice_design(
            text=[job.text for job in jobs],
            instruct=[job.instruct for job in jobs],
            language=[job.language for job in jobs],
            do_sample=True,
            max_new_tokens=800,
        )
        return [
            (job, wav, seed, batch_position)
            for batch_position, (job, wav) in enumerate(zip(jobs, wavs))
        ], int(sample_rate)
    except Exception as error:
        if not _is_oom(error) or len(jobs) == 1:
            raise
        try:
            import torch
            torch.cuda.empty_cache()
        except ImportError:
            pass
        midpoint = len(jobs) // 2
        first, sample_rate = _generate_batch(model, jobs[:midpoint], seed)
        second, sample_rate = _generate_batch(model, jobs[midpoint:], seed + midpoint)
        return first + second, sample_rate


def write_candidate(
    job: CandidateJob,
    wav,
    sample_rate: int,
    batch_seed: int,
    batch_position: int,
    batch_size: int,
    effective_seed: int,
) -> Path:
    """Write OGG then its metadata sidecar using replace-based atomic publishes."""
    job.output.parent.mkdir(parents=True, exist_ok=True)
    wav = np.asarray(wav, dtype=np.float32)
    with tempfile.NamedTemporaryFile(
        prefix=f".{job.output.stem}.", suffix=".ogg", dir=job.output.parent, delete=False
    ) as handle:
        audio_tmp = Path(handle.name)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "f32le", "-ar", str(sample_rate), "-ac", "1", "-i", "pipe:0",
                "-c:a", "libvorbis", "-q:a", "2", str(audio_tmp),
            ],
            input=wav.tobytes(), check=True, capture_output=True,
        )
        os.replace(audio_tmp, job.output)
    finally:
        audio_tmp.unlink(missing_ok=True)

    metadata = {
        "npc": job.npc,
        "slug": job.slug,
        "index": job.index,
        "language": job.language,
        "sample_text": job.text,
        "instruct": job.instruct,
        "seed": effective_seed,
        "batch_seed": batch_seed,
        "batch_position": batch_position,
        "batch_size": batch_size,
        "model_revision": MODEL_ID,
        "sha256": sha256_file(job.output),
        "sample_rate": sample_rate,
        "duration_seconds": round(len(wav) / sample_rate, 3),
    }
    sidecar = job.output.with_suffix(".json")
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix=f".{sidecar.stem}.", suffix=".json",
        dir=sidecar.parent, delete=False,
    ) as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        metadata_tmp = Path(handle.name)
    os.replace(metadata_tmp, sidecar)
    return job.output


def candidate_pair_is_complete(
    job: CandidateJob,
    batch_seed: int | None = None,
    batch_position: int | None = None,
    batch_size: int | None = None,
) -> bool:
    """Return true only when an existing audio file matches its published sidecar."""
    sidecar = job.output.with_suffix(".json")
    if not job.output.is_file() or not sidecar.is_file():
        return False
    try:
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        stored_seed = metadata.get("seed")
        stored_batch_seed = metadata.get("batch_seed")
        stored_batch_position = metadata.get("batch_position")
        stored_batch_size = metadata.get("batch_size")
        sample_rate = metadata.get("sample_rate")
        duration_seconds = metadata.get("duration_seconds")
        return (
            metadata.get("npc") == job.npc
            and metadata.get("slug") == job.slug
            and metadata.get("index") == job.index
            and metadata.get("language") == job.language
            and metadata.get("sample_text") == job.text
            and metadata.get("instruct") == job.instruct
            and metadata.get("model_revision") == MODEL_ID
            and isinstance(stored_seed, int)
            and not isinstance(stored_seed, bool)
            and isinstance(stored_batch_seed, int)
            and not isinstance(stored_batch_seed, bool)
            and isinstance(stored_batch_position, int)
            and not isinstance(stored_batch_position, bool)
            and isinstance(stored_batch_size, int)
            and not isinstance(stored_batch_size, bool)
            and stored_batch_size > 0
            and 0 <= stored_batch_position < stored_batch_size
            and isinstance(sample_rate, (int, float))
            and not isinstance(sample_rate, bool)
            and sample_rate > 0
            and isinstance(duration_seconds, (int, float))
            and not isinstance(duration_seconds, bool)
            and duration_seconds > 0
            and (batch_seed is None or stored_batch_seed == batch_seed)
            and (batch_position is None or stored_batch_position == batch_position)
            and (batch_size is None or stored_batch_size == batch_size)
            and metadata.get("sha256") == sha256_file(job.output)
        )
    except (OSError, json.JSONDecodeError):
        return False


def _scheduled_batches(jobs: list[CandidateJob], seed_base: int, batch_size: int):
    batch_size = max(1, batch_size)
    for start in range(0, len(jobs), batch_size):
        yield seed_base + start, jobs[start:start + batch_size]


def _scheduled_batch_is_complete(scheduled_batch: list[CandidateJob], batch_seed: int) -> bool:
    batch_size = len(scheduled_batch)
    return all(
        candidate_pair_is_complete(
            job,
            batch_seed=batch_seed,
            batch_position=batch_position,
            batch_size=batch_size,
        )
        for batch_position, job in enumerate(scheduled_batch)
    )


def generate_jobs(
    model,
    jobs: list[CandidateJob],
    seed_base: int,
    batch_size: int,
    skip_existing: bool,
) -> list[Path]:
    """Generate jobs in resumable batches, splitting a batch on OOM."""
    generated: list[Path] = []
    for batch_seed, scheduled_batch in _scheduled_batches(jobs, seed_base, batch_size):
        scheduled_batch_size = len(scheduled_batch)
        if skip_existing and _scheduled_batch_is_complete(scheduled_batch, batch_seed):
            continue
        results, sample_rate = _generate_batch(model, scheduled_batch, batch_seed)
        for batch_position, (job, wav, effective_seed, _) in enumerate(results):
            generated.append(
                write_candidate(
                    job,
                    wav,
                    sample_rate,
                    batch_seed,
                    batch_position,
                    scheduled_batch_size,
                    effective_seed,
                )
            )
    return generated


def load_model(device: str):
    import torch
    from qwen_tts import Qwen3TTSModel
    return Qwen3TTSModel.from_pretrained(
        MODEL_ID, device_map=device, dtype=torch.bfloat16, attn_implementation="sdpa"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--designs", type=Path, default=Path(__file__).with_name("npc_voice_designs.json"))
    parser.add_argument("--voice-bibles", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).with_name("reference_candidates"))
    parser.add_argument("--npcs", nargs="*", default=None)
    parser.add_argument("--candidates", type=int, default=10)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--seed-base", type=int, default=1000)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def run(args) -> tuple[int, int]:
    designs = load_designs_or_voice_bibles(args.designs, args.voice_bibles)
    if args.npcs:
        wanted = set(args.npcs)
        filtered_designs = {}
        for design_id, design in designs["designs"].items():
            members = [str(npc) for npc in (design.get("npcs") or [design.get("npc") or design_id])]
            retained_members = [npc for npc in members if npc in wanted]
            if retained_members:
                filtered_designs[design_id] = {**design, "npcs": retained_members}
        designs = {"designs": filtered_designs}
    designs = {
        "designs": {
            did: design
            for did, design in designs["designs"].items()
            if (design.get("voice_generation") or "") != "skip"
        }
    }
    jobs = build_candidate_jobs(designs, args.output_dir, args.candidates)
    skipped = 0
    if args.skip_existing and not args.overwrite:
        for batch_seed, scheduled_batch in _scheduled_batches(jobs, args.seed_base, args.batch_size):
            if _scheduled_batch_is_complete(scheduled_batch, batch_seed):
                skipped += len(scheduled_batch)
    if args.dry_run:
        for job in jobs:
            print(f"would generate {job.output}")
        return 0, skipped
    model = load_model(args.device)
    generated = generate_jobs(
        model, jobs, args.seed_base, args.batch_size, args.skip_existing and not args.overwrite
    )
    return len(generated), skipped


def main() -> int:
    generated, skipped = run(build_parser().parse_args())
    print(f"Candidate generation complete. Generated: {generated}, Skipped: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
