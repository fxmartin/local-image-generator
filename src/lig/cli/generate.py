"""`lig generate`: resolve config, pre-flight memory, pick the backend, write PNG + sidecar."""

import sys
from pathlib import Path

import typer

from lig.backends.base import Backend, EngineUnavailable
from lig.cli import scripting
from lig.cli.progress import generation_progress
from lig.core import config as cfg
from lig.core import rewriter, run
from lig.core.models import GenerateRequest
from lig.models.registry import RegistryError, load_registry

EXIT_USAGE = 2
EXIT_UNAVAILABLE = 4


def _fail(message: str, code: int) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code)


HOST_HELP = "Run on this `lig serve` host (a [hosts] name); default: default_host from config."


def engine_flag(engine: str | None, host: str | None) -> str | None:
    """`--host` implies the remote engine and cannot be combined with another one."""
    if host is None:
        return engine
    if engine not in (None, "remote"):
        raise _fail(f"--host runs on the remote engine; drop --engine {engine}", EXIT_USAGE)
    return "remote"


def open_backend(
    ctx: typer.Context, settings: cfg.Settings, host: str | None = None
) -> tuple[Backend, str]:
    """Build the configured backend and confirm it can run; exit 2/4 otherwise."""
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
    return backend, engine_name


def stdin_is_interactive() -> bool:
    return sys.stdin.isatty()


def _prompt_source(
    prompt: str | None, prompt_from: Path | None, rewrite: bool, settings: cfg.RewriterSettings
) -> rewriter.PromptSource:
    """The prompt to render, from the argument or a saved sidecar; usage errors raise."""
    if prompt is not None and prompt_from is not None:
        raise run.UsageError("give either PROMPT or --prompt-from, not both")
    if prompt_from is not None:
        if rewrite:
            raise run.UsageError(
                "--rewrite and --prompt-from are exclusive: the saved prompt is reused as is"
            )
        try:
            return rewriter.load_prompt_file(prompt_from)
        except rewriter.RewriterError as exc:
            raise run.UsageError(str(exc)) from exc
    if prompt is None:
        raise run.UsageError("give a PROMPT or --prompt-from FILE.json")
    if rewrite and not (settings.endpoint and settings.model):
        raise run.UsageError(
            "--rewrite needs rewriter.endpoint and rewriter.model in config "
            "(env: LIG_REWRITER__ENDPOINT, LIG_REWRITER__MODEL)"
        )
    return rewriter.PromptSource(prompt, None)


def _rewrite_request(
    request: GenerateRequest, settings: cfg.RewriterSettings, quiet: bool
) -> tuple[GenerateRequest, str | None]:
    """Expand the prompt; returns the request to render and the original prompt if it changed.

    An unusable rewriter is not fatal: ask whether to go on with the original prompt, or just
    warn and go on when nobody can answer."""
    try:
        expanded = rewriter.rewrite_prompt(
            request.prompt, settings.endpoint or "", settings.model or ""
        )
    except rewriter.RewriterError as exc:
        typer.echo(f"warning: {exc}", err=True)
        if not stdin_is_interactive():
            typer.echo("warning: continuing with the original prompt", err=True)
        elif not typer.confirm("Continue with the original prompt?", err=True):
            raise typer.Exit(1) from exc
        return request, None
    if not quiet:
        typer.echo(f"rewritten prompt: {expanded}", err=True)
    return request.model_copy(update={"prompt": expanded}), request.prompt


def generate(
    ctx: typer.Context,
    prompt: str | None = typer.Argument(None, help="What to draw."),
    rewrite: bool = typer.Option(
        False, "--rewrite", help="Expand the prompt through the [rewriter] LLM endpoint first."
    ),
    prompt_from: Path | None = typer.Option(  # noqa: B008
        None,
        "--prompt-from",
        help="Reuse the prompt of a saved sidecar .json (its expansion, if any); no rewriter call.",
    ),
    size: str | None = typer.Option(None, "--size", help="WIDTHxHEIGHT, multiples of 32."),
    steps: int | None = typer.Option(None, "--steps", help="Sampling steps."),
    seed: int | None = typer.Option(None, "--seed", help="Seed; random (and recorded) if omitted."),
    engine: str | None = typer.Option(
        None,
        "--engine",
        help="Engine: auto, sdcpp, ncnn, mlx, fake or remote.",
        autocompletion=scripting.complete_engine,
    ),
    host: str | None = typer.Option(
        None, "--host", help=HOST_HELP, autocompletion=scripting.complete_host
    ),
    out: Path | None = typer.Option(None, "--out", help="Output directory."),  # noqa: B008
    negative: str | None = typer.Option(None, "--negative", help="Negative prompt."),
    guidance: float | None = typer.Option(None, "--guidance", help="Guidance scale."),
    transparent: bool = typer.Option(
        False, "--transparent", help="RGBA PNG with a transparent background (sdcpp, fake)."
    ),
    force: bool = typer.Option(False, "--force", help="Run even if memory looks too tight."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Print only the final path."),
    as_json: bool = typer.Option(False, "--json", help=scripting.JSON_HELP),
    open_: bool = typer.Option(False, "--open", help=scripting.OPEN_HELP),
) -> None:
    """Generate an image from a text prompt."""
    from lig.cli.app import memory_preflight  # late: app imports this module

    try:
        resolved = cfg.load_settings({"engine": engine_flag(engine, host), "output_dir": out})
        source = _prompt_source(prompt, prompt_from, rewrite, resolved.settings.rewriter)
        request = run.build_request(
            source.prompt,
            resolved,
            size=size,
            steps=steps,
            seed=seed,
            negative=negative,
            guidance=guidance,
            transparent=transparent,
        )
    except (cfg.ConfigError, run.UsageError) as exc:
        raise _fail(str(exc), EXIT_USAGE) from exc
    settings = resolved.settings
    for warning in resolved.warnings:
        typer.echo(f"warning: {warning}", err=True)
    if (warning := run.negative_prompt_warning(request)) is not None:
        typer.echo(f"warning: {warning}", err=True)

    backend, engine_name = open_backend(ctx, settings, host)
    if transparent and not backend.capabilities().supports_transparent:
        raise _fail(
            f"engine '{engine_name}' cannot render transparent output; "
            "use --engine sdcpp\nrun `lig doctor` for details",
            EXIT_UNAVAILABLE,
        )

    original_prompt = source.original
    if rewrite:
        request, original_prompt = _rewrite_request(request, settings.rewriter, quiet)

    try:
        figures = run.estimate_memory(load_registry(), engine_name, request)
    except RegistryError as exc:
        raise _fail(str(exc), 1) from exc
    if figures is not None:
        memory_preflight(figures[0], figures[1], force)

    with generation_progress(
        quiet=quiet, indeterminate=bool(getattr(backend, "progress_indeterminate", False))
    ) as on_progress:
        path = run.run_generate(
            backend, request, settings.output_dir, on_progress, original_prompt=original_prompt
        )
    if as_json:
        scripting.emit_json(scripting.image_document(path))
    else:
        typer.echo(str(path))
    if open_:
        scripting.open_in_viewer(path)
