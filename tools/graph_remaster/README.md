# Ultima VII Graph Remaster Pipeline

This renderer-neutral pipeline keeps the Black Gate logical coordinate system
at 320x200 and writes canonical 6x RGBA masters. It does not modify Exult
renderer code, original FLX archives, or copyrighted game data.

## Setup

```bash
uv sync --project tools/graph_remaster
uv run --project tools/graph_remaster pytest tools/graph_remaster/tests -q
```

For local CUDA generation, run the CLI from the CUDA-enabled Python
environment rather than the lightweight project environment. For the current
machine this is:

```bash
VIRTUAL_ENV=/home/joe/flux2-klein/.venv uv run --active \
  --project tools/graph_remaster graph-remaster generate \
  --config remaster_pipeline.toml --device 1
```

The project environment intentionally keeps `torch` and `diffusers` optional;
the active environment must provide the CUDA-enabled builds for the selected
backend. The local machine has a cached Flux2 Klein 4B model and a ready-to-run
FP8 configuration:

```bash
HF_HUB_OFFLINE=1 VIRTUAL_ENV=/home/joe/flux2-klein/.venv uv run --active \
  --project tools/graph_remaster graph-remaster generate \
  --config remaster_pipeline_flux2_klein_fp8.toml --device 0 JOB_ID
```

`flux2_klein` is a single-reference image-editing backend. It does not send
Canny/edge controls to the model, uses the source image as the reference, and
quantizes only the Flux transformer to FP8; text encoding and VAE remain BF16.
The exact source alpha mask is restored by the postprocess stage. This mode is
intended for re-imagining material detail and must be reviewed before use.

Create a local `pipeline.toml` with `[project] name = "black-gate"`,
`[paths] data = "game-data"` and `work = "remaster-data"`, plus the required
`[render] scale = 6`, `logical_width = 320`, and `logical_height = 200`.
Point `data` at user-owned Black Gate files only. The source adapter invokes
`ipack` without a shell and keeps indexed fixtures separate from RGBA masters.

## Stages and review

Use `inventory`, `extract`, `prepare-controls`, `generate`, `validate`,
`review`, and `package`. Generation accepts `--backend mock` for a lightweight
fixture run, `sdxl_controlnet --real-model-smoke` for SDXL testing, or
`flux2_klein` for local Flux2 Klein image editing.
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
