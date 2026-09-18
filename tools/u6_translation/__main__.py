from __future__ import annotations
import argparse
import json
from pathlib import Path
from .audit import (correctness_report, coverage_report, format_terminal_report,
                    combine_audit_reports, load_audit_table, merge_input_issues, report_exit_code,
                    write_json_report)
from .catalog import load_catalog, write_catalog
from .deploy import DEPLOY_ROOT, DEFAULT_TABLE_PATH, deploy_staged_files
from .emit import emit_approved_table
from .extract import extract_catalog, extract_usecode_translation_rows
from .ollama_backend import OllamaBackend, OllamaConfig
from .prompts import PROMPT_VERSION, TERMS_PATH
from .review_html import write_review_html
from .runtime_table import load_runtime_table, merge_runtime_rows, write_runtime_table
from .speaker_map import load_speaker_capture, speaker_map_from_capture
from .translate import translate_catalog
from .traditional import convert_runtime_table
from .voice_generation import run_voice_generation
from .voice_manifest import (
    build_voice_rows,
    load_voice_assignments,
    voice_key_collisions,
    write_generation_manifests,
)

def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m tools.u6_translation")
    sub = parser.add_subparsers(dest="command")
    legacy = sub.add_parser("_legacy"); legacy.add_argument("path")
    extract = sub.add_parser("extract")
    extract.add_argument("--mod-root", required=True); extract.add_argument("--ucxt", required=True)
    extract.add_argument("--runtime-catalog"); extract.add_argument("--include-static", action="store_true")
    extract.add_argument(
        "--fallback-usecode",
        help="base USECODE used by inherited book and item_say handlers",
    )
    extract.add_argument("--terms", default=str(TERMS_PATH))
    extract.add_argument("--output", required=True)
    fallback_books = sub.add_parser("import-fallback-books")
    fallback_books.add_argument("--english-usecode", required=True)
    fallback_books.add_argument("--chinese-usecode", required=True)
    fallback_books.add_argument("--ucxt", required=True)
    fallback_books.add_argument("--table", default=str(DEFAULT_TABLE_PATH))
    translate = sub.add_parser("translate")
    translate.add_argument("--catalog", required=True); translate.add_argument("--output", required=True)
    translate.add_argument("--cache", required=True); translate.add_argument("--model", required=True)
    translate.add_argument("--url", required=True); translate.add_argument("--batch-size", type=int, default=8)
    translate.add_argument("--timeout", type=float, default=120.0); translate.add_argument("--retries", type=int, default=3)
    audit = sub.add_parser("audit"); modes = audit.add_subparsers(dest="mode", required=True)
    for mode in ("coverage", "correctness", "all"):
        p = modes.add_parser(mode); p.add_argument("--catalog", required=True); p.add_argument("--table", required=True)
        p.add_argument("--report", required=True); p.add_argument("--glossary", default=str(Path(__file__).with_name("u6_glossary.tsv")))
        # Kept as an opt-in compatibility input; the shared manifest is the
        # default source for people, locations, and proper entities.
        p.add_argument("--names")
        p.add_argument("--terms", default=str(TERMS_PATH))
        p.add_argument("--strict", action="store_true")
        p.add_argument("--semantic-strict", action="store_true")
    emit = sub.add_parser("emit"); emit.add_argument("--catalog", required=True); emit.add_argument("--review", required=True); emit.add_argument("--output", default=str(DEFAULT_TABLE_PATH))
    convert_traditional = sub.add_parser(
        "convert-traditional",
        help="check or convert Simplified glyphs in a runtime translation table",
    )
    convert_traditional.add_argument("--input", required=True)
    convert_traditional.add_argument("--output")
    convert_mode = convert_traditional.add_mutually_exclusive_group()
    convert_mode.add_argument("--check", action="store_true")
    convert_mode.add_argument("--dry-run", action="store_true")
    review_html = sub.add_parser("review-html")
    review_html.add_argument("--catalog", required=True); review_html.add_argument("--table", required=True)
    review_html.add_argument("--output", required=True); review_html.add_argument("--model", default="qwen3.8:27b")
    review_html.add_argument("--prompt-version", default=PROMPT_VERSION); review_html.add_argument("--audit")
    review_html.add_argument("--speaker-map", help="JSON mapping of dialogue identity to speaker name")
    review_html.add_argument(
        "--speaker-capture",
        help="runtime U6 speaker capture TSV; overrides static map entries",
    )
    deploy = sub.add_parser("deploy", help="copy checked-in translation files into a game tree")
    deploy.add_argument("--game-root", required=True)
    deploy.add_argument("--staging-root", default=str(DEPLOY_ROOT))
    deploy.add_argument("--dry-run", action="store_true")
    voice_manifest = sub.add_parser("voice-manifest")
    voice_manifest.add_argument("--catalog", required=True)
    voice_manifest.add_argument("--table", required=True)
    voice_manifest.add_argument("--speaker-capture", required=True)
    voice_manifest.add_argument("--assignments", required=True)
    voice_manifest.add_argument("--output-dir", required=True)
    voice_generate = sub.add_parser("voice-generate")
    voice_generate.add_argument("--manifest-dir", required=True)
    voice_generate.add_argument("--output-root", required=True)
    voice_generate.add_argument("--language", choices=("en", "zh", "both"), required=True)
    voice_generate.add_argument("--dry-run", action="store_true")
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
        fallback = Path(args.fallback_usecode) if args.fallback_usecode else None
        entries = extract_catalog(
            Path(args.mod_root), Path(args.ucxt), runtime, fallback,
            include_runtime_terms=args.include_static or runtime is not None,
            terms=Path(args.terms),
        )
        # A CLI extraction without a runtime capture is the static dialogue
        # catalog used by the legacy candidate workflow.
        if runtime is None and not args.include_static:
            entries = [entry for entry in entries if entry.kind == "dialogue"]
        write_catalog(Path(args.output), entries); return 0
    if args.command == "import-fallback-books":
        additions = extract_usecode_translation_rows(
            Path(args.english_usecode), Path(args.chinese_usecode), Path(args.ucxt)
        )
        table = Path(args.table)
        write_runtime_table(table, merge_runtime_rows(load_runtime_table(table), additions))
        print(f"Imported {len(additions)} fallback book/scroll rows into {table}")
        return 0
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
            report = correctness_report(
                catalog, rows, Path(args.glossary), None, args.semantic_strict,
                Path(args.names) if args.names else None, Path(args.terms),
            )
        else:
            correctness = correctness_report(
                catalog, rows, Path(args.glossary), None, args.semantic_strict,
                Path(args.names) if args.names else None, Path(args.terms),
            )
            report = combine_audit_reports(coverage, correctness)
        if raw: report = merge_input_issues(report, raw)
        write_json_report(Path(args.report), report); print(format_terminal_report(report)); return report_exit_code(report, args.strict)
    if args.command == "emit":
        emit_approved_table(load_catalog(Path(args.catalog)), Path(args.review), Path(args.output)); return 0
    if args.command == "deploy":
        game_root = Path(args.game_root).resolve()
        report = deploy_staged_files(
            game_root,
            Path(args.staging_root),
            dry_run=args.dry_run,
        )
        label = "planned" if report.dry_run else "copied"
        for path in report.copied:
            print(f"{label}\t{path.relative_to(game_root).as_posix()}")
        for path in report.skipped:
            print(f"skipped\t{path.relative_to(game_root).as_posix()}")
        print(
            "Deployment: "
            f"copied={len(report.copied)} "
            f"skipped={len(report.skipped)} "
            f"dry_run={int(report.dry_run)}"
        )
        return 0
    if args.command == "voice-manifest":
        rows = build_voice_rows(
            load_catalog(Path(args.catalog)),
            load_runtime_table(Path(args.table)),
            speaker_map_from_capture(load_speaker_capture(Path(args.speaker_capture))),
            load_voice_assignments(Path(args.assignments)),
        )
        output_dir = Path(args.output_dir)
        write_generation_manifests(output_dir, rows)
        collisions = voice_key_collisions(rows)
        approved = sum(row.status == "approved" for row in rows)
        review = sum(row.status != "approved" for row in rows)
        print(
            "Voice manifest: "
            f"approved={approved} review={review} skipped={review} "
            f"collisions={len(collisions)}"
        )
        return 2 if collisions else 0
    if args.command == "voice-generate":
        generator = Path(__file__).parents[1] / "voice_acting" / "generate_qwen3_voice.py"
        return run_voice_generation(
            Path(args.manifest_dir), Path(args.output_root), args.language,
            args.dry_run, generator,
        )
    if args.command == "convert-traditional":
        if not (args.check or args.dry_run) and not args.output:
            raise ValueError("--output is required unless --check or --dry-run is used")
        report = convert_runtime_table(
            Path(args.input),
            Path(args.output) if args.output else None,
            check=args.check,
            dry_run=args.dry_run,
        )
        print(
            "Traditional conversion: "
            f"rows={report.rows} changed_rows={report.changed_rows} "
            f"changed_characters={report.changed_characters} "
            f"unresolved={len(report.unresolved)}"
        )
        if args.dry_run:
            for change in report.changes:
                print(f"{change.kind}\t{change.key}\t{change.before} => {change.after}")
        if report.unresolved:
            for key, character in report.unresolved:
                print(f"unresolved Simplified character {character} in {key}")
            return 2
        if args.check and report.changed_rows:
            return 1
        return 0
    if args.command == "review-html":
        audit = None
        if args.audit:
            audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))
        speaker_map = None
        if args.speaker_map:
            speaker_map = json.loads(Path(args.speaker_map).read_text(encoding="utf-8"))
            if isinstance(speaker_map, dict) and isinstance(speaker_map.get("speakers"), dict):
                speaker_map = speaker_map["speakers"]
            if not isinstance(speaker_map, dict):
                raise ValueError("speaker map must be a JSON object")
        if args.speaker_capture:
            runtime_speakers = speaker_map_from_capture(
                load_speaker_capture(Path(args.speaker_capture))
            )
            speaker_map = {**(speaker_map or {}), **runtime_speakers}
        write_review_html(
            Path(args.output),
            load_catalog(Path(args.catalog)),
            load_runtime_table(Path(args.table)),
            model=args.model,
            prompt_version=args.prompt_version,
            audit=audit,
            speaker_map=speaker_map,
        )
        return 0
    parser.error("a command is required")

if __name__ == '__main__':
    raise SystemExit(main())
