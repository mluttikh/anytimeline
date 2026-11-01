"""A measure's text: its fields filled in (``fields.ts`` is the twin, tested against the same
cases). ``{time}`` is the time between, ``{events}`` the events between in the order,
``{change}`` the change in value between two samples, ``{rate}`` that change per unit of
time, ``{a}`` and ``{b}`` the ends' times. A field takes a format after a colon:
``{time:ms}`` a unit, ``{time:.2}`` the digits, ``{time:ms.4}`` both; ``{change:+.2f}`` (and
events and rate) a sign, ``,`` for thousands, digits, and ``f``, ``e``, ``%`` or ``g`` as in
Python. ``{a.col}`` and ``{b.col}``, a column of an end's row, are filled in by the plot
(``notes.measure``) with Python's own formats."""

from __future__ import annotations

import datetime as dt
import math
import re
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np

from anytimeline import axis as ax

FIELD = re.compile(r"\{(time|events|change|rate|a|b)(?::([^{}]*))?\}")
COLUMN = re.compile(r"\{([ab])\.([^{}:]+)(:[^{}]*)?\}")
TIME_SPEC = re.compile(r"^(ns|us|µs|ms|s|min|h|d)?(?:\.(\d{1,2}))?$")
NUMBER_SPEC = re.compile(r"^([+ -]?)(,?)(?:\.(\d{1,2}))?([fe%g]?)$")
UNITS = {
    "ns": (1, "ns"), "us": (10**3, "µs"), "µs": (10**3, "µs"), "ms": (10**6, "ms"),
    "s": (10**9, "s"), "min": (60 * 10**9, "min"), "h": (3600 * 10**9, "h"),
    "d": (86400 * 10**9, "d"),
}  # fmt: skip


def check(text: str) -> None:
    """Raise when a field's format is not one it takes (``{time:xs}``, ``{change:q}``)."""
    for m in FIELD.finditer(text):
        name, spec = m.group(1), m.group(2)
        if not spec:
            continue
        if name == "time" and not TIME_SPEC.match(spec):
            raise ValueError(
                f"{m.group(0)}: a time's format is a unit (ns, us, ms, s, min, h, d) and/or "
                "digits (.3), such as {time:ms} or {time:s.2}"
            )
        if name in ("a", "b"):
            raise ValueError(f"{m.group(0)}: an end's time takes no format")
        if name in ("events", "change", "rate") and not NUMBER_SPEC.match(spec):
            raise ValueError(
                f"{m.group(0)}: a number's format is a sign, ',', digits and f, e, % or g, "
                "such as {change:+.2f}"
            )


DURATION = re.compile(r"^\s*([0-9]*\.?[0-9]+(?:e[+-]?\d+)?)\s*(ns|us|µs|ms|s|min|h|d)\s*$")


def check_duration(name: str, value: Any) -> None:
    """Raise when ``value`` is not a duration a measure takes (``limit=``, ``min=``,
    ``max=``): text such as ``"200ms"`` or ``"1.5 h"``, a timedelta, or a number (on a plot of
    numbers, in its units; on a plot of times, nanoseconds is not meant, so not taken)."""
    if value is None:
        return
    if isinstance(value, str):
        if not DURATION.match(value):
            raise ValueError(
                f"{name} is a duration such as '200ms', '1.5 h' (ns, us, ms, s, min, h, d), "
                f"got {value!r}"
            )
        return
    if isinstance(value, bool) or not isinstance(
        value, int | float | dt.timedelta | np.timedelta64
    ):
        raise TypeError(f"{name} is a duration ('200ms', a timedelta) or a number, got {value!r}")
    if isinstance(value, int | float) and (not math.isfinite(value) or value < 0):
        raise ValueError(f"{name} is a duration of 0 or more, got {value!r}")


def duration_ns(value: Any) -> float | None:
    """A duration in nanoseconds: text (``"200ms"``) or a timedelta; None: a plain number."""
    if isinstance(value, str):
        m = DURATION.match(value)
        if not m:
            raise ValueError(f"not a duration: {value!r}")
        return float(m.group(1)) * UNITS[m.group(2)][0]
    if isinstance(value, np.timedelta64):
        return float(value.astype("timedelta64[ns]").astype(np.int64))
    if isinstance(value, dt.timedelta):
        return (value.days * 86_400 + value.seconds) * 1e9 + value.microseconds * 1e3
    return None


