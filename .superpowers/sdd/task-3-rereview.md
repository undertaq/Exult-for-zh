# Task 3 Re-review: Atomic Reference Installation and Backup

## Scope

Reviewed `tools/voice_acting/install_reference_voices.py` and
`tools/voice_acting/test_install_reference_voices.py` against
`.superpowers/sdd/task-3-brief.md` and the findings in `task-3-review.md`.
No implementation files were modified.

## Verification

- `python3 -m unittest tools.voice_acting.test_install_reference_voices -v`
  passed: 13 tests.
- `python3 -m py_compile tools/voice_acting/install_reference_voices.py
  tools/voice_acting/test_install_reference_voices.py` passed.
- `git diff --check` for the reviewed files reported no whitespace errors.

## Findings

### Minor: destination roots may follow symlinks

`install()` accepts `refs_dir` and `backup_root` paths without rejecting
symlinks. A symlink at `voice/refs` would make backup reads and per-file
publication operate in the symlink target, potentially installing outside the
intended project directory. The source root is resolved and constrained, but
the destination roots do not receive equivalent validation. For a local,
trusted checkout this is low risk; for a defensive installer, reject symlinked
destination roots (and unexpected symlinked destination parents) before backup
or publication.

### Minor: rollback does not remove newly created empty directories

During publication, `destination.parent.mkdir(..., exist_ok=True)` can create
directories before a later file publication fails. `_restore_published()`
restores or removes files but does not remove directories created by this
transaction. This does not corrupt reference audio and the normal destinations
are directly under `voice/refs`, but a failed install can leave empty layout
directories behind. Track newly created parents or clean empty transaction-
created directories after rollback.

## Prior Findings Resolution

- **Atomic backup reservation:** resolved. `_reserve_backup_dir()` uses
  `mkdir(exist_ok=False)` and retries with a suffix, so an existing collision
  directory is never replaced.
- **Partial publication rollback test:** added and passing.
- **Backup collision preservation test:** added and passing.
- **`--verify-only` nonmutation test:** added and passing.
- **`--verify-installed` success/tamper test:** added and passing.

## Verdict

No critical or important findings. The prior review findings are fixed, and
Task 3 is approved for the expected trusted project-directory workflow. The
two minor hardening issues above should be addressed if the installer must
defend against symlinked or adversarial filesystem layouts.
