"""Shared test helpers (not collected by pytest)."""

from typing import Any


def construct(parent: object, name: str, *args: Any, **kwargs: Any) -> Any:
    """The dynamic construction path `parent.Name(...)`, via getattr.

    Static checkers cannot see attributes the metaclass binds at define
    time; getattr keeps the Any boundary explicit (the documented dynamic
    boundary — see types.py).
    """
    constructor: Any = getattr(parent, name)
    result: Any = constructor(*args, **kwargs)
    return result


def null_handler(*args: Any, **kwargs: Any) -> None:
    """A typed no-op handler for tests (lambdas are untyped under strict)."""
