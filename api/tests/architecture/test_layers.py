"""Enforces the hexagonal-architecture layer contracts declared in pyproject.toml (CR-004)."""

from __future__ import annotations

from click.testing import CliRunner
from importlinter.cli import lint_imports_command


def test_architecture_layer_contracts_are_not_violated() -> None:
    result = CliRunner().invoke(lint_imports_command, ["--no-cache"])
    assert result.exit_code == 0, (
        "import-linter contract violation (see pyproject.toml [tool.importlinter]):\n"
        f"{result.output}"
    )
