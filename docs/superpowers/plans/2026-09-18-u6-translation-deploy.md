# U6 Translation Staging and Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the reviewed U6 Traditional Chinese release files under `tools/u6_translation/deploy` and provide a safe CLI command that copies them to a game installation.

**Architecture:** A focused `deploy.py` module owns the fixed, mirrored release manifest, validates the complete staging tree, and performs atomic, mode-preserving copies. The CLI exposes `deploy`, while `emit` and fallback-book import default to the staged U6 table; explicit output/table paths remain supported. The staged table becomes the canonical checked-in release artifact, and current test consumers are pointed at it.

**Tech Stack:** Python 3 standard library (`argparse`, `pathlib`, `os`, `shutil`, `tempfile`, `stat`), existing `unittest`/`pytest` tests, C++ translation-table regression executable, checked-in UTF-8/CRLF game resource files.

**Spec:** `docs/superpowers/specs/2026-09-18-u6-translation-deploy-design.md`

## Global Constraints

- The staging tree mirrors paths below the game root.
- Supported staged files are exactly `patch/autonotes.txt`, `patch/textmsg.txt`, and `mods/Ultima6v1.3/patch/zh_translation.tsv`.
- The compiled `patch/usecode.zh` binary is excluded from staging and deployment.
- Deployment must reject missing files and path escapes before copying anything.
- Deployment must support `--dry-run`, preserve file content and mode, and be idempotent.
- Traditional-Chinese conversion remains deterministic and runs before emitted table release output.
- Existing explicit `--output` and `--table` invocations remain valid.

---

### Task 1: Add manifest validation and atomic deployment helper

**Files:**
- Create: `tools/u6_translation/deploy.py`
- Create: `tools/u6_translation/tests/test_deploy.py`

**Interfaces:**
- Produces `DEPLOY_ROOT: pathlib.Path`, `DEPLOY_RELATIVE_PATHS: tuple[str, ...]`, `DeploymentReport`, `validate_staging(stage_root: Path = DEPLOY_ROOT)`, and `deploy_staged_files(game_root: Path, stage_root: Path = DEPLOY_ROOT, *, dry_run: bool = False) -> DeploymentReport`.
- `DeploymentReport` exposes `copied: tuple[Path, ...]`, `skipped: tuple[Path, ...]`, and `dry_run: bool` for CLI reporting.
- `validate_staging` returns the resolved staged files in manifest order and raises `ValueError` for missing files, extra files, unsafe relative paths, or a staging root that is not a directory.

- [ ] **Step 1: Write failing manifest and deployment tests**

Add a `DeploymentTest` suite using `tempfile.TemporaryDirectory` and small UTF-8 files. Cover:

```python
def test_manifest_contains_only_supported_game_relative_files(self):
    self.assertEqual(
        DEPLOY_RELATIVE_PATHS,
        (
            "patch/autonotes.txt",
            "patch/textmsg.txt",
            "mods/Ultima6v1.3/patch/zh_translation.tsv",
        ),
    )

def test_deploy_copies_mirrored_paths_and_preserves_mode(self):
    # Build a temporary stage tree with all three manifest files, chmod one
    # source to 0o744, deploy it, and assert bytes/mode at the mirrored target.
    report = deploy_staged_files(game_root, stage_root)
    self.assertEqual(len(report.copied), 3)
    self.assertEqual((target / "patch/textmsg.txt").read_bytes(), b"午安\r\n")
    self.assertEqual(stat.S_IMODE((target / "patch/textmsg.txt").stat().st_mode), 0o744)

def test_dry_run_validates_and_does_not_modify_game_root(self):
    report = deploy_staged_files(game_root, stage_root, dry_run=True)
    self.assertTrue(report.dry_run)
    self.assertFalse((game_root / "patch/textmsg.txt").exists())

def test_second_deploy_skips_identical_files(self):
    deploy_staged_files(game_root, stage_root)
    report = deploy_staged_files(game_root, stage_root)
    self.assertEqual(report.copied, ())
    self.assertEqual(len(report.skipped), 3)

def test_missing_or_unsafe_manifest_input_fails_before_copy(self):
    # Omit one file and assert no target exists; separately exercise a ../ path
    # through the helper's manifest validation seam and assert ValueError.
```

- [ ] **Step 2: Run the focused tests and verify the expected RED failure**

