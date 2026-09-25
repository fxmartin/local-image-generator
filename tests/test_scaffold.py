import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ["backends", "cli", "core", "models", "server"]


@pytest.mark.skipif(
    shutil.which("git") is None or not (REPO_ROOT / ".git").exists(),
    reason="needs git and a git checkout",
)
@pytest.mark.parametrize("package", PACKAGES)
def test_package_is_not_gitignored(package):
    # Weight-cache ignore rules (e.g. models/) must not swallow source packages,
    # or a fresh clone ships without them.
    path = f"src/lig/{package}/__init__.py"
    result = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT, capture_output=True)
    assert result.returncode == 1, f"{path} is ignored by .gitignore"
