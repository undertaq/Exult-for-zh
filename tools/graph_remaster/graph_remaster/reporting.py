"""Small offline stage-report writer; later reporting tasks may replace its presentation."""

from __future__ import annotations

from html import escape
import json
from pathlib import Path
from typing import Mapping


def write_stage_html_report(path: Path, title: str, payload: Mapping[str, object]) -> None:
    """Write a self-contained HTML document with no network or CDN dependency."""

    body = escape(json.dumps(payload, indent=2, sort_keys=True))
    document = f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><title>{escape(title)}</title>
<style>body{{font:16px system-ui,sans-serif;margin:2rem;max-width:72rem}}pre{{background:#f4f4f4;padding:1rem;overflow:auto}}</style>
</head><body><h1>{escape(title)}</h1><pre>{body}</pre></body></html>\n"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(document, encoding="utf-8")
