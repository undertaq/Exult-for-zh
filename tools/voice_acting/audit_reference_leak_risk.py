#!/usr/bin/env python3
"""Audit voice reference texts that are likely to leak into cloned output."""

import argparse
import csv
import json
import re
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DESIGNS = PROJECT_DIR / "tools" / "voice_acting" / "npc_voice_designs.json"
DEFAULT_MAPPING = PROJECT_DIR / "tools" / "voice_acting" / "bilingual_mapping_review.json"
DEFAULT_OUTPUT_JSON = PROJECT_DIR / "voice" / "review_samples" / "full_generated_review" / "reference_leak_risk.json"
DEFAULT_OUTPUT_CSV = PROJECT_DIR / "voice" / "review_samples" / "full_generated_review" / "reference_leak_risk.csv"


SPECIFIC_NAME_RE = re.compile(
    r"\b(Avatar|Britannia|Fellowship|Lord British|Adjhar|Bollux|Iolo|Joe|"
    r"Shrine|Astelleron|Castambre|New Magincia|Trinsic|Moonglow)\b",
    re.IGNORECASE,
)
NARRATION_RE = re.compile(
    r"^(你看見|你看到|你告訴|他|她|這位|這名|當|The |He |She |You |This |That )"
)


def normalize_text(text):
    return re.sub(r"\s+", " ", (text or "").strip())


def has_cjk(text):
    return any("\u3400" <= ch <= "\u9fff" for ch in text or "")


def risk_terms(text):
    terms = []
    if SPECIFIC_NAME_RE.search(text or ""):
        terms.append("specific_names")
    if NARRATION_RE.search(text or ""):
        terms.append("narration_or_third_person")
    if "……" in (text or "") or "..." in (text or ""):
        terms.append("ellipsis_style")
    if len(text or "") > (90 if has_cjk(text) else 180):
        terms.append("long")
    return terms


def score_reference(text, exact_match_count, short_target_count):
    terms = risk_terms(text)
    score = 0
    score += 3 if "long" in terms else 0
    score += 2 if "specific_names" in terms else 0
    score += 2 if "narration_or_third_person" in terms else 0
    score += 1 if "ellipsis_style" in terms else 0
    score += 2 if exact_match_count else 0
    score += 1 if short_target_count >= 5 else 0
    return score, terms


def load_designs(path):
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    return payload.get("designs", payload)


def load_mapping(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_mapping_indexes(rows):
    texts_by_lang = {"zh": {}, "en": {}}
    rows_by_npc = {}
    for row in rows:
        npc = row.get("npc", "")
        rows_by_npc.setdefault(npc, []).append(row)
        for lang in ("zh", "en"):
            text = normalize_text(row.get(f"{lang}_text", ""))
            if text:
                texts_by_lang[lang].setdefault(text, []).append(row)
    return texts_by_lang, rows_by_npc


def audit_reference_leak_risk(designs, mapping_rows, min_score=5):
    texts_by_lang, rows_by_npc = build_mapping_indexes(mapping_rows)
    findings = []
    for design_id, design in designs.items():
        npc_names = design.get("npcs", []) or [design.get("npc", design_id)]
        npc = design.get("npc", design_id)
        for lang, text_key in (("zh", "ref_zh_text"), ("en", "ref_en_text")):
            text = normalize_text(design.get(text_key, ""))
            if not text:
                continue
            exact_rows = texts_by_lang[lang].get(text, [])
            same_npc_exact = sum(1 for row in exact_rows if row.get("npc") in npc_names)
            short_targets = 0
            total_targets = 0
            for npc_name in npc_names:
                for row in rows_by_npc.get(npc_name, []):
                    target = normalize_text(row.get(f"{lang}_text", ""))
                    if not target:
                        continue
                    total_targets += 1
                    if len(target) < len(text) * 0.45:
                        short_targets += 1
            score, terms = score_reference(text, len(exact_rows), short_targets)
            if score >= min_score:
                findings.append({
                    "score": score,
                    "design_id": design_id,
                    "npc": npc,
                    "lang": lang,
                    "length": len(text),
                    "risk_terms": terms,
                    "exact_match_rows": len(exact_rows),
                    "same_npc_exact_match_rows": same_npc_exact,
                    "short_targets": short_targets,
                    "total_targets": total_targets,
                    "ref_text": text,
                })
    findings.sort(key=lambda item: (-item["score"], -item["length"], item["design_id"], item["lang"]))
    return findings


def write_outputs(findings, output_json, output_csv):
    output_json.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "total_findings": len(findings),
        "critical_score_9_plus": sum(1 for item in findings if item["score"] >= 9),
        "high_score_7_plus": sum(1 for item in findings if item["score"] >= 7),
    }
    output_json.write_text(
        json.dumps({"summary": summary, "findings": findings}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if output_csv:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        with open(output_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "score", "design_id", "npc", "lang", "length", "risk_terms",
                    "exact_match_rows", "same_npc_exact_match_rows",
                    "short_targets", "total_targets", "ref_text",
                ],
            )
            writer.writeheader()
            for item in findings:
                row = dict(item)
                row["risk_terms"] = "|".join(row["risk_terms"])
                writer.writerow(row)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Audit reference texts likely to leak into cloned voice output.")
    parser.add_argument("--designs", default=str(DEFAULT_DESIGNS))
    parser.add_argument("--mapping", default=str(DEFAULT_MAPPING))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV))
    parser.add_argument("--min-score", type=int, default=5)
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    findings = audit_reference_leak_risk(
        load_designs(Path(args.designs)),
        load_mapping(Path(args.mapping)),
        min_score=args.min_score,
    )
    summary = write_outputs(findings, Path(args.output_json), Path(args.output_csv) if args.output_csv else None)
    print(json.dumps(summary, ensure_ascii=False))
    for item in findings[:args.top]:
        print(
            f"{item['score']:>2} {item['design_id']} {item['lang']} "
            f"len={item['length']} short={item['short_targets']}/{item['total_targets']} "
            f"terms={','.join(item['risk_terms'])}"
        )
        print(f"   {item['ref_text'][:180]}")


if __name__ == "__main__":
    main()
