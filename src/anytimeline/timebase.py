"""Time values: datetimes, durations and plain numbers, as ticks of one unit per plot.

Every layer's time column becomes a ``Times``: datetimes and durations as int64 counts of
the finest unit (ns, us, ms or s) that holds them without overflow (nanoseconds reach only
from 1677 to 2262), plain numbers as float64. The plot then puts all its layers on one
``TimeBase``: a unit (the coarsest of s, ms, us, ns that keeps every value exact), an origin
(the earliest value) and float64 ticks relative to that origin. Ticks are exact while they
stay below 2**53: 104 days in nanoseconds, 285 years in microseconds, 285,000 years in
milliseconds.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

UNITS: dict[str, int] = {"s": 1_000_000_000, "ms": 1_000_000, "us": 1_000, "ns": 1}
"""Nanoseconds per tick of each unit, coarsest first."""

INPUT_UNITS: dict[str, int] = {
    "d": 86_400_000_000_000, "h": 3_600_000_000_000, "min": 60_000_000_000, **UNITS,
}  # fmt: skip
"""What one unit of a numeric time or duration column can be."""

TimeKind = Literal["datetime", "duration", "number"]

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
_FINE_TO_COARSE = ("ns", "us", "ms", "s")


@dataclass(frozen=True)
class Times:
    """The time column of one layer.

    ``raw`` holds datetimes (since the Unix epoch, UTC) and durations as int64 counts of
    ``per`` nanoseconds; ``values`` holds plain numbers. ``valid`` is False for missing values.
    """

    kind: TimeKind
    raw: np.ndarray | None
    values: np.ndarray | None
    valid: np.ndarray
    timezone: str | None = None
    per: int = 1

    def take(self, rows: np.ndarray) -> Times:
        return Times(
            self.kind,
            self.raw[rows] if self.raw is not None else None,
            self.values[rows] if self.values is not None else None,
            self.valid[rows],
            self.timezone,
            self.per,
        )


def _int_ticks(values: np.ndarray, kind: str) -> tuple[np.ndarray, np.ndarray, int]:
    """datetime64 / timedelta64 values as int64 ticks of the finest unit that holds them."""
    unit = np.datetime_data(values.dtype)[0]
    start = _FINE_TO_COARSE.index(unit) if unit in _FINE_TO_COARSE else 3
    for name in _FINE_TO_COARSE[start:]:
        try:
            converted = values.astype(f"{kind}[{name}]")
        except OverflowError:
            continue
        return converted.view("i8").copy(), ~np.isnat(values), UNITS[name]
    raise OverflowError("times out of range")


def times(values: np.ndarray, *, timezone: str | None = None, unit: str | None = None) -> Times:
    """Read a time column.

    Args:
        values: The column: datetime64, timedelta64, numbers, or Python/pandas datetimes.
        timezone: The column's time zone (its values are then UTC instants).
        unit: For numbers only: what one unit of them is (``"d"``, ``"h"``, ``"min"``,
            ``"s"``, ``"ms"``, ``"us"``, ``"ns"``). They become durations; without it they
            stay plain numbers.
    """
    kind = values.dtype.kind
    if kind == "M":
        raw, valid, per = _int_ticks(values, "M8")
        return Times("datetime", raw, None, valid, timezone, per)
    if kind == "m":
        raw, valid, per = _int_ticks(values, "m8")
        return Times("duration", raw, None, valid, None, per)
    if kind in "iuf":
        floats = values.astype(np.float64)
        valid = np.isfinite(floats)
        if unit is None:
            return Times("number", None, floats, valid, None)
        if unit not in INPUT_UNITS:
            raise ValueError(f"unknown unit {unit!r}; use one of {list(INPUT_UNITS)}")
        raw = np.zeros(floats.shape, dtype=np.int64)
        raw[valid] = np.round(floats[valid] * INPUT_UNITS[unit]).astype(np.int64)
        return Times("duration", raw, None, valid, None, 1)
    if kind == "b":
        raise TypeError("a time column cannot be boolean")
    if kind == "O":
        return _objects(values, timezone)
    raise TypeError(
        f"a time column must hold datetimes, durations or numbers, got {values.dtype}; parse "
        "text first, e.g. pl.col('t').str.to_datetime()"
    )


def _objects(values: np.ndarray, timezone: str | None) -> Times:
    """Python datetimes, pandas Timestamps or timedeltas in an object array (as ns)."""
    present = [v for v in values if v is not None and v == v]
    n = len(values)
    if not present:
        return Times("number", None, np.zeros(n), np.zeros(n, bool))
    first = present[0]
    raw = np.zeros(n, dtype=np.int64)
    valid = np.zeros(n, dtype=bool)
    if isinstance(first, dt.datetime):
        tz = timezone or (str(first.tzinfo) if first.tzinfo is not None else None)
        for i, v in enumerate(values):
            if v is not None and v == v:
                raw[i], valid[i] = _datetime_ns(v), True
        return Times("datetime", raw, None, valid, tz)
    if isinstance(first, dt.timedelta):
        for i, v in enumerate(values):
            if v is not None and v == v:
                raw[i], valid[i] = int(getattr(v, "value", 0)) or _timedelta_ns(v), True
        return Times("duration", raw, None, valid, None)
    raise TypeError(
        f"a time column must hold datetimes, durations or numbers, got {type(first).__name__}"
    )


def _datetime_ns(value: dt.datetime) -> int:
    """Nanoseconds since the epoch; a naive datetime is read as UTC wall time."""
    stamp: Any = getattr(value, "value", None)
    if stamp is not None and value.tzinfo is not None:  # pandas Timestamp, aware
        return int(stamp)
    nanos = int(getattr(value, "nanosecond", 0))
    aware = value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
    return _timedelta_ns(aware - _EPOCH) + nanos


def _timedelta_ns(value: dt.timedelta) -> int:
    return (value.days * 86_400 + value.seconds) * 1_000_000_000 + value.microseconds * 1_000


@dataclass(frozen=True)
class TimeBase:
    """The time axis shared by a plot's layers."""

    kind: TimeKind
    unit: str  # "" for plain numbers
    origin_ns: int  # datetimes: ns since the epoch; durations: ns; numbers: 0 (any size)
    origin: float  # numbers: the value at tick 0
    timezone: str

    def ticks(self, t: Times) -> np.ndarray:
        """Float64 ticks of ``t`` relative to the origin (0 where a value is missing)."""
        out = np.zeros(t.valid.shape, dtype=np.float64)
        if self.kind == "number":
            assert t.values is not None
            out[t.valid] = t.values[t.valid] - self.origin
            return out
        assert t.raw is not None
        per = UNITS[self.unit]
        # the origin in the column's unit, exactly: whole ticks plus a remainder in ns
        whole = self.origin_ns // t.per
        rest = self.origin_ns - whole * t.per
        rel = t.raw[t.valid] - whole  # int64, exact
        out[t.valid] = rel * (t.per / per) - rest / per
        return out

    def spec(self, extent: tuple[float, float]) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "unit": self.unit,
            "origin_ns": str(self.origin_ns),
            "origin": self.origin,
            "timezone": self.timezone,
            "extent": [extent[0], extent[1]],
        }

    def to_value(self, tick: float) -> Any:
        """A tick back as a value of the data's kind (numpy datetime64, timedelta64, float)."""
        if self.kind == "number":
            return self.origin + tick
        per = UNITS[self.unit]
        unit: Any = self.unit or "ns"
        whole = self.origin_ns // per + round(tick)
        if self.kind == "datetime":
            return np.datetime64(whole, unit)
        return np.timedelta64(whole, unit)

    def to_ticks(self, value: Any) -> float:
        """A value of the data's kind (datetime, ISO string, duration or number) as a tick."""
        if self.kind == "number":
            return float(value) - self.origin
        if isinstance(value, str):
            value = np.datetime64(value) if self.kind == "datetime" else float(value)
        if isinstance(value, int | float) and self.kind == "duration":
            return float(value)
        t = times(np.asarray([value]), timezone=self.timezone)
        if t.kind != self.kind or t.raw is None:
            raise TypeError(f"expected a {self.kind}, got {value!r}")
        return float((int(t.raw[0]) * t.per - self.origin_ns) / UNITS[self.unit])


