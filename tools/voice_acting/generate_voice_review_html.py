#!/usr/bin/env python3
"""Generate a paged HTML review UI for voice clips.

Modes:
  mood-samples: review mood-clone sample refs/samples from a manifest.
  full: scan generated voice/en and voice/zh clips and attach manifest text.
"""

import argparse
import json
import os
import re
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE_DIR = PROJECT_DIR / "voice" / "review_samples" / "mood_clone"
DEFAULT_MAPPING = PROJECT_DIR / "tools" / "voice_acting" / "bilingual_mapping_review.json"
DEFAULT_VOICE_DIR = PROJECT_DIR / "voice"


def rel_url(path, base_dir):
    return os.path.relpath(Path(path), Path(base_dir)).replace(os.sep, "/")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def uses_zh_runtime_for_english_voice(entry, lang="en"):
    if lang != "en":
        return False
    if not (entry.get("en_text", "") or "").strip():
        return False
    if (entry.get("en_func_id", "") or "").strip() or (entry.get("en_offset_key", "") or "").strip():
        return False
    return bool(
        (entry.get("zh_func_id", "") or "").strip()
        and (entry.get("zh_offset_key", "") or "").strip()
    )


def uses_en_runtime_for_zh_voice(entry, lang="zh"):
    if lang != "zh":
        return False
    if not (entry.get("zh_text", "") or "").strip():
        return False
    if (entry.get("zh_func_id", "") or "").strip() or (entry.get("zh_offset_key", "") or "").strip():
        return False
    return bool(
        (entry.get("en_func_id", "") or "").strip()
        and (entry.get("en_offset_key", "") or "").strip()
    )


def build_base_name(entry, lang):
    if uses_en_runtime_for_zh_voice(entry, lang):
        fid = entry.get("en_func_id", "") or "0000"
        ok = entry.get("en_offset_key", "") or "0"
        seg = entry.get("en_segment", 0) or 0
    elif uses_zh_runtime_for_english_voice(entry, lang):
        fid = entry.get("zh_func_id", "") or "0000"
        ok = entry.get("zh_offset_key", "") or "0"
        seg = entry.get("zh_segment", 0) or 0
    else:
        fid = (
            entry.get(f"{lang}_func_id", "")
            or entry.get("zh_func_id", "")
            or entry.get("en_func_id", "")
            or "0000"
        )
        ok = entry.get(f"{lang}_offset_key", "") or "0"
        seg = entry.get(f"{lang}_segment", 0) or 0
    if isinstance(fid, str) and fid.lower().startswith("0x"):
        fid = fid[2:]
    return f"{str(fid).lower().zfill(4)}_{ok}_{seg}"


def npc_suffix(npc):
    try:
        from npc_data import NPC_NUMBERS
    except Exception:
        return ""
    npc_num = NPC_NUMBERS.get(npc or "")
    return f"_npc{npc_num}" if npc_num is not None else ""


def expected_filename(entry, lang):
    base = build_base_name(entry, lang)
    avatar_gender = entry.get("_avatar_voice_gender")
    if avatar_gender in ("male", "female"):
        return f"{base}_avatar_{avatar_gender}.ogg"
    return f"{base}{npc_suffix(entry.get('npc', ''))}.ogg"


def build_mapping_index(mapping_path):
    if not mapping_path.exists():
        return {}
    rows = load_json(mapping_path)
    index = {}
    for entry in rows:
        for lang in ("en", "zh"):
            text = (entry.get(f"{lang}_text", "") or "").strip()
            if not text:
                continue
            index[(lang, expected_filename(entry, lang))] = {
                "npc": entry.get("npc", ""),
                "speaker": entry.get("speaker", ""),
                "text": text,
                "func_id": entry.get(f"{lang}_func_id", "") or entry.get("zh_func_id", ""),
                "offset_key": entry.get(f"{lang}_offset_key", "") or entry.get("zh_offset_key", ""),
                "segment": entry.get(f"{lang}_segment", 0),
                "voice_prompt": entry.get("voice_prompt", ""),
                "voice_prompt_zh": entry.get("voice_prompt_zh", ""),
            }
    return index


