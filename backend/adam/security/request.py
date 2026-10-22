from collections.abc import Callable
from contextvars import ContextVar

AUTHORITY: ContextVar[Callable[[], None] | None] = ContextVar("adam_authority", default=None)
REMOTE_DEVICE: ContextVar[str | None] = ContextVar("adam_remote_device", default=None)


def check_authority() -> None:
    guard = AUTHORITY.get()
    if guard is not None:
        guard()
