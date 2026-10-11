"""Story 08.1-003: `--json`, `--open` and dynamic shell completion."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lig.cli import scripting
from lig.cli.app import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    for key in ("LIG_ENGINE", "LIG_SIZE", "LIG_STEPS", "LIG_OUTPUT_DIR", "LIG_DEFAULT_HOST"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def opened(monkeypatch):
    """Record viewer launches instead of starting a real viewer."""
    calls: list[list[str]] = []
    monkeypatch.setattr(scripting, "_popen", lambda argv, **_: calls.append(argv))
    return calls


SMALL = ["--engine", "fake", "--size", "256x256", "--steps", "2"]


# --json


def test_generate_json_is_one_document_matching_the_sidecar(tmp_path):
    result = runner.invoke(app, ["generate", "a lighthouse", *SMALL, "--json"])
    assert result.exit_code == 0, result.output
    doc = json.loads(result.stdout)
    png = Path(doc["path"])
    sidecar = json.loads(png.with_suffix(".json").read_text())
    assert doc["sidecar_path"] == str(png.with_suffix(".json"))
    assert {k: doc[k] for k in sidecar} == sidecar
    assert "loaded in" in result.stderr  # progress stays on stderr


def test_edit_json_carries_the_source(tmp_path):
    src = Path(json.loads(runner.invoke(app, ["generate", "x", *SMALL, "--json"]).stdout)["path"])
    result = runner.invoke(app, ["edit", str(src), "blue", *SMALL, "--json"])
    assert result.exit_code == 0, result.output
    doc = json.loads(result.stdout)
    assert doc["source_path"] and Path(doc["path"]).exists()


def test_seeds_json_lists_every_image_and_the_sheet(tmp_path):
    result = runner.invoke(app, ["seeds", "x", "-n", "2", "--seed-start", "7", *SMALL, "--json"])
    assert result.exit_code == 0, result.output
    doc = json.loads(result.stdout)
    assert doc["seed_start"] == 7
    assert [image["seed"] for image in doc["images"]] == [7, 8]
    assert Path(doc["sheet"]).exists()


def test_seeds_json_without_sheet_has_null_sheet_and_random_start(tmp_path):
    result = runner.invoke(app, ["seeds", "x", "-n", "1", *SMALL, "--no-sheet", "--json"])
    doc = json.loads(result.stdout)  # "seed start:" must not leak onto stdout
    assert doc["sheet"] is None and isinstance(doc["seed_start"], int)


def test_bench_json_is_the_report(tmp_path):
    result = runner.invoke(app, ["bench", "--engines", "fake", "--size", "256x256",
                                 "--steps", "2", "--json"])  # fmt: skip
    assert result.exit_code == 0, result.output
    doc = json.loads(result.stdout)
    written = json.loads(next((tmp_path / "bench").glob("*.json")).read_text())
    assert doc == written
    assert "wrote" in result.stderr


# --open


@pytest.mark.parametrize(("platform", "viewer"), [("linux", "xdg-open"), ("darwin", "open")])
def test_open_uses_the_platform_viewer(tmp_path, opened, monkeypatch, platform, viewer):
    monkeypatch.setattr(scripting.sys, "platform", platform)
    result = runner.invoke(app, ["generate", "x", *SMALL, "--open"])
    assert result.exit_code == 0, result.output
    assert opened == [[viewer, result.stdout.strip().splitlines()[-1]]]


def test_open_failure_is_a_warning_not_an_error(tmp_path, monkeypatch):
    def missing(argv, **_):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(scripting, "_popen", missing)
    result = runner.invoke(app, ["generate", "x", *SMALL, "--open"])
    assert result.exit_code == 0, result.output
    assert "warning: cannot open" in result.stderr


def test_edit_opens_the_edited_image(tmp_path, opened):
    src = runner.invoke(app, ["generate", "x", *SMALL]).stdout.strip().splitlines()[-1]
    result = runner.invoke(app, ["edit", src, "blue", *SMALL, "--open"])
    assert result.exit_code == 0, result.output
    assert opened[-1][1] == result.stdout.strip().splitlines()[-1]


def test_seeds_opens_the_sheet_or_else_each_image(tmp_path, opened):
    runner.invoke(app, ["seeds", "x", "-n", "2", *SMALL, "--open"])
    assert len(opened) == 1 and opened[0][1].endswith("_sheet.png")
    opened.clear()
    runner.invoke(app, ["seeds", "x", "-n", "2", *SMALL, "--open", "--no-sheet"])
    assert len(opened) == 2


# completion


def test_engine_completion_lists_known_engines():
    assert scripting.complete_engine("") == ["auto", "fake", "mlx", "ncnn", "remote", "sdcpp"]
    assert scripting.complete_engine("s") == ["sdcpp"]


def test_artifact_completion_reads_the_registry():
    names = scripting.complete_artifact("")
    assert names and all(isinstance(n, str) for n in names)
    prefix = names[0][:3]
    assert all(n.startswith(prefix) for n in scripting.complete_artifact(prefix))


def test_host_completion_reads_config_hosts(tmp_path):
    config = tmp_path / "cfg" / "lig" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('[hosts]\nm3max = "http://a:7860"\nhomelab = "http://b:7860"\n')
    assert scripting.complete_host("") == ["homelab", "m3max"]
    assert scripting.complete_host("m") == ["m3max"]


def test_host_completion_survives_a_broken_config(tmp_path):
    config = tmp_path / "cfg" / "lig" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("not = [toml")
    assert scripting.complete_host("") == []


def test_completion_is_wired_into_the_cli():
    env = {"_LIG_COMPLETE": "complete_bash", "COMP_WORDS": "lig generate x --engine s",
           "COMP_CWORD": "4"}  # fmt: skip
    result = runner.invoke(app, [], env=env, prog_name="lig")
    assert "sdcpp" in result.stdout


def test_install_completion_is_offered():
    assert "--install-completion" in runner.invoke(app, ["--help"]).stdout
