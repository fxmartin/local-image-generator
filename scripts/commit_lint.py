"""Python-only conventional-commit check, mirroring .commitlintrc.json.

The offline CI image has no Node, so commitlint itself cannot run there. Merge commits
are skipped; history before the range start is exempt by construction.

Usage: commit_lint.py <rev-range>   e.g. origin/main..HEAD
"""

import re
import subprocess
import sys
from pathlib import Path

TYPES = ("feat", "fix", "chore", "docs", "refactor", "test", "ci", "perf", "build", "revert")
MAX_HEADER = 72
_HEADER = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[a-z0-9._-]+)\))?!?: (?P<subject>\S.*)$")


def check_header(header: str) -> list[str]:
    """Return the rule violations for one commit header (empty when valid)."""
    problems = []
    if len(header) > MAX_HEADER:
        problems.append(f"header is {len(header)} chars, max {MAX_HEADER}")
    match = _HEADER.match(header)
    if not match:
        return [*problems, "expected 'type(scope): subject' with a lower-case type and scope"]
    if match["type"] not in TYPES:
        problems.append(f"type '{match['type']}' not in {', '.join(TYPES)}")
    subject = match["subject"]
    if subject[0].isupper():
        problems.append("subject must start lower-case")
    if subject.endswith("."):
        problems.append("subject must not end with a period")
    return problems


def commit_headers(rev_range: str, cwd: Path | None = None) -> list[str]:
    """Header lines of the non-merge commits in ``rev_range``, newest first."""
    out = subprocess.run(
        ["git", "log", "--no-merges", "--format=%s", rev_range],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.splitlines()


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    failed = False
    for header in commit_headers(argv[0]):
        if header.startswith("Merge "):
            continue
        for problem in check_header(header):
            failed = True
            print(f"commit-format: {header!r}: {problem}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
