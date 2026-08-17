#!/usr/bin/env python3
"""Audit whether generated voice audio matches its input text.

The script transcribes generated clips with a local ASR backend and compares the
transcript to the manifest text. It is intentionally backend-optional at import
time so unit tests can run without Whisper installed.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_REVIEW_DATA = PROJECT_DIR / "voice" / "review_samples" / "full_generated_review" / "voice_review_data.json"


def normalize_text(text):
    text = (text or "").lower()
    kept = []
    last_space = False
    for ch in text:
        is_cjk = "\u3400" <= ch <= "\u9fff"
        if ch.isalnum() or is_cjk:
            kept.append(ch)
            last_space = False
        elif ch.isspace() and not last_space:
            kept.append(" ")
            last_space = True
    return "".join(kept).strip()


def _compact_for_cer(text):
    return normalize_text(text).replace(" ", "")


def levenshtein(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                prev[j] + 1,
                cur[j - 1] + 1,
                prev[j - 1] + (ca != cb),
            ))
        prev = cur
    return prev[-1]


def character_error_rate(expected, transcript):
    expected_norm = _compact_for_cer(expected)
    transcript_norm = _compact_for_cer(transcript)
    if not expected_norm:
        return 0.0 if not transcript_norm else 1.0
    return levenshtein(expected_norm, transcript_norm) / len(expected_norm)


def word_error_rate(expected, transcript):
    expected_words = normalize_text(expected).split()
    transcript_words = normalize_text(transcript).split()
    if not expected_words:
        return 0.0 if not transcript_words else 1.0
    return levenshtein(expected_words, transcript_words) / len(expected_words)


def evaluate_transcript(expected, transcript, lang, pass_threshold=0.25):
    cer = character_error_rate(expected, transcript)
    wer = word_error_rate(expected, transcript) if lang == "en" else None
    return {
        "expected_norm": normalize_text(expected),
        "transcript_norm": normalize_text(transcript),
        "cer": cer,
        "wer": wer,
        "audit_status": "pass" if cer <= pass_threshold else "failed",
    }


class FasterWhisperTranscriber:
    def __init__(self, model_size, device, compute_type):
        from faster_whisper import WhisperModel

        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio_path, lang):
        segments, _ = self.model.transcribe(str(audio_path), language=lang if lang in ("en", "zh") else None)
        return "".join(segment.text for segment in segments).strip()


class OpenAIWhisperTranscriber:
    def __init__(self, model_size, device):
        import whisper

        self.whisper = whisper
        self.model = whisper.load_model(model_size, device=device)

    def transcribe(self, audio_path, lang):
        result = self.model.transcribe(str(audio_path), language=lang if lang in ("en", "zh") else None)
        return (result.get("text") or "").strip()


def build_transcriber(backend, model_size, device, compute_type):
    errors = []
    if backend in ("auto", "faster-whisper"):
        try:
            return FasterWhisperTranscriber(model_size, device, compute_type)
        except Exception as exc:
            errors.append(f"faster-whisper: {exc}")
            if backend == "faster-whisper":
                raise
    if backend in ("auto", "whisper"):
        try:
            return OpenAIWhisperTranscriber(model_size, device)
        except Exception as exc:
            errors.append(f"whisper: {exc}")
            if backend == "whisper":
                raise
    raise RuntimeError("No ASR backend available. Tried " + "; ".join(errors))


def load_review_rows(path):
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    rows = payload.get("rows", payload if isinstance(payload, list) else [])
    base_dir = path.parent
    loaded = []
    for row in rows:
        row = dict(row)
        audio = row.get("audio") or ""
        if audio:
            audio_path = Path(audio)
            if not audio_path.is_absolute():
                audio_path = (base_dir / audio_path).resolve()
            row["_audio_path"] = str(audio_path)
        loaded.append(row)
    return loaded


def filter_rows(rows, lang="", status="", limit=0):
    selected = []
    for row in rows:
        if lang and row.get("lang") != lang:
            continue
        if status and row.get("status") != status:
            continue
        if not row.get("text") or not row.get("_audio_path"):
            continue
        if not Path(row["_audio_path"]).exists():
            continue
        selected.append(row)
        if limit and len(selected) >= limit:
            break
    return selected


def audit_rows(rows, transcriber, pass_threshold):
    results = []
    for index, row in enumerate(rows, 1):
        audio_path = Path(row["_audio_path"])
        transcript = transcriber.transcribe(audio_path, row.get("lang", ""))
        metrics = evaluate_transcript(row.get("text", ""), transcript, row.get("lang", ""), pass_threshold)
        results.append({
            "index": index,
            "filename": row.get("filename", audio_path.name),
            "lang": row.get("lang", ""),
            "character": row.get("character", "") or row.get("npc", ""),
            "status": row.get("status", ""),
            "audio": str(audio_path),
            "expected": row.get("text", ""),
            "transcript": transcript,
            **metrics,
        })
        print(
            f"[{index}/{len(rows)}] {results[-1]['audit_status']} "
            f"{results[-1]['lang']} {results[-1]['filename']} CER={results[-1]['cer']:.3f}",
            flush=True,
        )
    return results


def write_outputs(results, output_json, output_csv):
    output_json.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "total": len(results),
        "pass": sum(1 for r in results if r["audit_status"] == "pass"),
        "failed": sum(1 for r in results if r["audit_status"] == "failed"),
    }
    output_json.write_text(
        json.dumps({"summary": summary, "rows": results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if output_csv:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        with open(output_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "audit_status", "cer", "wer", "lang", "character", "filename",
                    "expected", "transcript", "audio",
                ],
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(results)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Transcribe generated voice clips and compare them with manifest text.")
    parser.add_argument("--review-data", default=str(DEFAULT_REVIEW_DATA), help="voice_review_data.json generated by generate_voice_review_html.py")
    parser.add_argument("--output-json", default=str(PROJECT_DIR / "voice" / "review_samples" / "full_generated_review" / "voice_text_audit.json"))
    parser.add_argument("--output-csv", default=str(PROJECT_DIR / "voice" / "review_samples" / "full_generated_review" / "voice_text_audit.csv"))
    parser.add_argument("--backend", choices=["auto", "faster-whisper", "whisper"], default="auto")
    parser.add_argument("--model", default="small", help="Whisper/faster-whisper model size or path")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--compute-type", default="float16")
    parser.add_argument("--lang", choices=["", "en", "zh"], default="")
    parser.add_argument("--status", default="", help="Optional review row generation status filter, e.g. new")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--pass-threshold", type=float, default=0.25)
    args = parser.parse_args()

    review_data = Path(args.review_data)
    rows = filter_rows(load_review_rows(review_data), lang=args.lang, status=args.status, limit=args.limit)
    if not rows:
        print("No rows to audit.", file=sys.stderr)
        return 1
    transcriber = build_transcriber(args.backend, args.model, args.device, args.compute_type)
    results = audit_rows(rows, transcriber, args.pass_threshold)
    summary = write_outputs(results, Path(args.output_json), Path(args.output_csv) if args.output_csv else None)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