def time_base(columns: Sequence[Times], *, timezone: str | None = None) -> TimeBase:
    """One time base for these columns: the same kind, the coarsest exact unit, and the
    earliest value as origin."""
    if not columns:
        return TimeBase("number", "", 0, 0.0, timezone or "UTC")
    kinds = {c.kind for c in columns}
    if len(kinds) > 1:
        raise TypeError(f"the layers' times must be of one kind, got {sorted(kinds)}")
    kind = columns[0].kind
    zone = timezone or next((c.timezone for c in columns if c.timezone), None) or "UTC"
    present = [c for c in columns if c.valid.any()]
    if kind == "number":
        lows = [float(c.values[c.valid].min()) for c in present if c.values is not None]
        return TimeBase("number", "", 0, min(lows) if lows else 0.0, zone)
    if not present:
        return TimeBase(kind, "ms", 0, 0.0, zone)
    # the coarsest unit that keeps every value exact: no finer than the columns' storage
    finest_per = min(c.per for c in present)
    chosen = "ns"
    for name, per in UNITS.items():
        if per < finest_per:
            continue
        if all(
            not np.any(c.raw[c.valid] % (per // c.per))
            for c in present
            if c.raw is not None and per >= c.per
        ):
            chosen = name
            break
    per = UNITS[chosen]
    origin_ns = min(int(c.raw[c.valid].min()) * c.per for c in present if c.raw is not None)
    origin_ns = origin_ns // per * per
    return TimeBase(kind, chosen, origin_ns, 0.0, zone)