def format_voice_prompt(meta):
    """Combine EN/ZH reference-voice prompts for the review row display."""
    zh = (meta.get("voice_prompt_zh") or "").strip()
    en = (meta.get("voice_prompt") or "").strip()
    if zh and en:
        return f"{zh}\n---\n{en}"
    return zh or en


def rows_from_mood_samples(sample_dir):
    manifest_path = sample_dir / "manifest.json"
    manifest = load_json(manifest_path)
    refs = {}
    rows = []
    for item in manifest:
        if item.get("kind") == "ref":
            refs[(item["character"], item["mood"], item["lang"])] = item
    for item in manifest:
        if item.get("kind") != "sample":
            continue
        key = (item["character"], item["mood"], item["lang"])
        ref = refs.get(key, {})
        rows.append({
            "kind": "sample",
            "character": item["character"],
            "npc": item["character"],
            "speaker": item["character"],
            "mood": item["mood"],
            "lang": item["lang"],
            "text": item.get("text", ""),
            "audio": str((PROJECT_DIR / item["path"]).resolve()),
            "ref_audio": str((PROJECT_DIR / ref.get("path", item.get("ref", ""))).resolve()) if ref else "",
            "ref_text": ref.get("text", ""),
            "prompt": ref.get("prompt", ""),
            "note": item.get("note", ""),
            "filename": Path(item["path"]).name,
        })
    return rows


def parse_generated_filename(path):
    stem = path.stem
    match = re.match(r"^(?P<func>[0-9a-fA-F]{4})_(?P<offset>.+)_(?P<segment>\d+)(?:_(?P<suffix>.+))?$", stem)
    return match.groupdict() if match else {}


def _build_paired_new(voice_dir, mapping_path, since_mtime):
    """Build set of (lang, filename) where paired EN/ZH entry has either file new.

    When EN and ZH generation runs on separate GPUs at different times,
    a paired entry's files may have different mtimes. Without pairing,
    ``only_new=True`` would exclude one language's file while including
    the other, producing unbalanced per-NPC EN/ZH counts in the review.
    """
    with open(mapping_path) as f:
        entries = json.load(f)
    paired = set()
    for entry in entries:
        en_text = (entry.get('en_text', '') or '').strip()
        zh_text = (entry.get('zh_text', '') or '').strip()
        if not en_text or not zh_text:
            continue
        en_fn = expected_filename(entry, 'en')
        zh_fn = expected_filename(entry, 'zh')
        en_m = int((voice_dir / 'en' / en_fn).stat().st_mtime) if (voice_dir / 'en' / en_fn).exists() else 0
        zh_m = int((voice_dir / 'zh' / zh_fn).stat().st_mtime) if (voice_dir / 'zh' / zh_fn).exists() else 0
        if en_m >= since_mtime or zh_m >= since_mtime:
            paired.add(('en', en_fn))
            paired.add(('zh', zh_fn))
    return paired


