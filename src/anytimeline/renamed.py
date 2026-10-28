"""Attributes that were removed in 0.5.0: an old name raises an error that gives the new one,
instead of Python's "has no attribute". They go in a later release."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


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
