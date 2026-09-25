"""Typer entry point for the `lig` CLI. Subcommands are stubs until their stories land."""

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from lig.core import config as cfg

app = typer.Typer(
    name="lig",
    help="Generate images locally with Qwen-Image-2.1.",
    no_args_is_help=True,
)


def _stub(name: str) -> None:
    typer.echo(f"lig {name}: not implemented yet")


@app.command()
def generate() -> None:
    """Generate an image from a text prompt."""
    _stub("generate")


@app.command()
def edit() -> None:
    """Edit an existing image with a prompt."""
    _stub("edit")


@app.command()
def seeds() -> None:
    """Explore seeds for a prompt."""
    _stub("seeds")


@app.command()
def bench() -> None:
    """Benchmark the configured engine on this host."""
    _stub("bench")


@app.command()
def models() -> None:
    """Download, verify and switch model weights."""
    _stub("models")


@app.command()
def doctor() -> None:
    """Diagnose the local setup."""
    _stub("doctor")


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
def serve() -> None:
    """Serve a local backend to other hosts (needs the serve extra)."""
    _stub("serve")
