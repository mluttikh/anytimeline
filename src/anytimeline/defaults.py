"""Defaults per method: arguments a team sets once (``set_defaults``), which every
``Timeline(...)`` and layer method then takes when the call leaves them out.

The call wins, then the defaults set here, then the method's own defaults. Defaults are
checked when set: an argument the method does not take, or a word its options do not have,
raises then, and nothing of that call is kept. Not defaults: a layer's table (``data``) and
its ``name``.

The plot remembers each layer's call (``remembered``), so ``plot.update(name, ...)`` can
call the method again with its last arguments and the changes.
"""

from __future__ import annotations

import functools
import inspect
import types
import typing
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from typing import Any, Literal, TypeVar

METHODS = ("plot", "events", "intervals", "states", "values", "spans")
"""What takes defaults: ``plot`` is the ``Timeline`` constructor; the others its methods."""

NOT_DEFAULTS = frozenset({"self", "data", "name"})

_DEFAULTS: dict[str, dict[str, Any]] = {}

F = TypeVar("F", bound=Callable[..., Any])


def set_defaults(
    *,
    plot: Mapping[str, Any] | None = None,
    events: Mapping[str, Any] | None = None,
    intervals: Mapping[str, Any] | None = None,
    states: Mapping[str, Any] | None = None,
    values: Mapping[str, Any] | None = None,
    spans: Mapping[str, Any] | None = None,
) -> None:
    """Set defaults for the plots and layers made from now on: dicts of a method's
    arguments. ``plot`` is for ``Timeline(...)``; ``events``, ``intervals``, ``states``,
    ``values`` and ``spans`` for those methods.

    ```python
    import anytimeline

    anytimeline.set_defaults(
        plot={"font_size": 14, "height": 420},
        events={"lane": "service", "tooltip": ["request", "status"]},
    )
    ```

    A call's own arguments win over these. Setting defaults for a method again adds to
    those set before (a name set again takes the new value);
    [`reset_defaults`][anytimeline.reset_defaults] removes them.

    Raises:
        TypeError: An argument the method does not take, or ``data`` or ``name``.
        ValueError: A word that is not one of the argument's options
            (``events={"overlap": "spread"}``). Nothing of the call is kept then.
    """
    given = {
        "plot": plot,
        "events": events,
        "intervals": intervals,
        "states": states,
        "values": values,
        "spans": spans,
    }
    checked = {kind: _checked(kind, args) for kind, args in given.items() if args is not None}
    for kind, args in checked.items():
        _DEFAULTS[kind] = {**_DEFAULTS.get(kind, {}), **args}


def get_defaults() -> dict[str, dict[str, Any]]:
    """The defaults set, per method: ``{"plot": {...}, "events": {...}}`` (a copy). Paste it
    into ``set_defaults(**...)`` in a module your team shares."""
    return {kind: dict(args) for kind, args in _DEFAULTS.items() if args}


def reset_defaults(*methods: str) -> None:
    """Remove the defaults set: of the methods named (``"plot"``, ``"events"``, ...), or
    all."""
    unknown = [m for m in methods if m not in METHODS]
    if unknown:
        raise ValueError(f"no method {unknown[0]!r} takes defaults; they are {list(METHODS)}")
    for kind in methods or METHODS:
        _DEFAULTS.pop(kind, None)


@contextmanager
def defaults(**methods: Mapping[str, Any]) -> Generator[None]:
    """Defaults inside a ``with`` block only, as [`set_defaults`][anytimeline.set_defaults]
    takes them; afterwards (also after an error) the defaults are as before.

    ```python
    with anytimeline.defaults(plot={"font_size": 18}):
        plot = Timeline().events(log, lane="service")  # larger text, for slides
    ```
    """
    before = {kind: dict(args) for kind, args in _DEFAULTS.items()}
    try:
        set_defaults(**methods)
        yield
    finally:
        _DEFAULTS.clear()
        _DEFAULTS.update(before)