def rows_from_full_voice(voice_dir, mapping_path, since_mtime=0, only_new=False):
    mapping = build_mapping_index(mapping_path)

    if only_new and since_mtime:
        paired_new = _build_paired_new(voice_dir, mapping_path, since_mtime)
    else:
        paired_new = set()

    rows = []
    seen = set()
    for (lang, filename), meta in sorted(mapping.items()):
        npc = meta.get("npc", "")
        if "|" in npc:
            continue
        path = voice_dir / lang / filename
        exists = path.exists()
        mtime = int(path.stat().st_mtime) if exists else 0
        is_new = bool(exists and since_mtime and mtime >= since_mtime)
        if only_new and not is_new:
            if (lang, filename) in paired_new:
                is_new = True
            else:
                continue
        seen.add((lang, filename))
        rows.append({
                "kind": "generated",
                "status": "new" if is_new else ("generated" if exists else "missing"),
                "character": meta.get("npc", ""),
                "npc": meta.get("npc", ""),
                "speaker": meta.get("speaker", ""),
                "mood": "",
                "lang": lang,
                "text": meta.get("text", ""),
                "audio": str(path.resolve()) if exists else "",
                "ref_audio": "",
                "ref_text": "",
                "prompt": format_voice_prompt(meta),
                "filename": filename,
                "func_id": meta.get("func_id", ""),
                "offset_key": meta.get("offset_key", ""),
                "segment": meta.get("segment", ""),
            })
    for lang in ("en", "zh"):
        lang_dir = voice_dir / lang
        if not lang_dir.exists():
            continue
        for path in sorted(lang_dir.glob("*.ogg")):
            if (lang, path.name) in seen:
                continue
            mtime = int(path.stat().st_mtime)
            is_new = bool(since_mtime and mtime >= since_mtime)
            if only_new and not is_new:
                continue
            meta = mapping.get((lang, path.name), {})
            parsed = parse_generated_filename(path)
            rows.append({
                "kind": "generated",
                "status": "new_orphan" if is_new else "orphan",
                "character": meta.get("npc", ""),
                "npc": meta.get("npc", ""),
                "speaker": meta.get("speaker", ""),
                "mood": "",
                "lang": lang,
                "text": meta.get("text", ""),
                "audio": str(path.resolve()),
                "ref_audio": "",
                "ref_text": "",
                "prompt": "",
                "filename": path.name,
                "func_id": meta.get("func_id", parsed.get("func", "")),
                "offset_key": meta.get("offset_key", parsed.get("offset", "")),
                "segment": meta.get("segment", parsed.get("segment", "")),
                "size": path.stat().st_size,
                "modified": mtime,
            })
    return rows


def write_report(rows, out_dir, title, review_id=""):
    out_dir.mkdir(parents=True, exist_ok=True)
    data_path = out_dir / "voice_review_data.json"
    html_path = out_dir / "index.html"
    rows = normalize_audio_paths(rows, out_dir)
    rows = add_review_keys(rows)
    payload = {"title": title, "review_id": review_id, "rows": rows}
    data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(build_html(title, payload), encoding="utf-8")
    return html_path, data_path


def review_key(row):
    lang = row.get("lang", "")
    filename = row.get("filename", "")
    if lang and filename:
        return f"{lang}:{filename}"
    parts = [
        row.get("kind", ""),
        row.get("character", "") or row.get("npc", ""),
        lang,
        row.get("mood", ""),
        row.get("text", ""),
        row.get("audio", ""),
    ]
    return ":".join(str(part) for part in parts)


def add_review_keys(rows):
    keyed = []
    for row in rows:
        row = dict(row)
        row["review_key"] = row.get("review_key") or review_key(row)
        keyed.append(row)
    return keyed


def normalize_audio_paths(rows, out_dir):
    normalized = []
    for row in rows:
        row = dict(row)
        for key in ("audio", "ref_audio"):
            value = row.get(key, "")
            if not value:
                continue
            path = Path(value)
            if not path.is_absolute():
                path = (PROJECT_DIR / path).resolve()
            row[key] = rel_url(path, out_dir)
        normalized.append(row)
    return normalized


