# Ultima 6 Runtime Traditional Chinese Translation Design

## Goal

Add a Traditional Chinese language mode to the `Ultima6v1.3` Exult mod without creating, loading, or switching to a second usecode file. When the player selects Chinese, the English usecode remains authoritative and gameplay text is translated at display time from a reviewed mapping table.

The system covers Ultima 6 gameplay text only:

- NPC dialogue and dialogue segments.
- Conversation choice options.
- Gameplay barks and text-message resources.
- Item, location, and spell names shown during gameplay.

Exult menus, configuration screens, Exult Studio/editor views, and other engine UI remain outside the translation scope.

## Non-goals

- Generating or modifying `usecode.zh`.
- Translating arbitrary engine strings globally.
- Translating text through a network service while the game runs.
- Replacing the English strings used for game logic, comparisons, saves, or branching.
- Automatically accepting model-generated translations without review.

## Existing constraints and integration points

The repository already has `BilingualManager`, language selection through the existing `config/audio/text/language` setting, Chinese font/layout support, alternate-usecode loading, and voice/conversation code. The new feature must preserve those behaviors for mods that already provide alternate usecode files.

The active mod's `<PATCH>` path is established by the normal `BaseGameInfo`/`ModInfo` path setup. The translation table is therefore loaded from:

```text
<PATCH>/zh_translation.tsv
```

The current `Ultima6v1.3` mod supplies English usecode and `textmsg.txt`, but no Chinese usecode. In this table-only mode, switching to Chinese must leave the English usecode machine active. Existing alternate-usecode behavior remains available for other mods and for mods that explicitly ship `usecode.zh`.

## Architecture

Add a source-aware `GameplayTranslationManager` separate from the language-indexed text arrays and separate from `BilingualManager`'s alternate-usecode selection.

The manager owns:

- Loading and validating `<PATCH>/zh_translation.tsv`.
- Lookup by stable gameplay key and English source hash.
- Language-mode enablement for table-only Chinese display.
- Diagnostic counters for hits, misses, stale rows, malformed rows, and fallbacks.
- Optional catalog capture used by the offline extraction pipeline.

Gameplay display call sites ask the manager for a translated display copy. They do not mutate the English source or the data used by game logic.

The runtime flow is:

```text
active mod <PATCH>
        |
        v
zh_translation.tsv --> GameplayTranslationManager <-- existing language setting
        |
        +--> dialogue display
        +--> choice display copies
        +--> gameplay barks/text messages
        +--> item/location/spell display names
```

For a table-only U6 mode, `BilingualManager::get_usecode(CHINESE)` and usecode reload paths must resolve to the English machine when no `usecode.zh` exists. A missing alternate usecode must never install a null machine or change the execution language of the game.

## Runtime translation behavior

### Dialogue

`Usecode_internal::say_string()` already has the useful conversation identity: function id, voice/string trace information, and segment ordinal. The runtime key is:

```text
dialogue:<function-id>:<offset-key>:<segment>
```

The English source hash is calculated from the raw English segment before dynamic token substitution. At display time:

1. Obtain the raw English segment.
2. Look up the key and verify its source hash.
3. Use the Chinese value when the row is valid; otherwise use English.
4. Resolve player-name, honorific, pronoun, gender, and variable tokens using the existing conversation logic.
5. Render with the existing Chinese-capable font and layout path.

The manager must not translate or alter the string used for voice matching, script state, or conversation logic.

### Conversation choice options

Choice options are first-class translation entries. `Conversation::answers` continues to hold the original English answer strings. When choices are rendered, the conversation creates a temporary translated display vector using:

```text
choice:<function-id>:<callsite-offset>:<ordinal>
```

The displayed Chinese string is selected by key and source hash, but selection still returns the original ordinal/English answer to usecode. This preserves all existing answer comparisons and branches, including answers that contain text not suitable for display.

Choice translation therefore has these guarantees:

- Every option can be translated independently.
- A missing or stale row shows the original English option.
- Choice order and selection behavior do not change.
- The translated copy is discarded after rendering.
- Exult menu choices are not routed through this manager.

### Gameplay text messages and names

Indexed gameplay strings are translated only at gameplay display boundaries. The key kinds are:

