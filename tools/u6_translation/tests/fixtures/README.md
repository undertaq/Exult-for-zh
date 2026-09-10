# U6 translation fixtures

`runtime_catalog.tsv` is a deterministic capture fixture containing dialogue, a conversation choice, and a text-message entry. The choice row (`choice:0x0401:0x0088:0`, source `one`) demonstrates the invariant used by the runtime: the displayed choice may be Traditional Chinese, while the original English answer remains the internal value used for comparison, indexing, and game logic.

The indexed mod fixture supplies static patch resources and a UCXT shell fixture for extraction tests. It is test input only; no fixture output is copied to the external mod. Generated catalogs, candidates, caches, audit reports, review files, and `zh_translation.tsv` belong in temporary or external paths and are not committed.
