from __future__ import annotations
import argparse
import json
from pathlib import Path
from .audit import (correctness_report, coverage_report, format_terminal_report,
                    combine_audit_reports, load_audit_table, merge_input_issues, report_exit_code,
                    write_json_report)
from .catalog import load_catalog, write_catalog
from .emit import emit_approved_table
from .extract import extract_catalog
from .ollama_backend import OllamaBackend, OllamaConfig
from .prompts import PROMPT_VERSION
from .review_html import write_review_html
from .runtime_table import load_runtime_table
from .translate import translate_catalog

def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m tools.u6_translation")
    sub = parser.add_subparsers(dest="command")
    legacy = sub.add_parser("_legacy"); legacy.add_argument("path")
    extract = sub.add_parser("extract")
    extract.add_argument("--mod-root", required=True); extract.add_argument("--ucxt", required=True)
    extract.add_argument("--runtime-catalog"); extract.add_argument("--include-static", action="store_true")
    extract.add_argument("--output", required=True)
    translate = sub.add_parser("translate")
    translate.add_argument("--catalog", required=True); translate.add_argument("--output", required=True)
    translate.add_argument("--cache", required=True); translate.add_argument("--model", required=True)
    translate.add_argument("--url", required=True); translate.add_argument("--batch-size", type=int, default=8)
    translate.add_argument("--timeout", type=float, default=120.0); translate.add_argument("--retries", type=int, default=3)
    audit = sub.add_parser("audit"); modes = audit.add_subparsers(dest="mode", required=True)
    for mode in ("coverage", "correctness", "all"):
        p = modes.add_parser(mode); p.add_argument("--catalog", required=True); p.add_argument("--table", required=True)
        p.add_argument("--report", required=True); p.add_argument("--glossary", default=str(Path(__file__).with_name("u6_glossary.tsv")))
        p.add_argument("--strict", action="store_true")
        p.add_argument("--semantic-strict", action="store_true")
    emit = sub.add_parser("emit"); emit.add_argument("--catalog", required=True); emit.add_argument("--review", required=True); emit.add_argument("--output", required=True)
    review_html = sub.add_parser("review-html")
    review_html.add_argument("--catalog", required=True); review_html.add_argument("--table", required=True)
    review_html.add_argument("--output", required=True); review_html.add_argument("--model", default="qwen3.8:27b")
    review_html.add_argument("--prompt-version", default=PROMPT_VERSION); review_html.add_argument("--audit")
    # Task 6/7 accepted a bare catalog path; retain that invocation.
    if argv is None:
        import sys
        argv = sys.argv[1:]
    if len(argv) == 1 and not argv[0].startswith('-'):
        argv = ["_legacy", argv[0]]
    args = parser.parse_args(argv)
    if args.command == "_legacy":
        for entry in load_catalog(Path(args.path)): print(entry.key, entry.source)
        return 0
    if args.command == "extract":
        runtime = Path(args.runtime_catalog) if args.runtime_catalog else None
        entries = extract_catalog(Path(args.mod_root), Path(args.ucxt), runtime)
        # A CLI extraction without a runtime capture is the static dialogue
        # catalog used by the legacy candidate workflow.
        if runtime is None and not args.include_static:
            entries = [entry for entry in entries if entry.kind == "dialogue"]
        write_catalog(Path(args.output), entries); return 0
    if args.command == "translate":
        translate_catalog(
            Path(args.catalog),
            Path(args.output),
            Path(args.cache),
            OllamaBackend(OllamaConfig(
                url=args.url, model=args.model, timeout_seconds=args.timeout, retries=args.retries,
            )),
            PROMPT_VERSION,
            batch_size=args.batch_size,
        )
        return 0
    if args.command == "audit":
        catalog = load_catalog(Path(args.catalog)); rows, raw = load_audit_table(Path(args.table))
        coverage = coverage_report(catalog, rows)
        if args.mode == "coverage":
            report = coverage
        elif args.mode == "correctness":
            report = correctness_report(catalog, rows, Path(args.glossary), None, args.semantic_strict)
        else:
            correctness = correctness_report(catalog, rows, Path(args.glossary), None, args.semantic_strict)
            report = combine_audit_reports(coverage, correctness)
        if raw: report = merge_input_issues(report, raw)
        write_json_report(Path(args.report), report); print(format_terminal_report(report)); return report_exit_code(report, args.strict)
    if args.command == "emit":
        emit_approved_table(load_catalog(Path(args.catalog)), Path(args.review), Path(args.output)); return 0
    if args.command == "review-html":
        audit = None
        if args.audit:
            audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))
        write_review_html(
            Path(args.output),
            load_catalog(Path(args.catalog)),
            load_runtime_table(Path(args.table)),
            model=args.model,
            prompt_version=args.prompt_version,
            audit=audit,
        )
        return 0
    parser.error("a command is required")

if __name__ == '__main__':
    raise SystemExit(main())
