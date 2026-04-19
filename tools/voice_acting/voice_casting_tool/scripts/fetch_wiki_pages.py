"""Download wiki pages for NPCs, parse into structured JSON.

Reads wiki_urls.csv produced by resolve_wiki_urls.py, fetches each page via
the MediaWiki parse API, and writes one JSON file per NPC into wiki_cache/.

JSON shape:
{
  "npc_name": "Caroline",
  "url": "https://wiki.ultimacodex.com/wiki/Caroline",
  "title": "Caroline",
  "summary_html": "<p>...</p>",
  "summary_text": "...",
  "infobox": {"Occupation": "...", "Location": "...", ...},
  "fetched_at": "2026-04-18T..."
}

Skips NPCs whose cache file already exists unless --force is passed.
"""

import argparse
import csv
import datetime
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
TOOL_DIR = THIS_DIR.parent
VOICE_DIR = TOOL_DIR.parent
OUT_DIR = TOOL_DIR / "data" / "wiki_data"
CSV_PATH = OUT_DIR / "wiki_urls.csv"
CACHE_DIR = OUT_DIR / "wiki_cache"

WIKI_API = "https://wiki.ultimacodex.com/api.php"
USER_AGENT = "exult-voice-casting-tool/1.0 (contact: local tool)"


def http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_parse(title: str) -> dict:
    params = {
        "action": "parse",
        "page": title,
        "prop": "text|wikitext",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
    }
    url = f"{WIKI_API}?{urllib.parse.urlencode(params)}"
    return http_get_json(url)


INFOBOX_RE = re.compile(r"\{\{\s*Infobox[^}|]*\|(.*?)\}\}", re.DOTALL | re.IGNORECASE)
PARAM_SPLIT_RE = re.compile(r"(?<!\[)\|(?!])")


def strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def parse_infobox_html(full_html: str) -> dict[str, str]:
    """Extract key/value pairs from the first floating infobox table.

    The Ultima Codex infoboxes are <table> elements with inline style (no
    'infobox' class), typically floated right. We take the first table and
    parse its <tr> rows into key/value pairs, with two-column rows providing
    the data and single-column rows acting as section headers.
    """
    # Find the first top-level table (we consumed just its html to the end)
    m = re.search(r"<table[\s\S]*?</table>", full_html, re.IGNORECASE)
    if not m:
        return {}
    tbl = m.group(0)
    # Pull rows
    rows = re.findall(r"<tr[\s>][\s\S]*?</tr>", tbl, re.IGNORECASE)
    result: dict[str, str] = {}
    section = ""
    for row in rows:
        cells = re.findall(r"<t[dh][\s>][\s\S]*?</t[dh]>", row, re.IGNORECASE)
        if not cells:
            continue
        # Strip colspan full-width rows: if a single cell spans 2 cols, treat
        # as heading/section label (but skip image-only rows)
        if len(cells) == 1:
            text = strip_html(cells[0])
            # Skip image-only headers, appearance markers, name title
            if not text or text.lower().startswith(("appearances", "ultima")):
                section = text
                continue
            # Keep NPC title as _title but don't clobber
            if "_section" not in result:
                result["_section"] = text
            continue
        if len(cells) >= 2:
            k = strip_html(cells[0]).rstrip(":").strip()
            v = strip_html(cells[1]).strip()
            if k and v and k.lower() not in ("appearances",):
                # Some NPCs have both U7 and SI - prefix key with section if
                # it would overwrite
                if k in result and result[k] != v:
                    if section:
                        result[f"{k} ({section})"] = v
                    continue
                result[k] = v
    result.pop("_section", None)
    return result


def parse_infobox(wikitext: str) -> dict[str, str]:
    """Extract key=value pairs from an {{Infobox ...}} wikitext template.

    This is a fallback used when the rendered HTML doesn't contain a usable
    table. Most Ultima Codex NPC pages have all the data in the HTML so this
    is rarely used."""
    m = re.search(r"\{\{\s*Infobox[^}|]*?\s*\|", wikitext, re.IGNORECASE | re.DOTALL)
    if not m:
        return {}
    start = m.end()
    depth = 2  # already inside {{
    i = start
    params_text_start = start
    params: list[str] = []
    current_start = start
    while i < len(wikitext):
        ch = wikitext[i]
        if ch == "{" and wikitext[i:i + 2] == "{{":
            depth += 2
            i += 2
            continue
        if ch == "}" and wikitext[i:i + 2] == "}}":
            depth -= 2
            if depth == 0:
                params.append(wikitext[current_start:i])
                break
            i += 2
            continue
        if ch == "[" and wikitext[i:i + 2] == "[[":
            # Skip past wikilinks so their pipes don't split params
            depth += 2
            i += 2
            continue
        if ch == "]" and wikitext[i:i + 2] == "]]":
            depth -= 2
            i += 2
            continue
        if ch == "|" and depth == 2:
            params.append(wikitext[current_start:i])
            current_start = i + 1
        i += 1

    result: dict[str, str] = {}
    for p in params:
        if "=" not in p:
            continue
        k, _, v = p.partition("=")
        key = k.strip()
        val = clean_wiki_value(v.strip())
        if key and val:
            result[key] = val
    return result


