"""Pre-flight peak-memory estimate: refuse a run that would swap instead of finishing."""

from lig.models.registry import Registry, RegistryError

GIB = 1024**3


class MemoryRefusal(RuntimeError):
    """The estimated peak exceeds available memory and the run was not forced."""


def _gib(value: int) -> str:
    return f"{value / GIB:.1f} GiB"


def estimate_peak_bytes(
    registry: Registry, engine: str, platform: str, width: int, height: int, edit: bool = False
) -> int:
    """`sum(loaded artifact sizes) * engine_factor + activation(size)`, all in system memory.

    The vision projector is only loaded for edits. Text-encoder offload moves weights between
    GPU and host, but on an iGPU that is one pool, so the total is what matters.
    """
    try:
        spec = registry.engine_memory[engine]
    except KeyError:
        raise RegistryError(f"no memory constants for engine '{engine}'") from None
    loaded = sum(
        a.size_bytes for a in registry.set_for(engine, platform) if edit or a.role != "mmproj"
    )
    return int(loaded * spec.factor + spec.activation_bytes_per_pixel * width * height)


def check(estimate: int, available: int | None, force: bool) -> str | None:
    """Return a warning when forced past a shortfall, raise MemoryRefusal when not forced.

    An unknown available figure (probe failed) never blocks a run.
    """
    if available is None or estimate <= available:
        return None
    figures = f"estimated peak {_gib(estimate)}, available {_gib(available)}"
    if force:
        return f"{figures}; continuing because of --force"
    raise MemoryRefusal(
        f"not enough memory: {figures}.\n"
        "hints: close other applications, choose a smaller size, enable text-encoder "
        "offload, or pass --force to run anyway"
    )
