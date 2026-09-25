"""`lig generate`: resolve config, pre-flight memory, pick the backend, write PNG + sidecar."""

from pathlib import Path

import typer

from lig.backends.base import EngineUnavailable
from lig.core import config as cfg
from lig.core import run
from lig.models.registry import RegistryError, load_registry

EXIT_USAGE = 2
EXIT_UNAVAILABLE = 4


def _fail(message: str, code: int) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code)


def generate(
    ctx: typer.Context,
    prompt: str = typer.Argument(..., help="What to draw."),
    size: str | None = typer.Option(None, "--size", help="WIDTHxHEIGHT, multiples of 32."),
    steps: int | None = typer.Option(None, "--steps", help="Sampling steps."),
    seed: int | None = typer.Option(None, "--seed", help="Seed; random (and recorded) if omitted."),
    engine: str | None = typer.Option(None, "--engine", help="Engine: auto, sdcpp, ncnn, fake."),
    out: Path | None = typer.Option(None, "--out", help="Output directory."),  # noqa: B008
    negative: str | None = typer.Option(None, "--negative", help="Negative prompt."),
    guidance: float | None = typer.Option(None, "--guidance", help="Guidance scale."),
    force: bool = typer.Option(False, "--force", help="Run even if memory looks too tight."),
) -> None:
    """Generate an image from a text prompt."""
    from lig.cli.app import memory_preflight  # late: app imports this module

    try:
        resolved = cfg.load_settings({"engine": engine, "output_dir": out})
        request = run.build_request(
            prompt,
            resolved,
            size=size,
            steps=steps,
            seed=seed,
            negative=negative,
            guidance=guidance,
        )
    except (cfg.ConfigError, run.UsageError) as exc:
        raise _fail(str(exc), EXIT_USAGE) from exc
    settings = resolved.settings
    for warning in resolved.warnings:
        typer.echo(f"warning: {warning}", err=True)
    if (warning := run.negative_prompt_warning(request)) is not None:
        typer.echo(f"warning: {warning}", err=True)

    engine_name = run.resolve_engine_name(settings)
    verbose = bool((ctx.obj or {}).get("verbose"))
    try:
        backend = run.make_backend(engine_name, settings, verbose=verbose)
        availability = backend.available()
    except run.UsageError as exc:
        raise _fail(str(exc), EXIT_USAGE) from exc
    except EngineUnavailable as exc:
        raise _fail(f"{exc}\nrun `lig doctor` for details", EXIT_UNAVAILABLE) from exc
    if not availability.ok:
        raise _fail(run.unavailable_message(engine_name, availability), EXIT_UNAVAILABLE)

    try:
        figures = run.estimate_memory(load_registry(), engine_name, request)
    except RegistryError as exc:
        raise _fail(str(exc), 1) from exc
    if figures is not None:
        memory_preflight(figures[0], figures[1], force)

    path = run.run_generate(backend, request, settings.output_dir)
    typer.echo(str(path))
