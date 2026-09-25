import importlib.util

import pytest
from typer.testing import CliRunner

from lig.cli.app import app

runner = CliRunner()

SUBCOMMANDS = ["generate", "edit", "seeds", "bench", "models", "doctor", "config", "serve"]


def test_help_lists_all_subcommands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in SUBCOMMANDS:
        assert name in result.output


STUBS = [n for n in SUBCOMMANDS if n not in ("config", "doctor")]


@pytest.mark.parametrize("name", STUBS)
def test_stub_exits_zero(name, monkeypatch):
    # `serve` checks for its optional extra; pin it as installed so the result does not
    # depend on whether this venv was synced with `--extra serve` (CI's is not).
    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda mod, *a: object() if mod in {"fastapi", "uvicorn"} else real_find_spec(mod, *a),
    )
    result = runner.invoke(app, [name])
    assert result.exit_code == 0
    assert "not implemented" in result.output
