import json
from pathlib import Path

import platformdirs
import pytest
from typer.testing import CliRunner

from lig.cli.app import app
from lig.core import config as cfg
from lig.models import cache
from lig.models.registry import load_registry

runner = CliRunner()


@pytest.fixture
def models_dir(tmp_path, monkeypatch):
    target = tmp_path / "cache" / "models"
    monkeypatch.setenv("LIG_MODELS_DIR", str(target))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    return target


def test_default_models_dir_is_user_cache_dir():
    assert cfg.Settings().models_dir == Path(platformdirs.user_cache_dir("lig")) / "models"


def test_ensure_models_dir_creates_it(tmp_path):
    target = tmp_path / "a" / "b"
    assert cache.ensure_models_dir(target) == target
    assert target.is_dir()


def test_status_transitions(tmp_path):
    artifact = load_registry().artifacts[0]
    assert cache.artifact_status(tmp_path, artifact) == "missing"
    part = tmp_path / f"{artifact.filename}.part"
    part.write_bytes(b"x")
    assert cache.artifact_status(tmp_path, artifact) == "partial"
    part.unlink()
    (tmp_path / artifact.filename).write_bytes(b"x")
    assert cache.artifact_status(tmp_path, artifact) == "unverified"
    cache.marker_path(tmp_path, artifact).write_text("")
    assert cache.artifact_status(tmp_path, artifact) == "installed"


def test_list_creates_dir_and_shows_table(models_dir):
    result = runner.invoke(app, ["models", "list"])
    assert result.exit_code == 0, result.output
    assert models_dir.is_dir()
    for word in ("name", "role", "engines", "size", "license", "status", "missing", "free"):
        assert word in result.output


def test_list_engine_filter(models_dir):
    data = json.loads(runner.invoke(app, ["models", "list", "--engine", "sdcpp", "--json"]).output)
    assert data["artifacts"]
    assert all("sdcpp" in a["engines"] for a in data["artifacts"])
    none = json.loads(runner.invoke(app, ["models", "list", "--engine", "nope", "--json"]).output)
    assert none["artifacts"] == []


def test_list_json_reports_status_and_totals(models_dir):
    artifact = load_registry().artifacts[0]
    models_dir.mkdir(parents=True)
    (models_dir / artifact.filename).write_bytes(b"12345")
    data = json.loads(runner.invoke(app, ["models", "list", "--json"]).output)
    row = next(a for a in data["artifacts"] if a["name"] == artifact.name)
    assert row["status"] == "unverified"
    assert set(row) >= {"name", "role", "engines", "size_bytes", "license", "status"}
    assert data["cache_bytes"] == 5
    assert data["free_bytes"] > 0
    assert data["models_dir"] == str(models_dir)
