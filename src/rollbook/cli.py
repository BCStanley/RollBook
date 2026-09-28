"""RollBook's command-line interface.

Deliberately built on the standard library (`argparse`) rather than a
third-party CLI framework: this is a zero-runtime-dependency package for
as long as that's sufficient, in keeping with the project's goal of being
trivially reproducible on any researcher's machine. A richer framework
(e.g. typer) can replace this file later if a phase genuinely needs UX
argparse can't give it — nothing outside this module depends on how the
CLI is built.

One subcommand group per pipeline system (see `rollbook/__init__.py` for
the full list). Each group currently exposes a single placeholder `run`
subcommand that reports the system isn't built yet; real subcommands
replace these placeholders as each phase of the project plan lands,
without changing how the CLI is wired together.
"""

from __future__ import annotations

import argparse
import sys
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from rollbook.ocr_io.manifest import ManifestError, ensure_manifest_cached, load_manifest, find_model, ModelEntry, ensure_model_cached
from rollbook.ocr_io.run_kraken import render_pdf_pages, run_kraken_per_page, concatenate_pages
import tempfile
from rich.console import Console
from rollbook.cleaning.pages import load_lines
from rollbook.cleaning.review_app import ReviewApp, export_clean_text

from rollbook.__about__ import __version__

# (subcommand name, system module name, phase it's implemented in, help text)
SYSTEM_GROUPS: list[tuple[str, str, int, str]] = [
    ("ocr", "ocr_io", 2, "Adapt scans to raw text via a trained OCR model."),
    ("clean", "cleaning", 2, "Correct & normalize raw OCR output."),
    ("parse", "parsing", 3, "Split cleaned lines into structured case records."),
    ("canon", "canonical", 4, "Canonicalize case records into matchable tokens."),
    ("build-db", "candidatedb", 5, "Build & query the candidate case database."),
    ("match", "matching", 6, "Rank candidate matches for each target case."),
    ("narrow", "narrow", 7, "Format ranked candidates for human review."),
    ("review", "review", 7, "Ingest a hand-reviewed CSV into confirmed matches."),
    ("index", "index", 7, "Compile confirmed matches into the final index."),
    ("models", "ocr_io.manifest", 2, "List and fetch OCR model weights."),
]

console = Console()

def default_cache_dir() -> Path:
    xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache_home:
        base = Path(xdg_cache_home)
    else:
        base = Path.home() / ".cache"
    return base / "rollbook"


def _not_yet_implemented(system: str, phase: int) -> int:
    print(f"'{system}' is not yet implemented — landing in Phase {phase} of the project plan.")
    return 1


