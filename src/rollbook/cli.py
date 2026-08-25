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
from collections.abc import Callable, Sequence

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


def _not_yet_implemented(system: str, phase: int) -> int:
    print(f"'{system}' is not yet implemented — landing in Phase {phase} of the project plan.")
    return 1


def _print_help_and_succeed(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 0


def _print_version() -> int:
    print(__version__)
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
