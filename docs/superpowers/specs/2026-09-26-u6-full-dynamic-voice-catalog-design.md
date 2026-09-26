# U6 Full Dynamic-Voice Catalog Design

## Goal

Complete the Ultima VI dynamic-dialogue voice catalog so every supported
runtime-composed dialogue template has reviewed English and Traditional
Chinese audio, routed to the correct speaker or narrator identity. Preserve
the actual runtime text shown to the player while speaking a reviewed,
generic, context-appropriate version of dynamic values.

This extends the U6 runtime-aware composite playback design. U6 continues to
use its shared runtime usecode identity and table-driven Traditional Chinese
translation flow; it does not adopt U7's separate bilingual usecode-map
architecture.

## Scope and current baseline

The current dynamic voice template manifest contains 491 entries. The full
route count is not treated as a fixed number: it must be recomputed from the
canonical templates after speaker identities, role spans, language variants,
and any gender-dependent wording are resolved. The initial estimated route
count is a planning figure, not a completion target.

In scope:

- Every dynamic dialogue template discovered through U6 usecode provenance,
  including templates already in the manifest and newly discovered templates
  found during coverage analysis.
- English and Traditional Chinese canonical spoken transcripts and generated
  audio for every required speaker/role route.
- Correct speaker, narrator, cross-talk, and Avatar-gender resolution.
- Review artifacts, validation, packaging, and game integration after audio
  approval.

Out of scope:

- Rewriting unrelated static U6 translations or static dialogue audio.
- Changing U6's bilingual runtime architecture to match U7.
- Runtime TTS, save-specific audio generation, or speaking raw dynamic values.
- Changing displayed dialogue, conversation timing, or usecode behavior beyond
  what is strictly required to identify and play the complete dynamic line.

## Design

### 1. Discover the complete dynamic catalog

Use the compiled-usecode provenance and the existing dynamic-template
extraction pipeline as the source of truth. Enumerate every dynamic dialogue
template and its ordered fragments, slots, page/click boundaries, and
speaker/narrator role spans. Compare this inventory with the canonical
manifest and the audio/translation manifests to report missing, duplicate,
stale, and orphaned entries.

Do not define completeness as “all current manifest rows generated.” Newly
discovered usecode templates must either be added to the canonical manifest
or be explicitly classified as non-spoken/control-only with evidence. The
coverage report must make every exclusion visible.

Keep U6's shared source identity between English and Traditional Chinese.
Language selects the transcript/audio variant; it does not select a different
usecode identity. Preserve runtime composite ordering and the `~` page and
`*` click-only boundaries. Neither control marker is spoken.

### 2. Audit translations and canonical spoken text

Review every dynamic template's English and Traditional Chinese text, not just
the two known day-period examples. For each row:

- Validate that source and translation have the same placeholder count and
  identity, including repeated/reordered placeholders where supported.
- Validate marker and role-span boundaries, punctuation, and proper-name
  preservation.
- Confirm the Traditional Chinese is grammatical and does not duplicate a
  word or mistranslate a phrase because of a placeholder boundary.
- Check that the canonical spoken transcript is a complete, natural line and
  includes a reasonable generic replacement for every dynamic slot.
- Keep visible runtime values unchanged; do not put save-specific names or
  arbitrary values into generated speech.

Automated checks should flag structural problems and suspicious translation
patterns. Human review decides wording; do not blindly auto-rewrite catalog
translations. Fix approved wording in the authoritative translation/override
source, then rebuild the derived manifest and review data. Breeze TTS 2 receives
Traditional Chinese input for the Chinese voice, matching the established U6
voice-generation preference.

### 3. Resolve speaker and reference identity from evidence

Resolve each speaking route from compiled-usecode actor/function provenance
and reviewed role-marker metadata. Do not infer a speaker from the current
face, the last name mentioned, or a runtime log alone. Compare the generated
speaker/role spans back to usecode cross-conversion so a referenced NPC does
not accidentally inherit the current NPC's voice, and vice versa.

Apply the following reference policy:

- If a U6 NPC has the same identity as an NPC with an approved U7 reference,
  reuse that U7 reference clip, following the established `voice/refs`
  convention.
- Otherwise reuse an approved U6 reference when it exists.
- For a real speaking character with no suitable reference, generate a
  character-specific Breeze voice-design reference from a reviewed
  description. Use NPC descriptions and portraits as supporting evidence;
  do not use a guessed gender or a non-speaking actor alias as a voice design.
- Map usecode actor IDs and aliases to a canonical voice identity only when
  usecode evidence supports that mapping. If a route cannot be resolved, stop
  preflight and report it rather than using a narrator or unrelated NPC as a
  fallback.
- When narrator speech is explicitly assigned to a line, use the narrator
  voice matching the speaking character's gender. NPC-owned dialogue uses the
  NPC voice; cross-talk uses the identity of the character whose words are
  being spoken.
