#!/usr/bin/env python3
"""Select diverse reference candidates and replace clips that fail audio audit."""
from __future__ import annotations

import argparse
import copy
import json
import math
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


CANONICAL_FEMALE_NARRATOR_SLUG = "narrator_female"
FEMALE_NARRATOR_SLUG_ALIASES = {"unknown", "npc_unknown", CANONICAL_FEMALE_NARRATOR_SLUG}
ECAPA_SAMPLE_RATE = 16000


@dataclass(frozen=True)
class AudioAudit:
    path: Path
    valid: bool
    reason: str | None
    duration_seconds: float
    clipping_ratio: float
    silence_ratio: float


def cosine_distance(left, right) -> float:
    left = np.asarray(left, dtype=np.float64)
    right = np.asarray(right, dtype=np.float64)
    return float(1.0 - np.dot(left, right) / ((np.linalg.norm(left) * np.linalg.norm(right)) + 1e-12))


def _candidate_vectors(embeddings: dict, candidates: int) -> tuple[list[str], list[list[np.ndarray]]]:
    slugs = sorted(embeddings)
    vectors = [[np.asarray(vector, dtype=np.float64) for vector in embeddings[slug][:candidates]] for slug in slugs]
    if any(not vector_set for vector_set in vectors):
        raise ValueError("every character needs at least one candidate embedding")
    return slugs, vectors


def _score(indices: list[int], vectors: list[list[np.ndarray]]) -> tuple[float, float]:
    total = 0.0
    floor = math.inf
    for left in range(len(indices)):
        for right in range(left + 1, len(indices)):
            distance = cosine_distance(vectors[left][indices[left]], vectors[right][indices[right]])
            total += distance
            floor = min(floor, distance)
    return total, floor if floor != math.inf else 0.0


def select_maximin(embeddings: dict, candidates: int, restarts: int) -> dict[str, int]:
    """Maximize minimum cast distance, then total distance, deterministically."""
    slugs, vectors = _candidate_vectors(embeddings, candidates)
    counts = [len(vector_set) for vector_set in vectors]
    if len(slugs) == 1:
        return {slugs[0]: select_medoid(vectors[0])}

    def improve(indices: list[int]) -> list[int]:
        indices = list(indices)
        changed = True
        while changed:
            changed = False
            for position, count in enumerate(counts):
                _, current_floor = _score(indices, vectors)
                best_index = indices[position]
                best_floor = current_floor
                for candidate in range(count):
                    trial = list(indices)
                    trial[position] = candidate
                    _, trial_floor = _score(trial, vectors)
                    if trial_floor > best_floor + 1e-12:
                        best_index, best_floor = candidate, trial_floor
                if best_index != indices[position]:
                    indices[position] = best_index
                    changed = True
        return indices

    starts = [[0] * len(slugs)]
    rng = np.random.default_rng(0)
    for _ in range(max(0, restarts)):
        starts.append([int(rng.integers(0, count)) for count in counts])

    best = improve(starts[0])
    best_total, best_floor = _score(best, vectors)
    for start in starts[1:]:
        chosen = improve(start)
        total, floor = _score(chosen, vectors)
        if (
            floor > best_floor + 1e-12
            or (
                abs(floor - best_floor) <= 1e-12
                and (
                    total > best_total + 1e-12
                    or (abs(total - best_total) <= 1e-12 and tuple(chosen) < tuple(best))
                )
            )
        ):
            best, best_total, best_floor = chosen, total, floor

    changed = True
    while changed:
        changed = False
        for position, count in enumerate(counts):
            best_index = best[position]
            for candidate in range(count):
                trial = list(best)
                trial[position] = candidate
                total, floor = _score(trial, vectors)
                if floor >= best_floor - 1e-12 and total > best_total + 1e-12:
                    best_index, best_total = candidate, total
            if best_index != best[position]:
                best[position] = best_index
                changed = True
    return dict(zip(slugs, best))


def select_medoid(vectors) -> int:
    return min(
        range(len(vectors)),
        key=lambda index: sum(cosine_distance(vectors[index], other) for other in vectors),
    )


def select_medoids(embeddings: dict) -> dict[str, int]:
    """Pick the representative candidate for each Avatar/Narrator voice."""
    return {
        slug: select_medoid([np.asarray(vector, dtype=np.float64) for vector in vectors])
        for slug, vectors in sorted(embeddings.items())
    }


def _is_special_slug(slug: str, special_npcs: set[str]) -> bool:
    normalized = slug.lower()
    return (
        slug in special_npcs
        or normalized in FEMALE_NARRATOR_SLUG_ALIASES
        or "avatar" in normalized
        or "narrator" in normalized
    )


def select_language_candidates(
    embeddings: dict, candidates: int, restarts: int, special_npcs: set[str] | None = None
) -> dict[str, int]:
    """Select a language's cast while keeping special narrators out of maximin."""
    special_npcs = special_npcs or set()
    special_slugs = {slug for slug in embeddings if _is_special_slug(slug, special_npcs)}
    cast_embeddings = {slug: vectors for slug, vectors in embeddings.items() if slug not in special_slugs}
    selected = select_maximin(cast_embeddings, candidates, restarts) if cast_embeddings else {}
    selected.update(select_medoids({slug: embeddings[slug] for slug in special_slugs}))
    return selected


def load_audio(path: Path) -> tuple[np.ndarray, int]:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    sample_rate = int(probe.stdout.strip())
    decoded = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "pipe:1"],
        check=True, capture_output=True,
    )
    return np.frombuffer(decoded.stdout, dtype=np.float32), sample_rate