Run:

```sh
python3 -m pytest -q tools/u6_translation/tests/test_deploy.py
```

Expected: collection/import failures because `deploy.py` and its public interfaces do not exist yet.

- [ ] **Step 3: Implement the minimal deployment module**

Define the fixed tuple in game-relative POSIX spelling. Resolve both roots, reject any manifest entry whose resolved path is outside its root, require the exact regular-file set, and reject extra files under the staging tree. Before copying, validate every source and target so a missing/unsafe entry cannot leave a partial deployment. For each changed file, write bytes to a same-directory temporary file, copy source mode with `shutil.copystat`, and replace the target with `os.replace`; compare existing bytes and `stat.S_IMODE` to classify identical files as `skipped`. In dry-run mode, perform validation and report planned copies without creating targets.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the same pytest command. Expected: all deployment helper tests pass with no warnings.

- [ ] **Step 5: Commit the helper and tests**

```sh
git add tools/u6_translation/deploy.py tools/u6_translation/tests/test_deploy.py
git commit -m "feat: add safe U6 translation deployment helper"
```

### Task 2: Integrate staged defaults into generation and CLI

**Files:**
- Modify: `tools/u6_translation/emit.py`
- Modify: `tools/u6_translation/__main__.py`
- Modify: `tools/u6_translation/tests/test_emit.py`
- Modify: `tools/u6_translation/tests/test_cli.py`

**Interfaces:**
- `emit_approved_table(catalog, review_path, output_path: Path | None = None) -> None` writes to `DEFAULT_TABLE_PATH` when `output_path` is `None`.
- `import-fallback-books --table` becomes optional and defaults to `DEFAULT_TABLE_PATH`; explicit tables remain unchanged.
- `deploy --game-root PATH [--staging-root PATH] [--dry-run]` calls `deploy_staged_files` and prints each relative result plus `copied`, `skipped`, and `dry_run` counts.

- [ ] **Step 1: Write failing default-output and CLI tests**

Add tests that patch `tools.u6_translation.emit.DEFAULT_TABLE_PATH` for direct emitter calls or pass a temporary staging root for the subprocess command, then assert:

```python
def test_emit_defaults_to_staged_table(self):
    with patch("tools.u6_translation.emit.DEFAULT_TABLE_PATH", temporary_output):
        emit_approved_table(catalog, review_path)
    self.assertTrue(temporary_output.exists())

def test_deploy_command_supports_dry_run_and_staging_root(self):
    result = self._run(
        "deploy", "--game-root", str(game_root),
        "--staging-root", str(stage_root), "--dry-run",
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn("dry_run=1", result.stdout)
    self.assertFalse((game_root / "patch/textmsg.txt").exists())

def test_emit_explicit_output_still_wins(self):
    emit_approved_table(catalog, review_path, explicit_output)
    self.assertTrue(explicit_output.exists())
```

Use a temporary staging tree containing all manifest files for the subprocess test; do not modify the checked-in deploy tree during tests.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```sh
python3 -m pytest -q tools/u6_translation/tests/test_emit.py tools/u6_translation/tests/test_cli.py
```

Expected: the new default/deploy assertions fail because output is still required and the CLI has no `deploy` command.

- [ ] **Step 3: Implement staged defaults and CLI wiring**

Import `DEFAULT_TABLE_PATH` from `deploy.py`. Make the emitter path optional while retaining the existing explicit path behavior. Add the optional fallback-book table argument with the same default. Register the `deploy` parser with required `--game-root`, optional `--staging-root` defaulting to `DEPLOY_ROOT`, and `--dry-run`; call the helper and render stable tab-separated result lines and one summary line. Convert helper `ValueError` failures into the existing CLI error path rather than copying partially.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the two test modules again; expected: all existing and new assertions pass.

- [ ] **Step 5: Commit the integration**

```sh
git add tools/u6_translation/emit.py tools/u6_translation/__main__.py \
  tools/u6_translation/tests/test_emit.py tools/u6_translation/tests/test_cli.py
git commit -m "feat: stage U6 release output and expose deploy command"
```

### Task 3: Move release table consumers to the staging tree

