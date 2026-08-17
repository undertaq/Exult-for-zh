# Task 3 Review Findings

1. Reserve the final timestamped backup directory atomically with `mkdir(exist_ok=False)` and fail or retry on collision. Never replace a path that was only previously observed absent.
2. Add focused regression tests for injected partial-publication failure and rollback, backup collision preservation, `--verify-only`, and `--verify-installed`.

