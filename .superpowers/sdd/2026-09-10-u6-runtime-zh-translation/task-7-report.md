# Task 7 report

Status: complete.

Implemented the stdlib `urllib` Ollama/Qwen backend with the required defaults, JSON-only chat requests, schema validation, retry handling with chained final errors, and stable batch ordering. Added prompt construction using Traditional Chinese rules from `Translation_Guide.md` plus an isolated five-row U6 glossary. Translation cache keys include operation, source hash, model, prompt version, and glossary hash. Semantic review writes advisory JSONL records without modifying candidate translations.

Verification:

- `python3 -m unittest tools.u6_translation.tests.test_ollama_backend tools.u6_translation.tests.test_translate -v` — 10 tests passed.
- `python3 -m unittest discover -s tools/u6_translation/tests -v` — 32 tests passed.
- `python3 -m compileall -q tools/u6_translation` — passed.
- All HTTP tests mock `urllib.request.urlopen`; no network I/O was performed.

Scope note: the worktree contained unrelated pre-existing untracked files. Only the requested Task 7 files were staged, plus this required report.