def _print_help_and_succeed(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 0


def _print_version() -> int:
    print(__version__)
    return 0

# Handling Models

def _list_models() -> int:
    cache_dir = default_cache_dir()
    try:
        manifest_path = ensure_manifest_cached(cache_dir)
        manifest = load_manifest(manifest_path)
    except ManifestError as e:
        print(f"models -- list: could not list models: {e}")
        return 1
    print("=== Segmentation Models ===")
    for model in manifest.segmentation_models:
        print(f"{model.name}@{model.version}")
    print("\n\n=== Recognition Models ===")
    for model in manifest.recognition_models:
        print(f"    {model.name}@{model.version}")
    return 0


def _run_ocr(
        pdf_path: Path,
        output_path: Path,
        seg_selector: str,
        ocr_selector: str,
        dpi: int,
) -> int:
    def _print_progress(page: int, total: int) -> None:
        print(f"\rocr: completed page {page}/{total}.\n", end="", flush=True)
    cache_dir = default_cache_dir()
    try:
        manifest_path = ensure_manifest_cached(cache_dir)
        manifest = load_manifest(manifest_path)
        ocr_model_entry: ModelEntry = find_model(ocr_selector, manifest.recognition_models)
        seg_model_entry: ModelEntry = find_model(seg_selector, manifest.segmentation_models)
        print(f"""ocr: Found ModelEntries for {seg_selector} and {ocr_selector}.
        Ensuring they are cached.
        """)
        ocr_model_path: Path = ensure_model_cached(ocr_model_entry, cache_dir)
        seg_model_path: Path = ensure_model_cached(seg_model_entry, cache_dir)
        print(f"""ocr: Models {seg_selector} and {ocr_selector} cached at {str(seg_model_path)} and {str(ocr_model_path)}.
        """)
    except ManifestError as e:
        print(f"ocr: {e}")
        return 1
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with console.status(f"ocr: Rendering {pdf_path} as png images..."):
                images: tuple[Path, ...] = render_pdf_pages(pdf_path, tmp_path, dpi=dpi)
            print(f"ocr: Rendered {len(images)} pages. Running ocr on each.")
            txts: tuple[Path, ...] = run_kraken_per_page(
                image_paths = images,
                output_dir = tmp_path,
                seg_model_path = seg_model_path,
                ocr_model_path = ocr_model_path,
                extra_args = None,
                on_page_done = _print_progress)
            print("ocr: Finished ocr on individual pages. Concatenating.")
            final_txt = concatenate_pages(
                page_paths = txts,
                filename = str(output_path.name),
                output_dir = output_path.parent)
            print(f"ocr: completed ocr on {str(pdf_path)}: {str(output_path)}.")
        return 0
    except Exception as e:
        print(f"ocr: {e}")
        return 1

def _run_clean(input_path: Path, history_path: Path | None) -> int:
    ReviewApp(input_path, history_path).run()
    return 0

def _export_clean(input_path: Path, output_path: Path) -> int:
    working_path = input_path.with_suffix(".working.txt")
    if not working_path.exists():
        print(f"clean: no working copy found at {working_path} -- run 'rollbook clean run {input_path}' first.")
        return 1
    lines = load_lines(working_path)
    output_path.write_text(export_clean_text(lines), encoding="utf-8")
    print(f"clean: exported: {output_path}")
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rollbook",
        description=(
            "Turn scans of 19th-century case indexes into a structured, "
            "queryable database of authorities."
        ),
    )
    parser.set_defaults(func=lambda _args: _print_help_and_succeed(parser))

    subparsers = parser.add_subparsers(
        dest="command", metavar="{" + ",".join(name for name, *_ in SYSTEM_GROUPS) + ",version}"
    )

    for name, system, phase, help_text in SYSTEM_GROUPS:
        group_parser = subparsers.add_parser(name, help=help_text, description=help_text)
        group_parser.set_defaults(func=lambda _args, gp=group_parser: _print_help_and_succeed(gp))
        group_sub = group_parser.add_subparsers(dest="subcommand")

        if name == "models":
            list_parser = group_sub.add_parser("list", help="List available OCR / segmentation models.")
            list_parser.set_defaults(func=lambda _args: _list_models())
        elif name == "ocr":
            run_parser = group_sub.add_parser("run", help="Run the OCR pipline on a PDF")
            run_parser.add_argument("input", type=Path, help="Input PDF file.")
            run_parser.add_argument("--output", required=True, type=Path, help="Output .txt file.")
            run_parser.add_argument("--seg-model", required=True, help="Segmentation model selector (name@version).")
            run_parser.add_argument("--ocr-model", required=True, help="Recognition model selector (name@version).")
            run_parser.add_argument("--dpi", type=int, default=400, help="Rendering DPI (default: 400).")
            run_parser.set_defaults(
                func=lambda args: _run_ocr(args.input, args.output, args.seg_model, args.ocr_model, args.dpi)
            )
        elif name == "clean":
            run_parser = group_sub.add_parser("run", help="Interactively review and correct OCR output.")
            run_parser.add_argument("input", type=Path, help="Input raw OCR .txt file.")
            run_parser.add_argument(
                "--history", type=Path, default=None,
                help="Correction history file (default: <input>.corrections.jsonl).",
            )
            run_parser.set_defaults(func=lambda args: _run_clean(args.input, args.history))
            export_parser = group_sub.add_parser(
                "export", help="Export the cleaned, marker-free text for a reviewed document."
            )
            export_parser.add_argument("input", type=Path, help="The same input path use with 'clean run'.")
            export_parser.add_argument("--output", required=True, type=Path, help="Output .txt file.")
            export_parser.set_defaults(func=lambda args: _export_clean(args.input, args.output))


        else: 
            run_parser = group_sub.add_parser("run", help=f"Run {name}. Not yet implemented.")
            run_parser.set_defaults(
                func=lambda _args, system=system, phase=phase: _not_yet_implemented(system, phase)
            )

    version_parser = subparsers.add_parser("version", help="Print the installed RollBook version.")
    version_parser.set_defaults(func=lambda _args: _print_version())

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func: Callable[[argparse.Namespace], int] = args.func
    return func(args)


def app() -> None:
    """Console-script entry point (see `[project.scripts]` in pyproject.toml)."""
    sys.exit(main())


if __name__ == "__main__":
    app()
