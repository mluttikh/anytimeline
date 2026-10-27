"""The plot's settings: plain Python attributes, checked when set, and sent to the widget
that shows the plot once it has one (``plot.widget``).

```python
class Timeline:
    tool: Tool = setting("pan", one_of(TOOLS))

    @validates("tool")
    def _valid_tool(self, value, name): ...  # more checks; returns the value to keep

    @observes("tool")
    def _tool_changed(self, change): ...  # after a change: change["old"], change["new"]
```

A setting the browser changes (the tool, the selection, the text size) comes back through
the widget and is checked and observed as if set in Python. A wrong kind of value is a
``TypeError``, a wrong value of the right kind a ``ValueError``.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

Check = Callable[[Any, str], Any]
"""A setting's check of a value: the value to keep, or a TypeError or ValueError."""


class Setting:
    """A setting of the plot, kept in ``plot._settings``; see [`setting`][]."""

    def __init__(self, default: Any, check: Check | None, *, sync: bool) -> None:
        self.default = default
        self.check = check
        self.sync = sync
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, obj: Any, owner: type | None = None) -> Any:
        if obj is None:
            return self
        return obj._settings[self.name]

    def __set__(self, obj: Any, value: Any) -> None:
        obj._set(self.name, value)


def setting(default: Any, check: Check | None = None, *, sync: bool = True) -> Any:
    """A setting of the plot with its default and its check (``sync``: the widget shows it).
    Typed as the value, as ``dataclasses.field``: annotate the attribute with its type."""
    return Setting(default, check, sync=sync)


def validates(*names: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a method ``(self, value, name) -> value`` that checks these settings further."""

    def mark(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn._validates = names  # ty: ignore[unresolved-attribute]
        return fn

    return mark


def observes(*names: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a method ``(self, change)`` called after these settings change."""

    def mark(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn._observes = names  # ty: ignore[unresolved-attribute]
        return fn

    return mark


class Hooks:
    """A class's settings, and its validators and observers by setting."""

    def __init__(self, cls: type) -> None:
        self.settings: dict[str, Setting] = {}
        self.validators: dict[str, list[Callable[..., Any]]] = {}
        self.observers: dict[str, list[Callable[..., Any]]] = {}
        seen: set[str] = set()
        for klass in cls.__mro__:
            for key, value in vars(klass).items():
                if key in seen:
                    continue  # overridden in a subclass
                seen.add(key)
                if isinstance(value, Setting):
                    self.settings[key] = value
                for name in getattr(value, "_validates", ()):
                    self.validators.setdefault(name, []).append(value)
                for name in getattr(value, "_observes", ()):
                    self.observers.setdefault(name, []).append(value)

    def defaults(self) -> dict[str, Any]:
        """Each setting's default, a copy of its own."""
        return {name: copy.deepcopy(s.default) for name, s in self.settings.items()}

    @property
    def synced(self) -> list[str]:
        """The settings the widget shows."""
        return [name for name, s in self.settings.items() if s.sync]


_HOOKS: dict[type, Hooks] = {}


def hooks(cls: type) -> Hooks:
    """A class's settings, validators and observers (found once per class)."""
    found = _HOOKS.get(cls)
    if found is None:
        found = _HOOKS[cls] = Hooks(cls)
    return found


def same(a: Any, b: Any) -> bool:
    """Whether a setting kept its value (as traitlets compares: equal, else the same object)."""
    try:
        return bool(a == b)
    except Exception:  # e.g. arrays, whose == is per element
        return a is b


# ---------------------------------------------------------------- checks of a value's kind


def one_of(options: Sequence[Any]) -> Check:
    """One of the options (``None`` among them: also None)."""

    def check(value: Any, name: str) -> Any:
        if not any(value is o or (isinstance(value, str) and value == o) for o in options):
            listed = ", ".join(repr(o) for o in options)
            raise ValueError(f"{name} must be one of {listed}, got {value!r}")
        return value

    return check


def flag(value: Any, name: str) -> bool:
    """True or False."""
    if not isinstance(value, bool | np.bool_):
        raise TypeError(f"{name} must be True or False, got {value!r}")
    return bool(value)


def whole(value: Any, name: str) -> int:
    """A whole number."""
    if isinstance(value, bool) or not isinstance(value, int | np.integer):
        raise TypeError(f"{name} must be a whole number, got {value!r}")
    return int(value)


def number(value: Any, name: str) -> float:
    """A number (not NaN)."""
    if isinstance(value, bool) or not isinstance(value, int | float | np.integer | np.floating):
        raise TypeError(f"{name} must be a number, got {value!r}")
    if math.isnan(value):
        raise ValueError(f"{name} must be a number, got {value!r}")
    return float(value)


def between(low: float, high: float, kind: Check = number, unit: str = "") -> Check:
    """A number (or whole number, ``kind=whole``) from ``low`` to ``high``."""

    def check(value: Any, name: str) -> Any:
        value = kind(value, name)
        if not low <= value <= high:
            raise ValueError(f"{name} must be {low:g} to {high:g}{unit}, got {value!r}")
        return value

    return check


def at_least(low: float, kind: Check = whole, unit: str = "") -> Check:
    """A number (by default a whole one) of at least ``low``."""

    def check(value: Any, name: str) -> Any:
        value = kind(value, name)
        if value < low:
            raise ValueError(f"{name} must be at least {low:g}{unit}, got {value!r}")
        return value

    return check


def text(value: Any, name: str) -> str:
    """Text."""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text, got {value!r}")
    return value


def text_or_none(value: Any, name: str) -> str | None:
    """Text, or None."""
    return None if value is None else text(value, name)


def mapping(value: Any, name: str) -> dict[Any, Any]:
    """A dict (a copy of it)."""
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a dict, got {type(value).__name__}")
    return dict(value)


def values_or_none(value: Any, name: str) -> list[Any] | None:
    """A list of values (lane names, groups), or None."""
    if value is None:
        return None
    if isinstance(value, str | bytes) or not isinstance(value, Sequence | np.ndarray):
        raise TypeError(f"{name} must be a list, got {value!r}")
    return list(value)