def clean_wiki_value(v: str) -> str:
    # Strip trailing newlines/whitespace
    v = v.strip()
    # [[Target|Display]] -> Display; [[Target]] -> Target
    v = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", v)
    v = re.sub(r"\[\[([^\]]+)\]\]", r"\1", v)
    # '''bold''' / ''italic''
    v = re.sub(r"'''(.+?)'''", r"\1", v)
    v = re.sub(r"''(.+?)''", r"\1", v)
    # <ref>...</ref>
    v = re.sub(r"<ref[^>]*>.*?</ref>", "", v, flags=re.DOTALL)
    v = re.sub(r"<ref[^/]*/>", "", v)
    # Strip simple tags we don't care about
    v = re.sub(r"<br\s*/?>", ", ", v)
    v = re.sub(r"<[^>]+>", "", v)
    v = html.unescape(v)
    v = re.sub(r"\s+", " ", v).strip()
    return v


def extract_summary_html(full_html: str) -> tuple[str, str]:
    """Return (summary_html, summary_text) - everything before the first
    section heading, with nav/table-of-contents stripped."""
    # Cut off at the first <h2> (section heading) or <h1>
    cut = len(full_html)
    for pat in (r"<h2[\s>]", r"<h1[\s>]"):
        m = re.search(pat, full_html)
        if m:
            cut = min(cut, m.start())
    head = full_html[:cut]
    # Drop any leading tables (infoboxes are tables, often without a recognizable class)
    head = re.sub(r'<table[\s\S]*?</table>', "", head, flags=re.IGNORECASE)
    head = re.sub(r'<div[^>]*id="toc"[^>]*>.*?</div>', "", head,
                  flags=re.DOTALL | re.IGNORECASE)
    head = re.sub(r'<div[^>]*class="[^"]*toc[^"]*"[^>]*>.*?</div>', "", head,
                  flags=re.DOTALL | re.IGNORECASE)
    # Strip empty paragraphs and extra whitespace
    head = re.sub(r"<p>\s*</p>", "", head)
    head = head.strip()

    text = re.sub(r"<[^>]+>", "", head)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return head, text


def fetch_one(npc_name: str, title: str, url: str) -> dict:
    data = fetch_parse(title)
    parse = data.get("parse", {})
    full_html = (parse.get("text") or "").strip()
    wikitext = (parse.get("wikitext") or "").strip()
    infobox = parse_infobox_html(full_html)
    if not infobox:
        infobox = parse_infobox(wikitext)
    summary_html, summary_text = extract_summary_html(full_html)
    return {
        "npc_name": npc_name,
        "url": url,
        "title": parse.get("title") or title,
        "summary_html": summary_html,
        "summary_text": summary_text,
        "infobox": infobox,
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name) + ".json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="re-download pages that already exist in cache")
    ap.add_argument("--only", metavar="NAME",
                    help="only fetch this one NPC (for testing)")
    args = ap.parse_args()

    if not CSV_PATH.exists():
        print(f"error: {CSV_PATH} not found. Run resolve_wiki_urls.py first.",
              file=sys.stderr)
        return 1
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    fetched = 0
    skipped = 0
    failed = 0
    for row in rows:
        name = row["npc_name"]
        if args.only and name != args.only:
            continue
        status = row.get("status", "")
        title = row.get("wiki_title", "")
        url = row.get("wiki_url", "")
        if status not in ("found", "manual", "disambig") or not title:
            continue
        out_path = CACHE_DIR / safe_filename(name)
        if out_path.exists() and not args.force:
            skipped += 1
            continue
        print(f"Fetching {name!r} ({title})...", end=" ", flush=True)
        try:
            data = fetch_one(name, title, url)
        except Exception as e:
            print(f"FAILED: {e}")
            failed += 1
            continue
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"ok ({len(data['infobox'])} infobox fields, "
              f"{len(data['summary_text'])} chars summary)")
        fetched += 1
        time.sleep(0.5)

    print()
    print(f"Fetched {fetched}, skipped {skipped}, failed {failed}")
    print(f"Cache dir: {CACHE_DIR}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