- Keep separate male and female Avatar voice variants and select the correct
  one at runtime from the active Avatar gender.

Before rendering, produce a route-resolution report containing the usecode
identity, canonical character, voice role, gender variant, reference source,
and confidence/evidence for every route. Missing references or ambiguous
speaker mappings are hard preflight failures, not warnings.

### 4. Generate the full route set safely and resumably

Generate all required English and Traditional Chinese routes with Breeze-TTS 2
from the reviewed canonical transcripts. Keep each route's speaker identity,
role, language, and relevant Avatar-gender variant explicit in the job key and
metadata.

Use both GPUs through independent job shards, not multi-request model batches.
After a small smoke benchmark and memory check, use GPU 0's fast inference
mode and the memory-safe mode on GPU 1. If current device capacity differs,
choose modes based on measured free memory rather than forcing a mode that can
OOM. Independent jobs may run concurrently; each model request remains
isolated to avoid the speaker-identity drift previously seen with batched
inference.

The job system must be resumable and idempotent. A completed route is reusable
only when its transcript, voice/reference identity, model/configuration, and
generation signature match. Changed transcripts or references invalidate
only affected routes. Do not silently accept stale audio because the filename
exists.

### 5. Periodic review and approval gate

Generate a full-catalog review page under
`u6_voice/dynamic_voice_review/full_catalog/` and refresh it approximately
once per minute during generation. Keep the page readable while jobs are
running, showing at least:

- NPC/voice portrait where available, canonical speaker, gender, and role;
- usecode/template identity and source/runtime template;
- English and Traditional Chinese display and spoken transcripts;
- placeholder/slot meaning and speaker/narrator span boundaries;
- reference source, generation state, route key, and playable audio;
- pending, failed, stale, and completed counts, with failures visible rather
  than omitted.

The review page must contain all routes, including pending/failed entries, so
it is a coverage tool as well as an audio player. Pause for user review when
the full render is ready. Do not package or deploy regenerated dynamic audio
until the user approves the review.

### 6. Package and integrate after approval

After approval, run catalog and package validation, build the voice assets
through the established U6 packaging path, and copy the resulting game asset
to the configured U6 game directory (`../Ultima7`, resolved and validated
before writing). Do not replace unrelated game files or copy intermediate
review/model artifacts.

Run runtime smoke tests covering at least:

- a dynamic name/value replacement where the spoken line remains complete;
- an NPC line and an explicitly narrator-owned line for that NPC;
- cross-talk where another NPC enters a conversation;
- male and female Avatar voice selection;
- a role-span boundary within one visible line;
- English and Traditional Chinese selection;
- a missing-asset diagnostic that fails closed without suppressing text or
  breaking conversation flow.

Compare runtime route identity and audio selection against the review
manifest, not just runtime logs. Confirm the installed package contains the
same generation signatures and coverage as the approved review artifact.

## Failure behavior

- Fail offline validation if a discovered spoken template lacks reviewed
  canonical speech, a required language/role/gender route, a valid reference,
  or a generated clip with matching provenance.
- Never substitute an unrelated NPC or narrator when speaker resolution fails.
- At runtime, resolve all required clips for a composite before playback. If a
  required clip is absent or invalid, play none of the misleading partial
  composite, log its template/route identity, and leave displayed text and
  conversation flow unaffected.
- Treat whitespace, punctuation, and control-only spans as non-spoken; do not
  report them as missing speech.
- Audio decode/playback failures remain non-fatal to text and input.
- An unclassified dynamic slot is a review failure. Never omit it silently or
  speak a raw placeholder token.

## Acceptance criteria

1. The compiled-usecode-derived inventory and canonical manifest reconcile;
   every spoken dynamic template is accounted for, with exclusions explained.
2. All dynamic translations pass structural checks and have reviewed,
   natural English and Traditional Chinese canonical speech.
3. Every route resolves to the intended NPC, narrator, cross-talk, or Avatar
   identity; no unresolved route uses a fallback voice.
4. All required routes have generated audio whose metadata matches its
   transcript, reference, role, language, and generation signature.
5. The periodic review page covers completed, pending, failed, and stale
   routes and is approved before packaging.
6. Packaging and runtime smoke tests pass for the scenarios above, and the
   installed game assets match the approved review manifest.
7. Existing static dialogue playback, displayed translations, timing, and
   U6's table-driven bilingual architecture remain unchanged.

## Verification

Add or update focused tests for dynamic-template extraction completeness,
placeholder/marker/role-span parity, translation suspicious-pattern checks,
route identity and reference resolution, narrator-gender pairing, Avatar
gender selection, generation-signature invalidation/resume, and fail-closed
composite playback. Run the relevant translation, dynamic voice manifest,
packaging, and runtime tests, then `git diff --check`. Before deployment,
review generated samples from both languages and all role classes, including
cross-talk and multi-span lines.
