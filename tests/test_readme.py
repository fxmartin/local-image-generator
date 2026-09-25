"""The README is a contract: its examples must match `lig --help`, and it must stay portable."""

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lig.cli.app import app

README = (Path(__file__).parent.parent / "README.md").read_text()
runner = CliRunner()

COMMANDS = ["generate", "edit", "seeds", "bench", "models"]
# Longest first so `lig models pull` is matched before `lig models`.
SUBCOMMANDS = {"bench": ["compare", "render"], "models": ["list", "pull", "verify", "rm", "path"]}


def _code_blocks() -> list[str]:
    return re.findall(r"```sh\n(.*?)```", README, re.S)


def _lig_lines() -> list[list[str]]:
    lines = []
    for block in _code_blocks():
        for line in block.splitlines():
            line = line.split("#")[0].strip()
            if line.startswith("lig "):
                lines.append(line.split())
    return lines


def _help(*path: str) -> str:
    result = runner.invoke(app, [*path, "--help"], terminal_width=200)
    assert result.exit_code == 0, result.output
    return result.output


def test_readme_stays_short():
    assert len(README.splitlines()) <= 300


def test_readme_has_no_hardcoded_hosts_or_home_paths():
    assert not re.search(r"/home/|/Users/|\.ts\.net|home-lab|hf_[A-Za-z0-9]{10}", README)


@pytest.mark.parametrize("command", COMMANDS)
def test_each_command_has_a_section_and_an_example(command):
    assert f"### `lig {command}`" in README
    assert any(line[1] == command for line in _lig_lines())


def test_every_flag_in_examples_exists_in_help():
    checked = 0
    for words in _lig_lines():
        command = words[1]
        if command not in COMMANDS:
            continue
        path = [command]
        if command in SUBCOMMANDS and len(words) > 2 and words[2] in SUBCOMMANDS[command]:
            path.append(words[2])
        help_text = _help(*path)
        for word in words[2:]:
            if word.startswith("-") and word != "-":
                assert word.split("=")[0] in help_text, f"{' '.join(words)}: {word} not in help"
                checked += 1
    assert checked >= 8


def test_documented_exit_code_meanings_match_the_code():
    assert "**3** memory pre-flight refusal" in README
    assert "**4** engine unavailable" in README
    assert "--force" in _help("generate")


def test_examples_run_against_the_fake_engine(tmp_path):
    result = runner.invoke(
        app,
        [
            "generate",
            "a fox",
            "--engine",
            "fake",
            "--size",
            "256x256",
            "--steps",
            "1",
            "--out",
            str(tmp_path),
            "-q",
        ],
    )
    assert result.exit_code == 0
    assert list(tmp_path.glob("*.png"))
