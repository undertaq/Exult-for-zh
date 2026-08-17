"""Ask Claude to suggest voice-search filter values for each NPC, based on
the NPC's name, wiki data, and dialog samples.

Writes one row per NPC to voice_casting_tool/data/wiki_data/voice_suggestions.csv.
Idempotent - skips rows already present unless --force or --only is used.

Constraints on Claude:
- Must pick filter values from the actual ElevenLabs-observed vocabulary
  (voice_filter_values.json), so the suggestions work when pasted into the
  search UI.
- Must respond with strict JSON matching a schema.
- Must provide a confidence level and one-sentence reasoning.
"""

import argparse
import csv
import json
import os
import random
import re
import sys
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("error: anthropic SDK not installed. Run: pip install anthropic",
          file=sys.stderr)
    sys.exit(1)

THIS_DIR = Path(__file__).resolve().parent
TOOL_DIR = THIS_DIR.parent
VOICE_DIR = TOOL_DIR.parent
MANIFEST = VOICE_DIR / "csvs" / "manifest.csv"
DATA_DIR = TOOL_DIR / "data" / "wiki_data"
WIKI_CACHE_DIR = DATA_DIR / "wiki_cache"
FILTER_VALUES_PATH = DATA_DIR / "voice_filter_values.json"
OUT_CSV = DATA_DIR / "voice_suggestions.csv"
ENV_PATH = VOICE_DIR / ".env"

MODEL = "claude-sonnet-4-6"

# City info from the server - same mapping used in the UI, so Claude knows the
# canonical Britannian location for each NPC. (Kept brief; this is a lookup
# table, not a full NPC DB.)
CITY_HINTS = {
    "Party": "a traveling companion of the Avatar",
    "Trinsic": "a knightly, honor-bound port city in the south",
    "Britain": "the grand capital city of Britannia",
    "Paws": "a rural farming village south of Britain",
    "Cove": "a small magical village by Lock Lake",
    "Minoc": "a craftsmen's town in the north, known for sacrifice",
    "Yew": "a woodland town of druids, judges, and justice",
    "Jhelom": "a warrior island of duelists and swordsmen",
    "New Magincia": "a remote farming island recovering from destruction",
    "Skara Brae": "a spectral island, mostly inhabited by ghosts",
    "Moonglow": "the island of mages and learning",
    "Terfin": "an island of gargoyles and winged folk",
    "Serpent's Hold": "the island fortress of the paladins",
    "Vesper": "a multicultural port with human-gargoyle coexistence",
    "Buccaneer's Den": "the pirate-run island of thieves and criminals",
    "Forge of Virtue": "the Isle of Fire, home to tests of the Avatar",
    "Ambrosia": "a far-flung isle with strange creatures",
    "Dagger Isle": "a mysterious fog-shrouded northern isle",
    "Fellowship Retreat": "a secluded Fellowship compound",
    "Dungeon": "a dungeon, likely hostile",
    "Spektran": "a tiny, remote island",
    "Endgame": "the Black Gate / final confrontation",
}


def load_env_key(name: str) -> str:
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get(name, "")


def load_filter_vocab() -> dict:
    data = json.loads(FILTER_VALUES_PATH.read_text(encoding="utf-8"))
    vals = data.get("values", {})
    # Return lists of just the raw value strings for each filter field.
    # Keep only values with count >= 2 to avoid typos/one-offs.
    def clean(key, min_count=2):
        return [e["value"] for e in vals.get(key, []) if e["count"] >= min_count]
    return {
        "gender": clean("gender", 1),
        "age": clean("age", 1),
        "accent": clean("accent", 5),  # keep top accents only
        "descriptive": clean("descriptive", 2),
        "use_case": clean("use_case", 1),
    }


def load_npcs_dialog() -> dict[str, list[str]]:
    """Return {npc_name: [dialog_line, ...]} from the manifest."""
    result: dict[str, list[str]] = {}
    with MANIFEST.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            speaker = (row.get("speaker") or "").strip()
            text = (row.get("text") or "").strip()
            if not speaker or not text:
                continue
            result.setdefault(speaker, []).append(text)
    return result


def load_wiki(npc_name: str) -> dict | None:
    # Filename convention from fetch_wiki_pages.py
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", npc_name) + ".json"
    p = WIKI_CACHE_DIR / safe
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def pick_dialog_samples(lines: list[str], n: int = 10) -> list[str]:
    """Pick up to n distinctive dialog lines - prefer medium-length, diverse,
    de-duplicated."""
    # Dedupe while preserving order
    seen = set()
    uniq: list[str] = []
    for ln in lines:
        key = ln.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(ln)
    if len(uniq) <= n:
        return uniq
    # Prefer medium-length lines (20-200 chars): these usually carry more
    # character than one-word mumbles or giant paragraphs.
    scored = sorted(uniq, key=lambda s: (
        0 if 20 <= len(s) <= 200 else 1,
        -len(s),  # longer first within each bucket
    ))
    return scored[:n]


