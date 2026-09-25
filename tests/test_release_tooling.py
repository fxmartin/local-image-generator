"""Conventional commits, changelog generation and tag/version alignment (Story 05.1-002)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


commit_lint = _load("commit_lint")
changelog = _load("changelog")
release_check = _load("release_check")


# --- commit_lint -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "header",
    [
        "feat(release-docs): conventional commits, changelog and (#05.1-002)",
        "fix: handle empty prompt",
        "fix(hooks)!: drop unused stdin",
        "docs: document the commit format",
    ],
)
def test_valid_headers_pass(header):
    assert commit_lint.check_header(header) == []


@pytest.mark.parametrize(
    "header",
    [
        "Add a feature",
        "feature: unknown type",
        "Feat: upper-case type",
        "feat(Scope): upper-case scope",
        "feat: Upper-case subject",
        "feat: trailing period.",
        "feat:no space",
        "feat: " + "x" * 70,
        "feat: ",
    ],
)
def test_invalid_headers_fail(header):
    assert commit_lint.check_header(header)


def test_rules_match_commitlintrc():
    rc = json.loads((ROOT / ".commitlintrc.json").read_text())
    assert rc["extends"] == ["@commitlint/config-conventional"]
    assert rc["rules"]["header-max-length"][2] == commit_lint.MAX_HEADER
    assert rc["rules"]["type-enum"][2] == list(commit_lint.TYPES)


def test_main_reports_bad_commits_and_skips_merges(monkeypatch, capsys):
    monkeypatch.setattr(
        commit_lint,
        "commit_headers",
        lambda rev_range: ["Merge branch 'x' into 'main'", "bad header", "fix: ok"],
    )
    assert commit_lint.main(["origin/main..HEAD"]) == 1
    out = capsys.readouterr().out
    assert "bad header" in out
    assert "Merge branch" not in out


def test_main_passes_on_clean_range(monkeypatch):
    monkeypatch.setattr(commit_lint, "commit_headers", lambda rev_range: ["fix: ok"])
    assert commit_lint.main(["origin/main..HEAD"]) == 0


def test_commit_headers_reads_git_log(tmp_path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "a: b")
    git(
        "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "fix: c"
    )
    assert commit_lint.commit_headers("HEAD", cwd=tmp_path) == ["fix: c", "a: b"]


# --- changelog -------------------------------------------------------------------------


def test_section_groups_by_commit_type():
    section = changelog.render_section(
        "1.2.0",
        "2026-09-26",
        [
            ("feat(cli): add seeds verb", ""),
            ("fix: crash on empty prompt", ""),
            ("chore: bump deps", ""),
            ("refactor(core)!: rename request", ""),
            ("fix: other", "BREAKING CHANGE: config key renamed"),
        ],
    )
    assert section.startswith("## [1.2.0] - 2026-09-26")
    breaking, features, fixes = (
        section.index("### Breaking changes"),
        section.index("### Features"),
        section.index("### Bug fixes"),
    )
    assert breaking < features < fixes
    assert "- **cli:** add seeds verb" in section
    assert "- crash on empty prompt" in section
    assert "rename request" in section.split("### Features")[0]
    assert "config key renamed" in section.split("### Features")[0]
    assert "bump deps" not in section


def test_prepend_inserts_below_header_and_is_idempotent():
    text = "# Changelog\n\nintro\n\n## [1.0.0] - 2026-01-01\n\n### Features\n\n- old\n"
    section = "## [1.1.0] - 2026-02-01\n\n### Features\n\n- new\n"
    out = changelog.prepend(text, "1.1.0", section)
    assert out.index("[1.1.0]") < out.index("[1.0.0]")
    assert out.startswith("# Changelog")
    assert changelog.prepend(out, "1.1.0", section) == out


def test_prepend_creates_header_when_missing():
    out = changelog.prepend("", "1.0.0", "## [1.0.0] - 2026-01-01\n")
    assert out.startswith("# Changelog")


# --- release_check ---------------------------------------------------------------------


def _project(tmp_path, pyproject="0.1.0", lock="0.1.0"):
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "local-image-generator"\nversion = "{pyproject}"\n'
    )
    (tmp_path / "uv.lock").write_text(
        f'[[package]]\nname = "other"\nversion = "9.9.9"\n\n'
        f'[[package]]\nname = "local-image-generator"\nversion = "{lock}"\n'
    )
    return tmp_path


def test_matching_tag_passes(tmp_path):
    assert release_check.check("v0.1.0", _project(tmp_path)) == []


def test_mismatched_tag_names_both_values(tmp_path):
    problems = release_check.check("v0.2.0", _project(tmp_path))
    assert any("v0.2.0" in p and "0.1.0" in p for p in problems)


def test_tag_without_v_prefix_is_rejected(tmp_path):
    assert release_check.check("0.1.0", _project(tmp_path))


def test_stale_lockfile_is_rejected(tmp_path):
    problems = release_check.check("v0.1.0", _project(tmp_path, lock="0.0.9"))
    assert any("uv.lock" in p and "0.0.9" in p for p in problems)


def test_main_exits_1_on_mismatch(tmp_path, capsys):
    assert release_check.main(["v0.2.0", "--root", str(_project(tmp_path))]) == 1
    err = capsys.readouterr().err
    assert "v0.2.0" in err and "0.1.0" in err


def test_main_exits_0_on_match(tmp_path):
    assert release_check.main(["v0.1.0", "--root", str(_project(tmp_path))]) == 0


def test_repo_lockfile_is_aligned_with_pyproject():
    assert release_check.check("v" + release_check.project_version(ROOT), ROOT) == []


# --- CI wiring -------------------------------------------------------------------------


def test_ci_has_commit_format_job_without_node_in_test_image():
    ci = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text())
    job = ci["commit-format"]
    assert any("scripts/commit_lint.py" in line for line in job["script"])
    assert job["rules"][0]["if"] == '$CI_PIPELINE_SOURCE == "merge_request_event"'
    assert ci["variables"].get("GIT_DEPTH") == "0"
    assert any("scripts/release_check.py" in line for line in ci["release-check"]["script"])


# --- coverage gaps: changelog CLI, git range, edge cases --------------------------------


def _git_repo(path, *messages):
    def git(*args):
        subprocess.run(
            ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t", *args],
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    for message in messages:
        git("commit", "-q", "--allow-empty", "-m", message)
    return git


def test_render_section_skips_non_conventional_and_reads_breaking_footer():
    section = changelog.render_section(
        "2.0.0",
        "2026-01-01",
        [
            ("not conventional", ""),
            ("chore: tidy", ""),
            ("feat(api): new route", "BREAKING CHANGE: route renamed"),
            ("fix!: drop flag", ""),
            ("feat: unscoped", ""),
        ],
    )
    assert "not conventional" not in section and "tidy" not in section
    assert "- **api:** route renamed" in section
    assert "- drop flag" in section
    assert "- unscoped" in section


def test_prepend_appends_when_no_release_yet():
    out = changelog.prepend("# Changelog\n", "1.0.0", "## [1.0.0] - 2026-01-01\n")
    assert out == "# Changelog\n\n## [1.0.0] - 2026-01-01\n"


def test_commits_since_returns_header_body_pairs(tmp_path, monkeypatch):
    git = _git_repo(tmp_path, "feat: first")
    git("tag", "v0.1.0")
    git("commit", "-q", "--allow-empty", "-m", "fix(core): second", "-m", "body text")
    monkeypatch.chdir(tmp_path)
    assert changelog.commits_since("v0.1.0") == [("fix(core): second", "body text")]
    assert [h for h, _ in changelog.commits_since(None)] == ["fix(core): second", "feat: first"]


def test_main_prints_section_without_write(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(changelog, "commits_since", lambda since: [("feat: shiny", "")])
    assert changelog.main(["1.2.3", "--date", "2026-02-03"]) == 0
    assert "## [1.2.3] - 2026-02-03" in capsys.readouterr().out


def test_main_write_creates_and_is_idempotent(tmp_path, monkeypatch):
    target = tmp_path / "CHANGELOG.md"
    monkeypatch.setattr(changelog, "CHANGELOG", target)
    monkeypatch.setattr(changelog, "commits_since", lambda since: [("fix: bug", "")])
    args = ["1.2.3", "--date", "2026-02-03", "--write"]
    assert changelog.main(args) == 0
    first = target.read_text()
    assert first.startswith("# Changelog") and "- bug" in first
    assert changelog.main(args) == 0
    assert target.read_text() == first


def test_commit_lint_main_requires_one_argument(capsys):
    assert commit_lint.main([]) == 2
    assert "Usage" in capsys.readouterr().err


def test_lock_version_is_none_when_project_missing_from_lock(tmp_path):
    root = _project(tmp_path)
    (root / "uv.lock").write_text('[[package]]\nname = "other"\nversion = "1.0.0"\n')
    assert release_check.lock_version(root) is None
