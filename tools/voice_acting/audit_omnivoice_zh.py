#!/usr/bin/env python3
"""Mine deterministic Mandarin pronunciation candidates for U6 OmniVoice.

The default mode only writes a candidate inventory and browser review page.  It
does not load OmniVoice or generate audio.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
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


def _source(
    kind: str, item: dict[str, Any], design_id: str = "", row_index: int | None = None
) -> dict[str, Any]:
    if kind == "mapping":
        npc = str(item.get("npc", ""))
        function = str(item.get("zh_func_id", item.get("func_id", "")))
        offset = str(item.get("zh_offset_key", item.get("offset_key", "")))
        segment = str(item.get("zh_segment", item.get("segment", "")))
        output = str(item.get("zh_output_filename", item.get("output", "")))
        return {
            "kind": kind,
            "npc": npc, "function": function, "output": output,
            "row_index": row_index,
            "row_key": ":".join((npc, function, offset, segment, output)),
        }
    npcs = item.get("npcs") or [item.get("npc", "")]
    return {
        "kind": kind,
        "npc": ", ".join(str(value) for value in npcs if value),
        "function": design_id,
        "output": "",
        "design_id": design_id,
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

    for row_index, row in enumerate(_load_json(mapping_path)):
        add(row.get("zh_text"), _source("mapping", row, row_index=row_index))
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
            expected = contextual[position] if position < len(contextual) else readings[0]
            controlled = source_text[:position] + _numbered_control(expected) + source_text[position + 1:]
            occurrence = {
                "position": position,
                "word_context": word_context,
                "expected_reading": expected,
                "pinyin_control_text": controlled,
            }
            if key in found:
                found[key]["occurrences"].append(occurrence)
                continue
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
                "occurrences": [occurrence],
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
            audio_path = output_dir / "audio" / f"{candidate['id']}.{kind}.ogg"
            metadata_path = audio_path.with_suffix(".json")
            metadata = {}
            try:
                metadata = _load_json(metadata_path)
            except (OSError, json.JSONDecodeError):
                pass
            variants.append({
                "kind": kind,
                "tts_text": tts_text,
                "audio": f"audio/{candidate['id']}.{kind}.ogg",
                "audio_exists": audio_path.exists(),
                "audio_status": metadata.get("status", "generated" if audio_path.exists() else "missing"),
                "audio_metadata": metadata,
                "eligible_for_adoption": eligible,
            })
        record.update({"status": "unreviewed", "variants": variants})
        records.append(record)
    return records


class OmniVoiceAudioBackend:
    """Thin adapter around the existing U6 OmniVoice generation helpers."""

    def __init__(self):
        import generate_omnivoice_u6 as generator
        self.generator = generator

    def load_model(self, gpu: int, model_id: str):
        return self.generator.load_model(gpu, model_id)

    def complete(self, output: Path, job: Any) -> bool:
        return self.generator._complete(output, job)

    def render(self, model: Any, job: Any, prompt_cache: dict[str, Any]):
        return self.generator._render_with_fallbacks(model, job, prompt_cache)

    def publish(self, job: Any, audio: Any, sample_rate: int, seed: int,
                args: argparse.Namespace, rendered_text: str) -> None:
        self.generator._publish_clone(job, audio, sample_rate, seed, args, rendered_text)


def _clone_with(job: Any, **changes: Any) -> Any:
    if dataclasses.is_dataclass(job):
        return dataclasses.replace(job, **changes)
    result = copy.copy(job)
    for key, value in changes.items():
        setattr(result, key, value)
    return result


def _base_clone_job(record: dict[str, Any], clone_jobs: Iterable[Any]) -> Any | None:
    mapping_sources = [source for source in record.get("sources", []) if source.get("kind") == "mapping"]
    for source in mapping_sources:
        for job in clone_jobs:
            if job.lang != "zh" or job.text != record["source_text"]:
                continue
            if source.get("npc") and job.npc != source["npc"]:
                continue
            if source.get("function") and job.func_id != source["function"]:
                continue
            if source.get("output") and Path(job.output).name != source["output"]:
                continue
            return job
    return None


def generate_selected_audio(
    records: list[dict[str, Any]], candidate_ids: Iterable[str], max_candidates: int,
    output_dir: Path, *, gpu: int, clone_jobs: Iterable[Any],
    backend: Any | None = None, model_id: str = "k2-fsa/OmniVoice",
) -> None:
    """Generate three review variants for an explicit bounded candidate set."""
    selected_ids = list(dict.fromkeys(candidate_ids))
    if max_candidates < 1:
        raise ValueError("--max-candidates must be positive")
    if not selected_ids:
        raise ValueError("--candidate-id is required with --generate-audio")
    if len(selected_ids) > max_candidates:
        raise ValueError("selected candidate count exceeds --max-candidates")
    by_id = {record["id"]: record for record in records}
    missing = [candidate_id for candidate_id in selected_ids if candidate_id not in by_id]
    if missing:
        raise ValueError(f"unknown candidate id(s): {', '.join(missing)}")
    clone_jobs = list(clone_jobs)
    work: list[tuple[dict[str, Any], dict[str, Any], Any]] = []
    for candidate_id in selected_ids:
        record = by_id[candidate_id]
        base = _base_clone_job(record, clone_jobs)
        if base is None:
            for variant in record["variants"]:
                relative = f"audio/{candidate_id}.{variant['kind']}.ogg"
                metadata_path = (output_dir / relative).with_suffix(".json")
                metadata = {
                    "status": "error", "candidate_id": candidate_id,
                    "variant": variant["kind"], "tts_text": variant["tts_text"],
                    "error": "no matching zh clone job",
                }
                metadata_path.parent.mkdir(parents=True, exist_ok=True)
                metadata_path.write_text(
                    json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                variant.update({"audio": relative, "audio_exists": False,
                                "audio_status": "error", "audio_error": metadata["error"],
                                "audio_metadata": metadata})
            continue
        for variant in record["variants"]:
            output = output_dir / "audio" / f"{candidate_id}.{variant['kind']}.ogg"
            variant["audio"] = f"audio/{candidate_id}.{variant['kind']}.ogg"
            job = _clone_with(
                base, output=output, text=record["source_text"],
                tts_text=variant["tts_text"], override_revision="pronunciation-audit-v1",
            )
            work.append((record, variant, job))
    if not work:
        return
    backend = backend or OmniVoiceAudioBackend()
    pending = []
    for record, variant, job in work:
        if backend.complete(job.output, job):
            try:
                metadata = _load_json(job.output.with_suffix(".json"))
            except (OSError, json.JSONDecodeError):
                metadata = {"status": "generated"}
            variant.update({"audio_exists": True, "audio_status": "generated",
                            "audio_metadata": metadata})
        else:
            pending.append((record, variant, job))
    if not pending:
        return
    model = backend.load_model(gpu, model_id)
    args = argparse.Namespace(gpu=gpu, model=model_id)
    prompt_cache: dict[str, Any] = {}
    for record, variant, job in pending:
        metadata_path = job.output.with_suffix(".json")
        try:
            if not backend.complete(job.output, job):
                (audio, sample_rate, seed), rendered_text = backend.render(model, job, prompt_cache)
                backend.publish(job, audio, sample_rate, seed, args, rendered_text)
            metadata = _load_json(metadata_path)
            metadata.update({
                "status": "generated", "candidate_id": record["id"],
                "variant": variant["kind"], "eligible_for_adoption": variant["eligible_for_adoption"],
                "sources": record.get("sources", []),
            })
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            variant.update({"audio_exists": True, "audio_status": "generated", "audio_metadata": metadata})
            variant.pop("audio_error", None)
        except Exception as error:
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            metadata = {
                "status": "error", "candidate_id": record["id"], "variant": variant["kind"],
                "tts_text": variant["tts_text"], "error": f"{type(error).__name__}: {error}",
            }
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            variant.update({"audio_exists": False, "audio_status": "error",
                            "audio_error": metadata["error"], "audio_metadata": metadata})


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
                for occurrence in candidate.get("occurrences", []):
                    occurrence["pinyin_control_text"] = candidate["pinyin_control_text"]
                    if 0 <= index < len(syllables):
                        occurrence["expected_reading"] = syllables[index]
                break


def _review_html(payload: dict[str, Any]) -> str:
    embedded = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return f'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>OmniVoice 中文發音審核</title>
<style>body{{font:14px system-ui;margin:0;background:#f5f7fa;color:#202124}}header{{position:sticky;top:0;background:white;padding:12px;border-bottom:1px solid #ccd3dd;z-index:2}}.filters{{display:flex;flex-wrap:wrap;gap:6px}}input,select,textarea,button{{font:inherit;padding:5px}}main{{padding:14px}}article{{background:white;border:1px solid #d7dde6;border-radius:8px;padding:12px;margin:0 0 12px}}.variants{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}}.variant{{background:#f4f6f9;padding:9px}}.text{{white-space:pre-wrap;word-break:break-word}}audio{{width:100%}}.meta{{color:#5f6368}}.review{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;margin-top:8px}}@media(max-width:800px){{.variants,.review{{grid-template-columns:1fr}}}}</style></head>
<body><header><h1>OmniVoice 中文發音審核</h1><div class="filters"><input id="search" type="search" placeholder="Search all"><select id="reason-filter"><option value="">All reasons</option><option>traditional_simplified</option><option>context_dependent</option><option>heteronym</option></select><input id="character-filter" placeholder="Character"><input id="source-filter" placeholder="Source / NPC"><select id="status-filter"><option value="">All status</option><option>unreviewed</option><option>pass</option><option>failed</option></select><select id="audio-filter"><option value="">All audio</option><option value="ready">Audio ready</option><option value="missing">Audio missing/error</option></select><select id="adoption-filter"><option value="">All adoption</option><option value="eligible">Pinyin eligible</option><option value="confirmed">Confirmed override</option><option value="unconfirmed">Unconfirmed</option></select><button id="prev">Previous</button><button id="next">Next</button><button id="export">Export JSONL</button><span id="summary"></span></div></header><main id="cards"></main>
<script id="audit-data" type="application/json">{embedded}</script><script>
const data=JSON.parse(document.getElementById('audit-data').textContent), state=JSON.parse(localStorage.getItem('omnivoice-pronunciation-review')||'{{}}');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const PAGE_SIZE=100; let page=0;
function review(c){{const old=state[c.id];if(typeof old==='string')state[c.id]={{status:old}};return state[c.id]||(state[c.id]={{status:c.status||'unreviewed',selected_variant:'pinyin_control',review_reason:'',reviewer_note:'',corrected_reading:c.expected_reading||''}});}}
function sourceText(c){{return c.sources.map(s=>[s.kind,s.npc,s.function,s.output,s.row_key,s.design_id].filter(Boolean).join(':')).join(' | ');}}
function filtered(){{const q=document.getElementById('search').value.toLowerCase(),reason=document.getElementById('reason-filter').value,ch=document.getElementById('character-filter').value,source=document.getElementById('source-filter').value.toLowerCase(),status=document.getElementById('status-filter').value,audio=document.getElementById('audio-filter').value,adoption=document.getElementById('adoption-filter').value;return data.candidates.filter(c=>{{const r=review(c),ready=c.variants.some(v=>v.audio_exists),eligible=c.variants.some(v=>v.eligible_for_adoption);return(!q||JSON.stringify(c).toLowerCase().includes(q))&&(!reason||c.reasons.includes(reason))&&(!ch||c.character.includes(ch))&&(!source||sourceText(c).toLowerCase().includes(source))&&(!status||r.status===status)&&(!audio||(audio==='ready')===ready)&&(!adoption||(adoption==='eligible'&&eligible)||(adoption==='confirmed'&&!!c.confirmed_rule)||(adoption==='unconfirmed'&&!c.confirmed_rule));}});}}
function render(){{const matches=filtered(),pages=Math.max(1,Math.ceil(matches.length/PAGE_SIZE));page=Math.min(page,pages-1);const shown=matches.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE);document.getElementById('cards').innerHTML=shown.map(c=>{{const r=review(c);return `<article data-id="${{c.id}}"><h2>${{esc(c.source_text)}} · ${{esc(c.character)}} / ${{esc(c.expected_reading)}}${{c.confirmed_rule?' · confirmed':''}}</h2><div class="meta">context: ${{esc(c.word_context)}} · readings: ${{esc(c.candidate_readings.join(', '))}} · ${{esc(c.reasons.join(', '))}}</div><p>Sources: ${{esc(sourceText(c))}}</p><div class="variants">${{c.variants.map(v=>`<label class="variant"><input type="radio" name="variant-${{c.id}}" data-field="selected_variant" value="${{v.kind}}" ${{r.selected_variant===v.kind?'checked':''}}><b>${{esc(v.kind)}}${{v.eligible_for_adoption?' (eligible for adoption)':''}}</b><div class="text">${{esc(v.tts_text)}}</div><audio controls preload="none" src="${{esc(v.audio)}}"></audio><div>${{esc(v.audio_status||'missing')}}</div></label>`).join('')}}</div><div class="review"><label>Status <select data-field="status"><option ${{r.status==='unreviewed'?'selected':''}}>unreviewed</option><option ${{r.status==='pass'?'selected':''}}>pass</option><option ${{r.status==='failed'?'selected':''}}>failed</option></select></label><label>Reason <input data-field="review_reason" value="${{esc(r.review_reason)}}"></label><label>Corrected reading <input data-field="corrected_reading" value="${{esc(r.corrected_reading)}}"></label><label>Reviewer note <textarea data-field="reviewer_note">${{esc(r.reviewer_note)}}</textarea></label></div></article>`;}}).join('');document.querySelectorAll('[data-field]').forEach(el=>el.onchange=()=>{{const card=el.closest('article'),r=review(data.candidates.find(c=>c.id===card.dataset.id));r[el.dataset.field]=el.value;localStorage.setItem('omnivoice-pronunciation-review',JSON.stringify(state));render();}});document.getElementById('summary').textContent=`${{matches.length}} candidates · page ${{page+1}}/${{pages}}`;}}
document.querySelectorAll('.filters input,.filters select').forEach(el=>el.oninput=()=>{{page=0;render()}});document.getElementById('prev').onclick=()=>{{page=Math.max(0,page-1);render()}};document.getElementById('next').onclick=()=>{{page++;render()}};
document.getElementById('export').onclick=()=>{{const lines=data.candidates.map(c=>{{const r=review(c),variant=c.variants.find(v=>v.kind===r.selected_variant)||c.variants[0];return JSON.stringify({{candidate_id:c.id,status:r.status,review_reason:r.review_reason,reviewer_note:r.reviewer_note,selected_variant:r.selected_variant,selected_tts_text:variant.tts_text,eligible_for_adoption:variant.eligible_for_adoption,source_text:c.source_text,character:c.character,word_context:c.word_context,expected_reading:c.expected_reading,corrected_reading:r.corrected_reading,reasons:c.reasons,confirmed_rule:c.confirmed_rule||null,sources:c.sources,occurrences:c.occurrences}});}}).join('\\n')+'\\n';const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([lines],{{type:'application/x-ndjson'}}));a.download='pronunciation_review.jsonl';a.click();URL.revokeObjectURL(a.href)}};render();
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
    parser.add_argument("--generate-audio", action="store_true", help="Generate three variants for an explicit bounded selection")
    parser.add_argument("--candidate-id", action="append", default=[], help="Candidate id selected for optional audio generation")
    parser.add_argument("--max-candidates", type=int, default=0, help="Required positive bound with --generate-audio")
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--model", default="k2-fsa/OmniVoice")
    parser.add_argument("--refs-dir", type=Path, default=PROJECT_DIR / "u6_voice" / "omnivoice_refs")
    parser.add_argument("--u7-manifest", type=Path, default=Path(__file__).resolve().parent / "reference_import_manifest.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.generate_audio:
        if args.max_candidates < 1 or not args.candidate_id:
            raise SystemExit("--generate-audio requires --candidate-id and positive --max-candidates")
    corpus = build_corpus(args.mapping, args.designs)
    candidates = mine_candidates(corpus)
    override_payload = _load_json(args.overrides)
    pronunciation_rules = override_payload.get("pronunciation", [])
    apply_confirmed_candidate_rules(candidates, pronunciation_rules)
    records = build_review_records(candidates, args.output_dir)
    if args.generate_audio:
        import generate_omnivoice_u6 as generator
        from omnivoice_overrides import load_omnivoice_overrides
        designs = _load_json(args.designs).get("designs", {})
        generation_overrides = load_omnivoice_overrides(args.overrides)
        reference_overrides = generator.load_reference_overrides(args.u7_manifest)
        clone_jobs = generator.build_clone_jobs(
            args.mapping, designs, args.refs_dir, PROJECT_DIR / "u6_voice" / "omnivoice",
            reference_overrides, generation_overrides,
        )
        try:
            generate_selected_audio(
                records, args.candidate_id, args.max_candidates, args.output_dir,
                gpu=args.gpu, clone_jobs=clone_jobs, model_id=args.model,
            )
        except ValueError as error:
            raise SystemExit(str(error)) from error
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
