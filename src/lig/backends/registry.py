"""Engine name -> backend class. The single place new engines are registered."""

from typing import Any

from lig.backends.base import Backend, EngineUnavailable
from lig.backends.fake import FakeBackend

BACKENDS: dict[str, type[Backend]] = {
    "fake": FakeBackend,
}


def get_backend(name: str, **kwargs: Any) -> Backend:
    try:
        cls = BACKENDS[name]
    except KeyError:
        known = ", ".join(sorted(BACKENDS))
        raise EngineUnavailable(f"unknown engine '{name}'; known engines: {known}") from None
    return cls(**kwargs)
