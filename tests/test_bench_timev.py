"""docs/bench/timev.py stands in for `/usr/bin/time -v` in the XPS bench runs."""

import subprocess
import sys
from pathlib import Path

TIMEV = Path(__file__).resolve().parents[1] / "docs" / "bench" / "timev.py"


def run_timev(*child: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TIMEV), *child], capture_output=True, text=True, timeout=60
    )


def test_reports_wall_time_peak_rss_and_exit_status_in_time_v_form():
    result = run_timev(sys.executable, "-c", "print('hello')")

    assert result.returncode == 0
    assert result.stdout == "hello\n"
    assert "Elapsed (wall clock) time (seconds): " in result.stderr
    assert "Maximum resident set size (kbytes): " in result.stderr
    assert "\tExit status: 0" in result.stderr
    peak = next(line for line in result.stderr.splitlines() if "Maximum resident set size" in line)
    assert int(peak.rsplit(":", 1)[1]) > 0


def test_propagates_child_exit_code():
    result = run_timev(sys.executable, "-c", "import sys; sys.exit(3)")

    assert result.returncode == 3
    assert "\tExit status: 3" in result.stderr
