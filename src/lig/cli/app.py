"""Typer entry point for the `lig` CLI. Subcommands are stubs until their stories land."""

import functools
import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from lig import __version__
from lig.backends.base import Backend, EngineError
from lig.backends.registry import BACKENDS
from lig.core import config as cfg
from lig.core import doctor as diag
from lig.core.logs import report_engine_error

app = typer.Typer(
    name="lig",
    help="Generate images locally with Qwen-Image-2.1.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"lig {__version__}")
        raise typer.Exit()


_debug = False  # set by the root callback; read by handle_engine_errors


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Echo engine output."),
    debug: bool = typer.Option(False, "--debug", help="Show Python tracebacks on failure."),
) -> None:
    """Generate images locally with Qwen-Image-2.1."""
    global _debug
    ctx.obj = {"verbose": verbose}
    _debug = debug


def handle_engine_errors(func: Callable[..., Any]) -> Callable[..., Any]:
    """Turn an EngineError into a readable report and exit 1; `--debug` re-raises instead."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except EngineError as error:
            if _debug:
                raise
            report_engine_error(error, error.log_path, Console(stderr=True))
            raise typer.Exit(1) from error

    return wrapper


def _stub(name: str) -> None:
    typer.echo(f"lig {name}: not implemented yet")


@app.command()
@handle_engine_errors
def generate() -> None:
    """Generate an image from a text prompt."""
    _stub("generate")


@app.command()
@handle_engine_errors
def edit() -> None:
    """Edit an existing image with a prompt."""
    _stub("edit")


@app.command()
@handle_engine_errors
def seeds() -> None:
    """Explore seeds for a prompt."""
    _stub("seeds")


@app.command()
@handle_engine_errors
def bench() -> None:
    """Benchmark the configured engine on this host."""
    _stub("bench")


@app.command()
@handle_engine_errors
def models() -> None:
    """Download, verify and switch model weights."""
    _stub("models")


def _platform_info(models_dir: Path) -> diag.PlatformInfo:
    return diag.collect_platform_info(models_dir)


def _engine_factories() -> dict[str, Callable[[], Backend]]:
    return {name: cls for name, cls in BACKENDS.items()}


def _fmt_bytes(value: int | None) -> str:
    return "unknown" if value is None else f"{value / 1024**3:.1f} GiB"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


@app.command()
@handle_engine_errors
def doctor(
    as_json: bool = typer.Option(False, "--json", help="Emit the report as JSON."),
) -> None:
    """Diagnose the local setup: platform facts and per-engine availability."""
    try:
        resolved = cfg.load_settings()
    except cfg.ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    report = diag.build_report(_platform_info(resolved.settings.models_dir), _engine_factories())
    if as_json:
        typer.echo(json.dumps(report, indent=2))
        return
    plat = report["platform"]
    facts = Table("platform", "value", box=None, pad_edge=False)
    for label, value in [
        ("os", plat["os"]),
        ("arch", plat["arch"]),
        ("Vulkan ICD", _yes_no(plat["vulkan_icd"])),
        ("Metal", _yes_no(plat["metal"])),
        ("oneAPI", _yes_no(plat["oneapi"])),
        ("RAM total", _fmt_bytes(plat["ram_total"])),
        ("RAM available", _fmt_bytes(plat["ram_available"])),
        ("models dir", plat["models_dir"]),
        ("disk free", _fmt_bytes(plat["disk_free"])),
    ]:
        facts.add_row(label, Text(str(value)))
    engines = Table("engine", "cached weights", "status", box=None, pad_edge=False)
    for row in report["engines"]:
        status = row["status"] + (f": {row['reason']}" if row["reason"] else "")
        cached = f"{row['cached_files']} file(s), {_fmt_bytes(row['cached_bytes'])}"
        engines.add_row(row["engine"], cached, Text(status))
    console = Console(soft_wrap=True)
    console.print(facts)
    console.print()
    console.print(engines)


config_app = typer.Typer(help="Show or initialise configuration.", no_args_is_help=True)
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show() -> None:
    """Print every effective setting and the layer it came from."""
    try:
        resolved = cfg.load_settings()
    except cfg.ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    for warning in resolved.warnings:
        typer.echo(f"warning: {warning}", err=True)
    exists = "" if resolved.path.is_file() else " (not found)"
    table = Table("key", "value", "source", box=None, pad_edge=False)
    for key, value, source in cfg.effective_values(resolved):
        table.add_row(key, Text(str(value)), source)
    Console(soft_wrap=True).print(table)
    typer.echo(f"config file: {resolved.path}{exists}")


@config_app.command("init")
def config_init() -> None:
    """Write a commented config.toml to the platform config dir."""
    path = cfg.default_config_path()
    try:
        cfg.write_config_template(path)
    except cfg.ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"wrote {path}")


@app.command()
@handle_engine_errors
def serve() -> None:
    """Serve a local backend to other hosts (needs the serve extra)."""
    if any(importlib.util.find_spec(mod) is None for mod in ("fastapi", "uvicorn")):
        typer.echo(
            "lig serve needs the 'serve' extra: uv tool install 'local-image-generator[serve]'",
            err=True,
        )
        raise typer.Exit(1)
    _stub("serve")
