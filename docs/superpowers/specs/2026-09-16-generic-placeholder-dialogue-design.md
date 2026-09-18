# Generic Placeholder Dialogue Translation Design

## Goal

Translate dialogue assembled from arbitrary runtime values without maintaining a finite NPC-specific `dynamic_templates.tsv` registry.

## Current problem

The runtime currently loads a hand-authored registry of dynamic dialogue templates. That registry can only cover sentences that someone has anticipated. `UC_ADDSI` and `UC_ADDSV` already expose the pieces used to build a sentence, but the final lookup path falls back to a finite list when a source string contains runtime values. A sentence supplied as one opaque `ADDSV` has no recoverable variable boundary after composition.

## Design

### 1. Main translation table is the only reviewed template source

Rows in `tools/u6_translation/zh_translation.tsv` remain the source of reviewed translations. Any dialogue row whose normalized source hash corresponds to a provenance-derived template is a generic template. No separate runtime registry or NPC-specific list is loaded.

The existing exact source hash remains the identity for a row. Placeholder names are metadata used for matching and substitution, not a list of known NPCs.

### 2. Generic runtime matcher and fallback

When an exact source lookup misses, the interpreter builds a canonical source template from the provenance tokens that assembled the sentence, then performs the normal source-hash lookup for that template. Matching must:

- support any valid placeholder name and any number of placeholders;
- preserve repeated placeholders and allow translated placeholders to be reordered;
- reject malformed placeholder contracts, ambiguous literal boundaries, and
  marker-count mismatches instead of guessing;
- substitute captured values into the translated row only after validating that every source placeholder has a corresponding translated placeholder.

The source template is hashed exactly like any other catalog source, so no source-text column or runtime wildcard index is required. The catalog parser validates arbitrary placeholder names and positional slots. Runtime must not search the completed English sentence for anchors or apply regular-expression/pattern matching.

If the canonical template has no reviewed row, the interpreter uses the same provenance tokens to translate each static fragment and each dynamic value independently, then concatenates the translated tokens. This fallback is structural, not text-pattern based. The complete canonical source is still recorded as an audit miss so it can receive a reviewed sentence-level translation later.

### 3. Runtime assembly provenance

The usecode interpreter records source fragments as it appends them:

- static `ADDSI` fragments retain their English text and existing translation key;
- dynamic `ADDSV` fragments retain their runtime value and an unkeyed dynamic-fragment marker;
- fragment order is preserved until `SAY` consumes the assembled string.

At `SAY`, a canonical source template is synthesized only when fragment boundaries are known: static text stays literal and each dynamic fragment becomes a positional placeholder (`<VAR0>`, `<VAR1>`, ...). The resulting source is looked up through the same table-native matcher. No NPC name or sentence is embedded in C++. When the row is absent, the token-level fallback translates the fragments and leaves the canonical row visible to audit.

If the interpreter receives a complete sentence as one opaque dynamic value, it performs exact lookup and records the source for audit. It must not invent a boundary or choose a fuzzy translation.

### 4. Extraction and audit

The Python catalog extractor emits runtime-observed canonical templates as ordinary dialogue rows, not into a second registry file. Existing placeholder token parsing is generalized to arbitrary valid names and validates:

- source/translation placeholder multiplicity (with name-aware reordering when
  names match, and positional matching when a translation renames slots);
- `@`, `~`, and `*` marker preservation;
- English-name preservation inside the same marker segment;
- unresolved opaque runtime strings for translator review.

The CLI command that writes `dynamic_templates.tsv` is removed or converted to a compatibility diagnostic; generated deployments no longer require that file.

### 5. Compatibility and failure behavior

An old `u6_dynamic_templates.tsv` may remain in a patch directory but is ignored. Exact translations continue to work unchanged. Invalid or ambiguous template matches return no translation, leave the English text visible, and create an audit record rather than risking a wrong sentence.

## Testing

Tests must cover:

1. an arbitrary placeholder name not present in any hard-coded list;
2. multiple placeholders, reordered translated placeholders, and repeated placeholders;
3. malformed placeholder contracts and ambiguous token sequences failing closed;
4. provenance-derived templates from static/dynamic interpreter fragments;
5. opaque whole-sentence fallback being exact-only and audited;
6. a structurally assembled sentence receiving fragment translation while its missing canonical template remains an audit miss;
7. extraction and audit operating without `dynamic_templates.tsv`;
8. existing dialogue, overhead text, marker, and name-preservation regressions.

## Non-goals

- Guessing semantic boundaries inside an opaque runtime string.
- Applying pattern matching to completed English sentences.
- Changing dialogue choice hitboxes or font metrics; those are separate rendering/input concerns.