def build_system_prompt(vocab: dict) -> str:
    return f"""You are helping a voice director cast AI voices for NPCs in Ultima VII: The Black Gate, a 1992 fantasy RPG set in Britannia. For each character, you will recommend ElevenLabs voice-library filter values so the director can find a fitting voice quickly.

## Your task

Given a character's name, wiki entry, city/location, and a handful of their in-game dialog lines, output a JSON object recommending:
- `gender`: one of the allowed values, or "" if unclear/irrelevant.
- `age`: one of the allowed values, or "" if unclear.
- `accent`: one of the allowed values, or "" if unclear. Prefer "british" for most Britannians unless text clearly suggests otherwise; use exotic accents only when dialect/speech patterns strongly hint at them (e.g. pirate -> "british" or broader, scholar -> refined, foreign visitor -> accent matching their culture).
- `descriptives`: 1-3 values from the allowed list that best capture the character's demeanor and personality (e.g. a warrior might be "confident, deep"; a child "cheerful, young"; a suspicious innkeeper "gruff, deep"). Pick the most distinctive ones.
- `use_cases`: 1-2 values from the allowed list. For NPCs, "characters_animation" is almost always primary; pick a secondary only if the character has a clear alternate role (narrator, advertiser, etc.).
- `confidence`: "high" if wiki + dialog clearly point to obvious choices; "medium" if some guesswork; "low" if very little to go on.
- `reasoning`: ONE sentence (max 30 words) summarizing why you picked these.

## Allowed filter values (you MUST pick from these lists; any other value is invalid)

- gender: {vocab['gender']}
- age: {vocab['age']}
- accent: {vocab['accent']}
- descriptive: {vocab['descriptive']}
- use_case: {vocab['use_case']}

## Output format

Respond with ONLY a JSON object, no prose before or after. Schema:

{{
  "gender": "string",
  "age": "string",
  "accent": "string",
  "descriptives": ["string", ...],
  "use_cases": ["string", ...],
  "confidence": "low" | "medium" | "high",
  "reasoning": "one sentence"
}}
"""


def build_user_prompt(npc_name: str, wiki: dict | None, city: str,
                       dialog_samples: list[str]) -> str:
    city_hint = CITY_HINTS.get(city, "")
    parts = [f"# Character: {npc_name}"]
    parts.append(f"\nCity/Location: {city}" + (f" - {city_hint}" if city_hint else ""))
    if wiki:
        if wiki.get("infobox"):
            parts.append("\n## Wiki infobox")
            for k, v in wiki["infobox"].items():
                parts.append(f"- {k}: {v}")
        if wiki.get("summary_text"):
            parts.append(f"\n## Wiki summary\n{wiki['summary_text'][:800]}")
    else:
        parts.append("\n(No wiki entry available for this character.)")
    if dialog_samples:
        parts.append(f"\n## Dialog samples ({len(dialog_samples)} lines)")
        for ln in dialog_samples:
            parts.append(f'- "{ln.strip()[:300]}"')
    else:
        parts.append("\n(No dialog samples available.)")
    parts.append("\nNow output the JSON recommendation.")
    return "\n".join(parts)


def parse_response(text: str) -> dict | None:
    """Extract JSON object from a Claude response, allowing code fences."""
    text = text.strip()
    # Strip ```json fences if present
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def validate(obj: dict, vocab: dict) -> tuple[bool, str]:
    if not isinstance(obj, dict):
        return False, "not an object"
    required = ["gender", "age", "accent", "descriptives", "use_cases",
                "confidence", "reasoning"]
    for k in required:
        if k not in obj:
            return False, f"missing {k}"
    for k in ("gender", "age", "accent"):
        if obj[k] and obj[k] not in vocab[k]:
            return False, f"{k}={obj[k]!r} not in allowed values"
    for v in obj["descriptives"]:
        if v not in vocab["descriptive"]:
            return False, f"descriptive={v!r} not in allowed values"
    for v in obj["use_cases"]:
        if v not in vocab["use_case"]:
            return False, f"use_case={v!r} not in allowed values"
    if obj["confidence"] not in ("low", "medium", "high"):
        return False, f"confidence={obj['confidence']!r}"
    return True, ""


def load_existing_suggestions() -> dict[str, dict]:
    if not OUT_CSV.exists():
        return {}
    result = {}
    with OUT_CSV.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            result[row["npc_name"]] = row
    return result


