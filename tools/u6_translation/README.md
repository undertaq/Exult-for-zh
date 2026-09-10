# U6 runtime Traditional Chinese translation

Task 8 provides the deterministic catalog, cache/resume translation, correctness and coverage audits, and approved-table emitter. Run these commands from the repository root with Python 3:

```sh
MOD_ROOT="$PWD/../Ultima_7/mods/Ultima6v1.3"
PATCH_DIR="$MOD_ROOT/Ultima6v1.3/patch"
UCXT="$PWD/tools/ucxt/ucxt"
OLLAMA_URL="http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL="qwen3:8b"
```

The runtime capture is enabled by `config/debug/translation/catalog_capture` and writes to the path configured by `config/debug/translation/catalog_path`. Capture rows use the runtime catalog format and retain the original English source, including choice answers.

## Extract

The reviewed extraction command combines static U6 resources with the fixture/runtime capture. It writes only the temporary catalog:

```sh
python3 -m tools.u6_translation extract \
  --mod-root "$MOD_ROOT" --ucxt "$UCXT" \
  --runtime-catalog tools/u6_translation/tests/fixtures/runtime_catalog.tsv \
  --output /tmp/u6_catalog.jsonl
```

The fixture includes a choice row such as `choice:0x0401:0x0088:0` with English source `one`. Choices are translated only for display. The English `answers` remain unchanged internally for usecode comparison, choice indexing, and game logic; no translated answer is written into usecode or configuration.

## Translate and audit

Translation uses the local Ollama endpoint and model above. Candidates and cache are review artifacts, not release output:

```sh
python3 -m tools.u6_translation translate \
  --catalog /tmp/u6_catalog.jsonl --output /tmp/u6_candidates.tsv \
  --cache /tmp/u6_translation_cache.json \
  --url "$OLLAMA_URL" --model "$OLLAMA_MODEL"
```

Before release, run the combined audit in strict mode. A nonzero exit status blocks emission and requires correction and rerun:

```sh
python3 -m tools.u6_translation audit all \
  --catalog /tmp/u6_catalog.jsonl --table /tmp/u6_candidates.tsv \
  --glossary tools/u6_translation/u6_glossary.tsv \
  --report /tmp/u6_audit.json --strict
```

Strict audit is a release gate: missing, stale, duplicate, orphan, unbound, untranslated, protected-term, Traditional-Chinese-policy, placeholder, or source-integrity failures require fixing. A human must inspect the candidate table and audit report and explicitly approve every row before emission. Automated or Ollama review is advisory and does not constitute approval.

## Emit the approved table

After strict audit succeeds and human approval is recorded in the review JSONL, emit directly to the actual patch directory:

```sh
python3 -m tools.u6_translation emit \
  --catalog /tmp/u6_catalog.jsonl --review /tmp/u6_review.jsonl \
  --output "$PATCH_DIR/zh_translation.tsv"
```

`zh_translation.tsv` is external generated output and must be reviewed before it is copied into the mod directory. Do not commit the `/tmp` catalog, candidates, cache, audit, or review artifacts. Do not modify the existing `Ultima6v1.3.cfg`, add an alternate usecode file, or change any C++/runtime implementation module. The only runtime behavior covered here is display-time translation while English answers and game logic remain authoritative.
