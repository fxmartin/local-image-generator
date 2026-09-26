"""Pick the `lig serve` listen address: tailnet by default, never the open network by accident."""

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

DEFAULT_PORT = 7860
LOOPBACK = "127.0.0.1"
# Tailscale hands out CGNAT addresses; interface names differ per OS (Linux vs macOS).
_TAILSCALE_IFACES = ("tailscale0",)
_TAILSCALE_IFACE_PREFIX = "utun"
_WILDCARDS = frozenset({"0.0.0.0", "::"})

TailscaleProbe = Callable[[], str | None]


def _is_tailnet_ip(text: str) -> bool:
    parts = text.split(".")
    if len(parts) != 4 or not all(p.isdigit() and int(p) < 256 for p in parts):
        return False
    return parts[0] == "100" and 64 <= int(parts[1]) <= 127


def _from_cli() -> str | None:
    if shutil.which("tailscale") is None:
        return None
    try:
        out = subprocess.run(
            ["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5, check=True
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return next((ln.strip() for ln in out.splitlines() if _is_tailnet_ip(ln.strip())), None)


def _from_interfaces() -> str | None:
    try:
        import psutil
    except ImportError:
        return None
    for name, addrs in psutil.net_if_addrs().items():
        if name in _TAILSCALE_IFACES or name.startswith(_TAILSCALE_IFACE_PREFIX):
            for addr in addrs:
                if _is_tailnet_ip(addr.address):
                    return str(addr.address)
    return None


def probe_tailscale_ip() -> str | None:
    """The host's Tailscale IPv4, or None when Tailscale is absent or down."""
    return _from_cli() or _from_interfaces()


@dataclass(frozen=True)
class BindDecision:
    host: str
    port: int
    notice: str | None = None
    warning: str | None = None


class BindRefused(ValueError):
    """An exposed bind was requested without the explicit override."""


def resolve_bind(
    explicit: tuple[str, int] | None,
    configured: tuple[str, int] | None,
    *,
    probe: TailscaleProbe | None = None,
    i_know: bool = False,
) -> BindDecision:
    """Explicit flag > configured `serve.bind` > tailnet address > loopback."""
    probe = probe or probe_tailscale_ip  # looked up late so tests can swap the module attribute
    chosen = explicit or configured
    if chosen is None:
        ip = probe()
        if ip:
            return BindDecision(
                ip, DEFAULT_PORT, notice=f"Tailscale is up: serving at http://{ip}:{DEFAULT_PORT}"
            )
        return BindDecision(
            LOOPBACK,
            DEFAULT_PORT,
            notice="Tailscale not detected: binding 127.0.0.1 (this host only). To expose it, "
            "start Tailscale, or pass --bind HOST:PORT (0.0.0.0 needs --i-know: there is no auth).",
        )
    host, port = chosen
    if host in _WILDCARDS and probe() is None:
        message = (
            f"binding {host}:{port} exposes lig serve to every network this host is on, "
            "and it has NO authentication; Tailscale was not detected."
        )
        if not i_know:
            raise BindRefused(f"{message} Pass --i-know to proceed anyway.")
        return BindDecision(host, port, warning=message)
    return BindDecision(host, port)
