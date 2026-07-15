#!/usr/bin/env python3
"""Multi-GPU voice regeneration orchestrator for generate_qwen3_voice.py.

Strategy
--------
Phase A (reference clips) and Phase B (clone-prompt building) are cheap-ish and
must run before generation, so they run once on the first GPU. Phase C (the
expensive bulk synthesis) is sharded across GPUs by *language*: one subprocess
per language, each loading the model once on its own device. This keeps both
GPUs busy for the long part and avoids reloading the model per NPC.

Only the first voice subprocess writes the periodic review HTML (it scans the
whole output tree, so a single writer avoids concurrent-file races while still
covering every language).

Usage
-----
    run_voice_regen_multigpu.py --gpus 0,1 --reference-workflow legacy
    run_voice_regen_multigpu.py --gpus 0,1 --dry-run
    run_voice_regen_multigpu.py --gpus 0,1 --force --force-refs --max-npcs 5
"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
GENERATOR = SCRIPT_DIR / "generate_qwen3_voice.py"

# Langs that Phase C can generate; mapped round-robin onto the GPU list.
VOICE_LANGS = ["zh", "en"]


def build_parser():
    p = argparse.ArgumentParser(description="Multi-GPU Qwen3-TTS voice regen orchestrator")
    p.add_argument("--gpus", type=str, default="0", help="Comma-separated CUDA device ids, e.g. 0,1")
    p.add_argument("--phase", choices=["all", "refs", "prompts", "voice"], default="all")
    p.add_argument("--reference-workflow", choices=["candidates", "legacy"], default="legacy")
    p.add_argument("--force", action="store_true")
    p.add_argument("--force-refs", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--generic-fallbacks", action="store_true")
    p.add_argument("--npc", type=str, default=None)
    p.add_argument("--max-npcs", type=int, default=None)
    p.add_argument("--review-out-dir", type=str, default=str(SCRIPT_DIR / "voice_review"))
    p.add_argument("--review-update-interval", type=int, default=120)
    p.add_argument("--logs-dir", type=str, default=str(SCRIPT_DIR / "logs"))
    return p


def run_on_gpu(gpu, phase_args, logs_dir, run_id):
    """Launch one generate_qwen3_voice.py subprocess on a specific GPU.

    We isolate the physical GPU via CUDA_VISIBLE_DEVICES, which remaps it to
    cuda:0 inside the subprocess, so the script is always told --device cuda:0.
    """
    env = dict(__import__("os").environ)
    env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    log_path = logs_dir / f"regen_gpu{gpu}_{run_id}.log"
    print(f"[orchestrator] gpu {gpu}: {' '.join(phase_args)}  -> {log_path}")
    with log_path.open("wb") as logf:
        proc = subprocess.Popen(
            phase_args,
            cwd=str(SCRIPT_DIR),
            env=env,
            stdout=logf,
            stderr=subprocess.STDOUT,
        )
    return proc, log_path


def wait_procs(procs):
    failed = []
    for gpu, (proc, log_path) in procs.items():
        rc = proc.wait()
        status = "OK" if rc == 0 else f"FAILED rc={rc}"
        print(f"[orchestrator] gpu {gpu}: {status}  (log: {log_path})")
        if rc != 0:
            failed.append((gpu, log_path))
    return failed


def main():
    import os

    args = build_parser().parse_args()
    gpus = [g.strip() for g in args.gpus.split(",") if g.strip()]
    if not gpus:
        print("No GPUs specified", file=sys.stderr)
        sys.exit(2)

    logs_dir = Path(args.logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    python = sys.executable
    common = [
        python, str(GENERATOR),
        "--reference-workflow", args.reference_workflow,
    ]
    if args.force:
        common.append("--force")
    if args.force_refs:
        common.append("--force-refs")
    if args.dry_run:
        common.append("--dry-run")
    if args.generic_fallbacks:
        common.append("--generic-fallbacks")
    if args.npc:
        common += ["--npc", args.npc]
    if args.max_npcs:
        common += ["--max-npcs", str(args.max_npcs)]

    # Phase A: reference clips (once, on first GPU).
    if args.phase in ("all", "refs"):
        print(f"[orchestrator] Phase A (refs) on gpu {gpus[0]}")
        procs = {}
        procs[gpus[0]] = run_on_gpu(
            gpus[0], common + ["--phase", "refs"], logs_dir, run_id
        )
        failed = wait_procs(procs)
        if failed:
            sys.exit(1)

    # Phase B: build clone prompts (once, on first GPU, needs the model).
    if args.phase in ("all", "prompts"):
        print(f"[orchestrator] Phase B (prompts) on gpu {gpus[0]}")
        procs = {}
        procs[gpus[0]] = run_on_gpu(
            gpus[0], common + ["--phase", "prompts"], logs_dir, run_id
        )
        failed = wait_procs(procs)
        if failed:
            sys.exit(1)

    # Phase C: sharded by language across GPUs, run concurrently.
    if args.phase in ("all", "voice"):
        langs = VOICE_LANGS
        print(f"[orchestrator] Phase C (voice) sharded by language across gpus {gpus}")
        procs = {}
        for idx, lang in enumerate(langs):
            gpu = gpus[idx % len(gpus)]
            phase_args = common + ["--phase", "voice", "--lang", lang, "--device", "cuda:0"]
            if gpu == gpus[0]:
                # First writer only, to avoid concurrent review-HTML races.
                phase_args += [
                    "--review-out-dir", args.review_out_dir,
                    "--review-update-interval", str(args.review_update_interval),
                ]
            procs[gpu] = run_on_gpu(gpu, phase_args, logs_dir, run_id)
        failed = wait_procs(procs)
        if failed:
            print("[orchestrator] Phase C had failures:", file=sys.stderr)
            for gpu, log_path in failed:
                print(f"  gpu {gpu}: see {log_path}", file=sys.stderr)
            sys.exit(1)

    print("[orchestrator] Done.")


if __name__ == "__main__":
    main()
