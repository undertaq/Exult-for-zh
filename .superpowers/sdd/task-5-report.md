# Task 5 Report: Resumable Missing Chinese Translation

## Implementation

- Added `tools/voice_acting/translate_missing_zh_text.py`.
- Added focused tests in `tools/voice_acting/test_translate_missing_zh_text.py`.
- Selection is limited to rows with non-empty `en_text` and empty/whitespace-only `zh_text`.
- Ollama defaults to `http://127.0.0.1:11434/api/chat` and `qwen3.6:35b`, with JSON-only output, temperature zero, disabled hidden reasoning, batching, and a configurable timeout.
- Cache keys include model, prompt version, and source text. Cache records store accepted/rejected validation results so interrupted runs can resume.
- Validation checks empty output, model commentary, placeholder multiset equality, English-to-Chinese dialogue span counts, balanced `「」`, and common Simplified-only characters.
- Mapping application deep-copies rows and changes only `zh_text` on accepted rows that were previously empty.

## Verification

- Dry run: exactly 85 rows selected.
- Focused translation tests: 7 passed.
- Alignment and quote-balance regression tests: 6 passed.
- `py_compile` passed.
- `bilingual_mapping_review.json` was not written by this task because no translation response was accepted.

## External blocker

The installed local Ollama tags include `qwen3.6:35b` and `qwen3.6:27b`, but `/api/chat` did not return even a minimal JSON request within the attempted runtime. The 35B request exceeded 180 seconds; a retry with a 900-second timeout and `think: false` was stopped after the model process disappeared without a response. A minimal 27B request also timed out. Therefore no cache or audit file was generated and no unverified translations were inserted into the mapping.

The command to resume once Ollama is responsive is:

```bash
python3 tools/voice_acting/translate_missing_zh_text.py \
  --mapping tools/voice_acting/bilingual_mapping_review.json \
  --model qwen3.6:35b \
  --cache tools/voice_acting/missing_zh_translation_cache.jsonl \
  --audit tools/voice_acting/missing_zh_translation_audit.json \
  --batch-size 4 --timeout 900
```
