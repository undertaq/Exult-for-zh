# Task 3 Report: Atomic Reference Installation and Backup

## Status

Implemented the Task 3 installer in:

- `tools/voice_acting/install_reference_voices.py`
- `tools/voice_acting/test_install_reference_voices.py`

The installer preflights every selected EN/ZH pair against its candidate sidecar
hash, index, language, slug, and exact design reference text. It requires one
selected bilingual pair for each individual design and rejects duplicate slugs,
design assignments, and destinations.

Installation stages copies beside the target reference directory, verifies staged
hashes, publishes an immutable `voice_backup/refs_<timestamp>/` backup of refs
and clone prompts, replaces each destination with `Path.replace()`, verifies the
published hashes, and writes an optional provenance manifest with an atomic
same-directory replace. A failed publish restores destinations from the backup.

CLI modes implemented:

- `--dry-run`: preflight and report planned item count without mutation.
- `--verify-only`: preflight and report validated item count without mutation.
- `--verify-installed`: preflight and compare installed destination hashes.
- Installation requires an explicit `--manifest`; there is no implicit manifest
  generation.

## TDD Record

RED 1:

```text
python3 -m unittest tools.voice_acting.test_install_reference_voices -v
ImportError: cannot import name 'install_reference_voices'
```

GREEN 1:

```text
Ran 8 tests ... OK
```

RED 2:

```text
test_preflight_rejects_design_assigned_to_multiple_npcs ... FAIL
AssertionError: InstallError not raised
```

GREEN 2 and final focused verification:

```text
python3 -m unittest tools.voice_acting.test_install_reference_voices -v
Ran 9 tests ... OK

python3 -m py_compile tools/voice_acting/install_reference_voices.py \
  tools/voice_acting/test_install_reference_voices.py
exit 0
```

## Deferred Work and Concerns

- The live `tools/voice_acting/reference_candidates` directory was not read or
  modified.
- The sibling selection was not preflighted because its complete merged
  selection and regenerated individual designs are intentionally deferred.
- No `reference_import_manifest.json` was generated, no `voice/refs` file was
  replaced, and no real `voice_backup` directory was created.
- Git remained read-only; no staging or commit operation was attempted.

## Fix Review

RED:

```text
python3 -m unittest \
  tools.voice_acting.test_install_reference_voices.InstallReferenceVoicesTest.test_install_reserves_backup_directory_without_replacing_collision -v
FAIL: expected refs_fixed_01, received refs_fixed
```

The test injects an empty final backup-directory collision after backup staging.
The previous check-then-replace flow reused that directory rather than reserving
a new one atomically.

GREEN:

```text
test_install_reserves_backup_directory_without_replacing_collision ... ok
test_install_rolls_back_after_injected_partial_publication_failure ... ok
test_verify_only_does_not_mutate_filesystem ... ok
test_verify_installed_succeeds_then_rejects_tampering ... ok

python3 -m unittest tools.voice_acting.test_install_reference_voices -v
Ran 13 tests ... OK

python3 -m py_compile tools/voice_acting/install_reference_voices.py \
  tools/voice_acting/test_install_reference_voices.py
exit 0
```

`_reserve_backup_dir()` now uses `mkdir(exist_ok=False)` to atomically reserve
the final directory and retries with a suffix on collision. Backup content is
copied into the reserved directory; no existing backup directory is replaced.
All review tests use temporary fixture paths only. No real candidates,
references, manifests, backups, or generation processes were read or changed.
