#!/usr/bin/env python3
"""Audit acoustic variation between generated Qwen reference clips.

Run after `generate_qwen3_voice.py --phase refs` and before building clone
prompts. The goal is not speaker verification; it is an early warning that
reference clips in the same language are acoustically too similar.
"""
import argparse
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent.parent
DEFAULT_REFS_DIR = PROJECT_DIR / "voice" / "refs"
DEFAULT_JSON_OUTPUT = SCRIPT_DIR / "reference_tone_variation_report.json"

FEATURE_KEYS = [
    "duration_s",
    "rms",
    "zero_crossing_rate",
    "spectral_centroid_hz",
    "spectral_bandwidth_hz",
    "f0_hz",
    "f0_std_hz",
]


def parse_reference_filename(path):
    """Return (design_id, lang) for `<design_id>_<zh|en>_ref.ogg`."""
    match = re.match(r"(.+)_(zh|en)_ref\.(?:ogg|wav)$", Path(path).name, re.IGNORECASE)
    if not match:
        return None
    return match.group(1), match.group(2).lower()


def to_mono(samples):
    data = np.asarray(samples, dtype=np.float32)
    if data.ndim == 2:
        data = data.mean(axis=1)
    return data


def spectral_features(samples, sample_rate):
    if len(samples) == 0:
        return 0.0, 0.0
    window = np.hanning(len(samples)).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(samples * window))
    freqs = np.fft.rfftfreq(len(samples), 1.0 / sample_rate)
    total = float(np.sum(spectrum))
    if total <= 1e-12:
        return 0.0, 0.0
    centroid = float(np.sum(freqs * spectrum) / total)
    bandwidth = float(np.sqrt(np.sum(((freqs - centroid) ** 2) * spectrum) / total))
    return centroid, bandwidth


def estimate_f0(samples, sample_rate, frame_ms=80, hop_ms=40):
    frame = max(256, int(sample_rate * frame_ms / 1000))
    hop = max(128, int(sample_rate * hop_ms / 1000))
    min_lag = max(1, int(sample_rate / 420.0))
    max_lag = max(min_lag + 1, int(sample_rate / 60.0))
    values = []
    for start in range(0, max(1, len(samples) - frame + 1), hop):
        chunk = samples[start:start + frame]
        if len(chunk) < frame:
            break
        chunk = chunk - float(np.mean(chunk))
        energy = float(np.dot(chunk, chunk))
        if energy <= 1e-8:
            continue
        corr = np.correlate(chunk, chunk, mode="full")[len(chunk) - 1:]
        limit = min(max_lag, len(corr) - 1)
        if limit <= min_lag:
            continue
        lag = int(np.argmax(corr[min_lag:limit + 1]) + min_lag)
        strength = float(corr[lag] / energy)
        if strength >= 0.25:
            values.append(sample_rate / lag)
    if not values:
        return 0.0, 0.0
    return float(np.median(values)), float(np.std(values))


def extract_features(samples, sample_rate):
    """Extract compact tone/prosody features from mono or stereo samples."""
    data = to_mono(samples)
    if len(data) == 0 or sample_rate <= 0:
        return {key: 0.0 for key in FEATURE_KEYS}
    rms = float(np.sqrt(np.mean(data ** 2)))
    zero_crossing_rate = float(np.mean(np.abs(np.diff(np.signbit(data))).astype(np.float32)))
    centroid, bandwidth = spectral_features(data, sample_rate)
    f0_hz, f0_std_hz = estimate_f0(data, sample_rate)
    return {
        "duration_s": float(len(data) / sample_rate),
        "rms": rms,
        "zero_crossing_rate": zero_crossing_rate,
        "spectral_centroid_hz": centroid,
        "spectral_bandwidth_hz": bandwidth,
        "f0_hz": f0_hz,
        "f0_std_hz": f0_std_hz,
    }


def feature_vector(record):
    features = record["features"]
    return np.array([
        float(features.get("rms", 0.0)) / 0.5,
        float(features.get("zero_crossing_rate", 0.0)) / 0.2,
        float(features.get("spectral_centroid_hz", 0.0)) / 5000.0,
        float(features.get("spectral_bandwidth_hz", 0.0)) / 3000.0,
        float(features.get("f0_hz", 0.0)) / 400.0,
        float(features.get("f0_std_hz", 0.0)) / 120.0,
    ], dtype=np.float64)


def tone_distance(left, right):
    return float(np.linalg.norm(left - right))