def _group(whole: str) -> str:
    return re.sub(r"\B(?=(\d{3})+(?!\d))", ",", whole)


def format_number(v: float, spec: str) -> str:
    """A number with a format as Python's (``formatNumber``): the sign ``−``."""
    m = NUMBER_SPEC.match(spec)
    if not m or not math.isfinite(v):
        return ax.fmt_number(v)
    sign, comma, digits, kind = m.groups()
    p = None if digits is None else int(digits)
    a = abs(v)
    if kind in ("f", "%"):
        body = ax.to_fixed(a * 100 if kind == "%" else a, 6 if p is None else p)
    elif kind == "e":
        body = re.sub(r"e([+-])(\d)$", r"e\g<1>0\2", ax.to_exponential(a, 6 if p is None else p))
    else:
        body = ax.fmt_number(a, 6 if p is None else p).replace(" ", "," if comma else " ")
    if comma and kind in ("f", "%"):
        whole, _, frac = body.partition(".")
        body = _group(whole) + (f".{frac}" if frac else "")
    if kind == "%":
        body += "%"
    negative = v < 0 and float(re.sub(r"[,% ]", "", body)) != 0
    return ("−" if negative else "+" if sign == "+" else " " if sign == " " else "") + body


def format_time(axis: ax.TimeAxis, dx: float, spec: str) -> str:
    """A time between ends (ticks, ≥ 0) with a format (``formatTime``)."""
    m = TIME_SPEC.match(spec)
    if not spec or not m:
        return axis.format_measure(dx)
    unit, digits = m.groups()
    sig = 3 if digits is None else max(1, int(digits))
    if axis.kind == "order":
        return f"{ax.fmt_number(dx, sig)} events"
    if axis.kind == "number":
        return ax.fmt_number(dx, sig)
    ns = dx * axis.per_ns
    if not unit:
        return ax.format_duration(ns, 0, sig=sig)
    per, name = UNITS[unit]
    return f"{ax.js_str(float(ax.to_precision(ns / per, sig)))} {name}"


def _events(events: int | None, spec: str | None) -> str:
    if events is None:
        return ""
    if spec:
        return format_number(events, spec)
    return f"{ax.fmt_number(events)} event{'s' * (events != 1)}"


def change_text(change: float, spec: str = "") -> str:
    """A change in value, signed, to three digits; with a format, as it says."""
    if spec:
        return format_number(change, spec)
    sign = "+" if change > 0 else "−" if change < 0 else ""
    return sign + ax.fmt_number(abs(change), 3)


def fill(axis: ax.TimeAxis | None, text: str | None, n: Mapping[str, Any], order: bool) -> str:
    """A measure's text with its fields filled in (``fillMeasure``): ``n`` has ``span``,
    ``a`` and ``b`` (ticks), ``events`` and ``change``."""
    span = abs(n["span"])
    time = axis.format_measure(span) if axis else ax.js_str(span)
    change = n.get("change")
    if text is None:
        parts = [
            time,
            _events(n.get("events"), None) if order else "",
            f"Δ {change_text(change)}" if change is not None else "",
        ]
        return " · ".join(p for p in parts if p)

    def field(m: re.Match[str]) -> str:
        name, spec = m.group(1), m.group(2) or ""
        if name == "time":
            return format_time(axis, span, spec) if axis else ax.js_str(span)
        if name == "events":
            return _events(n.get("events"), m.group(2))
        if name == "change":
            return "" if change is None else change_text(change, spec)
        if name == "rate":
            if change is None or axis is None:
                return ""
            rate = axis.rate(change, n["span"])
            if rate is None:
                return ""
            if spec:
                return f"{format_number(rate[0], spec)} per {rate[1]}"
            return axis.format_rate(change, n["span"]) or ""
        x = n[name]
        return axis.format_full(x) if axis else ax.js_str(x)

    return FIELD.sub(field, text)


def fill_columns(text: str, row_text: Callable[[str, str], str]) -> str:
    """``{a.col}`` and ``{b.col}`` filled in: ``row_text(end, template)`` formats a template
    of the end's columns (``"{col:%H:%M}"``) with its row."""
    return COLUMN.sub(
        lambda m: row_text(m.group(1), "{" + m.group(2) + (m.group(3) or "") + "}"), text
    )