```text
textmsg:<message-id>
item:<item-id-and-variant>
location:<location-id>
misc:<name-id>
spell:<spell-id>
```

The exact identity components are emitted by the catalog extractor, so variants such as plural, quantity, quality, or gender cannot collide. `get_text_msg()`, `get_item_name()`, and `get_misc_name()` must not be globally changed to return Chinese because those lookups also feed menus, editor code, internal comparisons, and other non-gameplay consumers. Instead, gameplay display paths request translated copies after the English value has been selected.

Gameplay barks that originate from a text-message resource use the `textmsg` key at the bark display boundary. The English text-message array remains unchanged.

### Language and fallback rules

- English mode always displays English.
- Chinese mode uses the runtime table only when the active mod supplies a valid `zh_translation.tsv` and no alternate Chinese usecode is active.
- A mod with an existing `usecode.zh` keeps its legacy alternate-usecode behavior; the table-only U6 path does not create or require that file.
- Missing table, missing row, malformed row, invalid UTF-8, invalid key, or source-hash mismatch falls back to English.
- Every fallback is counted and can be logged in diagnostic mode.
- Changing the language marks affected gameplay windows dirty so visible text is repainted immediately.

## Runtime table contract

`zh_translation.tsv` is a dependency-free UTF-8 tab-separated file with this header:

```text
# u6-translation-v1
# kind\tkey\tsource_sha256\tzh
```

Each data row contains exactly four escaped fields:

```text
dialogue\tdialogue:0x0401:1a_2f:0\t<64 lowercase hex chars>\t<Traditional Chinese>
choice\tchoice:0x0401:0x0088:0\t<64 lowercase hex chars>\t<Traditional Chinese>
textmsg\ttextmsg:0x0123\t<64 lowercase hex chars>\t<Traditional Chinese>
item\titem:0x01f4\t<64 lowercase hex chars>\t<Traditional Chinese>
location\tlocation:0x002a\t<64 lowercase hex chars>\t<Traditional Chinese>
misc\tmisc:0x0042\t<64 lowercase hex chars>\t<Traditional Chinese>
spell\tspell:0x12\t<64 lowercase hex chars>\t<Traditional Chinese>
```

Field escaping is deterministic: backslash, tab, newline, and carriage return are encoded as `\\`, `\\t`, `\\n`, and `\\r`. The parser rejects unknown escape sequences, wrong field counts, invalid hashes, duplicate keys, and rows with empty Chinese text.

`source_sha256` is SHA-256 over the normalized raw English source used to create the catalog row. Normalization is limited to the documented UTF-8/newline normalization; game-specific markup and placeholders are preserved before hashing. A translation is valid only when both its key and source hash match the runtime source.

The emitter sorts rows by kind and key, rejects duplicate keys, and writes a stable file. This makes diffs reviewable and prevents a translation generated for an older usecode/text resource from silently being used.

## Offline extraction and translation pipeline

The pipeline lives under `tools/u6_translation/` and never runs a model from the game process.

```text
extract --> catalog.jsonl --> translate/cache --> convert-traditional --> audit --> human review --> emit
```

The `convert-traditional` stage checks the candidate/runtime TSV against the
same unambiguous Simplified-character inventory used by correctness auditing.
It applies the checked-in OpenCC-s2t-derived character map, preserves
placeholders, English-only names, protected terms, hashes, and punctuation,
and writes atomically. `--check` is the non-mutating release gate; the emitter
repeats the conversion before its final deterministic audit as a safety net.

### Extraction

- Use `ucxt -ftt` and existing usecode parsing capabilities to seed statically discoverable strings.
- Parse the active mod's `textmsg.txt` and other indexed gameplay resources.
- Provide a runtime catalog-capture mode for composite identities that static analysis cannot determine exactly, especially dialogue segments and choice call sites.
- Capture the original English source, stable key, source hash, kind, origin, context, and protected-token inventory.
- Keep separate scope tags so Exult menu/editor strings cannot enter the gameplay catalog accidentally.

### Translation

Use a local Ollama HTTP backend, configurable by URL and model. The default should work with the locally available Qwen installation, while allowing a larger Qwen model for final quality passes. The game has no Ollama dependency.

Each model request includes:

- Stable key and text kind.
- English source and nearby context.
- Ultima 6 terminology glossary.
- Traditional Chinese requirement.
- Instructions to preserve all protected markers and placeholders exactly.
- Instructions to keep spell incantations and other explicitly protected terms unchanged.

The cache key includes source hash, model name, prompt version, and glossary version. The pipeline supports retries, resume, and deterministic JSONL cache records. Model output is a candidate until approved.

### Audit and review

The pipeline includes one CLI with focused subcommands:

```text
python -m tools.u6_translation.audit coverage ...
python -m tools.u6_translation.audit correctness ...
python -m tools.u6_translation.audit all ...
```

Coverage reports include:

- Total catalog rows by kind.
- Approved translations by kind.
- Missing, stale-hash, duplicate, and orphan rows.
- Entry coverage and character-weighted coverage.
- Separate counts for dialogue segments and every conversation choice option.
- Runtime-observed entries that are absent from the static catalog.

Correctness reports include deterministic checks for:

- UTF-8, TSV escaping, field count, key syntax, and hash validity.
- Required control markers, placeholders, newline structure, and segment structure.
- Empty output, accidental source duplication, and malformed model responses.
- Traditional-Chinese policy violations using the configured checker.
- Glossary and protected-term consistency.

An optional Ollama review pass compares English meaning and Chinese meaning and records a cached `pass`, `warning`, `fail`, or `needs-human-review` result with a suggested correction. It never edits the approved table. Automated checks are authoritative for structural safety; semantic review remains reviewable rather than silently accepted.

Audit output is available as a human-readable terminal summary and machine-readable JSON. Normal development mode reports missing translations without blocking exploration. Strict release mode exits non-zero for missing/stale rows, structural correctness failures, or explicitly configured semantic-review failures.

## Error handling and observability

The runtime must fail open to English. It must not abort gameplay because a translation row is missing or malformed.

Diagnostic logging identifies the kind, key, and failure reason without logging player-sensitive state. Counters expose table load status, row count, translation hits, misses, stale hashes, and fallbacks. A developer diagnostic mode can emit runtime catalog records for newly encountered keys.

The offline tools fail closed for emission: `emit` refuses to create a release table when structural audit failures remain. It preserves the source catalog and model cache so a failed run can resume without re-translating successful entries.

## Testing and acceptance criteria

### Runtime tests

- Parse valid rows and reject malformed escapes, hashes, duplicate keys, and invalid UTF-8.
- Verify source-hash matching and English fallback for missing/stale rows.
- Verify dialogue keys and segment ordinals remain stable.
- Verify translated choice options render while original English answers remain unchanged and still drive usecode branching.
- Verify missing choice translations fall back individually rather than disabling other options.
- Verify text-message, item, location, and spell display paths translate only in gameplay.
- Verify Exult menus, configuration, editor paths, and internal English comparisons remain unchanged.
- Verify U6 table-only mode never installs or reloads a null/alternate Chinese usecode machine.
- Verify language switching repaints visible gameplay text and save/load behavior remains unchanged.

### Offline-tool tests

- Extract representative dialogue, choices, text messages, and names into deterministic catalog JSONL.
- Detect missing, stale, duplicate, and orphan rows with correct per-kind and weighted coverage.
- Detect loss of markers/placeholders, simplified-Chinese policy violations, and glossary conflicts.
- Mock Ollama responses to test retries, cache hits, malformed responses, resume behavior, and prompt-version invalidation without requiring a running model.
- Verify deterministic row ordering and stable TSV escaping.
- Verify strict mode returns a failure status and non-strict mode produces a reviewable report.

### Manual smoke test

Launch `Ultima6v1.3` with no `usecode.zh`, switch between English and Chinese, speak with an NPC, view multiple choice options, trigger a bark, inspect item/location names, and open Exult menus. Chinese gameplay text must appear without changing game behavior; English fallback must work after removing or corrupting a table row.

## Compatibility and rollout

The first release adds the manager and tooling without requiring a translation table. Existing mods continue to behave as before. The U6 mod gains `zh_translation.tsv` only after the catalog has passed strict audit and human review.

No alternate usecode is committed for the U6 Chinese mode. The only shipped translation artifact is the reviewed runtime mapping table plus the offline tooling and its tests.
