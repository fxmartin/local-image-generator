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


@pytest.mark.parametrize("name", SUBCOMMANDS)
def test_stub_exits_zero(name):
    result = runner.invoke(app, [name])
    assert result.exit_code == 0
    assert "not implemented" in result.output
