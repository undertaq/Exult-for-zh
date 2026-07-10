#!/usr/bin/env python3
"""Generate an HTML review report for portrait-assisted voice designs."""
import argparse
import html
import json
import re
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DESIGNS_PATH = SCRIPT_DIR / "npc_voice_designs.json"
REPORT_JSON_PATH = SCRIPT_DIR / "portrait_voice_design_report.json"
OUTPUT_PATH = SCRIPT_DIR / "portrait_voice_design_report.html"
PORTRAIT_REL_DIR = "voice_casting_tool/data/portraits"
PORTRAITS_DIR = SCRIPT_DIR / PORTRAIT_REL_DIR
REFS_REL_DIR = "../../voice/refs"
REFS_DIR = SCRIPT_DIR.parent.parent / "voice" / "refs"


def esc(value):
    return html.escape(str(value or ""), quote=True)


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_name(name):
    value = re.sub(r"[^a-z0-9]+", "", (name or "").lower())
    if value.endswith("u7"):
        value = value[:-2]
    return value


def build_portrait_index(portraits_dir=PORTRAITS_DIR):
    portraits_dir = Path(portraits_dir)
    index = {}
    if not portraits_dir.exists():
        return index
    for path in sorted(portraits_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif"}:
            continue
        index.setdefault(normalize_name(path.stem), path)
    return index


def portrait_name_variants(name):
    base = normalize_name(name)
    variants = [base]
    for prefix in ("lord",):
        if base.startswith(prefix) and len(base) > len(prefix):
            variants.append(base[len(prefix):])
    return [variant for variant in variants if variant]


def find_portrait_for_name(name, portrait_index):
    variants = portrait_name_variants(name)
    for variant in variants:
        portrait = portrait_index.get(variant)
        if portrait:
            return portrait
    for key, portrait in portrait_index.items():
        for variant in variants:
            if key.startswith(variant) or variant.startswith(key):
                return portrait
    return None


def portrait_for_design(design, portrait_index):
    for name in design.get("npcs", []):
        portrait = find_portrait_for_name(name, portrait_index)
        if portrait:
            return portrait.name
    portrait = find_portrait_for_name(design.get("npc", ""), portrait_index)
    if portrait:
        return portrait.name
    return ""


def portraits_for_design(design, portrait_index):
    portraits = []
    seen = set()
    for name in design.get("npcs", []):
        portrait = find_portrait_for_name(name, portrait_index)
        if portrait and portrait.name not in seen:
            portraits.append((name, portrait.name))
            seen.add(portrait.name)
    if not portraits:
        portrait = find_portrait_for_name(design.get("npc", ""), portrait_index)
        if portrait:
            portraits.append((design.get("npc", ""), portrait.name))
    return portraits


def processed_by_design(report):
    return {
        item.get("design_id"): item
        for item in report.get("processed", [])
        if item.get("design_id")
    }


def sort_design_items(designs, report):
    processed = processed_by_design(report)

    def key(item):
        design_id, design = item
        is_processed = design_id in processed or bool(design.get("_portrait_voice_analysis"))
        return (0 if is_processed else 1, design.get("npc", design_id).lower(), design_id)

    return sorted(designs.get("designs", {}).items(), key=key)


def ref_audio_links(design_id):
    players = []
    for lang in ("en", "zh"):
        rel = f"{REFS_REL_DIR}/{design_id}_{lang}_ref.ogg"
        players.append(
            f'<div class="player"><span>{lang.upper()}</span>'
            f'<audio controls preload="none" src="{esc(rel)}"></audio></div>'
        )
    return "\n".join(players)


def format_size(size):
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def ref_status_html(design_id, refs_dir=REFS_DIR):
    items = []
    for lang in ("en", "zh"):
        path = Path(refs_dir) / f"{design_id}_{lang}_ref.ogg"
        label = lang.upper()
        if path.exists():
            stat = path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            items.append(
                f'<div class="ref ok">{label} ref · {esc(format_size(stat.st_size))} · {esc(mtime)}</div>'
            )
        else:
            items.append(f'<div class="ref missing">{label} missing</div>')
    return "\n".join(items)


def row_html(design_id, design, processed, portrait_index):
    meta = design.get("_portrait_voice_analysis") or {}
    processed_item = processed.get(design_id, {})
    analysis = processed_item.get("analysis") or {}
    stored_portraits = meta.get("portraits") or processed_item.get("portraits") or []
    portrait = meta.get("portrait") or processed_item.get("portrait") or ""
    portrait_items = []
    if stored_portraits:
        name_by_portrait = {}
        for npc_name, portrait_name in portraits_for_design(design, portrait_index):
            name_by_portrait[portrait_name] = npc_name
        portrait_items = [
            (name_by_portrait.get(portrait_name, design.get("npc", "")), portrait_name)
            for portrait_name in stored_portraits
        ]
    elif portrait:
        portrait_items = [(design.get("npc", ""), portrait)]
    else:
        portrait_items = portraits_for_design(design, portrait_index)
    portrait_html = ""
    if portrait_items:
        chunks = []
        for npc_name, portrait_name in portrait_items:
            rel = f"{PORTRAIT_REL_DIR}/{portrait_name}"
            chunks.append(
                f'<div class="portraitItem"><img src="{esc(rel)}" alt="{esc(portrait_name)}">'
                f'<div class="path">{esc(npc_name)}<br>{esc(portrait_name)}</div></div>'
            )
        portrait_html = f'<div class="portraitGrid">{"".join(chunks)}</div>'
    else:
        portrait_html = '<div class="missing">No matched portrait</div>'

    previous = meta.get("previous_voice_desc_en", "")
    model = meta.get("model") or processed_item.get("model", "")
    changed = processed_item.get("changed", "")
    badge = ""
    if meta or processed_item:
        badge = '<span class="badge">vision updated</span>'
    if changed is True:
        badge += '<span class="badge changed">changed</span>'

    npcs = ", ".join(design.get("npcs", []))
    vision_prompt = analysis.get("voice_desc_en", "")
    traits = meta.get("visual_traits") or analysis.get("visual_traits", "")
    temperament = meta.get("temperament") or analysis.get("temperament", "")
    has_vision = bool(meta or processed_item)
    if not has_vision:
        vision_block = f"""
        <div class="pending">Not analyzed yet</div>
        <div class="label">Prompt currently used for references</div>
        <p>{esc(design.get('voice_desc_en', ''))}</p>
        """
    else:
        vision_block = f"""
        <div class="label">Vision prompt</div>
        <p>{esc(vision_prompt)}</p>
        <div class="label">Previous prompt</div>
        <p>{esc(previous)}</p>
        <div class="label">Traits</div>
        <p>{esc(traits)}</p>
        <div class="label">Temperament</div>
        <p>{esc(temperament)}</p>
        <div class="sub">Model: {esc(model)}</div>
        """

    return f"""
    <tr>
      <td class="portrait">{portrait_html}</td>
      <td>
        <div class="title">{esc(design.get('npc') or design_id)} {badge}</div>
        <div class="sub">{esc(design_id)} · {esc(design.get('type', ''))}</div>
        <div class="sub">{esc(npcs)}</div>
        <div class="audio">{ref_audio_links(design_id)}</div>
        <div class="refstatus">{ref_status_html(design_id)}</div>
      </td>
      <td>
        <div class="label">Current English prompt</div>
        <p>{esc(design.get('voice_desc_en', ''))}</p>
        <div class="label">Current Chinese prompt</div>
        <p>{esc(design.get('voice_desc_zh', ''))}</p>
      </td>
      <td>
        {vision_block}
      </td>
      <td>
        <div class="label">Reference EN text</div>
        <p>{esc(design.get('ref_en_text', ''))}</p>
        <div class="label">Reference ZH text</div>
        <p>{esc(design.get('ref_zh_text', ''))}</p>
      </td>
    </tr>
    """


def build_html(designs, report, portrait_index=None):
    portrait_index = portrait_index if portrait_index is not None else build_portrait_index()
    processed = processed_by_design(report)
    rows = "\n".join(row_html(design_id, design, processed, portrait_index) for design_id, design in sort_design_items(designs, report))
    processed_count = len(processed)
    design_count = len(designs.get("designs", {}))
    generated_at = datetime.now().isoformat(timespec="seconds")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Portrait Voice Design Review</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #202124;
      --muted: #60646c;
      --line: #d7dbe2;
      --head: #f3f5f7;
      --badge: #174ea6;
      --changed: #137333;
    }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--ink);
      background: #ffffff;
    }}
    header {{
      padding: 20px 24px 12px;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 24px;
      letter-spacing: 0;
    }}
    .summary {{
      color: var(--muted);
      font-size: 13px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }}
    th {{
      position: sticky;
      top: 0;
      z-index: 1;
      background: var(--head);
      border-bottom: 1px solid var(--line);
      text-align: left;
      font-size: 12px;
      padding: 8px;
    }}
    td {{
      vertical-align: top;
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      font-size: 13px;
      line-height: 1.35;
    }}
    th:nth-child(1), td:nth-child(1) {{ width: 120px; }}
    th:nth-child(2), td:nth-child(2) {{ width: 180px; }}
    th:nth-child(3), td:nth-child(3) {{ width: 28%; }}
    th:nth-child(4), td:nth-child(4) {{ width: 28%; }}
    img {{
      display: block;
      width: 96px;
      height: 96px;
      image-rendering: pixelated;
      object-fit: contain;
      border: 1px solid var(--line);
      background: #f8f9fa;
    }}
    .portraitGrid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
      gap: 8px;
    }}
    .portraitItem {{
      min-width: 0;
    }}
    p {{
      margin: 3px 0 10px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }}
    .title {{
      font-weight: 700;
      font-size: 14px;
      margin-bottom: 4px;
    }}
    .sub, .path {{
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
      margin-top: 4px;
    }}
    .audio {{
      margin-top: 8px;
    }}
    .player {{
      display: grid;
      grid-template-columns: 24px minmax(0, 1fr);
      align-items: center;
      gap: 6px;
      margin-top: 5px;
      color: var(--muted);
      font-size: 11px;
    }}
    .player audio {{
      width: 100%;
      height: 28px;
    }}
    .label {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      margin-top: 4px;
    }}
    .badge {{
      display: inline-block;
      margin-left: 6px;
      padding: 2px 5px;
      border-radius: 4px;
      background: var(--badge);
      color: white;
      font-size: 11px;
      font-weight: 400;
    }}
    .badge.changed {{
      background: var(--changed);
    }}
    .missing {{
      color: #a50e0e;
      font-size: 12px;
    }}
    .pending {{
      display: inline-block;
      margin: 0 0 8px;
      padding: 3px 6px;
      border-radius: 4px;
      background: #fef7e0;
      color: #8a5a00;
      font-size: 12px;
      font-weight: 700;
    }}
    .refstatus {{
      margin-top: 8px;
    }}
    .ref {{
      font-size: 11px;
      margin-top: 3px;
      overflow-wrap: anywhere;
    }}
    .ref.ok {{
      color: #137333;
    }}
    .ref.missing {{
      color: #a50e0e;
    }}
    a {{
      color: #174ea6;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Portrait Voice Design Review</h1>
    <div class="summary">Generated {esc(generated_at)} · {processed_count} vision-updated design(s) · {design_count} total design(s)</div>
  </header>
  <table>
    <thead>
      <tr>
        <th>Portrait</th>
        <th>Design</th>
        <th>Current Prompt</th>
        <th>Vision Analysis</th>
        <th>Reference Text</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</body>
</html>
"""


def write_report(designs, report, output_path):
    output_path = Path(output_path)
    output_path.write_text(build_html(designs, report), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--designs", default=str(DESIGNS_PATH))
    parser.add_argument("--report-json", default=str(REPORT_JSON_PATH))
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    args = parser.parse_args()

    designs = load_json(args.designs, {"designs": {}})
    report = load_json(args.report_json, {"processed": []})
    write_report(designs, report, args.output)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