**Files:**
- Create: `tools/u6_translation/deploy/mods/Ultima6v1.3/patch/zh_translation.tsv` (seed from the currently deployed, audited U6 table)
- Create: `tools/u6_translation/deploy/patch/textmsg.txt` (seed from the converted deployed resource)
- Create: `tools/u6_translation/deploy/patch/autonotes.txt` (seed from the converted deployed resource)
- Delete: `tools/u6_translation/zh_translation.tsv` after consumers are updated
- Modify: `tests/gameplay_translation_table_test.cc`
- Modify: `tools/u6_translation/tests/test_taynith_translation.py`
- Modify: `tools/u6_translation/tests/fixtures/README.md`
- Modify: `tools/u6_translation/README.md`

**Interfaces:**
- The checked-in deploy table is the canonical release table used by C++ and Python regression tests.
- `validate_staging()` must accept exactly the three checked-in files and reject `usecode.zh` or any other file.

- [ ] **Step 1: Add a failing staging-content regression test**

Extend `test_deploy.py` with a repository-tree assertion:

```python
def test_checked_in_staging_contains_exact_release_files(self):
    self.assertEqual(
        {path.relative_to(DEPLOY_ROOT).as_posix() for path in DEPLOY_ROOT.rglob("*") if path.is_file()},
        set(DEPLOY_RELATIVE_PATHS),
    )
    self.assertFalse((DEPLOY_ROOT / "usecode.zh").exists())
```

Run it and confirm RED because the staging tree does not exist.

- [ ] **Step 2: Populate the release tree and update consumers**

Create the mirrored directories and copy the current active external U6 `zh_translation.tsv`, global converted `patch/textmsg.txt`, and global converted `patch/autonotes.txt` into them without normalizing line endings. Preserve source modes (664 for the U6 table, 744 for global patch resources). Remove the old root table after updating every active test/reference from `tools/u6_translation/zh_translation.tsv` to `tools/u6_translation/deploy/mods/Ultima6v1.3/patch/zh_translation.tsv`. Update README commands to use the staged table and document the deploy command, dry run, mirrored layout, and exclusion of `usecode.zh`.

- [ ] **Step 3: Run staging-content and translation-table tests**

Run:

```sh
python3 -m pytest -q tools/u6_translation/tests/test_deploy.py tools/u6_translation/tests/test_taynith_translation.py
make -j2 gameplay_translation_table_test
./gameplay_translation_table_test
```

Expected: the checked-in manifest is exact, the Traditional-Chinese table loads, and the C++ executable exits 0.

- [ ] **Step 4: Commit the staged release artifacts and consumer updates**

```sh
git add tools/u6_translation/deploy tools/u6_translation/README.md \
  tools/u6_translation/tests/test_deploy.py \
  tools/u6_translation/tests/test_taynith_translation.py \
  tools/u6_translation/tests/fixtures/README.md \
  tests/gameplay_translation_table_test.cc
git rm tools/u6_translation/zh_translation.tsv
git commit -m "feat: check in U6 translation deployment artifacts"
```

### Task 4: Full verification and release handoff

**Files:**
- Modify: `tools/u6_translation/README.md` only if verification exposes a command/documentation mismatch.

- [ ] **Step 1: Run the complete Python translation test suite**

```sh
python3 -m pytest -q tools/u6_translation/tests
```

Expected: zero failures.

- [ ] **Step 2: Validate every staged table and converted resource**

```sh
python3 -m tools.u6_translation convert-traditional \
  --input tools/u6_translation/deploy/mods/Ultima6v1.3/patch/zh_translation.tsv \
  --check
python3 -m tools.u6_translation deploy --game-root "$(mktemp -d)" --dry-run
```

Expected: conversion reports `changed_rows=0`, and dry-run reports three planned files without changing the temporary game root.

- [ ] **Step 3: Run C++ regression and repository checks**

```sh
make -j2 gameplay_translation_table_test
./gameplay_translation_table_test
git diff --check
git status --short --branch
```

Expected: build/test exit 0, no whitespace errors, and only intended tracked changes plus pre-existing untracked artifacts.

- [ ] **Step 4: Commit any documentation-only correction and report the release workflow**

If Step 4.1–4.3 found a documentation-only mismatch, commit it with:

```sh
git add tools/u6_translation/README.md
git commit -m "docs: finalize U6 deployment workflow"
```

Report the staged paths, the exact deploy command, test counts, and the fact that `usecode.zh` remains intentionally excluded.
