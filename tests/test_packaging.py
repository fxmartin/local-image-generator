import importlib.util
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

import lig
from lig.cli.app import app

runner = CliRunner()
PYPROJECT = tomllib.loads((Path(__file__).resolve().parent.parent / "pyproject.toml").read_text())


def test_version_flag_prints_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert lig.__version__ in result.output


def test_package_version_matches_pyproject():
    assert lig.__version__ == PYPROJECT["project"]["version"]


def test_doctor_runs():
    assert runner.invoke(app, ["doctor"]).exit_code == 0


def test_serve_without_extra_prints_install_hint(monkeypatch):
    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: None if name in {"fastapi", "uvicorn"} else real_find_spec(name, *a),
    )
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 1
    assert "uv tool install" in result.output
    assert "[serve]" in result.output


def test_serve_with_extra_installed_runs(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: object())
    assert runner.invoke(app, ["serve"]).exit_code == 0


def test_serve_help_works_without_extra():
    assert runner.invoke(app, ["serve", "--help"]).exit_code == 0


@pytest.mark.parametrize(
    "key", ["name", "description", "license", "classifiers", "urls", "authors", "keywords"]
)
def test_project_metadata_complete(key):
    assert PYPROJECT["project"].get(key)


def test_extras_are_optional():
    extras = PYPROJECT["project"]["optional-dependencies"]
    assert {"serve", "mlx"} <= extras.keys()
    base = " ".join(PYPROJECT["project"]["dependencies"])
    assert "fastapi" not in base and "mflux" not in base
