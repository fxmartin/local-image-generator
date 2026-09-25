"""Pre-flight memory estimate and refusal: offline, memory probes injected."""

import pytest
import typer

from lig.cli import app as cli_app
from lig.core import doctor as diag
from lig.core import memory
from lig.models.registry import RegistryError, load_registry

GIB = 1024**3
# Phase 0, XPS, sd.cpp 1024²: engine-reported weights (8949.76 MB) plus the 3551 MB the
# VAE decode asked for (docs/bench/xps13.md). RSS undercounts on the UMA iGPU, so it is not used.
SPIKE_MEASURED_BYTES = int((8949.76 + 3551) * 1024**2)


def test_estimate_matches_formula() -> None:
    registry = load_registry()
    spec = registry.engine_memory["sdcpp"]
    loaded = sum(a.size_bytes for a in registry.set_for("sdcpp", "linux") if a.role != "mmproj")
    expected = int(loaded * spec.factor + spec.activation_bytes_per_pixel * 1024 * 1024)
    assert memory.estimate_peak_bytes(registry, "sdcpp", "linux", 1024, 1024) == expected


def test_estimate_within_20_percent_of_phase0_measurement() -> None:
    estimate = memory.estimate_peak_bytes(load_registry(), "sdcpp", "linux", 1024, 1024)
    assert abs(estimate - SPIKE_MEASURED_BYTES) / SPIKE_MEASURED_BYTES <= 0.20


def test_edit_counts_the_vision_projector() -> None:
    registry = load_registry()
    text = memory.estimate_peak_bytes(registry, "sdcpp", "linux", 768, 768)
    edit = memory.estimate_peak_bytes(registry, "sdcpp", "linux", 768, 768, edit=True)
    assert edit > text


def test_estimate_grows_with_size() -> None:
    registry = load_registry()
    small = memory.estimate_peak_bytes(registry, "sdcpp", "linux", 512, 512)
    large = memory.estimate_peak_bytes(registry, "sdcpp", "linux", 1024, 1024)
    assert large > small


def test_unknown_engine_is_an_error() -> None:
    with pytest.raises(RegistryError):
        memory.estimate_peak_bytes(load_registry(), "nope", "linux", 512, 512)


def test_check_passes_when_it_fits() -> None:
    assert memory.check(10 * GIB, 20 * GIB, force=False) is None


def test_check_refuses_with_figures_and_hints() -> None:
    with pytest.raises(memory.MemoryRefusal) as info:
        memory.check(25 * GIB, 10 * GIB, force=False)
    text = str(info.value)
    assert "25.0 GiB" in text and "10.0 GiB" in text
    assert "close" in text and "smaller" in text and "--force" in text


def test_check_force_returns_warning() -> None:
    warning = memory.check(25 * GIB, 10 * GIB, force=True)
    assert warning is not None and "25.0 GiB" in warning


def test_check_unknown_available_does_not_refuse() -> None:
    assert memory.check(25 * GIB, None, force=False) is None


def test_cli_preflight_exits_3(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(typer.Exit) as info:
        cli_app.memory_preflight(25 * GIB, 10 * GIB, force=False)
    assert info.value.exit_code == 3
    assert "--force" in capsys.readouterr().err


def test_cli_preflight_force_warns_and_proceeds(capsys: pytest.CaptureFixture[str]) -> None:
    cli_app.memory_preflight(25 * GIB, 10 * GIB, force=True)
    assert "warning" in capsys.readouterr().err


VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               1000.
Pages active:                             5000.
Pages inactive:                           2000.
Pages speculative:                         500.
Pages wired down:                         3000.
"""


def test_parse_vm_stat() -> None:
    assert diag.parse_vm_stat(VM_STAT) == 3500 * 16384


def test_parse_vm_stat_garbage() -> None:
    assert diag.parse_vm_stat("nonsense") is None
