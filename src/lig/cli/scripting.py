"""Story 08.1-003: `--json` documents, `--open` in the system viewer, completion callbacks.

Completion callbacks run on every Tab press, so they read only local files (the
packaged registry, the config) and swallow every error: a broken config must
never print a traceback into the shell.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import typer

from lig.backends.registry import BACKENDS
from lig.core import config as cfg
from lig.models.registry import RegistryError, load_registry

JSON_HELP = "Print one JSON document on stdout instead of the path (progress stays on stderr)."
OPEN_HELP = "Open the result in the system image viewer."

_popen = subprocess.Popen  # seam: tests record launches instead of starting a viewer


def emit_json(document: Any) -> None:
    typer.echo(json.dumps(document, indent=2))


def image_document(png: Path) -> dict[str, Any]:
    """The image's sidecar plus where the PNG and the sidecar are."""
    sidecar = png.with_suffix(".json")
    document = json.loads(sidecar.read_text())
    return {"path": str(png), "sidecar_path": str(sidecar), **document}


def open_in_viewer(path: Path) -> None:
    """`open` on macOS, `xdg-open` elsewhere; a viewer that will not start is only a warning."""
    viewer = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        _popen(
            [viewer, str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        typer.echo(f"warning: cannot open {path} with {viewer}: {exc}", err=True)


def _matching(names: list[str], incomplete: str) -> list[str]:
    return sorted(n for n in names if n.startswith(incomplete))


def complete_engine(incomplete: str) -> list[str]:
    return _matching(["auto", "remote", *BACKENDS], incomplete)


def complete_artifact(incomplete: str) -> list[str]:
    try:
        names = [artifact.name for artifact in load_registry().artifacts]
    except RegistryError:
        return []
    return _matching(names, incomplete)


def complete_host(incomplete: str) -> list[str]:
    try:
        hosts = cfg.load_settings().settings.hosts
    except Exception:  # noqa: BLE001 — never break the user's shell on Tab
        return []
    return _matching(list(hosts), incomplete)
