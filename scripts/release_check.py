"""Fail unless a release tag vX.Y.Z matches pyproject.toml and uv.lock.

Usage: release_check.py <tag> [--root DIR]
"""

import argparse
import sys
import tomllib
from pathlib import Path


def project_version(root: Path) -> str:
    return tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]


def _project_name(root: Path) -> str:
    return tomllib.loads((root / "pyproject.toml").read_text())["project"]["name"]


def lock_version(root: Path) -> str | None:
    lock = tomllib.loads((root / "uv.lock").read_text())
    name = _project_name(root)
    return next((p["version"] for p in lock["package"] if p["name"] == name), None)


def check(tag: str, root: Path) -> list[str]:
    """Return the mismatches between ``tag``, pyproject.toml and uv.lock."""
    version = project_version(root)
    problems = []
    if tag != f"v{version}":
        problems.append(f"tag {tag} != pyproject.toml version {version} (expected v{version})")
    locked = lock_version(root)
    if locked != version:
        problems.append(
            f"uv.lock version {locked} != pyproject.toml version {version}; run `uv lock`"
        )
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    problems = check(args.tag, args.root)
    for problem in problems:
        print(f"release-check: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
