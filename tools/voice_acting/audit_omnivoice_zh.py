#!/usr/bin/env python3
"""Mine deterministic Mandarin pronunciation candidates for U6 OmniVoice.

The default mode only writes a candidate inventory and browser review page.  It
does not load OmniVoice or generate audio.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any, Iterable


PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MAPPING = PROJECT_DIR / "u6_voice" / "manifests" / "u6_qwen3_mapping.json"
DEFAULT_DESIGNS = PROJECT_DIR / "u6_voice" / "u6_npc_voice_designs.json"
DEFAULT_OVERRIDES = PROJECT_DIR / "u6_voice" / "manifests" / "omnivoice_overrides.json"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "u6_voice" / "omnivoice_pronunciation_review"

# Frequently context-sensitive Mandarin characters.  pypinyin's heteronym
# inventory extends this list; this set keeps known contextual risks visible
# even when its phrase dictionary returns only one reading.
CONTEXT_DEPENDENT_CHARS = frozenset(
    "行長重樂還著得地的了為傳處數種量藏露調朝相應間角率更少好難便空系都只假強差教校省覺血宿載冠"
)
_CJK = re.compile(r"[\u3400-\u9fff]")


def _load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _source(kind: str, item: dict[str, Any], design_id: str = "") -> dict[str, str]:
    if kind == "mapping":
        return {
            "kind": kind,
            "npc": str(item.get("npc", "")),
            "function": str(item.get("zh_func_id", item.get("func_id", ""))),
            "output": str(item.get("zh_output_filename", item.get("output", ""))),
        }
    npcs = item.get("npcs") or [item.get("npc", "")]
    return {
        "kind": kind,
        "npc": ", ".join(str(value) for value in npcs if value),
        "function": design_id,
        "output": "",
    }


def build_corpus(mapping_path: Path, designs_path: Path = DEFAULT_DESIGNS) -> list[dict[str, Any]]:
    """Return unique exact Traditional strings with every traceable source."""
    by_text: dict[str, dict[str, Any]] = {}

    def add(text: Any, source: dict[str, str]) -> None:
        if not isinstance(text, str) or not text.strip():
            return
        record = by_text.setdefault(text, {"source_text": text, "sources": []})
        if source not in record["sources"]:
            record["sources"].append(source)

    for row in _load_json(mapping_path):
        add(row.get("zh_text"), _source("mapping", row))
    designs_payload = _load_json(designs_path)
    for design_id, design in designs_payload.get("designs", {}).items():
        add(design.get("ref_zh_text"), _source("design", design, str(design_id)))
    return list(by_text.values())


def _dependencies():
    try:
        from opencc import OpenCC
        from pypinyin import Style, lazy_pinyin, pinyin
    except ImportError as error:  # pragma: no cover - exercised by CLI environment
        raise RuntimeError(
            "audit_omnivoice_zh requires opencc-python-reimplemented and pypinyin"
        ) from error
    return OpenCC("t2s"), Style, lazy_pinyin, pinyin


def _numbered_control(reading: str) -> str:
    return reading.upper().replace("Ü", "V")


def mine_candidates(corpus: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mine and dedupe candidates by (source_text, character, word_context)."""
    converter, Style, lazy_pinyin, pinyin = _dependencies()
    found: dict[tuple[str, str, str], dict[str, Any]] = {}
    reading_cache: dict[str, list[str]] = {}
    for corpus_item in corpus:
        source_text = corpus_item["source_text"]
        simplified = converter.convert(source_text)
        contextual = lazy_pinyin(
            source_text, style=Style.TONE3, neutral_tone_with_five=True,
            errors=lambda value: list(value),
        )
        for position, character in enumerate(source_text):
            if not _CJK.fullmatch(character):
                continue
            if character not in reading_cache:
                reading_cache[character] = sorted(set(pinyin(
                    character, style=Style.TONE3, heteronym=True,
                    neutral_tone_with_five=True, errors="default",
                )[0]))
            readings = reading_cache[character]
            traditional_variant = converter.convert(character) != character
            context_sensitive = character in CONTEXT_DEPENDENT_CHARS
            if not (traditional_variant or context_sensitive or len(readings) > 1):
                continue
            start, end = max(0, position - 2), min(len(source_text), position + 3)
            word_context = source_text[start:end]
            key = (source_text, character, word_context)
            if key in found:
                continue
            expected = contextual[position] if position < len(contextual) else readings[0]
            controlled = source_text[:position] + _numbered_control(expected) + source_text[position + 1:]
            reasons = []
            if traditional_variant:
                reasons.append("traditional_simplified")
            if context_sensitive:
                reasons.append("context_dependent")
            if len(readings) > 1:
                reasons.append("heteronym")
            digest = hashlib.sha256("\x1f".join(key).encode("utf-8")).hexdigest()[:16]
            found[key] = {
                "id": f"zh-{digest}",
                "source_text": source_text,
                "simplified_text": simplified,
                "character": character,
                "word_context": word_context,
                "expected_reading": expected,
                "candidate_readings": readings,
                "pinyin_control_text": controlled,
                "reasons": reasons,
                "sources": corpus_item["sources"],
            }
    return sorted(found.values(), key=lambda item: (
        item["source_text"], item["character"], item["word_context"], item["id"]
    ))


