# Wiki data for voice casting app

This directory holds data scraped from https://wiki.ultimacodex.com/ for each NPC,
so the casting app can display wiki bios/infoboxes offline without hitting the
wiki every time.

## Workflow

### Phase 1: Resolve URLs

```
python tools/voice_acting/voice_casting_tool/scripts/resolve_wiki_urls.py
```

This reads NPC names from `csvs/manifest.csv`, probes the MediaWiki API
(`action=query&redirects=1`), and writes `wiki_urls.csv` with one row per NPC:

```
npc_name, wiki_title, wiki_url, status, notes
```

Status values:
- `found`     - Page exists (possibly after a redirect we followed).
- `disambig`  - Page is a disambiguation page; needs manual resolution.
- `not_found` - No page exists under any candidate title.
- `manual`    - You set this by hand; the script leaves these alone.

The script is idempotent: if a row is already `found` or `manual` it is
skipped. To re-resolve a row, delete its `wiki_title`/`wiki_url` and set its
status to empty.

You can also edit `wiki_urls.csv` by hand to correct entries - just set
`status` to `manual`.

### Phase 2: Download pages

```
python tools/voice_acting/voice_casting_tool/scripts/fetch_wiki_pages.py
```

Reads `wiki_urls.csv`, fetches each page via `action=parse`, and stores one
JSON file per NPC in `wiki_cache/` with fields:

- `url`         - canonical wiki URL
- `title`       - page title
- `summary`     - HTML of the lead section (before the first heading)
- `infobox`     - key/value pairs extracted from `{{Infobox Character}}`
- `fetched_at`  - ISO timestamp

Existing cache files are skipped unless `--force` is passed.

## Runtime

The casting app's Express server reads `wiki_cache/*.json` at startup and
exposes them via `/api/npcs/:name/wiki`. The NPC detail page renders the
infobox + summary and links back to the wiki.
