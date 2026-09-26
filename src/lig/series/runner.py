"""Story 09.2-001: loop over the shots, one `lig generate` per shot, sequentially."""

import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from lig import __version__
from lig.series.manifest import (
    CONTINUITY_PROMPT,
    SERIES_FILE,
    SeriesManifest,
    ShotRecord,
    sidecar_path,
    write_manifest,
)
from lig.series.settings import SeriesError, SeriesSettings
from lig.series.shots import Shot

__all__ = ["SERIES_FILE"]
EXIT_FAILED = 1
# The interpreter running us, so a `uv tool` install needs no `lig` on PATH.
LIG_ARGV = [sys.executable, "-c", "from lig.cli.app import app; app()"]

# (argv after `lig`, progress label) -> (exit code, PNG path from the last stdout line)
Renderer = Callable[[list[str], str], tuple[int, str]]
Planner = Callable[[SeriesSettings], Iterable[Shot]]


@dataclass(frozen=True)
class LigFlags:
    """`lig generate` flags passed through unchanged; None means lig's own default."""

    size: str | None = None
    steps: int | None = None
    engine: str | None = None
    host: str | None = None
    negative: str | None = None
    guidance: float | None = None

    def argv(self) -> list[str]:
        pairs = [
            ("--size", self.size),
            ("--steps", self.steps),
            ("--engine", self.engine),
            ("--host", self.host),
            ("--negative", self.negative),
            ("--guidance", self.guidance),
        ]
        return [part for flag, value in pairs if value is not None for part in (flag, str(value))]


@dataclass
class SeriesResult:
    paths: list[Path] = field(default_factory=list)
    exit_code: int = 0


def _prefix_stream(source: TextIO, label: str) -> None:
    for line in source:
        sys.stderr.write(f"[{label}] {line}" if line.strip() else line)
        sys.stderr.flush()


def render_with_lig(argv: list[str], label: str) -> tuple[int, str]:
    """Run `lig`, echo its stderr prefixed with `label`, return its last stdout line."""
    with subprocess.Popen(
        [*LIG_ARGV, *argv], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    ) as proc:
        assert proc.stdout is not None and proc.stderr is not None
        echo = threading.Thread(target=_prefix_stream, args=(proc.stderr, label), daemon=True)
        echo.start()
        stdout = proc.stdout.read()
        code = proc.wait()
        echo.join()
    lines = stdout.strip().splitlines()
    return code, lines[-1].strip() if lines else ""


def run_series(
    settings: SeriesSettings,
    plan: Planner,
    *,
    out_dir: Path,
    seed: int,
    flags: LigFlags,
    render: Renderer = render_with_lig,
    keep_going: bool = False,
    request: str = "",
    gemma_model: str | None = None,
) -> SeriesResult:
    """Plan and render shot by shot; the next `gemma` call waits for the render to finish.

    A `lig` failure stops the series with lig's exit code (finished shots stay);
    `keep_going` renders the rest and exits 1 at the end.
    """
    result = SeriesResult()
    manifest = SeriesManifest(
        request=request,
        gemma_model=gemma_model,
        plan=settings,
        continuity=CONTINUITY_PROMPT,
        seed=seed,
        lig_version=__version__,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    write_manifest(out_dir, manifest)
    stopped = False
    shots = iter(plan(settings))
    index = 0
    while True:
        try:
            shot = next(shots)
        except StopIteration:
            break
        except SeriesError as error:
            print(f"error: {error}", file=sys.stderr)
            result.exit_code = error.exit_code
            manifest.shots.append(
                ShotRecord(index=index + 1, status="failed", exit_code=error.exit_code)
            )
            stopped = True
            break
        index += 1
        label = f"{index}/{settings.count} {shot.title}"
        argv = ["generate", shot.prompt, "--seed", str(seed), "--out", str(out_dir), *flags.argv()]
        started = time.monotonic()
        code, path = render(argv, label)
        entry = ShotRecord(
            index=index,
            status="done",
            title=shot.title,
            scene=shot.scene,
            prompt=shot.prompt,
            wall_seconds=round(time.monotonic() - started, 3),
        )
        if code == 0 and path:
            result.paths.append(Path(path))
            print(path, flush=True)
            entry.png, entry.sidecar, entry.exit_code = path, sidecar_path(path), 0
        else:
            code = code or EXIT_FAILED
            entry.status, entry.exit_code = "failed", code
            print(f"error: shot {label} failed (lig exit {code})", file=sys.stderr)
            result.exit_code = EXIT_FAILED if keep_going else code
        manifest.shots.append(entry)
        write_manifest(out_dir, manifest)
        if code != 0 and not keep_going:
            stopped = True
            break
    if stopped:
        manifest.shots.extend(
            ShotRecord(index=n, status="skipped")
            for n in range(len(manifest.shots) + 1, settings.count + 1)
        )
    write_manifest(out_dir, manifest)
    return result
