"""`lig bench`: run one fixed prompt/seed per engine, record timings, compare hosts."""

import hashlib
import platform
import resource
import statistics
import sys
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from lig.backends.base import Backend, EngineError
from lig.core.models import GenerateRequest

SCHEMA_VERSION = 1
BENCH_PROMPT = "a red fox sitting in a snowy forest at dawn, detailed, sharp focus"
BENCH_SEED = 42
# Engines that run inside the lig process; the rest are subprocesses.
IN_PROCESS_ENGINES = frozenset({"fake", "mlx"})


class BenchError(Exception):
    """A bench file is unreadable or the comparison is not meaningful."""


class Timing(BaseModel):
    load_s: float = Field(ge=0)
    per_step_s: float = Field(ge=0)
    total_s: float = Field(ge=0)
    peak_rss_bytes: int = Field(ge=0)


class RunRecord(Timing):
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Client-side wall clock around generate(); for a remote run this includes transfer + SSE.
    wall_s: float | None = Field(default=None, ge=0)


class EngineEntry(BaseModel):
    engine: str
    engine_version: str
    build_backend: str
    weights: list[str]
    width: int
    height: int
    steps: int
    runs: list[RunRecord] = Field(min_length=1)
    median: Timing
    median_wall_s: float | None = None
    server_host: str | None = None  # set for remote runs: the machine that rendered the image
    image_sha256: str  # of the first run; identical runs share it under a fixed seed


class Skipped(BaseModel):
    engine: str
    reason: str


class BenchReport(BaseModel):
    schema_version: int = SCHEMA_VERSION
    date: str
    host: str
    client_host: str | None = None  # set for remote runs: where the request came from (== host)
    server_host: str | None = None  # set for remote runs: the `lig serve` machine
    prompt: str
    seed: int
    results: list[EngineEntry]
    skipped: list[Skipped]


def median(values: list[float]) -> float:
    return statistics.median(values)


def rss_to_bytes(value: int, platform_name: str = sys.platform) -> int:
    """`ru_maxrss` is kilobytes on Linux but bytes on macOS."""
    return value if platform_name == "darwin" else value * 1024


def peak_rss_bytes(in_process: bool) -> int:
    """Peak RSS so far: this process for in-process engines, waited children otherwise.

    Both counters are high-water marks for the whole lig process, so within one bench
    invocation a later engine's figure is at least the earlier one's.
    """
    who = resource.RUSAGE_SELF if in_process else resource.RUSAGE_CHILDREN
    return rss_to_bytes(resource.getrusage(who).ru_maxrss)


def build_backend(engine: str, platform_name: str = sys.platform) -> str:
    """Graphics API the engine is expected to use on this platform."""
    if engine == "fake":
        return "none"
    if engine == "mlx":
        return "mlx"
    return "metal" if platform_name == "darwin" else "vulkan"


def _weights(result_weights: list) -> list[str]:
    return [w.name for w in result_weights]


def bench_engine(engine: str, backend: Backend, request: GenerateRequest, runs: int) -> EngineEntry:
    """Generate `runs` times; engine errors propagate to the caller."""
    records: list[RunRecord] = []
    last = None
    for _ in range(runs):
        started = time.monotonic()
        last = backend.generate(request, None)
        wall_s = time.monotonic() - started
        timings = last.timings
        records.append(
            RunRecord(
                load_s=timings.load_s,
                per_step_s=timings.per_step_s,
                total_s=timings.total_s,
                peak_rss_bytes=peak_rss_bytes(engine in IN_PROCESS_ENGINES),
                image_sha256=hashlib.sha256(last.png).hexdigest(),
                wall_s=wall_s,
            )
        )
    assert last is not None
    return EngineEntry(
        engine=engine,
        engine_version=last.engine_version,
        build_backend=build_backend(engine),
        weights=_weights(last.weights),
        width=request.width,
        height=request.height,
        steps=request.steps,
        runs=records,
        median=Timing(
            load_s=median([r.load_s for r in records]),
            per_step_s=median([r.per_step_s for r in records]),
            total_s=median([r.total_s for r in records]),
            peak_rss_bytes=int(median([r.peak_rss_bytes for r in records])),
        ),
        median_wall_s=median([r.wall_s for r in records if r.wall_s is not None]),
        server_host=last.host if last.remote_host else None,
        image_sha256=records[0].image_sha256,
    )


def run_bench(
    engines: list[str],
    make_backend: Callable[[str], Backend],
    request: GenerateRequest,
    runs: int,
) -> BenchReport:
    """Bench each engine; an unavailable or failing one is recorded as skipped."""
    results: list[EngineEntry] = []
    skipped: list[Skipped] = []
    for name in engines:
        try:
            backend = make_backend(name)
            availability = backend.available()
            if not availability.ok:
                skipped.append(Skipped(engine=name, reason=availability.reason or "unavailable"))
                continue
            results.append(bench_engine(name, backend, request, runs))
        except (EngineError, ValueError) as exc:
            skipped.append(Skipped(engine=name, reason=str(exc).splitlines()[0]))
    client = platform.node() or "localhost"
    server = next((e.server_host for e in results if e.server_host), None)
    return BenchReport(
        date=date.today().isoformat(),
        host=client,
        client_host=client if server else None,
        server_host=server,
        prompt=request.prompt,
        seed=request.seed,
        results=results,
        skipped=skipped,
    )


