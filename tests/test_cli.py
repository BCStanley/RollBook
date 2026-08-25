"""Phase 0 smoke tests: the CLI installs and wires up correctly.

These don't test any pipeline behaviour yet (there isn't any) — just that
`rollbook --help` and every registered subcommand group are reachable,
which is this phase's whole exit criterion.
"""

from __future__ import annotations

import pytest

from rollbook.__about__ import __version__
from rollbook.cli import main

SYSTEM_SUBCOMMANDS = [
    "ocr",
    "clean",
    "parse",
    "canon",
    "build-db",
    "match",
    "narrow",
    "review",
    "index",
    "models",
]


def test_no_args_prints_help_and_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "rollbook" in captured.out.lower()


def test_help_flag_exits_cleanly() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0


@pytest.mark.parametrize("subcommand", SYSTEM_SUBCOMMANDS)
def test_each_system_subcommand_help_is_registered(subcommand: str) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([subcommand, "--help"])
    assert excinfo.value.code == 0


@pytest.mark.parametrize("subcommand", SYSTEM_SUBCOMMANDS)
def test_each_system_group_alone_prints_help(
    subcommand: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main([subcommand])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert subcommand in captured.out.lower()


@pytest.mark.parametrize("subcommand", SYSTEM_SUBCOMMANDS)
def test_each_system_stub_reports_not_yet_implemented(
    subcommand: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main([subcommand, "run"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "not yet implemented" in captured.out.lower()


def test_version_command_matches_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["version"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == __version__
