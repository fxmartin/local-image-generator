"""Story 07.1-003: `auto` picks MLX on Apple Silicon when the mlx extra is installed."""

import pytest

from lig.core import config as cfg
from lig.core import run


def _settings(**over):
    return cfg.Settings(**over)


def _resolve(settings, *, platform="darwin", machine="arm64", mflux=True):
    return run.resolve_engine_name(
        settings, platform=platform, machine=machine, has_module=lambda name: mflux
    )


def test_auto_on_apple_silicon_with_mflux_is_mlx():
    assert _resolve(_settings()) == "mlx"


def test_auto_on_apple_silicon_without_mflux_is_sdcpp():
    assert _resolve(_settings(), mflux=False) == "sdcpp"


@pytest.mark.parametrize(("platform", "machine"), [("darwin", "x86_64"), ("linux", "x86_64")])
def test_auto_elsewhere_is_sdcpp(platform, machine):
    assert _resolve(_settings(), platform=platform, machine=machine) == "sdcpp"


def test_default_host_still_wins_over_the_local_default():
    assert _resolve(_settings(default_host="m3max")) == "remote"


def test_an_explicit_engine_always_wins():
    assert _resolve(_settings(engine="sdcpp")) == "sdcpp"


def test_default_lookup_checks_for_the_mflux_module(monkeypatch):
    seen = []
    monkeypatch.setattr(run, "_module_installed", lambda name: seen.append(name) or False)
    run.resolve_engine_name(_settings(), platform="darwin", machine="arm64")
    assert seen == ["mflux"]
