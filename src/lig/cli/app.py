"""Typer entry point for the `lig` CLI. Subcommands are stubs until their stories land."""

import typer

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


@app.command()
def config() -> None:
    """Show or edit configuration."""
    _stub("config")


@app.command()
def serve() -> None:
    """Serve a local backend to other hosts (needs the serve extra)."""
    _stub("serve")
