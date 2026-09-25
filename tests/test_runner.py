import os
import sys
import textwrap
import time
from pathlib import Path

import pytest
from rich.console import Console

from lig.backends.base import EngineError
from lig.backends.runner import run_engine
from lig.core.logs import EngineLog


def make_stub(tmp_path: Path, body: str) -> list[str]:
    script = tmp_path / "stub.py"
    script.write_text(textwrap.dedent(body))
    return [sys.executable, str(script)]


@pytest.fixture
def log(tmp_path):
    with EngineLog("stub", log_dir=tmp_path / "logs", console=Console(quiet=True)) as engine_log:
        yield engine_log


def test_progress_lines_call_back_and_output_is_logged(tmp_path, log):
    argv = make_stub(
        tmp_path,
        """
        import sys
        for i in (1, 2, 3):
            print(f"step {i}/40", flush=True)
        print("|4/40 - 1.0it/s", file=sys.stderr, flush=True)
        """,
    )
    seen: list[tuple[int, int]] = []
    run_engine(argv, log=log, on_progress=lambda s, t: seen.append((s, t)))
    assert sorted(seen) == [(1, 40), (2, 40), (3, 40), (4, 40)]
    text = log.path.read_text()
    assert "step 3/40" in text and "|4/40" in text


def test_no_callback_is_fine(tmp_path, log):
    run_engine(make_stub(tmp_path, "print('step 1/2')"), log=log, on_progress=None)


def test_nonzero_exit_carries_code_and_last_20_stderr_lines(tmp_path, log):
    argv = make_stub(
        tmp_path,
        """
        import sys
        for i in range(30):
            print(f"err {i}", file=sys.stderr)
        sys.exit(3)
        """,
    )
    with pytest.raises(EngineError) as info:
        run_engine(argv, log=log, on_progress=None)
    message = str(info.value)
    assert "3" in message.splitlines()[0]
    assert "err 29" in message and "err 10" in message
    assert "err 9\n" not in message
    assert info.value.log_path == log.path


def test_timeout_kills_process_group_and_raises(tmp_path, log):
    pidfile = tmp_path / "child.pid"
    argv = make_stub(
        tmp_path,
        f"""
        import subprocess, sys, time
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        open({str(pidfile)!r}, "w").write(str(child.pid))
        time.sleep(60)
        """,
    )
    with pytest.raises(EngineError, match="^timeout"):
        run_engine(argv, log=log, on_progress=None, timeout=1.5, grace=1.0)
    child_pid = int(pidfile.read_text())
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
            # A zombie (no init reaper in CI) still answers signal 0; check its state.
            state = Path(f"/proc/{child_pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
            if state == "Z":
                break
        except (ProcessLookupError, FileNotFoundError):
            break
        time.sleep(0.1)
    else:
        pytest.fail("grandchild survived the process-group kill")


def test_sigterm_ignoring_child_is_escalated_to_sigkill(tmp_path, log):
    argv = make_stub(
        tmp_path,
        """
        import signal, time
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        print("ready", flush=True)
        time.sleep(60)
        """,
    )
    with pytest.raises(EngineError, match="^timeout"):
        run_engine(argv, log=log, on_progress=None, timeout=1.5, grace=0.5)


def test_ctrl_c_terminates_and_removes_partial_output(tmp_path, log):
    out = tmp_path / "partial.png"
    out.write_bytes(b"partial")

    def interrupt(step: int, total: int) -> None:
        raise KeyboardInterrupt

    argv = make_stub(tmp_path, "print('step 1/2', flush=True)\nimport time; time.sleep(60)")
    with pytest.raises(KeyboardInterrupt):
        run_engine(argv, log=log, on_progress=interrupt, output_path=out, grace=0.5)
    assert not out.exists()


def test_missing_binary_raises_engine_error(tmp_path, log):
    with pytest.raises(EngineError):
        run_engine([str(tmp_path / "nope")], log=log, on_progress=None)
