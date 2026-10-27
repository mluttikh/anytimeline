"""The selection in numbers: ``Timeline.summary`` and the panel the plot shows while something
is selected.

Per layer, the selected marks are counted by lane and colour category. Bars (intervals and
states) add their total and mean duration; open bars count, but have no duration. Events add
their first and last time, values their mean, least and greatest value. The panel shows the
same numbers, summed over lanes and over categories, as text written in Python (events: the
time from the first to the last).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from anytimeline.axis import fmt_number, format_duration
from anytimeline.layers import events as ev
from anytimeline.layers import intervals as iv
from anytimeline.layers import values as vl
from anytimeline.layers.common import Layout, Record
from anytimeline.timebase import UNITS, TimeBase, Times

PANEL_ROWS = 8
"""The most rows a block of the panel lists (the most marks first)."""


@dataclass
class Groups:
    """A layer's selected marks, grouped by lane and colour category."""

    kind: str  # "bars", "events" or "values"
    lane_title: str
    group: list[str] | None  # per group: its lanes' group (layers with ``group=``)
    color_title: str | None  # None: the layer has no colour categories
    lane: list[str]  # per group
    category: list[str | None]
    color: list[str | None]  # the category's colour (hex)
    count: np.ndarray  # int64
    # bars: total and mean (ns, or the time column's numbers); open: bars without an end
    total: np.ndarray | None = None
    mean: np.ndarray | None = None
    open: np.ndarray | None = None
    # events: first and last time (ticks); values: mean, least and greatest value
    first: np.ndarray | None = None
    last: np.ndarray | None = None
    low: np.ndarray | None = None
    high: np.ndarray | None = None
    numbers: bool = False  # bars' durations are plain numbers (not ns)


def positions(rec: Record, rows: Sequence[int]) -> np.ndarray:
    """The positions in ``rec.rows`` of the table rows ``rows`` (those not drawn left out)."""
    if not len(rows) or not len(rec.rows):
        return np.zeros(0, dtype=np.int64)
    pos_of_row = np.full(int(rec.rows.max()) + 1, -1, dtype=np.int64)
    pos_of_row[rec.rows] = np.arange(len(rec.rows))
    wanted = np.asarray([r for r in rows if 0 <= r < len(pos_of_row)], dtype=np.int64)
    pos = pos_of_row[wanted]
    return np.sort(pos[pos >= 0])


def _ns(t: Times, pos: np.ndarray) -> np.ndarray:
    """Times at ``pos`` as float64 ns (datetimes: since the epoch), or plain numbers."""
    if t.raw is None:
        assert t.values is not None
        return t.values[pos].astype(np.float64)
    return t.raw[pos].astype(np.float64) * t.per


def _span(starts: Times, ends: Times, pos: np.ndarray) -> np.ndarray:
    """Each bar's duration (ns, or the time column's numbers); exact while both ends have
    one unit."""
    if starts.raw is not None and ends.raw is not None and starts.per == ends.per:
        return (ends.raw[pos] - starts.raw[pos]).astype(np.float64) * starts.per
    return _ns(ends, pos) - _ns(starts, pos)


def group(rec: Record, lay: Layout, lane_names: Sequence[str], pos: np.ndarray) -> Groups:
    """The marks at positions ``pos`` of a layer, grouped by lane (in the plot's order) and
    colour category (in the legend's)."""
    lane_of = np.full(len(rec.rows), -1, dtype=np.int64)
    lane_of[rec.perm] = lay.lanes
    lanes = lane_of[pos]
    color = getattr(rec, "color", None)
    extra = color.extra if color is not None else {}
    if color is not None and "codes" in extra:
        codes = np.asarray(extra["codes"], dtype=np.int64)[pos]
        names: list[str] = extra["names"]
        palette = extra["palette"]
        title = (color.legend or {}).get("title") or "color"
    else:
        codes = np.zeros(len(pos), dtype=np.int64)
        names, palette, title = [], None, None
    key = lanes * (len(names) + 1) + codes
    keys, first, inverse, count = np.unique(
        key, return_index=True, return_inverse=True, return_counts=True
    )
    groups = getattr(rec, "lane_groups", None)
    lane_idx, code_idx = np.divmod(keys, len(names) + 1)
    if isinstance(rec, iv.IntervalsRecord):
        kind = "bars"
    elif isinstance(rec, vl.ValuesRecord):
        kind = "values"
    else:
        kind = "events"
    out = Groups(
        kind=kind,
        lane_title=getattr(rec, "lane_title", "") or "lane",
        group=None if groups is None else [str(v) for v in groups[pos[first]].tolist()],
        color_title=title,
        lane=[lane_names[i] if 0 <= i < len(lane_names) else "" for i in lane_idx.tolist()],
        category=[names[c] if names else None for c in code_idx.tolist()],
        color=[_hex(palette[c]) if palette is not None else None for c in code_idx.tolist()],
        count=count.astype(np.int64),
    )
    n = len(keys)

    def sums(values: np.ndarray) -> np.ndarray:
        return np.bincount(inverse, weights=values, minlength=n).astype(np.float64)

    def extreme(values: np.ndarray, ok: np.ndarray, fn: Any, empty: float) -> np.ndarray:
        got = np.full(n, empty)
        fn.at(got, inverse[ok], values[ok])
        got[got == empty] = np.nan
        return got

    if isinstance(rec, iv.IntervalsRecord):
        closed = rec.ends.valid[pos] & rec.starts.valid[pos]
        span = np.where(closed, _span(rec.starts, rec.ends, pos), 0.0)
        shut = sums(closed.astype(np.float64))
        out.total = sums(span)
        with np.errstate(invalid="ignore", divide="ignore"):
            out.mean = np.where(shut > 0, out.total / np.maximum(shut, 1), np.nan)
        out.total[shut == 0] = np.nan
        out.open = (out.count - shut).astype(np.int64)
        out.numbers = rec.starts.raw is None
    elif isinstance(rec, vl.ValuesRecord):
        v = rec.values[pos]
        ok = np.isfinite(v)
        k = sums(ok.astype(np.float64))
        with np.errstate(invalid="ignore", divide="ignore"):
            out.mean = sums(np.where(ok, v, 0.0)) / k
        out.low = extreme(v, ok, np.minimum, np.inf)
        out.high = extreme(v, ok, np.maximum, -np.inf)
    elif isinstance(rec, ev.EventsRecord) and rec.times is not None:
        t = lay.lo[np.argsort(rec.perm)][pos]  # each position's time, in ticks
        ok = np.isfinite(t)
        out.first = extreme(t, ok, np.minimum, np.inf)
        out.last = extreme(t, ok, np.maximum, -np.inf)
    return out


