"""Platform and engine diagnostics behind `lig doctor`; every probe is an injectable seam."""

import os
import platform
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from lig.backends.base import Backend

VULKAN_ICD_DIRS = [Path("/usr/share/vulkan/icd.d"), Path("/etc/vulkan/icd.d")]
ONEAPI_DIR = Path("/opt/intel/oneapi")
PROBE_TIMEOUT_S = 10


@dataclass(frozen=True)
class PlatformInfo:
    os: str
    arch: str
    vulkan_icd: bool
    metal: bool
    oneapi: bool
    ram_total: int | None
    ram_available: int | None
    models_dir: str
    disk_free: int | None


def _run_ok(argv: list[str]) -> bool:
    try:
        done = subprocess.run(argv, capture_output=True, timeout=PROBE_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def probe_vulkan(
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[[list[str]], bool] = _run_ok,
    icd_dirs: Iterable[Path] = VULKAN_ICD_DIRS,
) -> bool:
    """`vulkaninfo --summary` if installed and it succeeds, else any ICD json file."""
    if which("vulkaninfo") and run(["vulkaninfo", "--summary"]):
        return True
    return any(d.is_dir() and any(d.glob("*.json")) for d in icd_dirs)


def probe_oneapi(
    which: Callable[[str], str | None] = shutil.which,
    oneapi_dir: Path = ONEAPI_DIR,
) -> bool:
    return bool(which("sycl-ls")) or oneapi_dir.is_dir()


def parse_meminfo(text: str) -> tuple[int | None, int | None]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[key] = int(parts[0]) * 1024  # /proc/meminfo reports kB
    return values.get("MemTotal"), values.get("MemAvailable")


def parse_vm_stat(text: str) -> int | None:
    """Reclaimable bytes from `vm_stat`: free + inactive + speculative pages."""
    header = re.search(r"page size of (\d+) bytes", text)
    if not header:
        return None
    pages = {
        key: int(match.group(1))
        for key in ("free", "inactive", "speculative")
        if (match := re.search(rf"Pages {key}:\s+(\d+)", text))
    }
    if len(pages) != 3:
        return None
    return sum(pages.values()) * int(header.group(1))


def _vm_stat_available() -> int | None:
    try:
        done = subprocess.run(
            ["vm_stat"], capture_output=True, text=True, timeout=PROBE_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_vm_stat(done.stdout) if done.returncode == 0 else None


def probe_memory() -> tuple[int | None, int | None]:
    try:
        return parse_meminfo(Path("/proc/meminfo").read_text())
    except OSError:
        pass
    try:  # macOS has no /proc: total from sysconf, available from vm_stat
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"), _vm_stat_available()
    except (ValueError, OSError, AttributeError):
        return None, None


def disk_free_bytes(path: Path) -> int | None:
    """Free bytes on the filesystem that will hold `path`, even if it doesn't exist yet."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return None


def collect_platform_info(
    models_dir: Path,
    system: Callable[[], str] = platform.system,
    machine: Callable[[], str] = platform.machine,
    vulkan: Callable[[], bool] = probe_vulkan,
    oneapi: Callable[[], bool] = probe_oneapi,
    memory: Callable[[], tuple[int | None, int | None]] = probe_memory,
    disk_free: Callable[[Path], int | None] = disk_free_bytes,
) -> PlatformInfo:
    os_name = system()
    total, available = memory()
    return PlatformInfo(
        os=os_name,
        arch=machine(),
        vulkan_icd=vulkan(),
        metal=os_name == "Darwin",
        oneapi=oneapi(),
        ram_total=total,
        ram_available=available,
        models_dir=str(models_dir),
        disk_free=disk_free(models_dir),
    )


def _cached(models_dir: Path, engine: str) -> tuple[int, int]:
    root = models_dir / engine
    files = [p for p in root.rglob("*") if p.is_file()] if root.is_dir() else []
    return len(files), sum(p.stat().st_size for p in files)


def _engine_row(name: str, factory: Callable[[], Backend], models_dir: Path) -> dict[str, Any]:
    try:
        availability = factory().available()
        ok, reason = availability.ok, availability.reason
    except Exception as exc:  # a broken adapter must not hide the other rows
        ok, reason = False, f"{type(exc).__name__}: {exc}"
    files, size = _cached(models_dir, name)
    return {
        "engine": name,
        "status": "available" if ok else "unavailable",
        "reason": reason,
        "cached_files": files,
        "cached_bytes": size,
    }


def build_report(
    info: PlatformInfo, engines: Mapping[str, Callable[[], Backend]]
) -> dict[str, Any]:
    models_dir = Path(info.models_dir)
    return {
        "platform": asdict(info),
        "engines": [_engine_row(n, f, models_dir) for n, f in sorted(engines.items())],
    }
