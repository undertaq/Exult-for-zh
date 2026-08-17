"""Page through the ElevenLabs shared voices library and record all unique
values for filter-relevant fields (accent, use_case, descriptive, gender, age,
category, language).

The API docs don't publish enums for these fields, so we observe them. The
output is used by the casting tool to populate filter dropdowns.

Output:  voice_casting_tool/data/wiki_data/voice_filter_values.json

Re-run any time to refresh.
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
TOOL_DIR = THIS_DIR.parent
VOICE_DIR = TOOL_DIR.parent
OUT_DIR = TOOL_DIR / "data" / "wiki_data"
OUT_JSON = OUT_DIR / "voice_filter_values.json"
ENV_PATH = VOICE_DIR / ".env"

API_URL = "https://api.elevenlabs.io/v1/shared-voices"
USER_AGENT = "exult-voice-casting-tool/1.0"
PAGE_SIZE = 100

# Fields we want to gather unique values for. Response fields are singular
# (use_case, descriptive), but the filter params are plural (use_cases,
# descriptives) - we record the singular form seen in responses.
OBSERVED_FIELDS = ["accent", "use_case", "descriptive", "gender", "age",
                   "category", "language"]


def load_api_key() -> str:
    # Pull from .env manually (no python-dotenv dep)
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ELEVENLABS_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        print("error: ELEVENLABS_API_KEY not set (checked .env and env)",
              file=sys.stderr)
        sys.exit(1)
    return key


def fetch_page(page: int, language: str, api_key: str) -> dict:
    params = {"page": page, "page_size": PAGE_SIZE}
    if language:
        params["language"] = language
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "xi-api-key": api_key,
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--language", default="en",
                    help='language filter to scope the scan (default "en", '
                         'use "" for all languages)')
    ap.add_argument("--max-pages", type=int, default=100,
                    help="safety cap on how many pages to fetch (default 100)")
    args = ap.parse_args()

    api_key = load_api_key()
    counters: dict[str, Counter] = {f: Counter() for f in OBSERVED_FIELDS}
    total_voices = 0

    for page in range(args.max_pages):
        try:
            data = fetch_page(page, args.language, api_key)
        except Exception as e:
            print(f"page {page}: error {e}", file=sys.stderr)
            break
        voices = data.get("voices", [])
        total_voices += len(voices)
        for v in voices:
            for f in OBSERVED_FIELDS:
                val = v.get(f)
                if not val:
                    continue
                # Some fields might be lists (verified_languages) - skip
                if isinstance(val, list):
                    continue
                counters[f][str(val).strip()] += 1
        has_more = data.get("has_more", False)
        print(f"page {page}: {len(voices)} voices "
              f"(total {total_voices}, has_more={has_more})")
        if not has_more:
            break
        time.sleep(0.3)

    # Sort values by frequency so most common show up first in the UI.
    result = {
        "scanned_voices": total_voices,
        "language_filter": args.language,
        "values": {
            f: [{"value": val, "count": n} for val, n in counters[f].most_common()]
            for f in OBSERVED_FIELDS
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print()
    print(f"Wrote {OUT_JSON}")
    print(f"Scanned {total_voices} voices")
    for f in OBSERVED_FIELDS:
        top = counters[f].most_common(8)
        print(f"  {f} ({len(counters[f])} unique): "
              f"{', '.join(f'{v}({n})' for v, n in top)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
