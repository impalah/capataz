from __future__ import annotations

from pathlib import Path

import pytest

from capataz_runner.ssh_commands import SshCommandsError, load_ssh_commands

RUNNER_ROOT = Path(__file__).resolve().parents[1]


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "ssh_commands.yml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_shipped_allow_list_loads_and_every_command_renders() -> None:
    commands = load_ssh_commands(RUNNER_ROOT / "ssh_commands.yml")
    assert {"uptime", "disk_usage", "systemd_status"} <= set(commands)
    sample = {"systemd_status": {"unit": "docker.service"}}
    for command_id, command in commands.items():
        argv = command.render(sample.get(command_id, {}))
        assert argv[0] == command.argv[0]
    assert commands["disk_usage"].render({}) == ("df", "-h", "/")


@pytest.mark.parametrize(
    "text",
    [
        "commands: []\n",
        "other: {}\n",
        "commands:\n  Bad-Id: {argv: [uptime]}\n",
        "commands:\n  x: {argv: []}\n",
        "commands:\n  x: {argv: ['{p}'], params: {p: {pattern: '^a$'}}}\n",
        "commands:\n  x: {argv: [uptime, '{p}']}\n",
        "commands:\n  x: {argv: [uptime], params: {p: {pattern: '^a$'}}}\n",
        "commands:\n  x: {argv: [ls, '{p}'], params: {p: {pattern: '^a$', enum: [a]}}}\n",
        "commands:\n  x: {argv: [ls, '{p}'], params: {p: {pattern: '('}}}\n",
        "commands:\n  x: {argv: [ls, '{p}'], params: {p: {pattern: '^a$', default: b}}}\n",
        "commands:\n  x: {argv: [ls, '{p}'], params: {p: {enum: []}}}\n",
        "commands:\n  x: {argv: [uptime], timeout_seconds: 0}\n",
        "commands:\n  x: {argv: [uptime], shell: true}\n",
        "commands: [\n",
    ],
)
def test_invalid_allow_lists_are_rejected(tmp_path: Path, text: str) -> None:
    with pytest.raises(SshCommandsError):
        load_ssh_commands(_write(tmp_path, text))


def test_an_unreadable_allow_list_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(SshCommandsError, match="cannot read"):
        load_ssh_commands(tmp_path / "missing.yml")


def test_placeholders_are_whole_elements_only(tmp_path: Path) -> None:
    commands = load_ssh_commands(
        _write(
            tmp_path,
            "commands:\n  x:\n    argv: [echo, 'prefix-{p}', '{p}']\n"
            "    params: {p: {enum: [a]}}\n",
        )
    )
    # 'prefix-{p}' is a literal, never a partial substitution.
    assert commands["x"].render({"p": "a"}) == ("echo", "prefix-{p}", "a")