def takes_defaults(kind: str) -> Callable[[F], F]:
    """Decorate ``Timeline.__init__`` or a layer method: the arguments a call leaves out are
    filled from the defaults set for ``kind``. The signature stays the method's own, with
    its own defaults, for editors and ``help()``."""

    def wrap(fn: F) -> F:
        signature = inspect.signature(fn)
        _FUNCTIONS[kind] = fn

        @functools.wraps(fn)
        def call(*args: Any, **kwargs: Any) -> Any:
            set_here = _DEFAULTS.get(kind)
            if set_here:
                bound = signature.bind_partial(*args, **kwargs).arguments
                kwargs.update({k: v for k, v in set_here.items() if k not in bound})
            return fn(*args, **kwargs)

        return typing.cast(F, call)

    return wrap


def remembered[G: Callable[..., Any]](fn: G) -> G:
    """Decorate a layer method: the plot remembers the call's arguments (without the table),
    by the layer's name, for ``plot.update`` and ``plot.arguments``. A method that calls
    another (``spans`` calls ``intervals``) is remembered as itself."""
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def call(self: Any, *args: Any, **kwargs: Any) -> Any:
        depth = getattr(self, "_calling", 0)
        self._calling = depth + 1
        try:
            result = fn(self, *args, **kwargs)
        finally:
            self._calling = depth
        if depth == 0:
            given = dict(signature.bind(self, *args, **kwargs).arguments)
            given.pop("self", None)
            given.pop("data", None)
            name = given.pop("name", signature.parameters["name"].default)
            self._calls[str(name)] = (method, given)
        return result

    method = getattr(fn, "__name__", "")
    return typing.cast(G, call)


def changed(fn_name: str, given: Mapping[str, Any]) -> dict[str, Any]:
    """The arguments of a remembered call that differ from the method's own defaults."""
    params = inspect.signature(_FUNCTIONS[fn_name]).parameters
    out: dict[str, Any] = {}
    for key, value in given.items():
        default = params[key].default if key in params else inspect.Parameter.empty
        if not _same(value, default):
            out[key] = value
    return out


_FUNCTIONS: dict[str, Callable[..., Any]] = {}
"""The functions that take defaults, by kind (filled as they are decorated)."""


def _same(a: Any, b: Any) -> bool:
    if a is b:
        return True
    try:
        return bool(type(a) is type(b) and a == b)
    except Exception:  # arrays and tables compare element-wise
        return False


def _checked(kind: str, args: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(args, Mapping):
        raise TypeError(f"defaults for {kind} must be a dict of arguments, got {args!r}")
    fn = _function(kind)
    params = inspect.signature(fn).parameters
    options = _options(fn)
    out: dict[str, Any] = {}
    for key, value in args.items():
        if key in NOT_DEFAULTS:
            raise TypeError(f"{key!r} cannot have a default: give it with each call")
        if key not in params:
            takes = [p for p in params if p not in NOT_DEFAULTS]
            raise TypeError(f"{_label(kind)} takes no argument {key!r}; it takes {takes}")
        words = options.get(key)
        if words is not None and isinstance(value, str) and value not in words:
            raise ValueError(f"{_label(kind)}: {key} must be one of {words}, got {value!r}")
        out[key] = value
    return out


def _function(kind: str) -> Callable[..., Any]:
    if kind not in _FUNCTIONS:
        import anytimeline.plot  # noqa: F401  (decorating its methods fills _FUNCTIONS)
    return _FUNCTIONS[kind]


def _label(kind: str) -> str:
    return "Timeline()" if kind == "plot" else f"Timeline.{kind}()"


def _options(fn: Callable[..., Any]) -> dict[str, list[str]]:
    """Per argument typed as a choice of words (a Literal, maybe or None), the words."""
    try:
        hints = typing.get_type_hints(inspect.unwrap(fn))
    except Exception:  # an annotation that cannot be resolved here: checked when called
        return {}
    out: dict[str, list[str]] = {}
    for key, hint in hints.items():
        words = _words(hint)
        if words:
            out[key] = words
    return out


def _words(hint: Any) -> list[str] | None:
    if typing.get_origin(hint) is Literal:
        args = typing.get_args(hint)
        return list(args) if all(isinstance(a, str) for a in args) else None
    if typing.get_origin(hint) in (typing.Union, types.UnionType):
        parts = [a for a in typing.get_args(hint) if a is not type(None)]
        if len(parts) == 1:
            return _words(parts[0])
    return None
