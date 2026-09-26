"""Keeps .gitlab-ci.yml on the local-ci-cd platform's offline contract."""

from pathlib import Path

import yaml

CI_FILE = Path(__file__).resolve().parents[1] / ".gitlab-ci.yml"
# Same Alpine base `local-ci-cd cache warm-deps` warms with, so the cached wheels
# (musllinux) are the ones the job resolves. A glibc image misses every native wheel.
UV_GIT_IMAGE = "127.0.0.1:5001/local/uv-git@sha256:"


def _ci() -> dict:
    return yaml.safe_load(CI_FILE.read_text())


def test_uv_cache_dir_is_left_to_the_executor():
    # prepare_exec mounts the project-keyed uv cache volume and sets UV_CACHE_DIR;
    # overriding it points uv at an empty directory and every offline sync fails.
    ci = _ci()
    assert "UV_CACHE_DIR" not in ci.get("variables", {})
    assert "UV_CACHE_DIR" not in ci["test"].get("variables", {})


def test_installs_are_offline_and_frozen():
    ci = _ci()
    assert ci["variables"]["UV_OFFLINE"] == "1"
    assert ci["variables"]["UV_PYTHON_DOWNLOADS"] == "never"
    assert "uv sync --frozen" in ci["test"]["script"][0]


def test_ci_installs_the_serve_extra_so_server_tests_run():
    # Without it every FastAPI-dependent test is skipped (44 on 2026-09-26).
    assert "--extra serve" in _ci()["test"]["script"][0]


def test_job_image_is_the_digest_pinned_uv_git_image():
    assert _ci()["test"]["image"].startswith(UV_GIT_IMAGE)


def test_merge_requests_get_a_pipeline():
    # The sdlc merge gate polls the MR pipeline; without this rule there is none.
    rules = _ci()["workflow"]["rules"]
    assert any("merge_request_event" in rule.get("if", "") for rule in rules)


def test_test_job_runs_lint_format_and_coverage():
    script = _ci()["test"]["script"]
    assert "uv run ruff check ." in script
    assert "uv run ruff format --check ." in script
    assert "uv run pytest --cov" in script
