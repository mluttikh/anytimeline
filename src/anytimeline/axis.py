"""The time axis as the browser draws it (``js/src/core/time.ts``), for pictures drawn in
Python (``image``): ticks and labels from nanoseconds to centuries, in the plot's time zone,
and the numbers and durations of labels.

It is a port, kept line by line like the TypeScript, and the two are tested against the same
cases (``tests/fixtures/axis.json``, written by ``js/test/twins.test.ts``): a change to one
needs the same change to the other. Numbers are formatted as JavaScript formats them
(``Number.prototype.toPrecision``, ``toFixed``, ``String(number)``), not as Python does.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from zoneinfo import ZoneInfo

UNIT_NS = {"s": 10**9, "ms": 10**6, "us": 10**3, "ns": 1, "": 1}

SECOND = 10**9
MINUTE = 60 * SECOND
HOUR = 60 * MINUTE
DAY = 24 * HOUR

FIXED_STEPS = [
    1, 2, 5, 10, 20, 50, 100, 200, 500,
    10**3, 2 * 10**3, 5 * 10**3, 10**4, 2 * 10**4, 5 * 10**4, 10**5, 2 * 10**5, 5 * 10**5,
    10**6, 2 * 10**6, 5 * 10**6, 10**7, 2 * 10**7, 5 * 10**7, 10**8, 2 * 10**8, 5 * 10**8,
    SECOND, 2 * SECOND, 5 * SECOND, 10 * SECOND, 15 * SECOND, 30 * SECOND,
    MINUTE, 2 * MINUTE, 5 * MINUTE, 10 * MINUTE, 15 * MINUTE, 30 * MINUTE,
    HOUR, 2 * HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR,
]  # fmt: skip
"""Sub-day steps in ns (fixed length in local time)."""

CALENDAR_STEPS = [
    ("day", 1), ("day", 2), ("day", 7),
    ("month", 1), ("month", 3), ("month", 6),
    ("year", 1), ("year", 2), ("year", 5), ("year", 10), ("year", 20), ("year", 50),
    ("year", 100), ("year", 200), ("year", 500), ("year", 1000),
]  # fmt: skip
APPROX_NS = {"day": DAY, "month": 30.44 * DAY, "year": 365.25 * DAY}

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_LONG = [
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
]  # fmt: skip
WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

MIN_SPACING = {"short": 56, "medium": 72, "long": 96}
"""Minimum pixels between tick labels, by the kind of label."""


@dataclass(frozen=True)
class Tick:
    x: float
    """Position in ticks (the spec's unit, relative to its origin)."""
    label: str


@dataclass
class AxisTicks:
    minor: list[Tick] = field(default_factory=list)
    """The row of tick marks and labels."""
    context: list[Tick] = field(default_factory=list)
    """Context labels (the day of hour ticks, the year of month ticks), at their boundaries."""
    pinned: str = ""
    """The context label of the unit that holds the left edge (shown pinned there)."""


# ---------------------------------------------------------------------- calendar


def _days_from_civil(y: int, m: int, d: int) -> int:
    """Days since 1970-01-01 of a proleptic Gregorian date (any year)."""
    y -= m <= 2
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def _civil_from_days(z: int) -> tuple[int, int, int]:
    z += 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return yoe + era * 400 + (m <= 2), m, d


def _utc_of(y: int, mo: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> int:
    """The instant (ms) of a UTC wall time; months and days past their end carry over."""
    y += (mo - 1) // 12
    mo = (mo - 1) % 12 + 1
    days = _days_from_civil(y, mo, 1) + d - 1
    return ((days * 24 + h) * 60 + mi) * 60_000 + s * 1000


@cache
def _zone(tz: str) -> ZoneInfo | None:
    if tz == "UTC":
        return None
    try:
        return ZoneInfo(tz)
    except (ValueError, KeyError, OSError):  # as the browser: an unknown zone is UTC
        return None


_SECONDS_MIN = -62135596800  # 0001-01-01
_SECONDS_MAX = 253402300799  # 9999-12-31 23:59:59


def _offset_s(ms: float, tz: str) -> int:
    zone = _zone(tz)
    if zone is None:
        return 0
    seconds = min(_SECONDS_MAX - 86400, max(_SECONDS_MIN + 86400, math.floor(ms / 1000)))
    offset = datetime.fromtimestamp(seconds, UTC).astimezone(zone).utcoffset()
    return int(offset.total_seconds()) if offset is not None else 0


def parts_at(ms: float, tz: str) -> tuple[int, int, int, int, int, int]:
    """Local calendar parts (year, month, day, hour, minute, second) of a UTC instant in
    milliseconds; years before 1 as 0, -1, ... (1 BC, 2 BC)."""
    seconds = math.floor(ms / 1000) + _offset_s(ms, tz)
    days, rest = divmod(seconds, 86400)
    y, mo, d = _civil_from_days(days)
    return y, mo, d, rest // 3600, rest // 60 % 60, rest % 60


def offset_ms(ms: float, tz: str) -> int:
    """The zone's offset from UTC at an instant, in milliseconds."""
    return _offset_s(ms, tz) * 1000


def local_to_utc(y: int, mo: int, d: int, h: int, mi: int, s: int, tz: str) -> int:
    """The UTC instant (ms) of a local wall time; at a gap or overlap, the later reading."""
    wall = _utc_of(y, mo, d, h, mi, s)
    guess = wall - offset_ms(wall, tz)
    return wall - offset_ms(guess, tz)


def _weekday(days: int) -> int:
    return (days + 4) % 7  # 1970-01-01 was a Thursday


# ---------------------------------------------------------------------- axis


class TimeAxis:
    """The axis of a scene's ``time`` spec (``kind``, ``unit``, ``origin_ns``, ``origin``,
    ``timezone``)."""

    def __init__(self, spec: dict) -> None:
        self.kind: str = spec["kind"]
        self.per_ns: int = UNIT_NS.get(spec.get("unit") or "", 1)
        self.origin_ns = int(spec.get("origin_ns") or "0")
        self.origin = float(spec.get("origin") or 0)
        self.tz: str = spec.get("timezone") or "UTC"

    def ns_of(self, x: float) -> int:
        """Absolute ns of a tick (datetime: since the epoch; duration: since zero)."""
        whole = math.floor(x)
        frac = x - whole
        return self.origin_ns + whole * self.per_ns + js_round(frac * self.per_ns)

    def tick_of(self, ns: int) -> float:
        return float(ns - self.origin_ns) / self.per_ns

    def ticks(self, left: float, right: float, width_px: float) -> AxisTicks:
        if not right > left or width_px <= 0:
            return AxisTicks()
        if self.kind == "datetime":
            return self._calendar_ticks(left, right, width_px)
        if self.kind == "duration":
            return self._duration_ticks(left, right, width_px)
        if self.kind == "order":
            return self._number_ticks(left, right, width_px, lambda v: f"#{fmt_number(v + 1)}", 0)
        return self._number_ticks(left, right, width_px, fmt_number, self.origin)

    # -- plain numbers and ranks

    def _number_ticks(self, left, right, width_px, label, offset) -> AxisTicks:  # noqa: ANN001
        step = nice_step((right - left) * (MIN_SPACING["short"] / width_px), self.kind == "order")
        minor: list[Tick] = []
        lo = math.ceil((left + offset) / step)
        hi = math.floor((right + offset) / step)
        k = lo
        while k <= hi and len(minor) < 500:
            v = k * step
            minor.append(Tick(v - offset, label(_round_to(v, step))))
            k += 1
        return AxisTicks(minor)

    # -- durations

    def _duration_ticks(self, left: float, right: float, width_px: float) -> AxisTicks:
        px_per_ns = width_px / ((right - left) * self.per_ns)
        steps = [
            *FIXED_STEPS,
            DAY,
            2 * DAY,
            5 * DAY,
            10 * DAY,
            30 * DAY,
            100 * DAY,
            365 * DAY,
            3650 * DAY,
        ]
        step: float = next((s for s in steps if s * px_per_ns >= MIN_SPACING["medium"]), 0)
        if not step:
            raw = (right - left) * self.per_ns * (MIN_SPACING["medium"] / width_px)
            step = nice_step(raw, False)
        step_b = js_round(step)
        lo = self.ns_of(left)
        hi = self.ns_of(right)
        t = lo // step_b * step_b
        if t < lo:
            t += step_b
        minor: list[Tick] = []
        while t <= hi and len(minor) < 500:
            minor.append(Tick(self.tick_of(t), format_duration(float(t), step)))
            t += step_b
        return AxisTicks(minor)

    # -- datetimes

    def _calendar_ticks(self, left: float, right: float, width_px: float) -> AxisTicks:
        ns_per_px = ((right - left) * self.per_ns) / width_px
        lo = self.ns_of(left)
        hi = self.ns_of(right)
        fixed = next((s for s in FIXED_STEPS if s / ns_per_px >= _spacing_for(s)), None)
        if fixed is not None:
            minor = [
                Tick(self.tick_of(t), self._fixed_label(t, fixed))
                for t in self._fixed_ticks(lo, hi, fixed)
            ]
            if fixed < SECOND:
                boundaries = self._fixed_ticks(lo, hi, SECOND)
                context_label = self._second_context
            else:
                boundaries = self._calendar_steps(lo, hi, ("day", 1))
                context_label = self._day_context
            context = [Tick(self.tick_of(t), context_label(t)) for t in boundaries]
            return AxisTicks(minor, context, context_label(lo))
        cal = next(
            (
                c
                for c in CALENDAR_STEPS
                if APPROX_NS[c[0]] * c[1] / ns_per_px >= MIN_SPACING["short"]
            ),
            CALENDAR_STEPS[-1],
        )
        minor = [
            Tick(self.tick_of(t), self._calendar_label(t, cal))
            for t in self._calendar_steps(lo, hi, cal)
        ]
        context: list[Tick] = []
        pinned = ""
        if cal[0] == "day":
            steps = self._calendar_steps(lo, hi, ("month", 1))
            context = [Tick(self.tick_of(t), self._month_context(t)) for t in steps]
            pinned = self._month_context(lo)
        elif cal[0] == "month":
            steps = self._calendar_steps(lo, hi, ("year", 1))
            context = [Tick(self.tick_of(t), str(self._parts(t)[0])) for t in steps]
            pinned = str(self._parts(lo)[0])
        return AxisTicks(minor, context, pinned)

    def _parts(self, ns: int) -> tuple[int, int, int, int, int, int]:
        return parts_at(ns // 1_000_000, self.tz)

    def _fixed_ticks(self, lo: int, hi: int, step: int) -> list[int]:
        """Fixed steps aligned in local time, as absolute ns."""
        offset = offset_ms(lo // 1_000_000, self.tz) * 1_000_000
        local = (lo + offset) // step * step
        out: list[int] = []
        for _ in range(1000):
            t = local - offset
            if step >= HOUR:
                # keep hour ticks on the local clock across a daylight-saving change
                t = local - offset_ms(t // 1_000_000, self.tz) * 1_000_000
            if t > hi:
                break
            if t >= lo:
                out.append(t)
            local += step
        return out

    def _calendar_steps(self, lo: int, hi: int, step: tuple[str, int]) -> list[int]:
        """Calendar steps (local midnights, month and year starts) in [lo, hi], as absolute ns."""
        kind, n = step
        y, mo, d, *_ = self._parts(lo)
        if kind == "year":
            y, mo, d = y // n * n, 1, 1
        elif kind == "month":
            mo, d = (mo - 1) // n * n + 1, 1
        elif n == 7:
            # weeks start on Monday
            d -= (_weekday(_utc_of(y, mo, d) // 86_400_000) + 6) % 7
        elif n > 1:
            day_number = _utc_of(y, mo, d) // 86_400_000
            d -= day_number % n
        out: list[int] = []
        for _ in range(2000):
            wy, wmo, wd = _civil_from_days(_utc_of(y, mo, d) // 86_400_000)
            t = local_to_utc(wy, wmo, wd, 0, 0, 0, self.tz) * 1_000_000
            if t > hi:
                break
            if t >= lo:
                out.append(t)
            if kind == "year":
                y += n
            elif kind == "month":
                mo += n
            else:
                d += n
        return out

    def _fixed_label(self, t: int, step: int) -> str:
        if step < SECOND:
            return _fraction_label(t, step)
        _, _, _, h, mi, s = self._parts(t)
        if step < MINUTE:
            return f"{h:02d}:{mi:02d}:{s:02d}"
        return f"{h:02d}:{mi:02d}"

    def _calendar_label(self, t: int, step: tuple[str, int]) -> str:
        y, mo, d, *_ = self._parts(t)
        kind, n = step
        if kind == "year":
            return year_label(y)
        if kind == "month":
            return year_label(y) if mo == 1 and n < 12 else MONTHS[mo - 1]
        return f"{MONTHS[mo - 1]} {d}" if n >= 7 else str(d)

    def _second_context(self, t: int) -> str:
        y, mo, d, h, mi, s = self._parts(t)
        return f"{MONTHS[mo - 1]} {d}, {year_label(y)} {h:02d}:{mi:02d}:{s:02d}"

    def _day_context(self, t: int) -> str:
        y, mo, d, *_ = self._parts(t)
        weekday = WEEKDAYS[_weekday(_utc_of(y, mo, d) // 86_400_000)]
        return f"{weekday} {MONTHS[mo - 1]} {d}, {year_label(y)}"

    def _month_context(self, t: int) -> str:
        y, mo, *_ = self._parts(t)
        return f"{MONTHS_LONG[mo - 1]} {year_label(y)}"

    def format_full(self, x: float) -> str:
        """A time with all the precision of the data's unit (tooltips)."""
        if self.kind == "order":
            return f"#{fmt_number(js_round(x) + 1)}"
        if self.kind == "number":
            return fmt_number(self.origin + x, 10)
        ns = self.ns_of(x)
        digits = {"s": 0, "ms": 3, "us": 6, "ns": 9}.get(_unit_of(self.per_ns), 9)
        if self.kind == "duration":
            return format_duration(float(ns), max(1, 10 ** (9 - digits)), exact=True)
        y, mo, d, h, mi, s = self._parts(ns)
        sub = ns % 1_000_000_000
        if h == 0 and mi == 0 and s == 0 and sub == 0:  # a time exactly at midnight is a date
            return f"{year_label(y)}-{mo:02d}-{d:02d}"
        frac = "." + _group_digits(f"{sub:09d}"[:digits]) if digits else ""
        return f"{year_label(y)}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}{frac} {self.tz}"

    def format_span(self, dx: float) -> str:
        """A span of ticks as a duration ("2.5 s", "3 min"); for numbers and ranks as a number."""
        if self.kind == "order":
            return f"{fmt_number(dx)} events"
        if self.kind == "number":
            return fmt_number(dx, 3)
        return format_duration(dx * self.per_ns, 0, sig=2)


def _spacing_for(step_ns: int) -> int:
    return MIN_SPACING["long"] if step_ns < 10**6 else MIN_SPACING["medium"]


def _unit_of(per_ns: int) -> str:
    return (
        "s" if per_ns >= 10**9 else "ms" if per_ns >= 10**6 else "us" if per_ns >= 10**3 else "ns"
    )


def _fraction_label(t: int, step: int) -> str:
    """The fraction of a second of an instant, with as many digits as the step needs: ".25",
    ".250 300"."""
    digits = min(9, max(1, math.ceil(-math.log10(step / SECOND) - 1e-9)))
    grouped = min(9, math.ceil(digits / 3) * 3)
    return "." + _group_digits(f"{t % 1_000_000_000:09d}"[:grouped])


def _group_digits(s: str) -> str:
    return "\u2009".join(s[i : i + 3] for i in range(0, len(s), 3))


def year_label(y: int) -> str:
    return f"{1 - y} BC" if y <= 0 else str(y)


def nice_step(raw: float, integer: bool) -> float:
    """A 1-2-5 step at least ``raw`` (integers only when ``integer``)."""
    if not (raw > 0) or not math.isfinite(raw):
        return 1
    exp = math.floor(math.log10(raw))
    base = 10.0**exp
    m = raw / base
    step = (1 if m <= 1 else 2 if m <= 2 else 5 if m <= 5 else 10) * base
    return max(1, js_round(step)) if integer else step


def _round_to(v: float, step: float) -> float:
    decimals = max(0, -math.floor(math.log10(step)))
    return float(to_fixed(v, min(15, decimals)))


def fmt_number(v: float, precision: int = 6) -> str:
    """A number as the plot writes it: integers grouped by thin spaces ("1 234 567"), others
    to ``precision`` significant digits."""
    if not math.isfinite(v):
        return "–"
    if float(v).is_integer() and abs(v) < 1e15:
        return f"{int(v):,}".replace(",", "\u2009")
    a = abs(v)
    if a != 0 and (a < 1e-4 or a >= 1e15):
        text = to_exponential(v, max(0, precision - 1))
        mantissa, exp = text.split("e")
        if "." in mantissa:
            mantissa = mantissa.rstrip("0").rstrip(".")
        return f"{mantissa}e{exp}"
    return js_str(float(to_precision(v, precision)))


DURATION_UNITS = [
    (DAY, "d"), (HOUR, "h"), (MINUTE, "min"), (SECOND, "s"),
    (10**6, "ms"), (10**3, "µs"), (1, "ns"),
]  # fmt: skip


def format_duration(ns: float, step_ns: float, exact: bool = False, sig: int = 3) -> str:
    """A duration in ns as text. With ``step_ns`` > 0, enough decimals to tell steps apart;
    with ``exact``, the full value; else ``sig`` significant digits."""
    sign = "−" if ns < 0 else ""
    a = abs(ns)
    if a == 0:
        return "0"
    per, name = next((u for u in DURATION_UNITS if a >= u[0]), DURATION_UNITS[-1])
    value = a / per
    if exact:
        text = js_str(float(to_precision(value, 15)))
    elif step_ns > 0:
        decimals = max(0, min(9, math.ceil(-math.log10(step_ns / per) - 1e-9)))
        text = to_fixed(value, decimals)
    else:
        text = js_str(float(to_precision(value, sig)))
    return f"{sign}{text} {name}"


# ---------------------------------------------------------------------- JavaScript's numbers


def js_round(x: float) -> int:
    """``Math.round``: halves up."""
    return math.floor(x + 0.5)


def _exact(x: float) -> Decimal:
    return Decimal(x)


def to_fixed(x: float, digits: int) -> str:
    """``x.toFixed(digits)``."""
    if not math.isfinite(x) or abs(x) >= 1e21:
        return js_str(x)
    q = _exact(abs(x)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    text = f"{q:f}"
    return f"-{text}" if x < 0 and q != 0 else text


def to_precision(x: float, precision: int) -> str:
    """``x.toPrecision(precision)``."""
    if not math.isfinite(x):
        return js_str(x)
    if x == 0:
        return "0" if precision == 1 else "0." + "0" * (precision - 1)
    d = _exact(abs(x))
    e = d.adjusted()
    q = d.scaleb(-e).quantize(Decimal(1).scaleb(1 - precision), rounding=ROUND_HALF_UP)
    if q >= 10:
        e += 1
        q = d.scaleb(-e).quantize(Decimal(1).scaleb(1 - precision), rounding=ROUND_HALF_UP)
    digits = str(q).replace(".", "")
    sign = "-" if x < 0 else ""
    if e < -6 or e >= precision:
        mantissa = digits[0] + ("." + digits[1:] if precision > 1 else "")
        return f"{sign}{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"
    if e >= 0:
        whole, rest = digits[: e + 1], digits[e + 1 :]
        return f"{sign}{whole}.{rest}" if rest else f"{sign}{whole}"
    return f"{sign}0.{'0' * (-e - 1)}{digits}"


def to_exponential(x: float, digits: int) -> str:
    """``x.toExponential(digits)``."""
    if x == 0:
        return "0" + ("." + "0" * digits if digits else "") + "e+0"
    d = _exact(abs(x))
    e = d.adjusted()
    q = d.scaleb(-e).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    if q >= 10:
        e += 1
        q = d.scaleb(-e).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    sign = "-" if x < 0 else ""
    return f"{sign}{q:f}e{'+' if e >= 0 else '-'}{abs(e)}"


def js_str(x: float) -> str:
    """``String(x)``: the shortest digits that read back as ``x``, as JavaScript writes them."""
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    _, digit_tuple, exponent = Decimal(repr(abs(x))).normalize().as_tuple()
    digits = "".join(map(str, digit_tuple))
    k = len(digits)
    n = k + int(exponent)  # the value is 0.digits × 10^n
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return f"{sign}{digits[:n]}.{digits[n:]}"
    if -6 < n <= 0:
        return f"{sign}0.{'0' * -n}{digits}"
    e = n - 1
    mantissa = digits[0] + ("." + digits[1:] if k > 1 else "")
    return f"{sign}{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"