def _hex(rgba: np.ndarray) -> str:
    r, g, b = (int(v) for v in rgba[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def table(g: Groups, base: TimeBase | None, like: Any) -> Any:
    """The groups as a table of the type ``like`` is (Polars, PyArrow, pandas, or a dict of
    arrays): a column for the lane, one for the colour category (when there is one), then
    the numbers. Times are in the plot's time zone (a dict of arrays: UTC)."""
    cols: dict[str, Any] = {}
    if g.group is not None:
        cols["group"] = np.asarray(g.group, dtype=object)
    cols[g.lane_title] = np.asarray(g.lane, dtype=object)
    if g.color_title is not None:
        name = g.color_title if g.color_title != g.lane_title else f"{g.color_title} (color)"
        cols[name] = np.asarray(g.category, dtype=object)
    cols["count"] = g.count
    if g.total is not None and g.mean is not None and g.open is not None:
        cols["total"] = _durations(g.total, g.numbers)
        cols["mean"] = _durations(g.mean, g.numbers)
        cols["open"] = g.open
    if g.first is not None and g.last is not None:
        cols["first"] = _instants(g.first, base)
        cols["last"] = _instants(g.last, base)
    if g.low is not None and g.high is not None and g.mean is not None:
        cols["mean"] = g.mean
        cols["min"] = g.low
        cols["max"] = g.high
    if isinstance(like, Mapping):
        return cols
    import narwhals as nw

    native = nw.from_native(like, eager_only=True)
    out = nw.from_dict(
        {k: v.tolist() if v.dtype == object else v for k, v in cols.items()},
        backend=nw.get_native_namespace(native),
    )
    zone = base.timezone if base is not None and base.kind == "datetime" else "UTC"
    if "first" in cols and zone != "UTC":  # times in the plot's time zone
        out = out.with_columns(
            nw.col(c).dt.replace_time_zone("UTC").dt.convert_time_zone(zone)
            for c in ("first", "last")
        )
    return out.to_native()


def _durations(ns: np.ndarray, numbers: bool) -> np.ndarray:
    if numbers:
        return ns
    out = np.full(len(ns), np.timedelta64("NaT", "ns"), dtype="timedelta64[ns]")
    ok = np.isfinite(ns)
    out[ok] = np.round(ns[ok]).astype(np.int64).astype("timedelta64[ns]")
    return out


def _instants(ticks: np.ndarray, base: TimeBase | None) -> np.ndarray:
    if base is None:
        return ticks  # order only: positions
    values = [base.to_value(t) if np.isfinite(t) else None for t in ticks.tolist()]
    if base.kind == "number":
        return np.asarray([np.nan if v is None else v for v in values], dtype=np.float64)
    unit = "datetime64[ns]" if base.kind == "datetime" else "timedelta64[ns]"
    nat = np.datetime64("NaT", "ns") if base.kind == "datetime" else np.timedelta64("NaT", "ns")
    return np.asarray([nat if v is None else v for v in values]).astype(unit)


# ---------------------------------------------------------------------- the panel


def panel(name: str, g: Groups, base: TimeBase | None) -> dict[str, Any]:
    """What the plot's panel shows of a layer: the totals, then the numbers by colour
    category and by lane (the most marks first, at most PANEL_ROWS of each), as text."""
    text = _formatter(g, base)
    whole = _merge(g, np.zeros(len(g.count), dtype=np.int64))
    blocks = []
    if g.color_title is not None:
        cats = {c: i for i, c in enumerate(dict.fromkeys(g.category))}
        blocks.append(_block(g.color_title, g, [cats[c] for c in g.category], text, None))
    names = (
        g.lane if g.group is None else [f"{a} · {b}" for a, b in zip(g.group, g.lane, strict=True)]
    )
    lanes = {n: i for i, n in enumerate(dict.fromkeys(names))}
    if len(lanes) > 1:
        blocks.append(_block(g.lane_title, g, [lanes[n] for n in names], text, names))
    columns = ["count"]
    if g.kind == "bars":
        columns += ["total", "mean"]
    elif g.kind == "values":
        columns += ["mean", "min", "max"]
    elif g.first is not None:
        columns += ["span"]
    return {
        "layer": name,
        "columns": columns,
        "total": text(whole, 0),
        "blocks": blocks,
    }


def _merge(g: Groups, into: np.ndarray) -> dict[str, np.ndarray]:
    """The groups' numbers summed into the groups ``into`` (an index per group)."""
    n = int(into.max()) + 1 if len(into) else 0

    def add(v: np.ndarray) -> np.ndarray:
        return np.bincount(into, weights=v, minlength=n).astype(np.float64)

    def ext(v: np.ndarray, fn: Any, empty: float) -> np.ndarray:
        got = np.full(n, empty)
        ok = np.isfinite(v)
        fn.at(got, into[ok], v[ok])
        got[got == empty] = np.nan
        return got

    out: dict[str, np.ndarray] = {"count": add(g.count.astype(np.float64))}
    if g.total is not None and g.open is not None:
        total = np.nan_to_num(g.total)
        closed = add((g.count - g.open).astype(np.float64))
        out["total"] = np.where(closed > 0, add(total), np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            out["mean"] = out["total"] / closed
        out["open"] = add(g.open.astype(np.float64))
    if g.low is not None and g.high is not None and g.mean is not None:
        ok = np.isfinite(g.mean)
        weight = np.where(ok, g.count, 0).astype(np.float64)
        with np.errstate(invalid="ignore", divide="ignore"):
            out["mean"] = add(np.where(ok, g.mean, 0.0) * weight) / add(weight)
        out["min"] = ext(g.low, np.minimum, np.inf)
        out["max"] = ext(g.high, np.maximum, -np.inf)
    if g.first is not None and g.last is not None:
        out["first"] = ext(g.first, np.minimum, np.inf)
        out["last"] = ext(g.last, np.maximum, -np.inf)
    return out


def _block(
    title: str, g: Groups, into: list[int], text: Any, labels: list[str] | None
) -> dict[str, Any]:
    """A block of the panel: the groups summed into ``into``, labelled by colour category,
    or by ``labels`` (the lanes')."""
    idx = np.asarray(into, dtype=np.int64)
    merged = _merge(g, idx)
    first = {}
    for k, i in enumerate(into):
        first.setdefault(i, k)
    order = np.argsort(-merged["count"], kind="stable")
    rows = []
    for i in order[:PANEL_ROWS].tolist():
        k = first[i]
        row = text(merged, i)
        row["label"] = (g.category[k] if labels is None else labels[k]) or ""
        row["color"] = g.color[k] if labels is None else None
        rows.append(row)
    return {"title": title, "rows": rows, "more": max(0, len(order) - PANEL_ROWS)}


def _formatter(g: Groups, base: TimeBase | None) -> Any:
    def duration(v: float) -> str:
        if not np.isfinite(v):
            return "–"
        return fmt_number(float(v), 4) if g.numbers else format_duration(float(v), 0, False, 3)

    def span(ticks: float) -> str:
        """From the first event to the last: ticks as text (a plot of numbers: numbers)."""
        if not np.isfinite(ticks):
            return "–"
        if base is None or base.kind == "number":
            return fmt_number(float(ticks), 4)
        return format_duration(float(ticks) * UNITS[base.unit], 0, False, 3)

    def text(m: dict[str, np.ndarray], i: int) -> dict[str, Any]:
        row: dict[str, Any] = {"count": f"{int(m['count'][i]):,}"}
        if "total" in m:
            row["total"] = duration(m["total"][i])
            row["mean"] = duration(m["mean"][i])
            if m["open"][i]:
                row["open"] = f"{int(m['open'][i]):,} open"
        if "min" in m:
            row["mean"] = fmt_number(float(m["mean"][i]), 4)
            row["min"] = fmt_number(float(m["min"][i]), 4)
            row["max"] = fmt_number(float(m["max"][i]), 4)
        if "first" in m:
            row["span"] = span(m["last"][i] - m["first"][i])
        return row

    return text
