"""Layered configuration: flag > `LIG_*` env > config.toml > defaults, with per-key provenance."""

import os
import re
import shlex
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import platformdirs
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

ENV_PREFIX = "LIG_"
ENV_NESTED_SEP = "__"
SIZE_MULTIPLE = 32


class ConfigError(Exception):
    """Raised when the config file or a supplied value cannot be used."""


class ServeSettings(BaseModel):
    # None = tailnet address if Tailscale is up, else loopback (see lig.server.bind).
    bind: str | None = None
    # Seconds a warm engine stays loaded after the last job; 0 unloads after every job.
    idle_ttl: float = Field(default=600, ge=0)


class SdcppSettings(BaseModel):
    # Appended verbatim to the sd-cli argv; an env var is split shell-style.
    extra_args: list[str] = []

    @field_validator("extra_args", mode="before")
    @classmethod
    def _split_string(cls, value: Any) -> Any:
        return shlex.split(value) if isinstance(value, str) else value


class NcnnSettings(BaseModel):
    pass


class EnginesSettings(BaseModel):
    ncnn: NcnnSettings = NcnnSettings()
    sdcpp: SdcppSettings = SdcppSettings()


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: str = "auto"
    output_dir: Path = Path("./outputs")
    models_dir: Path = Path(platformdirs.user_cache_dir("lig")) / "models"
    default_host: str | None = None
    ncnn_binary: str | None = None
    ncnn_model_dir: Path | None = None
    steps: int = 40
    size: str = "1024x1024"
    serve: ServeSettings = ServeSettings()
    engines: EnginesSettings = EnginesSettings()

    @field_validator("size")
    @classmethod
    def _size_multiple_of_32(cls, value: str) -> str:
        match = re.fullmatch(r"(\d+)x(\d+)", value)
        if not match or any(int(d) % SIZE_MULTIPLE or int(d) == 0 for d in match.groups()):
            raise ValueError(f"must be WIDTHxHEIGHT, both multiples of {SIZE_MULTIPLE}")
        return value

    @field_validator("output_dir", "models_dir", "ncnn_model_dir")
    @classmethod
    def _expand_user(cls, value: Path | None) -> Path | None:
        return None if value is None else value.expanduser()


@dataclass
class ResolvedConfig:
    settings: Settings
    provenance: dict[str, str]
    path: Path
    warnings: list[str] = field(default_factory=list)


def default_config_path() -> Path:
    return Path(platformdirs.user_config_dir("lig")) / "config.toml"


def _leaf_keys(model: type[BaseModel], prefix: str = "") -> list[str]:
    keys: list[str] = []
    for name, info in model.model_fields.items():
        annotation = info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            keys += _leaf_keys(annotation, f"{prefix}{name}.")
        else:
            keys.append(f"{prefix}{name}")
    return keys


