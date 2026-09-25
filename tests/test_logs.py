import io

import pytest
from rich.console import Console
from typer.testing import CliRunner

from lig.backends.base import EngineError
from lig.cli.app import app, handle_engine_errors
from lig.core import logs
from lig.core.logs import MAX_LOG_FILES, EngineLog, prune_logs, report_engine_error, tail_lines

runner = CliRunner()


def quiet_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, width=200)


def test_streams_to_file_and_creates_missing_dir(tmp_path):
    log_dir = tmp_path / "state" / "logs"
    with EngineLog("sdcpp", log_dir=log_dir, console=quiet_console()) as log:
        log.write("step 1/40")
        log.write("step 2/40\n")
    assert log.path.parent == log_dir
    assert log.path.name.endswith("_sdcpp.log")
    assert log.path.read_text() == "step 1/40\nstep 2/40\n"


def test_default_dir_uses_platform_state_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(logs, "user_state_dir", lambda app: str(tmp_path / app))
    with EngineLog("fake") as log:
        pass
    assert log.path.parent == tmp_path / "lig" / "logs"


def test_verbose_echoes_and_quiet_does_not(tmp_path):
    for verbose in (True, False):
        out = io.StringIO()
        console = Console(file=out, force_terminal=False)
        with EngineLog("e", verbose=verbose, log_dir=tmp_path, console=console) as log:
            log.write("[bold]hello[/]")
        assert ("[bold]hello[/]" in out.getvalue()) is verbose


def test_prunes_oldest_beyond_limit(tmp_path):
    for i in range(MAX_LOG_FILES + 5):
        (tmp_path / f"2020{i:04d}T000000000000_e.log").write_text("x")
    with EngineLog("e", log_dir=tmp_path, console=quiet_console()) as log:
        pass
    remaining = sorted(p.name for p in tmp_path.glob("*.log"))
    assert len(remaining) == MAX_LOG_FILES
    assert log.path.name in remaining
    assert "20200000T000000000000_e.log" not in remaining


def test_prune_ignores_non_logs_and_small_dirs(tmp_path):
    (tmp_path / "keep.txt").write_text("x")
    (tmp_path / "a.log").write_text("x")
    prune_logs(tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == {"keep.txt", "a.log"}


def test_tail_lines(tmp_path):
    path = tmp_path / "x.log"
    path.write_text("\n".join(str(i) for i in range(30)))
    assert tail_lines(path) == [str(i) for i in range(10, 30)]
    assert tail_lines(None) == []
    assert tail_lines(tmp_path / "missing.log") == []


def test_report_plain_text_off_tty(tmp_path):
    path = tmp_path / "x.log"
    path.write_text("\n".join(f"line{i}" for i in range(25)))
    out = io.StringIO()
    report_engine_error(EngineError("boom\nextra"), path, Console(file=out, force_terminal=False))
    text = out.getvalue()
    assert text.splitlines()[0] == "Error: boom"
    assert "line4" not in text and "line5" in text and "line24" in text
    assert f"Log: {path}" in text
    assert "╭" not in text


def test_report_panel_on_tty(tmp_path):
    path = tmp_path / "x.log"
    path.write_text("line1")
    out = io.StringIO()
    report_engine_error(EngineError("boom"), path, Console(file=out, force_terminal=True))
    assert "╭" in out.getvalue()


def test_report_without_log(tmp_path):
    out = io.StringIO()
    report_engine_error(EngineError("boom"), None, Console(file=out, force_terminal=False))
    assert "Log:" not in out.getvalue()


@pytest.fixture
def failing_app(tmp_path):
    log_path = tmp_path / "run.log"
    log_path.write_text("engine said no\n")

    @app.command("_fail")
    @handle_engine_errors
    def _fail() -> None:
        raise EngineError("engine crashed", log_path=log_path)

    yield log_path
    app.registered_commands = [c for c in app.registered_commands if c.name != "_fail"]


def test_cli_handles_engine_error(failing_app):
    result = runner.invoke(app, ["_fail"])
    assert result.exit_code == 1
    assert "Error: engine crashed" in result.output
    assert "engine said no" in result.output
    assert str(failing_app) in result.output
    assert "Traceback" not in result.output


def test_cli_debug_reraises(failing_app):
    result = runner.invoke(app, ["--debug", "_fail"])
    assert isinstance(result.exception, EngineError)
