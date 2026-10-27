"""Arguments and attributes that were renamed or removed in 0.4.0: an old spelling raises an
error that gives the new one, instead of Python's "unexpected keyword argument". They go in
a later release."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def renamed(**moves: str) -> Callable[[F], F]:
    """Decorate a function so that each old keyword in ``moves`` raises a TypeError with its
    new spelling, e.g. ``@renamed(label="lane=")``. The signature stays the function's own
    (``inspect.signature`` follows ``__wrapped__``)."""

    def decorate(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            old = [k for k in kwargs if k in moves]
            if old:
                where = getattr(fn, "__qualname__", "").replace(".__init__", "")
                raise TypeError(
                    "; ".join(f"{where}({k}=...) is now {moves[k]}" for k in old)
                    + " (see the changelog)"
                )
            return fn(*args, **kwargs)

        return wrapper  # ty: ignore[invalid-return-type]

    return decorate


def gone(name: str, now: str) -> property:
    """A property that says where a removed attribute went."""

    def fail(*_args: Any) -> Any:
        raise AttributeError(f"{name} is now {now} (see the changelog)")

    return property(fail, fail)


def gone_method(name: str, now: str) -> Callable[..., Any]:
    """A method that says what replaced it."""

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise AttributeError(f"{name}() is now {now} (see the changelog)")

    return fail
