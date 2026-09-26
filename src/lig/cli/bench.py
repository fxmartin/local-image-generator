"""`lig bench`: engine comparison on this host, plus `compare` and `render` on saved JSON."""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from lig.backends.registry import BACKENDS
from lig.core import bench as core
from lig.core import config as cfg
from lig.core import run

EXIT_USAGE = 2
EXIT_UNAVAILABLE = 4

bench_app = typer.Typer(
    help="Benchmark engines on this host; `compare` and `render` work on saved results.",
    invoke_without_command=True,
)


def _fail(message: str, code: int) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code)


@bench_app.callback()
def bench(
    ctx: typer.Context,
    engines: str | None = typer.Option(
        None, "--engines", help="Comma-separated engines; default: every real engine."
    ),
    size: str | None = typer.Option(None, "--size", help="WIDTHxHEIGHT, multiples of 32."),
    steps: int | None = typer.Option(None, "--steps", help="Sampling steps."),
    runs: int = typer.Option(1, "--runs", help="Runs per engine; the median is reported."),
    host: str | None = typer.Option(
        None, "--host", help="Bench the remote engine on this `lig serve` host (a [hosts] name)."
    ),
    out: Path = typer.Option(Path("bench"), "--out", help="Directory for the JSON file."),  # noqa: B008
) -> None:
    """Run a fixed prompt and seed on each engine, print a table, write bench/<date>_<host>.json."""
    if ctx.invoked_subcommand is not None:
        return
    if runs < 1:
        raise _fail(f"invalid --runs {runs}: must be at least 1", EXIT_USAGE)
    if host is not None and engines not in (None, "remote"):
        raise _fail(f"--host runs on the remote engine; drop --engines {engines}", EXIT_USAGE)
    try:
        # Remote runs use the global 1024², 40-step defaults, like `lig generate --host`.
        resolved = cfg.load_settings({"engine": "remote"} if host is not None else None)
        request = run.build_request(
            core.BENCH_PROMPT, resolved, size=size, steps=steps, seed=core.BENCH_SEED
        )
    except (cfg.ConfigError, run.UsageError) as exc:
        raise _fail(str(exc), EXIT_USAGE) from exc
    settings = resolved.settings
    names = (
        ["remote"]
        if host is not None
        else [n.strip() for n in engines.split(",") if n.strip()]
        if engines
        else [n for n in sorted(BACKENDS) if n != "fake"]
    )
    verbose = bool((ctx.obj or {}).get("verbose"))
    report = core.run_bench(
        names,
        lambda n: run.make_backend(n, settings, verbose=verbose, host=host),
        request,
        runs,
    )
    _print_report(report)
    if not report.results:
        raise _fail("no engine ran; run `lig doctor` for details", EXIT_UNAVAILABLE)
    typer.echo(f"wrote {core.write_report(out, report)}")


def _print_report(report: core.BenchReport) -> None:
    console = Console(soft_wrap=True)
    if report.results:
        table = Table(*core.RESULT_HEADERS, box=None, pad_edge=False)
        for entry in report.results:
            table.add_row(*(Text(cell) for cell in core.result_row(entry)))
        console.print(table)
    for skipped in report.skipped:
        console.print(Text(f"skipped {skipped.engine}: {skipped.reason}"))


def _load(path: Path) -> core.BenchReport:
    try:
        return core.load_report(path)
    except core.BenchError as exc:
        raise _fail(str(exc), 1) from exc


@bench_app.command("compare")
def compare(
    a: Path = typer.Argument(..., help="Baseline bench JSON."),  # noqa: B008
    b: Path = typer.Argument(..., help="Bench JSON to compare against it."),  # noqa: B008
) -> None:
    """Print a delta table for two bench files from the same host."""
    report_a, report_b = _load(a), _load(b)
    try:
        core.check_comparable(report_a, report_b)
    except core.BenchError as exc:
        raise _fail(str(exc), 1) from exc
    rows = core.delta_rows(report_a, report_b)
    if not rows:
        raise _fail("the two files share no engine", 1)
    table = Table(*core.DELTA_HEADERS, box=None, pad_edge=False)
    for row in rows:
        table.add_row(*(Text(cell) for cell in row))
    Console(soft_wrap=True).print(table)


@bench_app.command("render")
def render(
    path: Path = typer.Argument(..., help="Bench JSON to render."),  # noqa: B008
) -> None:
    """Print a bench file as a Markdown table, for docs/bench/*.md."""
    typer.echo(core.render_markdown(_load(path)))


@bench_app.command("overhead")
def overhead(
    local: Path = typer.Argument(..., help="The Mac's local bench JSON."),  # noqa: B008
    remote: Path = typer.Argument(..., help="Bench JSON from `lig bench --host`."),  # noqa: B008
    limit: float = typer.Option(10.0, "--limit", help="Maximum acceptable overhead in seconds."),
) -> None:
    """Print remote total minus local total; exit 1 if it exceeds --limit."""
    try:
        result = core.compute_overhead(_load(local), _load(remote), limit)
    except core.BenchError as exc:
        raise _fail(str(exc), 1) from exc
    typer.echo(core.render_overhead(result))
    if not result.passed:
        raise _fail("overhead above target: open an issue with these numbers", 1)
