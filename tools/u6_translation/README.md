# U6 runtime Traditional Chinese translation

Task 8 provides the deterministic catalog, cache/resume translation, correctness and coverage audits, and approved-table emitter. Run these commands from the repository root with Python 3:

```sh
MOD_ROOT="$PWD/../Ultima_7/mods/Ultima6v1.3"
PATCH_DIR="$MOD_ROOT/Ultima6v1.3/patch"
UCXT="$PWD/tools/ucxt/src/ucxt"
OLLAMA_URL="http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL="qwen3.8:27b"
```

Build the extractor prerequisite first with `make -C tools/ucxt/src`. The extractor
passes the supplied mod's compiled `patch/usecode` file to UCXT with `-i` and `-a`,
and stages the bundled UCXT data files in a temporary config directory. This is
required because the compiled UCXT binary otherwise treats the mod root as a
hexadecimal function argument and cannot find its opcode table. The U6 mod also does
not ship the optional `patch/spellnames.txt` display resource, so spell catalog rows
appear only when that English-format resource exists.
The deterministic indexed fixture under `tools/u6_translation/tests/fixtures/indexed_mod`
is the supported extraction test input.

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
Semantic review remains advisory by default and cannot change deterministic findings,
candidate selection, or exit status. Pass `--semantic-strict` only for an explicitly
requested review gate.

## Emit the approved table

After strict audit succeeds and human approval is recorded in the review JSONL, emit directly to the actual patch directory:

```sh
python3 -m tools.u6_translation emit \
  --catalog /tmp/u6_catalog.jsonl --review /tmp/u6_review.jsonl \
  --output "$PATCH_DIR/zh_translation.tsv"
```

`zh_translation.tsv` is external generated output and must be reviewed before it is copied into the mod directory. Do not commit the `/tmp` catalog, candidates, cache, audit, or review artifacts. Do not modify the existing `Ultima6v1.3.cfg` or add an alternate usecode file. Runtime behavior is display-time translation while English answers and game logic remain authoritative. Spell names follow the same rule: the English name is captured from `spellnames.txt` and translated only at Spellbook paint time.