def _flatten(data: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{prefix}{key}."))
        else:
            flat[f"{prefix}{key}"] = value
    return flat


def _key_lines(text: str) -> dict[str, int]:
    """Map dotted key -> 1-based line, tracking `[table]` headers (tomllib gives no positions)."""
    lines: dict[str, int] = {}
    table = ""
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        header = re.fullmatch(r"\[\s*([^\[\]]+?)\s*\]\s*(#.*)?", line)
        if header:
            table = header.group(1).replace(" ", "") + "."
            continue
        assign = re.match(r"([A-Za-z0-9_.\-]+)\s*=", line)
        if assign:
            lines.setdefault(f"{table}{assign.group(1)}", number)
    return lines


def _read_file(path: Path) -> tuple[dict[str, Any], list[str]]:
    if not path.is_file():
        return {}, []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: cannot read: {exc}") from exc
    try:
        flat = _flatten(tomllib.loads(text))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc
    known = set(_leaf_keys(Settings))
    lines = _key_lines(text)
    warnings = [
        f"{path}: unknown key '{key}' at line {lines.get(key, '?')} ignored"
        for key in flat
        if key not in known
    ]
    return {k: v for k, v in flat.items() if k in known}, warnings


def _read_env(env: Mapping[str, str]) -> dict[str, Any]:
    by_env_name = {
        ENV_PREFIX + key.upper().replace(".", ENV_NESTED_SEP): key for key in _leaf_keys(Settings)
    }
    return {by_env_name[name]: value for name, value in env.items() if name in by_env_name}


def _nest(flat: Mapping[str, Any]) -> dict[str, Any]:
    nested: dict[str, Any] = {}
    for key, value in flat.items():
        *parents, leaf = key.split(".")
        node = nested
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value
    return nested


def load_settings(
    flags: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    path: Path | None = None,
) -> ResolvedConfig:
    """Resolve settings; `flags` use dotted keys and `None` means "flag not given"."""
    path = path or default_config_path()
    file_values, warnings = _read_file(path)
    layers = [
        ("flag", {k: v for k, v in (flags or {}).items() if v is not None}),
        ("env", _read_env(os.environ if env is None else env)),
        ("file", file_values),
    ]
    values: dict[str, Any] = {}
    provenance = {key: "default" for key in _leaf_keys(Settings)}
    for source, layer in reversed(layers):  # lowest precedence first, higher overwrite
        for key, value in layer.items():
            if key in provenance:
                values[key] = value
                provenance[key] = source
    try:
        settings = Settings.model_validate(_nest(values))
    except ValidationError as exc:
        bad = [(".".join(map(str, e["loc"])), e["msg"]) for e in exc.errors()]
        details = "; ".join(f"{key} (from {provenance.get(key)}): {msg}" for key, msg in bad)
        raise ConfigError(f"invalid configuration: {details}") from exc
    return ResolvedConfig(settings, provenance, path, warnings)


def _dotted_value(settings: Settings, key: str) -> Any:
    node: Any = settings
    for part in key.split("."):
        node = getattr(node, part)
    return node


def effective_values(resolved: ResolvedConfig) -> list[tuple[str, Any, str]]:
    return [
        (key, _dotted_value(resolved.settings, key), source)
        for key, source in resolved.provenance.items()
    ]


CONFIG_TEMPLATE = """\
# lig configuration. Precedence: command-line flag > LIG_* env var > this file > defaults.
# Nested keys map to env vars with a double underscore, e.g. LIG_SERVE__BIND.

# Inference engine: auto, sdcpp, ncnn, mlx or remote.
# engine = "auto"

# Where generated images are written.
# output_dir = "./outputs"

# Where model weights are cached.
# models_dir = "~/.cache/lig/models"

# Remote `lig serve` host on the tailnet, used by the remote engine.
# default_host = "macbook-pro-m3-max.tailac3c7a.ts.net:8765"

# Path to the qwenimage-ncnn-vulkan binary (default: found on PATH).
# ncnn_binary = "/opt/qwenimage-ncnn-vulkan/qwenimage-ncnn-vulkan"

# The qwenimage21/ model folder used by the ncnn engine.
# ncnn_model_dir = "~/.cache/lig/models/qwenimage21"

# Extra sd-cli arguments for the sdcpp engine, appended verbatim
# (env: LIG_ENGINES__SDCPP__EXTRA_ARGS, split shell-style).
# engines.sdcpp.extra_args = ["--model-args", "qwen_image_2_1_prefix_cache=false"]

# Sampling steps.
# steps = 40

# Image size as WIDTHxHEIGHT, both multiples of 32.
# size = "1024x1024"

# [serve]
# Unset: the Tailscale address on port 7860 if Tailscale is up, else 127.0.0.1:7860.
# bind = "100.64.0.1:7860"
# Seconds a warm (in-process) engine stays loaded after the last job; 0 = unload after every job.
# No effect on subprocess engines such as sdcpp.
# idle_ttl = 600
"""


def write_config_template(path: Path) -> None:
    """Write the commented template; refuses to overwrite an existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x") as handle:
            handle.write(CONFIG_TEMPLATE)
    except FileExistsError as exc:
        raise ConfigError(f"{path} already exists; refusing to overwrite") from exc