def apply_confirmed_overrides(text: str, lang: str, rules: Iterable[dict[str, Any]]) -> str:
    """Apply only explicit language-matched phrase substitutions."""
    result = text
    for rule in rules:
        source = rule.get("source")
        if lang == rule.get("lang") and source:
            result = result.replace(str(source), str(rule.get("tts", source)))
    return result


def build_review_records(candidates: Iterable[dict[str, Any]], output_dir: Path) -> list[dict[str, Any]]:
    records = []
    for candidate in candidates:
        record = dict(candidate)
        variants = []
        values = (
            ("traditional", candidate["source_text"], False),
            ("simplified", candidate["simplified_text"], False),
            ("pinyin_control", candidate["pinyin_control_text"], True),
        )
        for kind, tts_text, eligible in values:
            variants.append({
                "kind": kind,
                "tts_text": tts_text,
                "audio": f"audio/{candidate['id']}.{kind}.wav",
                "audio_exists": (output_dir / "audio" / f"{candidate['id']}.{kind}.wav").exists(),
                "eligible_for_adoption": eligible,
            })
        record.update({"status": "unreviewed", "variants": variants})
        records.append(record)
    return records


def apply_confirmed_candidate_rules(
    candidates: Iterable[dict[str, Any]], rules: Iterable[dict[str, Any]]
) -> None:
    """Prefer reviewed phrase controls over unreviewed pypinyin suggestions."""
    zh_rules = [rule for rule in rules if rule.get("lang") == "zh" and rule.get("source")]
    for candidate in candidates:
        for rule in zh_rules:
            source = str(rule["source"])
            if source in candidate["source_text"] and candidate["character"] in source:
                candidate["pinyin_control_text"] = apply_confirmed_overrides(
                    candidate["source_text"], "zh", [rule]
                )
                candidate["confirmed_rule"] = rule
                syllables = str(rule.get("expected_pinyin", "")).split()
                index = source.find(candidate["character"])
                if 0 <= index < len(syllables):
                    candidate["expected_reading"] = syllables[index]
                break


def _review_html(payload: dict[str, Any]) -> str:
    embedded = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return f'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>OmniVoice 中文發音審核</title>