def audit_candidate(path: Path) -> AudioAudit:
    try:
        wav, sample_rate = load_audio(path)
        if sample_rate <= 0 or wav.size == 0:
            raise ValueError("empty audio")
    except Exception:
        return AudioAudit(path, False, "unreadable", 0.0, 0.0, 1.0)
    duration = float(wav.size) / float(sample_rate)
    clipping = float(np.mean(np.abs(wav) >= 0.999))
    silence = float(np.mean(np.abs(wav) <= 0.001))
    if not 2.0 <= duration <= 20.0:
        return AudioAudit(path, False, "duration_seconds", duration, clipping, silence)
    if clipping > 0.01:
        return AudioAudit(path, False, "clipping_ratio", duration, clipping, silence)
    if silence > 0.80:
        return AudioAudit(path, False, "silence_ratio", duration, clipping, silence)
    return AudioAudit(path, True, None, duration, clipping, silence)


def _audit_for(audits: dict, slug: str, index: int) -> AudioAudit:
    source = audits[slug]
    return source[index] if isinstance(source, list) else source[index]


def _selection_index(value) -> int:
    if isinstance(value, dict):
        return int(value.get("index", value.get("candidate_index")))
    return int(value)


def replace_invalid_selections(selection: dict, audits: dict, embeddings: dict) -> dict:
    """Replace invalid picks with the valid candidate farthest from selected peers."""
    records = any(isinstance(value, dict) for value in selection.values())
    result = copy.deepcopy(selection)
    for slug in sorted(selection):
        chosen = _selection_index(result[slug])
        audit = _audit_for(audits, slug, chosen)
        if audit.valid:
            continue
        alternatives = [
            index for index in range(len(embeddings[slug]))
            if _audit_for(audits, slug, index).valid
        ]
        if not alternatives:
            raise ValueError(f"{slug} has no valid candidate to replace index {chosen}")
        peers = [
            (peer, _selection_index(result[peer])) for peer in result
            if peer != slug and _audit_for(audits, peer, _selection_index(result[peer])).valid
        ]
        replacement = max(
            alternatives,
            key=lambda index: min(
                (cosine_distance(embeddings[slug][index], embeddings[peer][peer_index]) for peer, peer_index in peers),
                default=math.inf,
            ),
        )
        if records:
            result[slug]["index"] = replacement
            result[slug]["replaced_index"] = chosen
            result[slug]["replacement_reason"] = audit.reason
            result[slug]["audit_metrics"] = asdict(_audit_for(audits, slug, replacement))
            result[slug]["audit_metrics"]["path"] = str(result[slug]["audit_metrics"]["path"])
        else:
            result[slug] = replacement
    return result


def load_encoder(device: str):
    from speechbrain.inference import SpeakerRecognition
    return SpeakerRecognition.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb", run_opts={"device": device})


def resample_for_ecapa(wav: np.ndarray, sample_rate: int) -> np.ndarray:
    if sample_rate == ECAPA_SAMPLE_RATE:
        return wav
    import torch
    import torchaudio.functional as torchaudio_functional

    return torchaudio_functional.resample(
        torch.tensor(wav), sample_rate, ECAPA_SAMPLE_RATE
    ).cpu().numpy()


def embed_candidates(encoder, paths: list[Path], device: str) -> list[np.ndarray]:
    import torch
    vectors = []
    for path in paths:
        wav, sample_rate = load_audio(path)
        wav = resample_for_ecapa(wav, sample_rate)
        with torch.no_grad():
            vector = encoder.encode_batch(torch.tensor(wav).unsqueeze(0).to(device)).squeeze().cpu().numpy()
        vectors.append(vector / (np.linalg.norm(vector) + 1e-12))
    return vectors


def embed_valid_candidates(
    encoder, paths: list[Path], audits: list[AudioAudit], device: str
) -> dict[int, np.ndarray]:
    """Embed only clips accepted by the audit and retain their original indices."""
    valid_indices = [index for index, audit in enumerate(audits) if audit.valid]
    valid_paths = [paths[index] for index in valid_indices]
    vectors = embed_candidates(encoder, valid_paths, device) if valid_paths else []
    return dict(zip(valid_indices, vectors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidates", type=int, default=10)
    parser.add_argument("--restarts", type=int, default=12)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--special-npcs", nargs="*", default=None,
                        help="Slugs selected by within-character medoid instead of cast diversity")
    args = parser.parse_args()
    result = {"languages": {}}
    special = set(args.special_npcs or [])
    for language in ("English", "Chinese"):
        paths_by_slug = {
            path.name: [path / f"candidate_{language}_{index}.ogg" for index in range(args.candidates)]
            for path in sorted(args.candidate_dir.iterdir()) if path.is_dir()
        }
        audits = {slug: [audit_candidate(path) for path in paths] for slug, paths in paths_by_slug.items()}
        no_valid = [slug for slug, slug_audits in audits.items() if not any(audit.valid for audit in slug_audits)]
        if no_valid:
            raise ValueError(f"{language} has no valid candidate for: {', '.join(sorted(no_valid))}")
        encoder = load_encoder(args.device)
        indexed_embeddings = {
            slug: embed_valid_candidates(encoder, paths, audits[slug], args.device)
            for slug, paths in paths_by_slug.items()
        }
        valid_indices = {slug: list(vectors) for slug, vectors in indexed_embeddings.items()}
        embeddings = {slug: list(vectors.values()) for slug, vectors in indexed_embeddings.items()}
        selected_indices = select_language_candidates(embeddings, args.candidates, args.restarts, special)
        selected = {
            slug: {"index": valid_indices[slug][index]}
            for slug, index in selected_indices.items()
        }
        all_embeddings = {
            slug: [indexed_embeddings[slug].get(index) for index in range(len(paths))]
            for slug, paths in paths_by_slug.items()
        }
        result["languages"][language] = replace_invalid_selections(selected, audits, all_embeddings)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
