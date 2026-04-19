"""Resolve NPC names to Ultima Codex wiki URLs.

Reads NPCs from the voice acting manifest and probes the MediaWiki API for
each one, trying several candidate titles. Writes wiki_urls.csv in
voice_casting_tool/data/wiki_data/ with the canonical title + URL per NPC.

Idempotent: rows already marked 'found' or 'manual' are preserved on re-run.
"""

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
TOOL_DIR = THIS_DIR.parent
VOICE_DIR = TOOL_DIR.parent
MANIFEST = VOICE_DIR / "csvs" / "manifest.csv"
OUT_DIR = TOOL_DIR / "data" / "wiki_data"
OUT_CSV = OUT_DIR / "wiki_urls.csv"

WIKI_API = "https://wiki.ultimacodex.com/api.php"
USER_AGENT = "exult-voice-casting-tool/1.0 (contact: local tool)"

# NPCs to skip (engine-only, party, unlikely to have useful wiki pages, etc.)
SKIP = {
    "Avatar",
    "Guard",
    "Wench",
    "Shrine",
    "Dark Core",
    "Palace Guard",
}

# Names where we should go straight to a specific title (disambig, or multiple
# wiki pages with the same name). Fill this in as you discover issues.
MANUAL_OVERRIDES: dict[str, str] = {
    "Budo": "Budo (U7)",
    "D Rel": "D'Rel",
    "For Lem": "For-Lem",
    "Frank": "Frank the Fox",
    "Garok": "Garok Al-Mat",
    "Grayson": "Grayson (U7)",
    "Iriale": "Iriale Silvermist",
    "John Paul": "Lord John-Paul",
    "Lap Lem": "Lap-Lem",
    "Shanda": "Hydra Brothers",
    "Shando": "Hydra Brothers",
    "Shandu": "Hydra Brothers",
    "Xorinia": "Xorinite Wisp",
}


def http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def candidate_titles(name: str, city: str) -> list[str]:
    """Generate ordered candidate wiki titles for an NPC."""
    cands = [name]
    # Generic names should try U7 qualifier first
    generic = name in {"Guard", "Farmer", "Mage", "Smith", "Sailor"}
    if generic:
        cands.insert(0, f"{name} (Ultima VII)")
        cands.insert(1, f"{name} (Ultima VII: The Black Gate)")
    else:
        cands.append(f"{name} (Ultima VII)")
        cands.append(f"{name} (Ultima VII: The Black Gate)")
    if city and city not in ("Unknown", "Party"):
        cands.append(f"{name} ({city})")
    # Dedupe while preserving order
    seen = set()
    out = []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def query_title(title: str) -> dict:
    """Query the MediaWiki API for a title, following redirects."""
    params = {
        "action": "query",
        "titles": title,
        "redirects": "1",
        "format": "json",
        "formatversion": "2",
        "prop": "categories",
        "cllimit": "50",
    }
    url = f"{WIKI_API}?{urllib.parse.urlencode(params)}"
    return http_get_json(url)


def resolve_one(name: str, city: str) -> dict:
    """Return {status, title, url, notes} for a single NPC."""
    if name in SKIP:
        return {"status": "skip", "title": "", "url": "", "notes": "in SKIP list"}

    if name in MANUAL_OVERRIDES:
        title = MANUAL_OVERRIDES[name]
        # Still verify it exists
        data = query_title(title)
        page = data.get("query", {}).get("pages", [{}])[0]
        if page.get("missing"):
            return {"status": "not_found", "title": title, "url": "",
                    "notes": f"override {title!r} missing on wiki"}
        return {
            "status": "manual",
            "title": page.get("title", title),
            "url": title_to_url(page.get("title", title)),
            "notes": "from MANUAL_OVERRIDES",
        }

    for candidate in candidate_titles(name, city):
        try:
            data = query_title(candidate)
        except Exception as e:
            return {"status": "error", "title": candidate, "url": "", "notes": str(e)}
        page = data.get("query", {}).get("pages", [{}])[0]
        if page.get("missing"):
            continue
        resolved_title = page.get("title", candidate)
        cats = [c.get("title", "") for c in page.get("categories", [])]
        is_disambig = any("disambig" in c.lower() for c in cats)
        note_parts = []
        if resolved_title != candidate:
            note_parts.append(f"redirected from {candidate!r}")
        if is_disambig:
            return {
                "status": "disambig",
                "title": resolved_title,
                "url": title_to_url(resolved_title),
                "notes": "; ".join(note_parts + ["disambig page"]),
            }
        return {
            "status": "found",
            "title": resolved_title,
            "url": title_to_url(resolved_title),
            "notes": "; ".join(note_parts),
        }

    return {"status": "not_found", "title": "", "url": "",
            "notes": f"tried: {', '.join(candidate_titles(name, city))}"}


def title_to_url(title: str) -> str:
    return "https://wiki.ultimacodex.com/wiki/" + urllib.parse.quote(title.replace(" ", "_"))


def load_npcs_from_manifest() -> list[tuple[str, str]]:
    """Return list of (npc_name, city) from the manifest. City is best-effort
    from the speaker column - we don't have a city map in Python, so we'll
    leave city blank and let the candidate generator handle fallbacks."""
    names: set[str] = set()
    with MANIFEST.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            speaker = (row.get("speaker") or "").strip()
            if speaker:
                names.add(speaker)
    return sorted((n, "") for n in names)


def load_existing() -> dict[str, dict]:
    if not OUT_CSV.exists():
        return {}
    result = {}
    with OUT_CSV.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            result[row["npc_name"]] = row
    return result


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_existing()
    npcs = load_npcs_from_manifest()

    rows: list[dict] = []
    new_resolved = 0
    skipped = 0
    for name, city in npcs:
        prev = existing.get(name)
        if prev and prev.get("status") in ("found", "manual", "skip"):
            rows.append(prev)
            skipped += 1
            continue

        print(f"Resolving {name!r}...", end=" ", flush=True)
        result = resolve_one(name, city)
        print(f"{result['status']} -> {result['title'] or '(none)'}")
        rows.append({
            "npc_name": name,
            "wiki_title": result["title"],
            "wiki_url": result["url"],
            "status": result["status"],
            "notes": result["notes"],
        })
        new_resolved += 1
        time.sleep(0.3)  # be polite to the wiki

    # Keep any rows from existing file that aren't in the manifest anymore,
    # so manual edits are never lost.
    manifest_names = {n for n, _ in npcs}
    for name, row in existing.items():
        if name not in manifest_names:
            rows.append(row)

    rows.sort(key=lambda r: r["npc_name"])
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["npc_name", "wiki_title", "wiki_url", "status", "notes"])
        w.writeheader()
        w.writerows(rows)

    print()
    print(f"Wrote {OUT_CSV}")
    print(f"  {len(rows)} total rows, {new_resolved} newly resolved, {skipped} skipped")
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    for s, n in sorted(by_status.items()):
        print(f"  {s}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
