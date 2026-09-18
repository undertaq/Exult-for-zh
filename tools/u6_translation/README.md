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

The runtime capture is enabled by `config/debug/translation/catalog_capture` and writes the source catalog to the path configured by `config/debug/translation/catalog_path`. It also writes `u6_runtime_speakers.tsv` by default; configure `config/debug/translation/speaker_path` to choose another relative `GAMEDAT` path. The speaker sidecar is populated by the running U6 actor/face context, so it does not depend on voice playback being enabled. Capture rows retain the original English source, including choice answers and overhead/bark text; delayed `item_say` values are captured before the final display translation, so Chinese output is never mistaken for source English. If a dynamic U6 helper or overhead text reuses one callsite for different strings, extraction rewrites only those colliding rows to source-stable keys derived from their SHA-256 source hash before emission. Runtime translation still matches the complete English source, so generated questions and observed barks remain translatable even when their usecode offsets collide.

The speaker sidecar uses this format:

```text
# u6-runtime-speakers-v1
# kind\tkey\tspeaker_id\tspeaker
dialogue\tdialogue:0x0401:1a_2f:0\t17\tIolo
```

Static usecode disassembly is not used as the authoritative U6 speaker source. Dialogue that was not visited while capture was enabled remains explicitly unresolved until runtime coverage is collected.

## Extract

The reviewed extraction command combines static U6 resources with the fixture/runtime capture. It writes only the temporary catalog:

```sh
python3 -m tools.u6_translation extract \
  --mod-root "$MOD_ROOT" --ucxt "$UCXT" \
  --runtime-catalog tools/u6_translation/tests/fixtures/runtime_catalog.tsv \
  --output /tmp/u6_catalog.jsonl
```

Extraction reads `tools/u6_translation/u6_english_terms.tsv` by default for
source-global protected runtime terms; pass `--terms /path/to/terms.tsv` when
auditing another inventory.

For a complete static catalog when no runtime capture is available, add
`--include-static`; this includes the UCXT dialogue plus indexed item,
location, miscellaneous, and text-message resources. Known U6 book and scroll
handlers are marked with `context=book`. Whenever the compiled usecode is
available (including the dialogue-only command), the extractor also
disassembles it and adds source-stable `static-usecode-template` rows for
contiguous `PUSHS`/`ADD`/`ADDSV` expressions that contain literal anchors on
both sides of a runtime value. These rows use positional placeholders
(`<VAR0>`, `<VAR1>`, ...) and a hash of the complete template, so every NPC
with the same failure cause enters the catalog without a hard-coded sentence
list. They are reviewed like any other dialogue row. At runtime, provenance
tokens from `addsi`, `pushs`, `addsv`, `add`, locals, and function arguments
form the same canonical template without searching the completed English
sentence. Every value appended by `ADDSV` is a dynamic slot at that boundary,
even when a helper returned it with literal provenance. Intrinsic `item_say`
overhead strings retain the same VM fragment provenance, so assembled barks use
the structural translator too. An exact template row wins; if it is absent, the runtime translates
the recorded fragments independently and the audit still reports the missing
canonical row. No NPC-specific template list is needed:

```sh
python3 -m tools.u6_translation extract \
  --mod-root "$MOD_ROOT" --ucxt "$UCXT" --include-static \
  --output /tmp/u6_catalog.jsonl
```