<style>body{{font:14px system-ui;margin:0;background:#f5f7fa;color:#202124}}header{{position:sticky;top:0;background:white;padding:14px;border-bottom:1px solid #ccd3dd;z-index:2}}main{{padding:14px}}article{{background:white;border:1px solid #d7dde6;border-radius:8px;padding:12px;margin:0 0 12px}}.variants{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}}.variant{{background:#f4f6f9;padding:9px}}code,.text{{white-space:pre-wrap;word-break:break-word}}button{{margin:3px;padding:6px 9px}}audio{{width:100%}}.meta{{color:#5f6368}}@media(max-width:800px){{.variants{{grid-template-columns:1fr}}}}</style></head>
<body><header><h1>OmniVoice 中文發音審核</h1><input id="search" type="search" placeholder="Search source, NPC, character"> <button id="prev">Previous</button><button id="next">Next</button> <button id="export">Export JSONL</button> <span id="summary"></span></header><main id="cards"></main>
<script id="audit-data" type="application/json">{embedded}</script><script>
const data=JSON.parse(document.getElementById('audit-data').textContent), state=JSON.parse(localStorage.getItem('omnivoice-pronunciation-review')||'{{}}');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const PAGE_SIZE=100; let page=0;
function filtered(){{const q=document.getElementById('search').value.toLowerCase();return data.candidates.filter(c=>!q||JSON.stringify(c).toLowerCase().includes(q));}}
function render(){{const matches=filtered(), pages=Math.max(1,Math.ceil(matches.length/PAGE_SIZE));page=Math.min(page,pages-1);const shown=matches.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE);document.getElementById('cards').innerHTML=shown.map(c=>`<article><h2>${{esc(c.source_text)}} · ${{esc(c.character)}} / ${{esc(c.expected_reading)}}</h2><div class="meta">context: ${{esc(c.word_context)}} · readings: ${{esc(c.candidate_readings.join(', '))}} · ${{esc(c.reasons.join(', '))}}</div><p>Sources: ${{esc(c.sources.map(s=>[s.kind,s.npc,s.function,s.output].filter(Boolean).join(':')).join(' | '))}}</p><div class="variants">${{c.variants.map(v=>`<div class="variant"><b>${{esc(v.kind)}}${{v.eligible_for_adoption?' (eligible for adoption)':''}}</b><div class="text">${{esc(v.tts_text)}}</div><audio controls preload="none" src="${{esc(v.audio)}}"></audio><div>${{v.audio_exists?'audio ready':'audio not generated'}}</div></div>`).join('')}}</div><div>Review: ${{['pass','failed','unreviewed'].map(x=>`<button data-id="${{c.id}}" data-status="${{x}}">${{x}}</button>`).join('')}} <b>${{esc(state[c.id]||c.status)}}</b></div></article>`).join('');document.querySelectorAll('button[data-id]').forEach(b=>b.onclick=()=>{{state[b.dataset.id]=b.dataset.status;localStorage.setItem('omnivoice-pronunciation-review',JSON.stringify(state));render()}});document.getElementById('summary').textContent=`${{matches.length}} candidates · page ${{page+1}}/${{pages}}`;}}
document.getElementById('search').oninput=()=>{{page=0;render()}};document.getElementById('prev').onclick=()=>{{page=Math.max(0,page-1);render()}};document.getElementById('next').onclick=()=>{{page++;render()}};
document.getElementById('export').onclick=()=>{{const lines=data.candidates.map(c=>JSON.stringify({{candidate_id:c.id,status:state[c.id]||c.status,source_text:c.source_text,character:c.character,word_context:c.word_context,expected_reading:c.expected_reading}})).join('\n')+'\n';const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([lines],{{type:'application/x-ndjson'}}));a.download='pronunciation_review.jsonl';a.click();URL.revokeObjectURL(a.href)}};render();
</script></body></html>'''


def write_audit(output_dir: Path, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "pronunciation_candidates.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "index.html").write_text(_review_html(payload), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--designs", type=Path, default=DEFAULT_DESIGNS)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--generate-audio", action="store_true", help="Reserved explicit opt-in; requires a bounded selection")
    parser.add_argument("--candidate-id", action="append", default=[], help="Candidate id selected for optional audio generation")
    parser.add_argument("--max-candidates", type=int, default=0, help="Required positive bound with --generate-audio")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.generate_audio:
        if args.max_candidates < 1 or not args.candidate_id:
            raise SystemExit("--generate-audio requires --candidate-id and positive --max-candidates")
        raise SystemExit("Audio generation is intentionally not implemented in the no-GPU Task 4 audit; inventory was not changed")
    corpus = build_corpus(args.mapping, args.designs)
    candidates = mine_candidates(corpus)
    override_payload = _load_json(args.overrides)
    pronunciation_rules = override_payload.get("pronunciation", [])
    apply_confirmed_candidate_rules(candidates, pronunciation_rules)
    records = build_review_records(candidates, args.output_dir)
    payload = {
        "schema_version": 1,
        "mapping": str(args.mapping),
        "designs": str(args.designs),
        "override_revision": override_payload.get("revision"),
        "corpus_count": len(corpus),
        "candidate_count": len(records),
        "confirmed_pronunciation_rules": pronunciation_rules,
        "candidates": records,
    }
    write_audit(args.output_dir, payload)
    print(f"corpus={len(corpus)} candidates={len(records)} output={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