def write_suggestions(rows: list[dict]) -> None:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["npc_name", "gender", "age", "accent", "descriptives",
                  "use_cases", "confidence", "reasoning"]
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in sorted(rows, key=lambda x: x["npc_name"]):
            w.writerow({k: r.get(k, "") for k in fieldnames})


def fetch_city_map() -> dict[str, str]:
    """Re-parse the CITY_MAP embedded in the Express server - cheap and avoids
    duplication. Falls back to empty dict if the file can't be scanned."""
    server_index = TOOL_DIR / "src" / "server" / "index.ts"
    if not server_index.exists():
        return {}
    text = server_index.read_text(encoding="utf-8")
    m = re.search(r"const CITY_MAP[^{]*\{([\s\S]*?)\n\};", text)
    if not m:
        return {}
    body = m.group(1)
    pairs = re.findall(r'"([^"]+)":\s*"([^"]+)"', body)
    return {k: v for k, v in pairs}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append",
                    help="run only this NPC (repeatable)")
    ap.add_argument("--limit", type=int, default=0,
                    help="process at most N NPCs (0 = all)")
    ap.add_argument("--force", action="store_true",
                    help="re-suggest even if already in the CSV")
    ap.add_argument("--dry-run", action="store_true",
                    help="print prompts/responses without writing CSV")
    args = ap.parse_args()

    key = load_env_key("ANTHROPIC_API_KEY")
    if not key:
        print("error: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1

    vocab = load_filter_vocab()
    dialog_map = load_npcs_dialog()
    city_map = fetch_city_map()

    targets = sorted(dialog_map.keys())
    if args.only:
        targets = [n for n in targets if n in args.only]
    existing = load_existing_suggestions()
    if not args.force:
        targets = [n for n in targets if n not in existing]
    if args.limit:
        targets = targets[:args.limit]

    if not targets:
        print("no NPCs to process (already done?)")
        return 0

    client = anthropic.Anthropic(api_key=key)
    system_prompt = build_system_prompt(vocab)

    results = list(existing.values())
    errors = []

    print(f"Processing {len(targets)} NPCs with {MODEL}...")
    for i, name in enumerate(targets, 1):
        city = city_map.get(name, "Unknown")
        wiki = load_wiki(name)
        dialog = pick_dialog_samples(dialog_map.get(name, []), n=10)
        user_prompt = build_user_prompt(name, wiki, city, dialog)

        if args.dry_run:
            print(f"\n{'='*70}\n[{i}/{len(targets)}] {name} ({city})\n{'='*70}")
            print("---- USER PROMPT ----")
            print(user_prompt[:1500])

        # Up to 2 attempts: initial, then a correction round if validation
        # catches an invalid value (model hallucinates plausible-sounding
        # descriptors that aren't in the ElevenLabs vocab).
        messages: list[dict] = [{"role": "user", "content": user_prompt}]
        parsed = None
        last_err = ""
        for attempt in range(2):
            try:
                resp = client.messages.create(
                    model=MODEL,
                    max_tokens=600,
                    system=[{
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }],
                    messages=messages,
                )
            except Exception as e:
                print(f"  {name}: API error {e}")
                last_err = str(e)
                parsed = None
                break
            text = resp.content[0].text if resp.content else ""
            candidate = parse_response(text)
            if not candidate:
                last_err = "parse failure"
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content":
                    "That was not valid JSON. Output ONLY the JSON object."})
                continue
            ok, err = validate(candidate, vocab)
            if ok:
                parsed = candidate
                break
            last_err = err
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content":
                f"Validation failed: {err}. You MUST pick values only from "
                f"the allowed lists given earlier. Try again."})
        if not parsed:
            print(f"  {name}: giving up -> {last_err}")
            errors.append((name, last_err))
            continue

        row = {
            "npc_name": name,
            "gender": parsed["gender"],
            "age": parsed["age"],
            "accent": parsed["accent"],
            "descriptives": "|".join(parsed["descriptives"]),
            "use_cases": "|".join(parsed["use_cases"]),
            "confidence": parsed["confidence"],
            "reasoning": parsed["reasoning"],
        }
        results = [r for r in results if r["npc_name"] != name]
        results.append(row)

        tag = f"[{parsed['confidence']}]"
        desc = " / ".join(parsed["descriptives"]) or "-"
        print(f"[{i}/{len(targets)}] {name} {tag}: "
              f"{parsed['gender'] or '-'}, {parsed['age'] or '-'}, "
              f"{parsed['accent'] or '-'}, {desc}")
        if args.dry_run:
            print("  reasoning:", parsed["reasoning"])

    if not args.dry_run:
        write_suggestions(results)
        print(f"\nWrote {OUT_CSV}")
    print(f"Processed {len(targets)} NPCs, {len(errors)} errors")
    if errors:
        for n, e in errors[:10]:
            print(f"  ERROR {n}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
