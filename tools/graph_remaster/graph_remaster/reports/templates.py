"""Small dependency-free HTML templates for offline review."""

from __future__ import annotations

from html import escape
import json
from typing import Mapping, Sequence


def document(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><style>
body{{font:16px system-ui,sans-serif;line-height:1.45;margin:2rem;max-width:90rem;color:#202124}}
nav{{display:flex;flex-wrap:wrap;gap:.75rem;margin-bottom:1.5rem}} nav a{{color:#0645ad}}
pre{{background:#f4f4f4;border:1px solid #ddd;border-radius:4px;padding:1rem;overflow:auto}}
table{{border-collapse:collapse}}th,td{{border:1px solid #ddd;padding:.4rem .6rem;text-align:left}}
.ok{{color:#176b2c}}.bad{{color:#a11}}button{{padding:.35rem .7rem}}
</style></head><body>{body}</body></html>\n"""


def nav_links(stage_files: Sequence[tuple[str, str]]) -> str:
    return "<nav>" + " ".join(
        f'<a href="{escape(href, quote=True)}">{escape(label)}</a>'
        for label, href in stage_files
    ) + "</nav>"


def payload_block(payload: Mapping[str, object]) -> str:
    return f"<pre>{escape(json.dumps(payload, indent=2, sort_keys=True, default=str))}</pre>"
