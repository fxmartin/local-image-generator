"""Shared subprocess plumbing for engine adapters (sd-cli, ncnn-vulkan, ...)."""

import os
import re
import signal
import subprocess
import threading
from collections import deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO

from lig.backends.base import EngineError, ProgressCallback
from lig.core.logs import TAIL_LINES, EngineLog

# Matches `step 3/40` and sd.cpp's `|3/40 - 1.2s/it` progress bar.
PROGRESS_PATTERN = re.compile(r"(?:\bstep\s+|\|\s*)(\d+)/(\d+)")
DEFAULT_GRACE_SECONDS = 5.0
REAP_HEADROOM_SECONDS = 10.0
POLL_SECONDS = 0.1


def _signal_group(proc: subprocess.Popen[str], sig: signal.Signals) -> None:
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass  # group already gone


def _terminate_group(proc: subprocess.Popen[str], grace: float) -> None:
    """SIGTERM the whole group, escalate to SIGKILL after `grace`, then reap with headroom."""
    _signal_group(proc, signal.SIGTERM)
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    # Descendants may outlive the leader, so always follow up with SIGKILL.
    _signal_group(proc, signal.SIGKILL)
    try:
        proc.wait(timeout=REAP_HEADROOM_SECONDS)
    except subprocess.TimeoutExpired:
        pass  # unkillable (D state); nothing more we can do


def run_engine(
    argv: Sequence[str],
    *,
    log: EngineLog,
    on_progress: ProgressCallback | None,
    timeout: float | None = None,
    grace: float = DEFAULT_GRACE_SECONDS,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    output_path: Path | None = None,
) -> None:
    """Run an engine binary to completion, streaming output to `log`.

    Raises EngineError on non-zero exit (with the last 20 stderr lines), on timeout, or when
    the binary cannot be launched. On Ctrl-C the process group is terminated, `output_path`
    (a partial result) is removed, and KeyboardInterrupt propagates.
    """
    try:
        proc = subprocess.Popen(
            list(argv),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            env=None if env is None else dict(env),
            cwd=cwd,
            start_new_session=True,  # own process group so killpg reaches grandchildren
        )
    except OSError as error:
        raise EngineError(f"cannot launch {argv[0]}: {error}", log_path=log.path) from error

    lock = threading.Lock()
    stderr_tail: deque[str] = deque(maxlen=TAIL_LINES)
    cancelled = threading.Event()

    def pump(stream: IO[str], is_stderr: bool) -> None:
        for raw in stream:
            line = raw.rstrip("\r\n")
            with lock:
                log.write(line)
                if is_stderr:
                    stderr_tail.append(line)
            match = PROGRESS_PATTERN.search(line)
            if match and on_progress is not None and not cancelled.is_set():
                try:
                    on_progress(int(match[1]), int(match[2]))
                except BaseException:  # noqa: BLE001 - surface in main thread as cancel
                    cancelled.set()
                    _signal_group(proc, signal.SIGTERM)

    assert proc.stdout is not None and proc.stderr is not None
    threads = [
        threading.Thread(target=pump, args=(proc.stdout, False), daemon=True),
        threading.Thread(target=pump, args=(proc.stderr, True), daemon=True),
    ]
    for thread in threads:
        thread.start()

    timed_out = False
    try:
        elapsed = 0.0
        while True:
            try:
                proc.wait(timeout=POLL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                elapsed += POLL_SECONDS
                if cancelled.is_set():
                    raise KeyboardInterrupt from None
                if timeout is not None and elapsed >= timeout:
                    timed_out = True
                    _terminate_group(proc, grace)
                    break
        if cancelled.is_set():  # callback aborted the run and the group already exited
            raise KeyboardInterrupt
    except KeyboardInterrupt:
        _terminate_group(proc, grace)
        if output_path is not None:
            output_path.unlink(missing_ok=True)
        raise
    finally:
        # Bounded joins: a leaked grandchild holding the pipe must not hang us.
        for thread in threads:
            thread.join(timeout=REAP_HEADROOM_SECONDS)

    stderr = "\n".join(stderr_tail)
    if timed_out:
        raise EngineError("timeout", stderr, log.path)
    if proc.returncode != 0:
        raise EngineError(f"engine exited with code {proc.returncode}", stderr, log.path)
