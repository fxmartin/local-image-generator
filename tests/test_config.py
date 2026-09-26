import itertools
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lig.cli.app import app
from lig.core import config as cfg

runner = CliRunner()

# key -> (default-layer sentinel is the model default; values per layer)
MATRIX = {
    "engine": ("sdcpp", "ncnn", "mlx"),
    "output_dir": ("/f/out", "/e/out", "/x/out"),
    "models_dir": ("/f/models", "/e/models", "/x/models"),
    "default_host": ("flag-host", "env-host", "file-host"),
    "steps": (11, 22, 33),
    "size": ("64x64", "128x128", "256x256"),
}
LAYERS = ("flag", "env", "file")


def _toml_val(v):
    return str(v) if isinstance(v, int) else f'"{v}"'


@pytest.mark.parametrize("key", MATRIX)
@pytest.mark.parametrize(
    "present", [c for n in range(4) for c in itertools.combinations(LAYERS, n)]
)
def test_precedence_matrix(tmp_path, key, present):
    flag_v, env_v, file_v = MATRIX[key]
    path = tmp_path / "config.toml"
    if "file" in present:
        path.write_text(f"{key} = {_toml_val(file_v)}\n")
    res = cfg.load_settings(
        flags={key: flag_v} if "flag" in present else {},
        env={f"LIG_{key.upper()}": str(env_v)} if "env" in present else {},
        path=path,
    )
    expected = next((layer for layer in LAYERS if layer in present), "default")
    assert res.provenance[key] == expected
    if expected == "default":
        assert getattr(res.settings, key) == getattr(cfg.Settings(), key)
    else:
        got = getattr(res.settings, key)
        want = dict(zip(LAYERS, MATRIX[key], strict=True))[expected]
        assert str(got) == str(want)


def test_none_flag_is_ignored(tmp_path):
    res = cfg.load_settings(flags={"engine": None}, env={}, path=tmp_path / "x.toml")
    assert res.provenance["engine"] == "default"


def test_nested_env_and_file(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('[serve]\nbind = "0.0.0.0:1"\n')
    res = cfg.load_settings(env={}, path=path)
    assert res.settings.serve.bind == "0.0.0.0:1"
    assert res.provenance["serve.bind"] == "file"
    res = cfg.load_settings(env={"LIG_SERVE__BIND": "1.1.1.1:2"}, path=path)
    assert res.settings.serve.bind == "1.1.1.1:2"
    assert res.provenance["serve.bind"] == "env"


def test_unknown_key_warns_with_line_and_continues(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text("steps = 5\n\nbogus = 1\n[serve]\nnope = 2\n")
    res = cfg.load_settings(env={}, path=path)
    assert res.settings.steps == 5
    assert any("bogus" in w and "line 3" in w for w in res.warnings)
    assert any("serve.nope" in w and "line 5" in w for w in res.warnings)


def test_invalid_value_raises(tmp_path):
    with pytest.raises(cfg.ConfigError, match="steps"):
        cfg.load_settings(env={"LIG_STEPS": "abc"}, path=tmp_path / "x.toml")
    with pytest.raises(cfg.ConfigError, match="size"):
        cfg.load_settings(env={"LIG_SIZE": "100x100"}, path=tmp_path / "x.toml")


def test_invalid_toml_raises(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text("= broken")
    with pytest.raises(cfg.ConfigError, match=str(path)):
        cfg.load_settings(env={}, path=path)


def test_default_config_path_is_platform_dir():
    assert cfg.default_config_path().name == "config.toml"
    assert "lig" in cfg.default_config_path().parts


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    path = tmp_path / "lig" / "config.toml"
    monkeypatch.setattr(cfg, "default_config_path", lambda: path)
    for k in list(__import__("os").environ):
        if k.startswith("LIG_"):
            monkeypatch.delenv(k)
    return path


def test_config_show(cfg_path, monkeypatch):
    cfg_path.parent.mkdir()
    cfg_path.write_text("steps = 7\nbogus = 1\n")
    monkeypatch.setenv("LIG_ENGINE", "ncnn")
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert str(cfg_path) in result.output
    lines = {ln.split()[0]: ln for ln in result.output.splitlines() if ln.split()}
    assert "ncnn" in lines["engine"] and "env" in lines["engine"]
    assert "7" in lines["steps"] and "file" in lines["steps"]
    assert "default" in lines["size"]
    assert "serve.bind" in lines
    assert "bogus" in result.output


def test_config_show_bad_value_exits_nonzero(cfg_path, monkeypatch):
    monkeypatch.setenv("LIG_STEPS", "abc")
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 1


def test_config_init_writes_then_refuses(cfg_path):
    result = runner.invoke(app, ["config", "init"])
    assert result.exit_code == 0
    text = cfg_path.read_text()
    assert text.lstrip().startswith("#")
    # the commented template must itself load cleanly
    res = cfg.load_settings(env={}, path=cfg_path)
    assert res.warnings == []
    before = text
    result = runner.invoke(app, ["config", "init"])
    assert result.exit_code == 1
    assert "exists" in result.output
    assert cfg_path.read_text() == before


def test_settings_paths_are_paths():
    assert isinstance(cfg.Settings().output_dir, Path)


def test_path_settings_expand_user(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('models_dir = "~/m"\n')
    res = cfg.load_settings(env={"LIG_OUTPUT_DIR": "~/o"}, path=path)
    assert res.settings.models_dir == Path.home() / "m"
    assert res.settings.output_dir == Path.home() / "o"


def test_non_utf8_file_raises_config_error(tmp_path):
    path = tmp_path / "c.toml"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(cfg.ConfigError, match=str(path)):
        cfg.load_settings(env={}, path=path)


def test_config_show_non_utf8_file_exits_nonzero(cfg_path):
    cfg_path.parent.mkdir()
    cfg_path.write_bytes(b"\xff\xfe")
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 1
    assert "error:" in result.output


def test_config_show_prints_brackets_literally(cfg_path, monkeypatch):
    monkeypatch.setenv("LIG_DEFAULT_HOST", "[bold]host")
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "[bold]host" in result.output


def test_serve_idle_ttl_default_and_validation():
    assert cfg.Settings().serve.idle_ttl == 600
    with pytest.raises(ValueError):
        cfg.Settings(serve={"idle_ttl": -1})


def test_template_host_example_uses_the_serve_default_port():
    from lig.server.bind import DEFAULT_PORT

    example = next(line for line in cfg.CONFIG_TEMPLATE.splitlines() if line.startswith("# m3max"))
    assert example.endswith(f':{DEFAULT_PORT}"')
