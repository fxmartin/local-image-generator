"""The API key lig sends to an OpenAI-compatible LLM gateway (larm on the M3 Max).

Kept out of config.toml on purpose: the key comes from `LIG_LLM_API_KEY` or a file of its own
(`llm.key` beside config.toml, chmod 600). `--rewrite` sends it as a Bearer token; `lig-series`
hands it to `gemma` as `LARM_API_KEY`, so the gateway counts both under lig's own key.
"""

import os
from pathlib import Path

import platformdirs

KEY_ENV = "LIG_LLM_API_KEY"
KEY_FILE = "llm.key"


def key_path() -> Path:
    return Path(platformdirs.user_config_dir("lig")) / KEY_FILE


def read_api_key() -> str | None:
    """The env var, else the key file; None when neither holds a key (keyless servers work)."""
    key = os.environ.get(KEY_ENV, "").strip()
    if key:
        return key
    try:
        key = key_path().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return key or None
