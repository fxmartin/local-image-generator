"""Generate a CHANGELOG.md section for a release from conventional commits.

Usage: changelog.py <version> [--since TAG] [--date YYYY-MM-DD] [--write]

Without --write the section is printed. With --write it is inserted into CHANGELOG.md
(idempotent per version). Only feat, fix and breaking changes are listed.
"""

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
_HEADER = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?: (?P<subject>.+)$")
_BREAKING_FOOTER = re.compile(r"^BREAKING[ -]CHANGE: (.+)$", re.MULTILINE)


def _line(scope: str | None, subject: str) -> str:
    return f"- **{scope}:** {subject}" if scope else f"- {subject}"


def render_section(version: str, day: str, commits: list[tuple[str, str]]) -> str:
    """Render ``## [version] - day`` from (header, body) pairs."""
    breaking: list[str] = []
    features: list[str] = []
    fixes: list[str] = []
    for header, body in commits:
        match = _HEADER.match(header)
        if not match:
            continue
        entry = _line(match["scope"], match["subject"])
        footer = _BREAKING_FOOTER.search(body)
        if match["bang"] or footer:
            breaking.append(entry if match["bang"] else _line(match["scope"], footer[1]))
        if match["type"] == "feat":
            features.append(entry)
        elif match["type"] == "fix":
            fixes.append(entry)
    parts = [f"## [{version}] - {day}"]
    for title, lines in (
        ("Breaking changes", breaking),
        ("Features", features),
        ("Bug fixes", fixes),
    ):
        if lines:
            parts.append(f"### {title}\n\n" + "\n".join(lines))
    return "\n\n".join(parts) + "\n"


def prepend(text: str, version: str, section: str) -> str:
    """Insert ``section`` above the newest release; a no-op if ``version`` is present."""
    if f"## [{version}]" in text:
        return text
    if not text.strip():
        return f"# Changelog\n\n{section}"
    head, sep, rest = text.partition("\n## ")
    if not sep:
        return f"{text.rstrip()}\n\n{section}"
    return f"{head}\n{section}\n## {rest}"


def commits_since(since: str | None) -> list[tuple[str, str]]:
    rev = f"{since}..HEAD" if since else "HEAD"
    out = subprocess.run(
        ["git", "log", "--no-merges", "--format=%s%x1f%b%x1e", rev],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    pairs = (record.strip("\n").split("\x1f", 1) for record in out.split("\x1e") if record.strip())
    return [(header, body) for header, body in pairs]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--since")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    section = render_section(args.version, args.date, commits_since(args.since))
    if not args.write:
        print(section, end="")
        return 0
    existing = CHANGELOG.read_text() if CHANGELOG.exists() else ""
    CHANGELOG.write_text(prepend(existing, args.version, section))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
