# Task 1 Report: Package bootstrap, configuration, and CLI

## Outcome

Implemented the initial `graph_remaster` Python package under
`tools/graph_remaster/` without changing Exult renderer sources, game data, or
any existing unrelated workspace files.

## Public interfaces

- `graph_remaster.config.load_config(path: Path) -> PipelineConfig`
- `graph_remaster.config.PipelineConfig.from_mapping(mapping)`
- `graph_remaster.cli.main(argv: Sequence[str] | None = None) -> int`
- `python -m graph_remaster --help`

## Configuration behavior

- TOML configuration is loaded with the Python standard library `tomllib`.
- Required fields are `project.name`, `paths.data`, and `paths.work`.
- Relative configured paths resolve against the directory containing the TOML
  file; standard artifact directories are derived below `paths.work` unless
  explicitly configured.
- Typed dataclasses are provided for paths, render settings, GPU settings,
  model settings, and asset profiles.
- The canonical render contract is enforced: scale must be `6` and logical
  dimensions must be exactly `320x200`.
- Invalid TOML, missing required values, malformed tables, and invalid render
  settings raise `ConfigError`.

## CLI behavior

The argparse CLI exposes these seven stages:

`inventory`, `extract`, `prepare-controls`, `generate`, `validate`, `review`,
and `package`.

Each stage accepts `--config`, `--run-id`, and an optional selector. The
`generate` stage additionally accepts `--backend`. Stage handlers currently
raise an explicit `NotImplementedError` pending their dedicated tasks.
`cli.py` imports only standard-library modules, so help does not import torch
or diffusers.

## TDD and verification evidence

1. Added `tests/test_config.py` first and ran the focused test. It failed at
   collection with `ModuleNotFoundError: No module named 'graph_remaster'`,
   confirming the package was absent.
2. Added the package and initial build-system metadata. The focused test then
   passed: `5 passed in 0.01s`.
3. Ran the equivalent help command with the available interpreter:
   `PYTHONPATH=tools/graph_remaster python3 -m graph_remaster --help`.
   The output listed all seven required commands.
4. Built the parser help text programmatically and confirmed
   `heavy_imports []` for `{torch, diffusers}` and `commands_present True`.
5. Ran `python3 -m compileall -q tools/graph_remaster/graph_remaster`
   successfully.

The literal brief command using `python` could not be invoked because this
environment provides `python3` but no `python` executable; the equivalent
interpreter command was verified.
