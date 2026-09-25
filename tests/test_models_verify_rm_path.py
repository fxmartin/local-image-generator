"""`lig models verify`, `rm` and `path` against a temp cache; no network."""

import hashlib

import pytest
from typer.testing import CliRunner

from lig.cli import app as cli_app
from lig.cli.app import app
from lig.models import cache
from lig.models.registry import Registry

runner = CliRunner()
PAYLOAD = b"weights" * 1000


def _art(name: str, payload: bytes = PAYLOAD) -> dict:
    return {
        "name": name,
        "repo": "r",
        "filename": f"{name}.gguf",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "engines": ["sdcpp"],
        "role": "bundle",
        "license": "mit",
        "url": "http://unused/" + name,
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setenv("LIG_MODELS_DIR", str(models))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("LIG_ENGINE", raising=False)
    registry = Registry.model_validate(
        {
            "artifacts": [_art("a"), _art("b")],
            "sets": {"s": {"engine": "sdcpp", "artifacts": ["a"]}},
        }
    )
    monkeypatch.setattr(cli_app, "load_registry", lambda: registry)
    return models, registry


def _install(models, registry, name, payload=PAYLOAD):
    art = registry.get(name)
    (models / art.filename).write_bytes(payload)
    cache.marker_path(models, art).write_text("")
    return art


def test_verify_healthy_prints_ok(env):
    models, reg = env
    _install(models, reg, "a")
    result = runner.invoke(app, ["models", "verify"])
    assert result.exit_code == 0, result.output
    assert "a: ok" in result.output


def test_verify_tampered_removes_marker_and_exits_1(env):
    models, reg = env
    art = _install(models, reg, "a", b"tampered")
    result = runner.invoke(app, ["models", "verify"])
    assert result.exit_code == 1
    assert "mismatch" in result.output
    assert not cache.marker_path(models, art).exists()


def test_verify_named_only_checks_that_artifact(env):
    models, reg = env
    _install(models, reg, "a")
    _install(models, reg, "b", b"bad")
    assert runner.invoke(app, ["models", "verify", "a"]).exit_code == 0
    assert runner.invoke(app, ["models", "verify", "b"]).exit_code == 1


def test_verify_skips_missing_and_unknown_name_fails(env):
    result = runner.invoke(app, ["models", "verify"])
    assert result.exit_code == 0
    assert "not installed" in result.output
    assert runner.invoke(app, ["models", "verify", "nope"]).exit_code == 1


def test_rm_confirms_with_size_and_deletes(env):
    models, reg = env
    art = _install(models, reg, "b")
    result = runner.invoke(app, ["models", "rm", "b"], input="y\n")
    assert result.exit_code == 0, result.output
    assert cache.human_size(len(PAYLOAD)) in result.output
    assert cache.artifact_status(models, art) == "missing"
    assert not cache.marker_path(models, art).exists()


def test_rm_declined_keeps_files(env):
    models, reg = env
    art = _install(models, reg, "b")
    result = runner.invoke(app, ["models", "rm", "b"], input="n\n")
    assert result.exit_code == 1
    assert cache.artifact_status(models, art) == "installed"


def test_rm_yes_skips_prompt(env):
    models, reg = env
    art = _install(models, reg, "b")
    assert runner.invoke(app, ["models", "rm", "b", "--yes"]).exit_code == 0
    assert cache.artifact_status(models, art) == "missing"


def test_rm_removes_part_and_corrupt_leftovers(env):
    models, reg = env
    art = reg.get("b")
    (models / f"{art.filename}.part").write_bytes(b"x")
    (models / f"{art.filename}.corrupt").write_bytes(b"x")
    assert runner.invoke(app, ["models", "rm", "b", "-y"]).exit_code == 0
    assert list(models.iterdir()) == []


def test_rm_nothing_present_exits_1(env):
    assert runner.invoke(app, ["models", "rm", "b", "--yes"]).exit_code == 1


def test_rm_warns_when_default_engine_loses_artifact(env, monkeypatch):
    models, reg = env
    _install(models, reg, "a")
    monkeypatch.setenv("LIG_ENGINE", "sdcpp")
    result = runner.invoke(app, ["models", "rm", "a", "--yes"])
    assert result.exit_code == 0
    assert "sdcpp" in result.output and "unavailable" in result.output


def test_rm_no_warning_for_unrelated_artifact(env, monkeypatch):
    models, reg = env
    _install(models, reg, "b")
    monkeypatch.setenv("LIG_ENGINE", "sdcpp")
    result = runner.invoke(app, ["models", "rm", "b", "--yes"])
    assert "unavailable" not in result.output


def test_path_installed_prints_absolute_path(env):
    models, reg = env
    _install(models, reg, "a")
    result = runner.invoke(app, ["models", "path", "a"])
    assert result.exit_code == 0
    assert result.stdout.strip() == str((models / "a.gguf").resolve())


def test_path_missing_prints_nothing_exits_1(env):
    result = runner.invoke(app, ["models", "path", "a"])
    assert result.exit_code == 1
    assert result.stdout == ""
