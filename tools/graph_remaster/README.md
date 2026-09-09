# Ultima VII Graph Remaster Pipeline

This renderer-neutral pipeline keeps the Black Gate logical coordinate system
at 320x200 and writes canonical 6x RGBA masters. It does not modify Exult
renderer code, original FLX archives, or copyrighted game data.

## Setup

```bash
uv sync --project tools/graph_remaster
uv run --project tools/graph_remaster pytest tools/graph_remaster/tests -q
```

Create a local `pipeline.toml` with `[project] name = "black-gate"`,
`[paths] data = "game-data"` and `work = "remaster-data"`, plus the required
`[render] scale = 6`, `logical_width = 320`, and `logical_height = 200`.
Point `data` at user-owned Black Gate files only. The source adapter invokes
`ipack` without a shell and keeps indexed fixtures separate from RGBA masters.

## Stages and review

Use `inventory`, `extract`, `prepare-controls`, `generate`, `validate`,
`review`, and `package`. Generation accepts `--backend mock` for a lightweight
fixture run or `sdxl_controlnet --real-model-smoke` for local model testing.
Select GPUs with `--device 0` or `--device 1`; automatic selection and the
spawned worker pool enforce one active job per physical GPU. The precision
ladder is FP16, offload/attention slicing/VAE tiling, supported FP8, INT8, and
INT4. Install `sdxl-fp8` and/or `sdxl-quantized` extras when those modes are
needed.

Every run writes offline relative HTML pages under `reports/RUN_ID/`. Start
the local review server with:

```bash
uv run --project tools/graph_remaster python -m graph_remaster review \
  --config pipeline.toml --run-id pilot --serve
```

Only validated candidates with an `APPROVE` decision are copied into a package
manifest. Review rejection/retry actions require a reason. No generated output
or original game data should be committed to the repository.
