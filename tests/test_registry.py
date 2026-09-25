"""Registry schema + loader: offline, pure YAML."""

import socket
import textwrap
from pathlib import Path

import pytest

from lig.models.registry import Registry, RegistryError, load_registry

SHA = "a" * 64


def _artifact(name: str, role: str, **over) -> str:
    fields = {
        "name": name,
        "repo": "org/repo",
        "filename": f"{name}.gguf",
        "sha256": SHA,
        "size_bytes": 10,
        "engines": ["sdcpp"],
        "role": role,
        "license": "apache-2.0",
        "url": f"https://example.test/{name}",
    }
    fields.update(over)
    lines = [
        f"  - {k}: {v!r}" if not isinstance(v, list) else f"  - {k}: {v}" for k, v in fields.items()
    ]
    # First key needs the list dash, the rest plain indentation.
    return "\n".join([lines[0]] + [ln.replace("  - ", "    ", 1) for ln in lines[1:]])


def _write(tmp_path: Path, artifacts: list[str], sets: str) -> Path:
    body = "artifacts:\n" + "\n".join(artifacts) + "\nsets:\n" + textwrap.indent(sets, "  ") + "\n"
    path = tmp_path / "registry.yaml"
    path.write_text(body)
    return path


FULL_SET = """\
sdcpp-q4:
  engine: sdcpp
  artifacts: [t, e, v]
"""


def _three(**over) -> list[str]:
    return [
        _artifact("t", "transformer", **over),
        _artifact("e", "text_encoder"),
        _artifact("v", "vae"),
    ]


def test_shipped_registry_loads_and_touches_no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network touched")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    reg = load_registry()
    assert reg.artifacts
    assert reg.set_for("sdcpp", "linux")


def test_valid_registry(tmp_path):
    reg = load_registry(_write(tmp_path, _three(), FULL_SET))
    assert [a.name for a in reg.set_for("sdcpp", "linux")] == ["t", "e", "v"]
    assert isinstance(reg, Registry)


def test_duplicate_names_fail(tmp_path):
    path = _write(tmp_path, _three() + [_artifact("t", "vae")], FULL_SET)
    with pytest.raises(RegistryError, match="duplicate.*'t'"):
        load_registry(path)


@pytest.mark.parametrize(
    ("over", "field"),
    [({"sha256": "abc"}, "sha256"), ({"size_bytes": -1}, "size_bytes")],
)
def test_invalid_field_names_artifact_and_field(tmp_path, over, field):
    path = _write(tmp_path, _three(**over), FULL_SET)
    with pytest.raises(RegistryError) as exc:
        load_registry(path)
    assert "'t'" in str(exc.value) and field in str(exc.value)


def test_unknown_role_rejected(tmp_path):
    path = _write(tmp_path, [_artifact("t", "bogus")] + _three()[1:], FULL_SET)
    with pytest.raises(RegistryError, match="role"):
        load_registry(path)


def test_set_referencing_unknown_artifact(tmp_path):
    sets = "sdcpp-q4:\n  engine: sdcpp\n  artifacts: [t, e, nope]\n"
    with pytest.raises(RegistryError, match="nope"):
        load_registry(_write(tmp_path, _three(), sets))


def test_missing_role_raises(tmp_path):
    sets = "sdcpp-q4:\n  engine: sdcpp\n  artifacts: [t, e]\n"
    reg = load_registry(_write(tmp_path, _three(), sets))
    with pytest.raises(RegistryError, match="vae"):
        reg.set_for("sdcpp", "linux")


def test_bundle_set_needs_no_other_roles(tmp_path):
    arts = [_artifact("b", "bundle", engines=["ncnn"])]
    sets = "ncnn-default:\n  engine: ncnn\n  artifacts: [b]\n"
    reg = load_registry(_write(tmp_path, arts, sets))
    assert [a.name for a in reg.set_for("ncnn", "linux")] == ["b"]


def test_platform_filtering_and_unknown_engine(tmp_path):
    sets = "sdcpp-q4:\n  engine: sdcpp\n  platforms: [linux]\n  artifacts: [t, e, v]\n"
    reg = load_registry(_write(tmp_path, _three(), sets))
    assert reg.set_for("sdcpp", "linux")
    with pytest.raises(RegistryError, match="darwin"):
        reg.set_for("sdcpp", "darwin")
    with pytest.raises(RegistryError, match="mlx"):
        reg.set_for("mlx", "linux")


def test_malformed_yaml_and_missing_file(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("artifacts: [")
    with pytest.raises(RegistryError):
        load_registry(bad)
    with pytest.raises(RegistryError):
        load_registry(tmp_path / "missing.yaml")
    top = tmp_path / "list.yaml"
    top.write_text("- 1")
    with pytest.raises(RegistryError):
        load_registry(top)
