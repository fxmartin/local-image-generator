"""FastAPI daemon exposing exactly one local backend, chosen when it starts."""

import logging
import platform
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from lig import __version__
from lig.backends.base import Backend
from lig.models import cache
from lig.models.registry import Registry

log = logging.getLogger(__name__)


def parse_bind(text: str) -> tuple[str, int]:
    """Split `HOST:PORT`; raise ValueError naming the bad value."""
    host, sep, port = text.rpartition(":")
    if not sep or not host or not port.isdigit() or not 0 < int(port) < 65536:
        raise ValueError(f"invalid bind '{text}': expected HOST:PORT, e.g. 127.0.0.1:8765")
    return host, int(port)


def _engine_version(backend: Backend) -> str:
    """Adapters that probe a binary can fail; health must still answer."""
    try:
        return str(backend.version())  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - any probe failure degrades to "unknown"
        log.warning("engine version probe failed: %s", exc)
        return "unknown"


def create_app(backend: Backend, registry: Registry, models_dir: Path) -> FastAPI:
    api = FastAPI(title="lig serve", version=__version__)
    started = time.monotonic()
    host = platform.node() or "localhost"

    def report() -> dict[str, Any]:
        return cache.build_report(registry, models_dir, backend.name)

    @api.get("/v1/health")
    def health() -> dict[str, Any]:
        artifacts = report()["artifacts"]
        return {
            "engine": backend.name,
            "engine_version": _engine_version(backend),
            "weights": {
                "installed": sum(a["status"] == "installed" for a in artifacts),
                "total": len(artifacts),
            },
            "loaded": False,  # nothing is held in memory until the generate endpoint lands
            "host": host,
            "lig_version": __version__,
            "uptime_s": round(time.monotonic() - started, 3),
        }

    @api.get("/v1/models")
    def models() -> dict[str, Any]:
        return report()

    return api