The U6 mod's book handler delegates unmodified books and scrolls to the base
BG `STATIC/USECODE` functions. The same base file also supplies schedule-driven
`item_say` overhead helpers (for example Blaine's bark function). Include that
fallback source in the audit catalog with `--fallback-usecode`; extraction
follows the compiled `item_say` intrinsic calls and does not maintain a list
of NPC names or sentences:

```sh
python3 -m tools.u6_translation extract \
  --mod-root "$MOD_ROOT" --ucxt "$UCXT" --include-static \
  --fallback-usecode "$PWD/../Ultima_7/STATIC/USECODE" \
  --output /tmp/u6_catalog_with_fallback_books_and_barks.jsonl
```

The corresponding Chinese base-usecode strings can be imported into the
runtime table. The importer pairs the English and Chinese fallback functions
by their `addsi` reference order, because UTF-8 changes their data offsets,
and preserves the original `~` page separators for runtime display:

```sh
python3 -m tools.u6_translation import-fallback-books \
  --english-usecode "$PWD/../Ultima_7/STATIC/USECODE" \
  --chinese-usecode "$PWD/../Ultima_7/patch/usecode.zh" \
  --ucxt "$UCXT" --table tools/u6_translation/zh_translation.tsv
```

The fixture includes a choice row such as `choice:0x0401:0x0088:0` with English source `one`. Choices are translated only for display. The English `answers` remain unchanged internally for usecode comparison, choice indexing, and game logic; no translated answer is written into usecode or configuration.

## Translate and audit

Placeholder names are generic (`<VAR0>`, `<PLAYER_NAME>`, `<NPC_NAME>`, etc.)
and are validated by the shared parser. The C++ runtime validates literal
anchors and matches placeholder slots by name when names are preserved (allowing
reordering), or by position when a reviewed translation renames them. Thus a
reviewed translation may use a semantic name even when usecode emitted `<VAR0>`.
Values are translated by source when available and preserved (such as player
names) when no value row exists. Ambiguous literal boundaries are rejected
rather than guessed. A complete opaque `ADDSV` sentence is intentionally
exact-only; it is captured for audit rather than guessed.

The glossary can mark source-global values returned by inherited usecode helpers
with `runtime_term`. Extraction emits those values as auditable
`dialogue:0x0000:runtime:<ordinal>` rows, so values such as `milord` and
`milady` translate even when no NPC-specific UCXT callsite exists. Greeting
time values use their literal provenance: `Good morning`, `Good afternoon`, and
`Good evening` render as `早安`, `午安`, and `晚安`, while noun phrases such as
`this fine afternoon` retain the ordinary time-of-day translation. The audit
checks these Taiwan wording rules and accepts the marker-only structural rows
that supply the runtime value.

`u6_english_terms.tsv` is the shared English-only inventory for people,
locations, proper entities, and professional terms. It includes the legacy
`u6_names.tsv` rows and declares terms such as `wisp` and `wisps` with
`runtime_term+protected`; adding a row there is enough for extraction, model
guidance, and audit enforcement. The audit matches professional terms as whole
words, so singular and plural forms cannot satisfy one another accidentally,
and checks every catalog kind—including dialogue, choices, book pages, items,
and runtime-captured overhead text. The same runtime rows make dynamic values
source-global, while sentence rows preserve the exact English term wherever it
appears. The old `--names` option remains accepted for compatibility, but new
invocations should pass the shared manifest with `--terms`.

Translation uses the local Ollama endpoint and model above. Candidates and cache are review artifacts, not release output:

```sh
python3 -m tools.u6_translation translate \
  --catalog /tmp/u6_catalog.jsonl --output /tmp/u6_candidates.tsv \
  --cache /tmp/u6_translation_cache.json \
  --url "$OLLAMA_URL" --model "$OLLAMA_MODEL" --batch-size 8
```

Translation requests default to eight rows because the local 27B model can
need tens of seconds per row. The cache is checkpointed after each batch, so
the same command safely resumes after an interrupted request.
For larger local timeouts, use `--timeout`; `--retries` controls retries per
batch.
If a singleton response is still unusable, that source is retained with
`status=model-failed` and flagged for human correction instead of aborting the
full run; a later run retries it from the cache.

Before release, run the combined audit in strict mode. A nonzero exit status blocks emission and requires correction and rerun:

```sh
python3 -m tools.u6_translation audit all \
  --catalog /tmp/u6_catalog.jsonl --table /tmp/u6_candidates.tsv \
  --glossary tools/u6_translation/u6_glossary.tsv \
  --names tools/u6_translation/u6_names.tsv \
  --terms tools/u6_translation/u6_english_terms.tsv \
  --report /tmp/u6_audit.json --strict
```

The English-only inventory is also a release gate. Its included legacy rows list
NPC, place, town, and location names that must remain in their exact English
spelling; the `proper` category covers other named entities such as ships,
shops, factions, and named diseases that also need to stay English.
For a standalone name row, the whole display value must be English; for a
sentence, the named span must remain English while the surrounding sentence may
be translated. Add a row to this inventory when a new U6 name is discovered.

Generate the offline review page after translation. It is self-contained and
works from a local `file://` URL: edit the Traditional Chinese textareas,
leave rows accepted by default, check `Needs modification` where needed, and
download the review JSONL when finished. The page also saves a draft in the
browser's local storage. Results are paginated at 50 matching entries per page;
dialogue rows show the attributed speaker when a speaker map is supplied, and
otherwise show the unresolved usecode function ID. Pass the audit report to
show row-level findings in the page:

```sh
python3 -m tools.u6_translation review-html \
  --catalog /tmp/u6_catalog.jsonl --table /tmp/u6_candidates.tsv \
  --audit /tmp/u6_audit.json --model "$OLLAMA_MODEL" \
  --speaker-capture /path/to/u6_runtime_speakers.tsv \
  --output reports/u6_translation_review_qwen3.8_27b.html
```

The optional `--speaker-capture` is the preferred U6 attribution source. A runtime
name overrides a static map entry; conflicting runtime names are shown as
`Ambiguous · name1 / name2`. Numeric-only observations remain labeled
`Unresolved · NPC <id>`. The legacy `--speaker-map` is still accepted as a
fallback JSON object keyed by `dialogue<TAB><dialogue-key>`
(or by the dialogue key alone), for example
`{"dialogue\\tdialogue:0x0401:10:0":"Iolo"}`. It may also be wrapped as
`{"speakers": {...}}`.

The translator canonicalizes exact repeated English source strings across
dialogue and gameplay rows. The correctness audit also reports any conflicting
translations as blocking `term_consistency` issues. Translated glossary terms
are checked against `u6_glossary.tsv`; English-only names, locations, and
professional terms are checked from `u6_english_terms.tsv` across every text
kind for consistent source spelling.

Strict audit is a release gate: missing, stale, duplicate, orphan, unbound, untranslated, English-name, protected-term, Traditional-Chinese-policy, placeholder, item quantity-format, source-integrity, `dialogue_speech_markers`, or `ascii_dot_runs` failures require fixing. ASCII dot runs (`..`, `...`, and longer contiguous runs) are punctuation data: they must remain identical in the Chinese translation rather than becoming full-width `。` or Unicode ellipses. Compiled static-template rows must also retain the source `@` speech-boundary count; the runtime converts complete `@...@` spans to `"..."` in English mode and `「...」` in Chinese mode only on the final display copy. UCXT fragments may contain one side of that pair (`@Good ` or `.@`); when a fragment translation omits its edge marker, the audit reports a non-blocking `fragment_speech_boundary` advisory and the runtime restores the marker from VM provenance during assembly. The report includes separate `book_contents`, `placeholder_templates`, `assembled_templates`, and `fragment_speech_boundaries` coverage sections so book/scroll text, runtime-only templates, statically recoverable assembled greetings, and provenance-restored speech edges cannot be hidden by aggregate dialogue coverage. `assembled_templates` is populated directly from compiled usecode, while `placeholder_templates.unobserved` continues to flag source-stable `fallback_<hash>` rows that are present only in a runtime table; rerun extraction with a runtime capture after exercising those opaque paths so their inferred template and placeholder multiplicity can be audited. Item translations must retain the source slash structure used for singular/plural formatting (for example `/gold nugget//s`), and every placeholder template must retain its token multiplicity. A human must inspect the candidate table and audit report and explicitly approve every row before emission. Automated or Ollama review is advisory and does not constitute approval.
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