def summarize_language(records):
    if not records:
        return {
            "count": 0,
            "f0_hz_mean": 0.0,
            "f0_hz_std": 0.0,
            "spectral_centroid_hz_mean": 0.0,
            "spectral_centroid_hz_std": 0.0,
        }
    f0 = np.array([r["features"]["f0_hz"] for r in records], dtype=np.float64)
    centroid = np.array([r["features"]["spectral_centroid_hz"] for r in records], dtype=np.float64)
    return {
        "count": len(records),
        "f0_hz_mean": round(float(f0.mean()), 2),
        "f0_hz_std": round(float(f0.std()), 2),
        "spectral_centroid_hz_mean": round(float(centroid.mean()), 2),
        "spectral_centroid_hz_std": round(float(centroid.std()), 2),
    }


def compact_record(record):
    return {
        "design_id": record["design_id"],
        "npc": record.get("npc", ""),
        "lang": record["lang"],
        "path": str(record["path"]),
        "features": record["features"],
    }


def audit_records(records, similarity_threshold=0.08, max_pairs=50):
    by_lang_records = defaultdict(list)
    for record in records:
        by_lang_records[record["lang"]].append(record)

    similar_pairs = []
    by_lang = {}
    for lang in sorted(by_lang_records):
        lang_records = by_lang_records[lang]
        by_lang[lang] = summarize_language(lang_records)
        if len(lang_records) < 2:
            continue
        vectors = [feature_vector(r) for r in lang_records]
        for i in range(len(lang_records)):
            for j in range(i + 1, len(lang_records)):
                distance = tone_distance(vectors[i], vectors[j])
                if distance <= similarity_threshold:
                    similar_pairs.append({
                        "lang": lang,
                        "distance": round(distance, 4),
                        "left": compact_record(lang_records[i]),
                        "right": compact_record(lang_records[j]),
                    })
    similar_pairs.sort(key=lambda row: row["distance"])
    return {
        "summary": {
            "total_refs": len(records),
            "similarity_threshold": similarity_threshold,
            "similar_pairs": len(similar_pairs),
        },
        "by_lang": by_lang,
        "similar_pairs": similar_pairs[:max_pairs],
    }


def load_design_names(designs_path):
    if not designs_path or not Path(designs_path).exists():
        return {}
    data = json.loads(Path(designs_path).read_text(encoding="utf-8"))
    return {
        did: design.get("npc") or ", ".join(design.get("npcs", [])) or did
        for did, design in data.get("designs", {}).items()
    }


def load_reference_records(refs_dir, designs_path=None):
    try:
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("soundfile is required to read reference clips") from exc

    names = load_design_names(designs_path)
    records = []
    for path in sorted(Path(refs_dir).glob("*_ref.*")):
        parsed = parse_reference_filename(path)
        if not parsed:
            continue
        design_id, lang = parsed
        samples, sample_rate = sf.read(str(path), dtype="float32")
        records.append({
            "design_id": design_id,
            "npc": names.get(design_id, design_id),
            "lang": lang,
            "path": str(path),
            "features": extract_features(samples, int(sample_rate)),
        })
    return records


def write_json_report(result, output_path):
    Path(output_path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def format_summary(result):
    lines = [
        f"reference clips: {result['summary']['total_refs']}",
        f"similarity threshold: {result['summary']['similarity_threshold']}",
        f"similar pairs: {result['summary']['similar_pairs']}",
        "",
    ]
    for lang, stats in sorted(result["by_lang"].items()):
        lines.append(f"[{lang}] count={stats['count']}")
        lines.append(f"  f0 mean/std: {stats['f0_hz_mean']} / {stats['f0_hz_std']} Hz")
        lines.append(
            "  centroid mean/std: "
            f"{stats['spectral_centroid_hz_mean']} / {stats['spectral_centroid_hz_std']} Hz"
        )
    if result["similar_pairs"]:
        lines.extend(["", "closest flagged pairs:"])
        for row in result["similar_pairs"][:20]:
            left = row["left"]
            right = row["right"]
            lines.append(
                f"  {row['lang']} d={row['distance']:.4f} "
                f"{left['design_id']}({left['npc']}) <-> {right['design_id']}({right['npc']})"
            )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Audit acoustic tone variation between generated reference clips."
    )
    parser.add_argument("--refs-dir", default=str(DEFAULT_REFS_DIR))
    parser.add_argument("--designs", default=str(SCRIPT_DIR / "npc_voice_designs.json"))
    parser.add_argument("--json-output", default=str(DEFAULT_JSON_OUTPUT))
    parser.add_argument("--threshold", type=float, default=0.08)
    parser.add_argument("--max-pairs", type=int, default=50)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when similar pairs are found.",
    )
    args = parser.parse_args(argv)

    records = load_reference_records(args.refs_dir, args.designs)
    result = audit_records(records, args.threshold, args.max_pairs)
    write_json_report(result, args.json_output)
    print(format_summary(result))
    print(f"\nJSON: {args.json_output}")
    if args.strict and result["summary"]["similar_pairs"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
