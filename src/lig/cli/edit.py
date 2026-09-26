"""`lig edit`: apply a prompt-driven edit to an existing image, recording its source."""

from pathlib import Path

import typer

from lig.backends.base import EngineUnavailable
from lig.cli.generate import EXIT_UNAVAILABLE, EXIT_USAGE, HOST_HELP, _fail, engine_flag
from lig.cli.progress import generation_progress
from lig.core import config as cfg
from lig.core import run
from lig.models.registry import RegistryError, load_registry


def edit(
    ctx: typer.Context,
    image: Path = typer.Argument(..., help="The PNG to edit."),  # noqa: B008
    prompt: str = typer.Argument(..., help="The edit instruction, e.g. 'make the teapot blue'."),
    size: str | None = typer.Option(
        None, "--size", help="WIDTHxHEIGHT; default: source size rounded down to 32."
    ),
    steps: int | None = typer.Option(None, "--steps", help="Sampling steps."),
    seed: int | None = typer.Option(None, "--seed", help="Seed; random (and recorded) if omitted."),
    engine: str | None = typer.Option(None, "--engine", help="Engine: auto, sdcpp, ncnn, fake."),
    strength: float | None = typer.Option(
        None, "--strength", help="How far to move from the source, 0.0 to 1.0."
    ),
    host: str | None = typer.Option(None, "--host", help=HOST_HELP),
    out: Path | None = typer.Option(None, "--out", help="Output directory."),  # noqa: B008
    force: bool = typer.Option(False, "--force", help="Run even if memory looks too tight."),
) -> None:
    """Edit an existing image with a prompt."""
    from lig.cli.app import memory_preflight  # late: app imports this module

    try:
        resolved = cfg.load_settings({"engine": engine_flag(engine, host), "output_dir": out})
        request = run.build_edit_request(
            prompt, image, resolved, size=size, steps=steps, seed=seed, strength=strength
        )
    except (cfg.ConfigError, run.UsageError) as exc:
        raise _fail(str(exc), EXIT_USAGE) from exc
    settings = resolved.settings
    for warning in resolved.warnings:
        typer.echo(f"warning: {warning}", err=True)
    if size is None:
        typer.echo(
            f"size: {request.width}x{request.height} (source size rounded down to multiples of 32)",
            err=True,
        )

    engine_name = run.resolve_engine_name(settings)
    verbose = bool((ctx.obj or {}).get("verbose"))
    try:
        backend = run.make_backend(engine_name, settings, verbose=verbose, host=host)
        availability = backend.available()
    except run.UsageError as exc:
        raise _fail(str(exc), EXIT_USAGE) from exc
    except EngineUnavailable as exc:
        raise _fail(f"{exc}\nrun `lig doctor` for details", EXIT_UNAVAILABLE) from exc
    if not availability.ok:
        raise _fail(run.unavailable_message(engine_name, availability), EXIT_UNAVAILABLE)
    if not backend.capabilities().supports_edit:
        reason = availability.reason or "the engine does not support edit"
        raise _fail(
            f"engine '{engine_name}' cannot edit: {reason}\nrun `lig doctor` for details",
            EXIT_UNAVAILABLE,
        )

    try:
        figures = run.estimate_memory(load_registry(), engine_name, request)
    except RegistryError as exc:
        raise _fail(str(exc), 1) from exc
    if figures is not None:
        memory_preflight(figures[0], figures[1], force)

    with generation_progress(
        quiet=False,
        indeterminate=bool(
            getattr(backend, "progress_indeterminate", False)
            or getattr(backend, "edit_progress_indeterminate", False)
        ),
    ) as on_progress:
        path = run.run_edit(backend, request, settings.output_dir, on_progress)
    typer.echo(str(path))