def html_embedded_json(payload):
    # Keep the page directly openable as file:// by embedding the same data
    # that is also written to voice_review_data.json for external tools.
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def build_html(title, payload):
    embedded_json = html_embedded_json(payload)
    return f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 0; color: #1f2933; background: #f7f8fa; }}
  header {{ position: sticky; top: 0; z-index: 2; background: #fff; border-bottom: 1px solid #d8dee6; padding: 14px 18px; }}
  h1 {{ font-size: 20px; margin: 0 0 10px; }}
  .controls {{ display: grid; grid-template-columns: 1.8fr repeat(5, minmax(110px, 0.7fr)); gap: 8px; align-items: center; }}
  input, select, button {{ font: inherit; padding: 7px 8px; border: 1px solid #b7c0cc; border-radius: 4px; background: #fff; }}
  input[type="checkbox"] {{ width: 16px; height: 16px; padding: 0; vertical-align: middle; }}
  main {{ padding: 16px 18px 28px; }}
  .summary {{ margin-bottom: 12px; font-size: 13px; color: #52616f; }}
  .review-actions {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 10px; }}
  .review-actions button {{ padding: 6px 9px; }}
  .review-cell {{ min-width: 116px; }}
  .review-checks {{ display: grid; gap: 6px; font-size: 13px; }}
  .review-checks label {{ display: flex; align-items: center; gap: 6px; }}
  .review-state-pass {{ background: #eef8ef; }}
  .review-state-failed {{ background: #fff1f0; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d8dee6; }}
  th, td {{ border-bottom: 1px solid #e4e8ee; padding: 8px; vertical-align: top; text-align: left; }}
  th {{ font-size: 12px; text-transform: uppercase; color: #52616f; background: #f0f3f6; }}
  audio {{ width: 230px; max-width: 100%; }}
  .text {{ max-width: 540px; white-space: pre-wrap; }}
  .prompt {{ max-width: 520px; color: #52616f; font-size: 12px; white-space: pre-wrap; }}
  .pager {{ display: flex; gap: 8px; align-items: center; margin: 12px 0; }}
  @media (max-width: 900px) {{
    .controls {{ grid-template-columns: 1fr 1fr; }}
    table, thead, tbody, tr, th, td {{ display: block; }}
    thead {{ display: none; }}
    tr {{ border: 1px solid #d8dee6; margin: 0 0 12px; background: #fff; }}
    td {{ border-bottom: 1px solid #e4e8ee; }}
    td::before {{ content: attr(data-label); display: block; font-size: 11px; text-transform: uppercase; color: #52616f; margin-bottom: 4px; }}
  }}
</style>
<header>
  <h1>{title}</h1>
  <div class="controls">
    <input id="search" placeholder="Search text, NPC, filename">
    <select id="lang"><option value="">All languages</option></select>
    <select id="character"><option value="">All characters</option></select>
    <select id="mood"><option value="">All moods</option></select>
    <select id="status"><option value="">All statuses</option></select>
    <select id="pageSize"><option>25</option><option selected>50</option><option>100</option><option>200</option></select>
  </div>
  <div class="review-actions">
    <button id="exportReviewState" type="button">Export review state</button>
    <button id="importReviewState" type="button">Import review state</button>
    <input id="importReviewFile" type="file" accept="application/json" hidden>
  </div>
</header>
<main>
  <div class="summary" id="summary">Loading...</div>
  <div class="pager"><button id="prev">Prev</button><span id="page"></span><button id="next">Next</button></div>
  <table>
    <thead><tr><th>Review</th><th>Status</th><th>Character</th><th>Lang</th><th>Mood</th><th>Audio</th><th>Reference</th><th>Text</th><th>Prompt / File</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
  <div class="pager"><button id="prev2">Prev</button><span id="page2"></span><button id="next2">Next</button></div>
</main>
<script id="voiceData" type="application/json">{embedded_json}</script>
<script>
let allRows = [];
let filtered = [];
let page = 0;
let reviewState = {{}};
const REVIEW_STORAGE_KEY = 'voiceReviewState:' + location.pathname + ':' + (JSON.parse(document.getElementById('voiceData').textContent).review_id || 'default');
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
function getReviewKey(row) {{
  if (row.review_key) return row.review_key;
  if (row.lang && row.filename) return `${{row.lang}}:${{row.filename}}`;
  return [row.kind, row.character || row.npc, row.lang, row.mood, row.text, row.audio].map(v => String(v || '')).join(':');
}}
function loadReviewState() {{
  try {{
    reviewState = JSON.parse(localStorage.getItem(REVIEW_STORAGE_KEY) || '{{}}') || {{}};
  }} catch (error) {{
    reviewState = {{}};
  }}
}}
function saveReviewState() {{
  localStorage.setItem(REVIEW_STORAGE_KEY, JSON.stringify(reviewState));
}}
function setReviewState(key, value) {{
  if (!value) delete reviewState[key];
  else reviewState[key] = value;
  saveReviewState();
  render();
}}
function reviewCounts(rows) {{
  return rows.reduce((acc, row) => {{
    const state = reviewState[getReviewKey(row)] || 'unreviewed';
    acc[state] = (acc[state] || 0) + 1;
    return acc;
  }}, {{}});
}}
function reviewControls(row) {{
  const key = getReviewKey(row);
  const state = reviewState[key] || '';
  const safeKey = esc(key);
  return `<div class="review-checks">
    <label><input type="checkbox" data-review-key="${{safeKey}}" data-review-value="pass" ${{state === 'pass' ? 'checked' : ''}}> Pass</label>
    <label><input type="checkbox" data-review-key="${{safeKey}}" data-review-value="failed" ${{state === 'failed' ? 'checked' : ''}}> Failed</label>
  </div>`;
}}
function uniqueValues(key) {{
  return [...new Set(allRows.map(r => r[key]).filter(Boolean))].sort((a,b) => String(a).localeCompare(String(b)));
}}
function fillSelect(id, key) {{
  const el = $(id);
  const first = el.querySelector('option');
  el.innerHTML = '';
  if (first) el.appendChild(first);
  for (const v of uniqueValues(key)) {{
    const opt = document.createElement('option');
    opt.value = v; opt.textContent = v;
    el.appendChild(opt);
  }}
}}
function applyFilters() {{
  const q = $('search').value.trim().toLowerCase();
  const lang = $('lang').value;
  const character = $('character').value;
  const mood = $('mood').value;
  const status = $('status').value;
  filtered = allRows.filter(r => {{
    if (lang && r.lang !== lang) return false;
    if (character && r.character !== character && r.npc !== character) return false;
    if (mood && r.mood !== mood) return false;
    if (status && r.status !== status) return false;
    if (!q) return true;
    return [r.status, r.character, r.npc, r.speaker, r.mood, r.lang, r.text, r.filename, r.prompt]
      .some(v => String(v || '').toLowerCase().includes(q));
  }});
  page = 0;
  render();
}}
function render() {{
  const size = Number($('pageSize').value || 50);
  const pages = Math.max(1, Math.ceil(filtered.length / size));
  page = Math.max(0, Math.min(page, pages - 1));
  const start = page * size;
  const shown = filtered.slice(start, start + size);
  const counts = allRows.reduce((acc, r) => {{ acc[r.status || 'unknown'] = (acc[r.status || 'unknown'] || 0) + 1; return acc; }}, {{}});
  const countText = Object.entries(counts).sort().map(([k,v]) => `${{k}}:${{v}}`).join(' · ');
  const progress = reviewCounts(allRows);
  const progressText = Object.entries(progress).sort().map(([k,v]) => `${{k}}:${{v}}`).join(' · ');
  $('summary').textContent = `${{filtered.length}} shown / ${{allRows.length}} total · ${{countText}} · review ${{progressText}}`;
  $('page').textContent = `Page ${{page + 1}} / ${{pages}}`;
  $('page2').textContent = $('page').textContent;
  $('rows').innerHTML = shown.map(r => `
    <tr class="review-state-${{esc(reviewState[getReviewKey(r)] || 'unreviewed')}}">
      <td class="review-cell" data-label="Review">${{reviewControls(r)}}</td>
      <td data-label="Status">${{esc(r.status || '')}}</td>
      <td data-label="Character">${{esc(r.character || r.npc || '')}}</td>
      <td data-label="Lang">${{esc(r.lang)}}</td>
      <td data-label="Mood">${{esc(r.mood || '')}}</td>
      <td data-label="Audio">${{r.audio ? `<audio controls preload="none" src="${{esc(r.audio)}}"></audio>` : ''}}</td>
      <td data-label="Reference">${{r.ref_audio ? `<audio controls preload="none" src="${{esc(r.ref_audio)}}"></audio><div class="prompt">${{esc(r.ref_text || '')}}</div>` : ''}}</td>
      <td data-label="Text"><div class="text">${{esc(r.text || '')}}</div></td>
      <td data-label="Prompt / File"><div class="prompt">${{esc(r.note || r.prompt || r.filename || '')}}</div></td>
    </tr>`).join('');
  $('rows').querySelectorAll('input[data-review-key]').forEach(input => {{
    input.addEventListener('change', () => {{
      const key = input.dataset.reviewKey;
      const value = input.checked ? input.dataset.reviewValue : '';
      setReviewState(key, value);
    }});
  }});
}}
for (const id of ['search','lang','character','mood','status','pageSize']) $(id).addEventListener('input', applyFilters);
for (const id of ['prev','prev2']) $(id).addEventListener('click', () => {{ page--; render(); }});
for (const id of ['next','next2']) $(id).addEventListener('click', () => {{ page++; render(); }});
function initialize(data) {{
  loadReviewState();
  allRows = data.rows || [];
  fillSelect('lang', 'lang');
  fillSelect('character', 'character');
  fillSelect('mood', 'mood');
  fillSelect('status', 'status');
  applyFilters();
}}
$('exportReviewState').addEventListener('click', () => {{
  const payload = {{
    title: {json.dumps(title)},
    exported_at: new Date().toISOString(),
    storage_key: REVIEW_STORAGE_KEY,
    state: reviewState,
  }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{type: 'application/json'}});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'voice_review_state.json';
  link.click();
  URL.revokeObjectURL(url);
}});
$('importReviewState').addEventListener('click', () => $('importReviewFile').click());
$('importReviewFile').addEventListener('change', event => {{
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {{
    try {{
      const parsed = JSON.parse(reader.result);
      reviewState = parsed.state || parsed || {{}};
      saveReviewState();
      render();
    }} catch (error) {{
      alert(`Failed to import review state: ${{error}}`);
    }}
  }};
  reader.readAsText(file);
}});
try {{
  initialize(JSON.parse($('voiceData').textContent));
}} catch (error) {{
  $('summary').textContent = `Failed to load embedded review data: ${{error}}`;
}}
</script>
"""


def main():
    parser = argparse.ArgumentParser(description="Generate voice review HTML with paged/lazy audio playback.")
    parser.add_argument("--mode", choices=["mood-samples", "full"], default="mood-samples")
    parser.add_argument("--sample-dir", default=str(DEFAULT_SAMPLE_DIR))
    parser.add_argument("--voice-dir", default=str(DEFAULT_VOICE_DIR))
    parser.add_argument("--mapping", default=str(DEFAULT_MAPPING))
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--title", default=None)
    parser.add_argument("--since-mtime", type=int, default=0, help="Mark files with mtime >= this Unix timestamp as new.")
    parser.add_argument("--only-new", action="store_true", help="In full mode, include only files generated after --since-mtime.")
    parser.add_argument("--review-id", default="", help="Stable id for this review run; changes reset browser-stored review marks.")
    args = parser.parse_args()

    if args.mode == "mood-samples":
        sample_dir = Path(args.sample_dir)
        rows = rows_from_mood_samples(sample_dir)
        out_dir = Path(args.out_dir) if args.out_dir else sample_dir
        title = args.title or "Mood Clone Review Samples"
    else:
        voice_dir = Path(args.voice_dir)
        rows = rows_from_full_voice(
            voice_dir,
            Path(args.mapping),
            since_mtime=args.since_mtime,
            only_new=args.only_new,
        )
        out_dir = Path(args.out_dir) if args.out_dir else PROJECT_DIR / "tools" / "voice_acting" / "voice_review_full"
        title = args.title or "Generated Voice Review"

    html_path, data_path = write_report(rows, out_dir, title, review_id=args.review_id)
    print(f"Wrote {html_path}")
    print(f"Wrote {data_path}")
    print(f"Rows: {len(rows)}")


if __name__ == "__main__":
    main()