def report_path(out_dir: Path, report: BenchReport) -> Path:
    return out_dir / f"{report.date}_{report.host}.json"


def write_report(out_dir: Path, report: BenchReport) -> Path:
    path = report_path(out_dir, report)
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n")
    return path


def load_report(path: Path) -> BenchReport:
    try:
        return BenchReport.model_validate_json(path.read_text())
    except (OSError, ValidationError) as exc:
        raise BenchError(f"{path}: not a valid bench file: {exc}") from exc


def check_comparable(a: BenchReport, b: BenchReport) -> None:
    if a.host != b.host:
        raise BenchError(
            f"refusing to compare different hosts ({a.host} vs {b.host}): "
            "timings are only meaningful on the same machine"
        )


def _pct(old: float, new: float) -> str:
    return "n/a" if old == 0 else f"{(new - old) / old * 100:+.1f}%"


def delta_rows(a: BenchReport, b: BenchReport) -> list[list[str]]:
    """One row per engine present in both reports: total s and its change, RSS change."""
    by_name = {e.engine: e for e in b.results}
    rows = []
    for old in a.results:
        new = by_name.get(old.engine)
        if new is None:
            continue
        rows.append(
            [
                old.engine,
                f"{old.median.total_s:.2f}",
                f"{new.median.total_s:.2f}",
                _pct(old.median.total_s, new.median.total_s),
                f"{old.median.per_step_s:.3f}",
                f"{new.median.per_step_s:.3f}",
                _pct(old.median.per_step_s, new.median.per_step_s),
                _pct(old.median.peak_rss_bytes, new.median.peak_rss_bytes),
            ]
        )
    return rows


DELTA_HEADERS = [
    "engine",
    "A total s",
    "B total s",
    "Δ total",
    "A s/step",
    "B s/step",
    "Δ s/step",
    "Δ RSS",
]
RESULT_HEADERS = [
    "engine",
    "version",
    "build",
    "weights",
    "size",
    "steps",
    "load s",
    "s/step",
    "total s",
    "peak RSS MiB",
    "image sha256",
]


def result_row(e: EngineEntry) -> list[str]:
    return [
        e.engine,
        e.engine_version,
        e.build_backend,
        ",".join(e.weights),
        f"{e.width}x{e.height}",
        str(e.steps),
        f"{e.median.load_s:.2f}",
        f"{e.median.per_step_s:.3f}",
        f"{e.median.total_s:.2f}",
        f"{e.median.peak_rss_bytes / 1024**2:.0f}",
        e.image_sha256[:12],
    ]


def render_markdown(report: BenchReport) -> str:
    """Markdown table for docs/bench/*.md, generated from the JSON."""
    lines = [
        f"Host `{report.host}`, {report.date}, seed {report.seed}, prompt: {report.prompt}",
        "",
        "| " + " | ".join(RESULT_HEADERS) + " |",
        "|" + "|".join("---" for _ in RESULT_HEADERS) + "|",
    ]
    lines += ["| " + " | ".join(result_row(e)) + " |" for e in report.results]
    if report.skipped:
        lines += ["", *(f"- skipped `{s.engine}`: {s.reason}" for s in report.skipped)]
    return "\n".join(lines)


class Overhead(BaseModel):
    """Remote cost over a local run of the same job, as seen from the client."""

    client_host: str
    server_host: str
    local_total_s: float
    remote_wall_s: float
    overhead_s: float
    limit_s: float

    @property
    def passed(self) -> bool:
        return self.overhead_s <= self.limit_s


def compute_overhead(local: BenchReport, remote: BenchReport, limit_s: float) -> Overhead:
    """Remote wall clock minus the Mac's local total, for the same prompt, seed and shape."""
    if not remote.server_host:
        raise BenchError("the remote file has no server_host: run `lig bench --host NAME`")
    if not local.results or not remote.results:
        raise BenchError("both bench files need at least one result")
    a, b = local.results[0], remote.results[0]
    if (local.prompt, local.seed, a.width, a.height, a.steps) != (
        remote.prompt,
        remote.seed,
        b.width,
        b.height,
        b.steps,
    ):
        raise BenchError("the two runs used different prompt, seed, size or steps")
    remote_wall = b.median_wall_s if b.median_wall_s is not None else b.median.total_s
    return Overhead(
        client_host=remote.client_host or remote.host,
        server_host=remote.server_host,
        local_total_s=a.median.total_s,
        remote_wall_s=remote_wall,
        overhead_s=remote_wall - a.median.total_s,
        limit_s=limit_s,
    )


def render_overhead(o: Overhead) -> str:
    verdict = "PASS" if o.passed else "FAIL"
    return (
        f"Remote overhead {o.client_host} -> {o.server_host}: "
        f"{o.remote_wall_s:.2f} s remote - {o.local_total_s:.2f} s local = "
        f"{o.overhead_s:+.2f} s (limit {o.limit_s:g} s): {verdict}"
    )
