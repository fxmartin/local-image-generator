"""`lig models pull --for ENGINE [--quant Q]` and `lig models prune`; no network."""

import hashlib
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lig.cli import app as cli_app
from lig.cli.app import app
from lig.models import cache, downloader
from lig.models.registry import Registry

runner = CliRunner()
PAYLOAD = b"weights" * 100


def _art(name: str, engines: list[str], role: str = "bundle") -> dict:
    return {
        "name": name,
        "repo": "r",
        "filename": f"{name}.gguf",
        "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
        "size_bytes": len(PAYLOAD),
        "engines": engines,
        "role": role,
        "license": "mit",
        "url": "http://unused/" + name,
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setenv("LIG_MODELS_DIR", str(models))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(sys, "platform", "linux")
    registry = Registry.model_validate(
        {
            "artifacts": [
                _art("q4", ["sdcpp"]),
                _art("q8", ["sdcpp"]),
                _art("mlx-w", ["mlx"]),
                _art("retired", ["sdcpp"]),
            ],
            "sets": {
                "sdcpp-q4": {"engine": "sdcpp", "quant": "q4", "artifacts": ["q4"]},
                "sdcpp-q8": {"engine": "sdcpp", "quant": "q8", "artifacts": ["q8"]},
                "mlx-q8": {
                    "engine": "mlx",
                    "quant": "q8",
                    "platforms": ["darwin"],
                    "artifacts": ["mlx-w"],
                },
            },
        }
    )
    monkeypatch.setattr(cli_app, "load_registry", lambda: registry)
    monkeypatch.setattr(downloader, "free_bytes", lambda _p: 10**12)
    pulled: list[str] = []

    def fake_pull(artifact, models_dir, client, force=False, on_progress=None):
        pulled.append(artifact.name)
        (models_dir / artifact.filename).write_bytes(PAYLOAD)
        cache.marker_path(models_dir, artifact).write_text("")
        return downloader.PullOutcome(artifact)

    monkeypatch.setattr(downloader, "pull_artifact", fake_pull)
    return models, registry, pulled


def _install(models, registry, name):
    art = registry.get(name)
    (models / art.filename).write_bytes(PAYLOAD)
    cache.marker_path(models, art).write_text("")
    return art


def test_for_sdcpp_pulls_only_the_default_set_and_names_it(env):
    _, _, pulled = env
    result = runner.invoke(app, ["models", "pull", "--for", "sdcpp"])
    assert result.exit_code == 0, result.output
    assert pulled == ["q4"]
    assert "sdcpp-q4" in result.output and "q4" in result.output
    assert "registry default" in result.output


def test_disk_estimate_printed_before_download(env):
    result = runner.invoke(app, ["models", "pull", "--for", "sdcpp"])
    assert result.output.index("to download") < result.output.index("free disk")


def test_quant_picks_the_alternative(env):
    _, _, pulled = env
    result = runner.invoke(app, ["models", "pull", "--for", "sdcpp", "--quant", "q8"])
    assert result.exit_code == 0, result.output
    assert pulled == ["q8"]
    assert "sdcpp-q8" in result.output
    assert "registry default" not in result.output


def test_unknown_quant_exits_2_listing_choices(env):
    _, _, pulled = env
    result = runner.invoke(app, ["models", "pull", "--for", "sdcpp", "--quant", "q2"])
    assert result.exit_code == 2
    assert "q4" in result.output and "q8" in result.output
    assert pulled == []


def test_mlx_on_linux_is_unsupported_platform(env):
    _, _, pulled = env
    result = runner.invoke(app, ["models", "pull", "--for", "mlx"])
    assert result.exit_code == 2
    assert "unsupported platform" in result.output
    assert pulled == []


def test_quant_without_engine_exits_2(env):
    assert runner.invoke(app, ["models", "pull", "q4", "--quant", "q8"]).exit_code == 2


def test_engine_alias_still_works(env):
    _, _, pulled = env
    assert runner.invoke(app, ["models", "pull", "--engine", "sdcpp"]).exit_code == 0
    assert pulled == ["q4"]


def test_prune_lists_orphans_and_deletes_on_confirm(env):
    models, reg, _ = env
    keep = [_install(models, reg, n) for n in ("q4", "q8")]
    gone = [_install(models, reg, n) for n in ("mlx-w", "retired")]
    result = runner.invoke(app, ["models", "prune"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "mlx-w" in result.output and "retired" in result.output
    assert "q4.gguf" not in result.output
    assert all(cache.artifact_status(models, a) == "missing" for a in gone)
    assert all(cache.artifact_status(models, a) == "installed" for a in keep)


def test_prune_declined_keeps_files(env):
    models, reg, _ = env
    art = _install(models, reg, "retired")
    assert runner.invoke(app, ["models", "prune"], input="n\n").exit_code == 1
    assert cache.artifact_status(models, art) == "installed"


def test_prune_yes_skips_prompt_and_removes_leftovers(env):
    models, reg, _ = env
    art = reg.get("retired")
    (models / f"{art.filename}.part").write_bytes(b"x")
    assert runner.invoke(app, ["models", "prune", "--yes"]).exit_code == 0
    assert list(models.iterdir()) == []


def test_prune_nothing_to_do(env):
    models, reg, _ = env
    _install(models, reg, "q4")
    result = runner.invoke(app, ["models", "prune"])
    assert result.exit_code == 0
    assert "nothing to prune" in result.output


def test_prune_unlink_failure_exits_1(env, monkeypatch):
    models, reg, _ = env
    _install(models, reg, "retired")

    def bad_unlink(self):
        raise OSError("boom")

    monkeypatch.setattr(Path, "unlink", bad_unlink)
    result = runner.invoke(app, ["models", "prune", "--yes"])
    assert result.exit_code == 1
    assert "error: boom" in result.output
