"""Typer entry point for the `lig` CLI. Subcommands are stubs until their stories land."""

import functools
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
import httpx
from rich.console import Console
from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TransferSpeedColumn
from rich.table import Table
from rich.text import Text

from lig.backends.base import Backend, EngineError
from lig.backends.registry import BACKENDS
from lig.core import config as cfg
from lig.core import doctor as diag
from lig.core.logs import report_engine_error

from lig import __version__
from lig.core import config as cfg
from lig.models import cache, downloader
from lig.models.registry import RegistryError, load_registry

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


models_app = typer.Typer(help="Inspect and download model weights.", no_args_is_help=True)
app.add_typer(models_app, name="models")


@models_app.command("list")
def models_list(
    engine: str | None = typer.Option(None, "--engine", help="Only show this engine's artifacts."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """Show each artifact's state, size and license, plus cache size and free disk."""
    try:
        resolved = cfg.load_settings()
        report = cache.build_report(
            load_registry(), cache.ensure_models_dir(resolved.settings.models_dir), engine
        )
    except (cfg.ConfigError, RegistryError, OSError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    if as_json:
        typer.echo(json.dumps(report, indent=2))
        return
    table = Table("name", "role", "engines", "size", "license", "status", box=None, pad_edge=False)
    for row in report["artifacts"]:
        table.add_row(
            row["name"],
            row["role"],
            ",".join(row["engines"]),
            cache.human_size(row["size_bytes"]),
            row["license"],
            row["status"],
        )
    console = Console(soft_wrap=True)
    console.print(table)
    console.print(
        f"cache: {cache.human_size(report['cache_bytes'])} used in {report['models_dir']}, "
        f"{cache.human_size(report['free_bytes'])} free"
    )


@models_app.command("pull")
def models_pull(
    name: str | None = typer.Argument(None, help="Artifact name to download."),
    engine: str | None = typer.Option(None, "--engine", help="Download this engine's full set."),
    force: bool = typer.Option(
        False, "--force", help="Re-download verified files and skip the free-disk check."
    ),
) -> None:
    """Download weights with resume, progress and sha256 verification."""
    if (name is None) == (engine is None):
        typer.echo("error: give exactly one of NAME or --engine", err=True)
        raise typer.Exit(2)
    err = Console(stderr=True, soft_wrap=True)
    try:
        registry = load_registry()
        artifacts = registry.set_for(engine, sys.platform) if engine else [registry.get(name)]
        models_dir = cache.ensure_models_dir(cfg.load_settings().settings.models_dir)
    except (cfg.ConfigError, RegistryError, OSError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc

    total = downloader.remaining_bytes(models_dir, artifacts, force)
    free = downloader.free_bytes(models_dir)
    typer.echo(f"to download: {cache.human_size(total)}, free disk: {cache.human_size(free)}")
    if not force and free < total + downloader.DISK_MARGIN_BYTES:
        typer.echo(
            f"error: not enough disk: need {cache.human_size(total)} plus "
            f"{cache.human_size(downloader.DISK_MARGIN_BYTES)} headroom; use --force to override",
            err=True,
        )
        raise typer.Exit(1)

    progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=err,
    )
    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, read=60.0)) as client, progress:
            for artifact in artifacts:
                task = progress.add_task(artifact.name, total=artifact.size_bytes)

                def update(done: int, _total: int, task=task) -> None:
                    progress.update(task, completed=done)

                outcome = downloader.pull_artifact(
                    artifact, models_dir, client, force=force, on_progress=update
                )
                for warning in outcome.warnings:
                    progress.console.print(f"warning: {warning}")
                if outcome.skipped:
                    progress.console.print(f"{artifact.name}: already installed")
                else:
                    progress.update(task, completed=artifact.size_bytes)
    except downloader.ChecksumMismatch as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    except (downloader.DownloadError, OSError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc


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
