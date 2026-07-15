#!/usr/bin/env python3
"""Generate a static, searchable review page for selected reference voices."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
from urllib.parse import unquote, urlparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LANGUAGES = ("English", "Chinese")
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PORTRAITS = SCRIPT_DIR / "voice_casting_tool" / "data" / "portraits"


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def selection_fingerprint(selection: dict) -> str:
    """Return a stable key for review decisions belonging to this selection."""
    payload = json.dumps(selection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_") or "npc"


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _relative(path: Path, output_path: Path) -> str:
    return os.path.relpath(path.resolve(), output_path.resolve().parent).replace(os.sep, "/")


def _candidate_index(path: Path) -> int | str:
    match = re.search(r"_(\d+)\.ogg$", path.name)
    return int(match.group(1)) if match else path.stem


def _candidate_metadata(candidate: Path) -> dict:
    data = _load_json(candidate.with_suffix(".json"), {})
    return data if isinstance(data, dict) else {}


def _bible_for(slug: str, bibles: Path | dict) -> dict:
    if isinstance(bibles, dict):
        value = bibles.get(slug, {})
        return value if isinstance(value, dict) else {}
    value = _load_json(Path(bibles) / f"{slug}.json", {})
    return value if isinstance(value, dict) else {}


def _audit_for(slug: str, audit: dict) -> dict:
    if not isinstance(audit, dict):
        return {}
    value = audit.get(slug)
    if isinstance(value, dict):
        return value
    value = (audit.get("audits") or audit.get("results") or {}).get(slug)
    if isinstance(value, dict):
        return value
    for item in audit.get("items", []) if isinstance(audit.get("items"), list) else []:
        if isinstance(item, dict) and item.get("slug") == slug:
            return item
    return {}


def _portrait_path(slug: str, record: dict, bible: dict, portrait_root: Path | None) -> Path | None:
    evidence = bible.get("evidence") if isinstance(bible.get("evidence"), dict) else {}
    image_url = evidence.get("image_url")
    image_name = ""
    if image_url:
        image_name = Path(unquote(urlparse(str(image_url)).path)).name
    candidates = [
        evidence.get("image_path"),
        evidence.get("portrait"),
        record.get("portrait"),
        image_name,
    ]
    roots = [portrait_root] if portrait_root else []
    for value in candidates:
        if not value:
            continue
        raw = Path(str(value))
        options = [raw]
        if portrait_root and not raw.is_absolute():
            options.insert(0, portrait_root / raw.name)
            options.append(portrait_root / raw)
        for option in options:
            if option.exists() and option.is_file():
                return option
    if portrait_root and portrait_root.exists():
        wanted = {_compact(slug), _compact(record.get("npc", slug))}
        if image_name:
            wanted.add(_compact(Path(image_name).stem))
        for path in sorted(portrait_root.iterdir()):
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif"}:
                stem = _compact(path.stem)
                if any(
                    stem == name
                    or stem.removesuffix("u7") == name
                    or (len(name) >= 4 and (stem.startswith(name) or name.startswith(stem)))
                    for name in wanted
                ):
                    return path
    return None


def _audit_label(audit: dict) -> tuple[str, bool]:
    warnings = audit.get("warnings") or audit.get("issues") or audit.get("errors") or []
    if isinstance(warnings, str):
        warnings = [warnings]
    warning = bool(warnings) or audit.get("status") in {"warning", "failed", "invalid"}
    return ("; ".join(str(item) for item in warnings) if warnings else str(audit.get("status", "ok")), warning)


def _audio_tag(path: Path | None, output_path: Path, label: str, extra_class: str = "") -> str:
    if path is None or not path.exists():
        return f'<span class="missing">missing {esc(label)} audio</span>'
    source = _relative(path, output_path)
    return (f'<audio class="lazy-audio {esc(extra_class)}" controls preload="none" '
            f'data-src="{esc(source)}" aria-label="{esc(label)} reference voice">'
            f'{esc(path.name)}</audio>')


def _candidate_cell(path: Path | None, output_path: Path, label: str, metadata: dict, selected: bool) -> str:
    classes = "selected" if selected else ""
    index = metadata.get("candidate", _candidate_index(path) if path else "")
    details = " · ".join(
        f"{key}: {metadata[key]}" for key in ("seed", "duration_seconds", "sample_rate", "sha256")
        if metadata.get(key) not in (None, "")
    )
    sample_text = metadata.get("text") or metadata.get("sample_text") or ""
    prompt = metadata.get("instruct") or metadata.get("voice_prompt_enriched") or ""
    return (f'<td class="{classes}"><div class="candidate-index">{esc(index)}'
            f'{" <strong>selected</strong>" if selected else ""}</div>'
            f'{_audio_tag(path, output_path, label, "candidate") if path else ""}'
            f'<div class="metadata">{esc(details)}</div>'
            f'<div class="candidate-text">{esc(sample_text)}</div>'
            f'<div class="metadata">{esc(prompt)}</div></td>')


def _build_card(slug: str, record: dict, bible: dict, candidate_root: Path, portrait_root: Path | None,
                output_path: Path, audit: dict) -> str:
    npc = record.get("npc", slug)
    portrait = _portrait_path(slug, record, bible, portrait_root)
    portrait_html = (f'<img loading="lazy" src="{esc(_relative(portrait, output_path))}" '
                     f'alt="{esc(npc)} portrait">' if portrait else '<div class="no-portrait">No portrait</div>')
    audit_text, audit_warning = _audit_label(audit)
    audit_class = " warning" if audit_warning else ""
    candidate_dir = candidate_root / slug
    selected_indices = {
        "English": record.get("english_index", record.get("index")),
        "Chinese": record.get("chinese_index", record.get("index")),
    }
    selected_paths: dict[str, Path | None] = {}
    candidates: dict[str, list[tuple[Path, dict]]] = {}
    for language in LANGUAGES:
        paths = sorted(candidate_dir.glob(f"candidate_{language}_*.ogg"), key=lambda p: (str(_candidate_index(p))))
        candidates[language] = [(path, _candidate_metadata(path)) for path in paths]
        selected_paths[language] = next(
            (path for path, meta in candidates[language]
             if str(meta.get("candidate", _candidate_index(path))) == str(selected_indices[language])),
            None,
        )
    portrait_flag = "true" if portrait else "false"
    warning_flag = "true" if audit_warning else "false"
    selected_players = "".join(
        f'<div class="selected-player"><h3>{language} · index {esc(selected_indices[language])}</h3>'
        f'{_audio_tag(selected_paths[language], output_path, language)}'
        f'<div class="selected-meta">seed: {esc(((_candidate_metadata(selected_paths[language]) if selected_paths[language] else {}).get("seed", record.get(language.lower() + "_seed", ""))))}</div></div>'
        for language in LANGUAGES
    )
    tables = []
    all_indices = sorted({str(meta.get("candidate", _candidate_index(path)))
                          for language in LANGUAGES for path, meta in candidates[language]},
                         key=lambda value: (0, int(value)) if value.isdigit() else (1, value))
    for language in LANGUAGES:
        by_index = {str(meta.get("candidate", _candidate_index(path))): (path, meta)
                    for path, meta in candidates[language]}
        rows = []
        for index in all_indices:
            path, meta = by_index.get(index, (None, {"candidate": index}))
            rows.append(f'<tr><th>{esc(index)}</th>'
                        f'{_candidate_cell(path, output_path, language, meta, index == str(selected_indices[language]))}'
                        f'</tr>')
        tables.append(f'<div class="candidate-language"><h4>{language} candidates</h4>'
                      f'<table><thead><tr><th>Candidate</th><th>{language}</th></tr></thead>'
                      f'<tbody>{"".join(rows)}</tbody></table></div>')
    prompt_en = bible.get("voice_prompt_enriched") or bible.get("voice_prompt_original", "")
    prompt_zh = bible.get("voice_prompt_enriched_zh") or bible.get("voice_prompt_zh", "")
    return f'''<section class="character" data-slug="{esc(slug)}" data-portrait="{portrait_flag}" data-warning="{warning_flag}">
      <div class="character-heading"><div class="portrait">{portrait_html}</div><div><h2>{esc(npc)}</h2><div class="slug">{esc(slug)}</div><div class="audit{audit_class}">Audit: {esc(audit_text)}</div></div></div>
      <div class="prompts"><div><h3>English voice design</h3><p>{esc(prompt_en)}</p></div><div><h3>Chinese voice design</h3><p>{esc(prompt_zh)}</p></div></div>
      <div class="selected-players">{selected_players}</div>
      <div class="review-controls" data-review-slug="{esc(slug)}"><span>Review:</span><label><input type="checkbox" data-status="pass"> Pass</label><label><input type="checkbox" data-status="failed"> Failed</label><span class="review-state">unreviewed</span></div>
      <details><summary>All candidates ({max(len(candidates["English"]), len(candidates["Chinese"]))} per language)</summary>{"".join(tables)}</details>
    </section>'''


def build_report(selection: dict, bibles: Path | dict, candidate_root: Path, output_path: Path, audit: dict) -> str:
    """Build the complete report without writing files or changing source data."""
    output_path = Path(output_path)
    candidate_root = Path(candidate_root)
    portrait_root = getattr(build_report, "portrait_root", None)
    cards = []
    for slug, record in (selection.get("selected") or {}).items():
        cards.append(_build_card(slug, record, _bible_for(slug, bibles), candidate_root,
                                 portrait_root, output_path, _audit_for(slug, audit)))
    fingerprint = selection_fingerprint(selection)
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    css = '''
      :root { color-scheme: light; --ink:#202124; --muted:#5f6368; --line:#d9dee7; --panel:#f7f9fc; --selected:#e4f2e7; --warn:#fff3cd; }
      * { box-sizing:border-box; } body { margin:0; color:var(--ink); font:14px system-ui, sans-serif; background:#fff; }
      header { position:sticky; top:0; z-index:5; padding:16px 22px; background:#fff; border-bottom:1px solid var(--line); }
      h1 { margin:0 0 6px; font-size:22px; } h2 { margin:0; font-size:20px; } h3,h4 { margin:0 0 6px; font-size:14px; }
      .summary,.slug,.metadata,.selected-meta { color:var(--muted); font-size:12px; } .summary { margin-bottom:10px; }
      .toolbar { display:flex; flex-wrap:wrap; gap:8px 14px; align-items:center; } .toolbar label { white-space:nowrap; }
      input[type=search] { min-width:220px; padding:7px 9px; border:1px solid #aeb6c2; border-radius:4px; }
      main { max-width:1500px; margin:0 auto; } .character { padding:20px 22px; border-bottom:1px solid var(--line); }
      .character-heading { display:flex; gap:14px; align-items:flex-start; margin-bottom:14px; } .portrait { width:112px; min-width:112px; height:112px; }
      .portrait img { width:112px; height:112px; object-fit:contain; image-rendering:pixelated; border:1px solid var(--line); background:var(--panel); }
      .no-portrait { height:112px; display:grid; place-items:center; color:var(--muted); background:var(--panel); border:1px solid var(--line); font-size:12px; text-align:center; }
      .audit { margin-top:8px; color:#26733b; font-size:12px; } .audit.warning { color:#8a5a00; background:var(--warn); padding:4px 6px; }
      .prompts { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:14px; } .prompts > div { background:var(--panel); padding:10px; border-left:3px solid #7192b8; }
      p { white-space:pre-wrap; overflow-wrap:anywhere; margin:0; line-height:1.45; } .selected-players { display:flex; flex-wrap:wrap; gap:14px; }
      .selected-player { min-width:280px; flex:1; } audio { width:100%; height:34px; } .missing { color:#a50e0e; font-size:12px; }
      .review-controls { display:flex; gap:12px; align-items:center; margin:14px 0; padding:8px 10px; background:var(--panel); } .review-state { color:var(--muted); margin-left:auto; }
      details { border-top:1px solid var(--line); padding-top:9px; } summary { cursor:pointer; font-weight:600; } .candidate-language { overflow-x:auto; margin-top:12px; }
      table { border-collapse:collapse; min-width:100%; } th,td { border:1px solid var(--line); padding:6px; text-align:left; vertical-align:top; min-width:180px; } th { background:var(--panel); }
      td.selected { background:var(--selected); outline:2px solid #4d965d; outline-offset:-2px; } td audio { min-width:160px; } .candidate-index strong { color:#26733b; font-size:11px; }
      .hidden { display:none; } @media (max-width:700px) { header { position:static; padding:14px; } .character { padding:16px 14px; } .prompts { grid-template-columns:1fr; } .portrait,.portrait img { width:88px; min-width:88px; height:88px; } .no-portrait { height:88px; } .selected-player { min-width:100%; } input[type=search] { min-width:0; width:100%; } }
    '''
    script = f'''<script>
      const reviewKey = "ultima-ref-review:{fingerprint}";
      const saved = JSON.parse(localStorage.getItem(reviewKey) || "{{}}");
      const cards = [...document.querySelectorAll('.character')];
      function loadMedia(node) {{ if (node.dataset.src && !node.src) node.src = node.dataset.src; }}
      const observer = new IntersectionObserver(entries => entries.forEach(e => {{ if (e.isIntersecting) {{ e.target.querySelectorAll('.lazy-audio').forEach(loadMedia); observer.unobserve(e.target); }} }}), {{rootMargin:'300px'}});
      cards.forEach(card => observer.observe(card));
      function updateReview(card) {{ const slug=card.dataset.slug, box=card.querySelector('.review-controls'), pass=box.querySelector('[data-status=pass]'), failed=box.querySelector('[data-status=failed]'); let value=pass.checked?'pass':failed.checked?'failed':''; if (pass.checked) failed.checked=false; if (failed.checked) pass.checked=false; if (value) saved[slug]=value; else delete saved[slug]; localStorage.setItem(reviewKey, JSON.stringify(saved)); box.querySelector('.review-state').textContent=value||'unreviewed'; update(); }}
      cards.forEach(card => {{ const value=saved[card.dataset.slug]||''; const box=card.querySelector('.review-controls'); box.querySelector('[data-status=pass]').checked=value==='pass'; box.querySelector('[data-status=failed]').checked=value==='failed'; box.querySelector('.review-state').textContent=value||'unreviewed'; box.querySelectorAll('input').forEach(input=>input.addEventListener('change',()=>updateReview(card))); }});
      function update() {{ const query=document.querySelector('#search').value.toLowerCase(), filter=document.querySelector('#filter').value; let visible=0, reviewed=0; cards.forEach(card=>{{ const value=saved[card.dataset.slug]||'', matchName=card.textContent.toLowerCase().includes(query), matchFilter=filter==='all'||(filter==='unreviewed'&&!value)||(filter==='passed'&&value==='pass')||(filter==='failed'&&value==='failed')||(filter==='missing-portrait'&&card.dataset.portrait==='false')||(filter==='missing-audio'&&card.textContent.includes('missing'))||(filter==='audit-warning'&&card.dataset.warning==='true'); card.classList.toggle('hidden',!(matchName&&matchFilter)); if(matchName&&matchFilter) visible++; if(value) reviewed++; }}); document.querySelector('#visible').textContent=visible; document.querySelector('#reviewed').textContent=reviewed; }}
      document.querySelector('#search').addEventListener('input',update); document.querySelector('#filter').addEventListener('change',update); update();
    </script>'''
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Reference Voice Review</title><style>{css}</style></head><body><header><h1>Reference Voice Review</h1><div class="summary">Generated {esc(generated)} · selection fingerprint <code>{esc(fingerprint)}</code> · visible <b id="visible">0</b> / {len(cards)} · reviewed <b id="reviewed">0</b></div><div class="toolbar"><input id="search" type="search" placeholder="Search character"><label>Filter <select id="filter"><option value="all">All</option><option value="unreviewed">Unreviewed</option><option value="passed">Passed</option><option value="failed">Failed</option><option value="missing-portrait">Missing portrait</option><option value="missing-audio">Missing audio</option><option value="audit-warning">Audit warnings</option></select></label></div></header><main>{''.join(cards)}</main>{script}</body></html>'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--bibles", type=Path, default=None,
                        help="Voice bible directory; defaults to SOURCE_ROOT/voice_bibles when present")
    parser.add_argument("--portrait-root", type=Path, default=DEFAULT_PORTRAITS)
    parser.add_argument("--audit-report", type=Path, default=None)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    selection = _load_json(args.selection, {})
    audit = _load_json(args.audit_report, {}) if args.audit_report else {}
    build_report.portrait_root = args.portrait_root
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bibles = args.bibles or (args.source_root / "voice_bibles")
    candidate_root = args.source_root / "references"
    if not candidate_root.is_dir():
        candidate_root = args.source_root
    page = build_report(selection, bibles, candidate_root, args.output, audit)
    args.output.write_text(page, encoding="utf-8")
    print(f"Wrote {args.output} ({len(selection.get('selected', {}))} character sections)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
