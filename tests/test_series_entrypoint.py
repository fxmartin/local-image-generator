"""`lig-series` ships with `lig`, its help needs no `gemma`, and the README documents it."""

import re
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from lig.series.cli import app

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())
README = (ROOT / "README.md").read_text()
runner = CliRunner()


def _series_section() -> str:
    return README.split("### Photo series")[1].split("\n## ")[0]


def test_entry_points_are_installed_together():
    scripts = PYPROJECT["project"]["scripts"]
    assert scripts["lig"] == "lig.cli.app:app"
    assert scripts["lig-series"] == "lig.series.cli:app"


def test_help_works_without_gemma(monkeypatch):
    monkeypatch.setenv("PATH", "")
    result = runner.invoke(app, ["--help"], terminal_width=200)
    assert result.exit_code == 0, result.output
    assert "--gemma" in result.output


def test_readme_documents_every_help_flag():
    help_text = runner.invoke(app, ["--help"], terminal_width=200).output
    flags = set(re.findall(r"--[a-z][a-z-]+", help_text))
    flags.discard("--help")
    section = _series_section()
    missing = {f for f in flags if f not in section}
    assert not missing, missing


def test_readme_photo_series_section_content():
    section = _series_section()
    for needle in ("--plan-only", "--from-plan", "--character", "M3 Max", "30 steps"):
        assert needle in section, needle
    assert "gemma" in section


def test_module_main_guard_runs_the_app(monkeypatch):
    import runpy
    import sys

    monkeypatch.setattr(sys, "argv", ["lig-series", "--help"])
    try:
        runpy.run_module("lig.series.cli", run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 0
    else:  # pragma: no cover
        raise AssertionError("expected SystemExit")
