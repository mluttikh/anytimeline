"""The values layer: a number over time in each lane (CPU, queue length, error rate), drawn as
a small line, area or step chart in the lane's band, behind its events and bars.

Samples are not events: they do not take places on the Order scale (a metric sampled every
second would crowd out the events); there, they are drawn between the events they fall
between. ``series`` splits a lane into several lines (p50 and p99, one per host).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, get_args

import numpy as np

from anytimeline import data as tables
from anytimeline import styling
from anytimeline.codec import Encoded, encode
from anytimeline.layers.common import lexsort, numbers
from anytimeline.timebase import TimeBase, Times, times
from anytimeline.types import ValuesKind, ValuesScale

KINDS = get_args(ValuesKind)
SCALES = get_args(ValuesScale)


@dataclass
class ValuesRecord:
    """A values layer as read from its table (rows with a time)."""

    name: str
    rows: np.ndarray
    times: Times
    values: np.ndarray  # float64, NaN: a gap in the line
    lanes: np.ndarray
    lane_title: str
    lane_declared: list[Any] | None
    series: np.ndarray | None
    series_title: str
    color: styling.Encoding  # per row
    kind: ValuesKind
    scale: ValuesScale
    ylim: tuple[float, float] | dict[Any, tuple[float, float]] | None
    width: float
    tooltip: dict[str, np.ndarray]
    hover: bool
    dropped: int
    select: bool = False
    perm: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    lane_groups: np.ndarray | None = None  # each row's group (group=), or None
    lane_group_declared: list[Any] | None = None

    @property
    def time_columns(self) -> list[Times]:
        return [self.times]


def build(
    data: Any,
    *,
    name: str,
    time: str,
    value: str,
    lane: str | None,
    series: str | None,
    color: str | None,
    palette: Mapping[Any, str] | Sequence[str] | None,
    kind: ValuesKind,
    scale: ValuesScale,
    ylim: tuple[float, float] | Mapping[Any, tuple[float, float]] | None,
    width: float,
    tooltip: Sequence[str] | None,
    time_unit: str | None,
    hover: bool,
) -> ValuesRecord:
    """Read a values layer from a table."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    if scale not in SCALES:
        raise ValueError(f"scale must be one of {SCALES}, got {scale!r}")
    for lim in ylim.values() if isinstance(ylim, Mapping) else [ylim] if ylim is not None else []:
        if not (len(lim) == 2 and float(lim[1]) > float(lim[0])):
            raise ValueError(f"ylim must be (low, high) with high above low, got {lim!r}")
    table = tables.frame(data)
    names = tables.column_names(table)
    tables.check(table, [time, value] + [c for c in (lane, series) if c] + list(tooltip or []))
    n = len(tables.column(table, time))
    t = times(
        tables.column(table, time),
        timezone=tables.time_zone(table, time),
        unit=time_unit,
        column=time,
    )
    rows = np.flatnonzero(t.valid)
    t = t.take(rows)
    v = numbers(tables.column(table, value)[rows], value)
    lanes = (
        tables.column(table, lane)[rows].astype(object)
        if lane is not None
        else np.full(len(rows), value, dtype=object)
    )
    lanes[tables.is_missing(lanes)] = "(missing)"
    groups = tables.column(table, series)[rows].astype(object) if series is not None else None
    if color is not None and color not in names and not styling.is_color(color):
        raise tables.NotFoundError(
            f"color={color!r} is neither a column nor a colour; columns: {names}"
        )
    by = series if color is None else (color if color in names else None)
    enc = styling.colors(
        tables.column(table, by)[rows] if by is not None else None,
        solid=color if (color is not None and color not in names) else None,
        title=by or "",
        declared=tables.categories(table, by) if by else None,
        palette=palette,
    )
    return ValuesRecord(
        name=name,
        rows=rows,
        times=t,
        values=v,
        lanes=lanes,
        lane_title=lane or "",
        lane_declared=tables.categories(table, lane) if lane else None,
        series=groups,
        series_title=series or "",
        color=enc,
        kind=kind,
        scale=scale,
        ylim={k: (float(a), float(b)) for k, (a, b) in ylim.items()}
        if isinstance(ylim, Mapping)
        else (float(ylim[0]), float(ylim[1]))
        if ylim is not None
        else None,
        width=float(width),
        tooltip={c: tables.column(table, c)[rows] for c in (tooltip or [])},
        hover=hover,
        dropped=int(n - len(rows)),
    )


@dataclass
class Samples:
    """A values layer's samples in the browser's order (by lane, series and time), kept for
    the levels and windows of a layer sent as levels."""

    time: np.ndarray
    value: np.ndarray
    run_starts: np.ndarray  # runs (a lane's series): their first samples, and the end
    run_lane: np.ndarray
    run_color: np.ndarray
    series: list[str] | None  # each run's
    ylim: np.ndarray


@dataclass
class Layout:
    """A values layer laid out on the plot's time base and lanes: its spec and buffers."""

    spec: dict[str, Any]
    buffers: list[Encoded]
    lo: np.ndarray  # sorted by lane, series and time: the samples' ticks
    hi: np.ndarray
    lanes: np.ndarray
    instants: list[tuple[np.ndarray, np.ndarray]]  # none: samples take no place in the order
    extent: tuple[float, float] | None  # the time range the samples cover
    samples: Samples


def layout(
    rec: ValuesRecord,
    base: TimeBase | None,
    lane_index: Mapping[Any, int],
    *,
    levelled: bool = False,
) -> Layout:
    """Sort the samples by lane, series and time; find each lane's range of values
    (``levelled``: no samples in the spec; the plot sends levels, and samples in windows)."""
    assert base is not None
    n = len(rec.rows)
    ticks = base.ticks(rec.times)
    lane = np.array([lane_index[v] for v in rec.lanes.tolist()], dtype=np.int64)
    if rec.series is not None:
        first = {v: i for i, v in reversed(list(enumerate(rec.series.tolist())))}
        group = np.array([first[v] for v in rec.series.tolist()], dtype=np.int64)
    else:
        group = np.zeros(n, dtype=np.int64)
    perm = lexsort((ticks, group, lane))
    rec.perm = perm
    t_s, v_s, lane_s, group_s = ticks[perm], rec.values[perm], lane[perm], group[perm]
    # runs: one line each (a lane's series)
    change = np.ones(n, dtype=bool)
    change[1:] = (lane_s[1:] != lane_s[:-1]) | (group_s[1:] != group_s[:-1])
    run_starts = np.append(np.flatnonzero(change), n).astype(np.uint32)
    run_first = run_starts[:-1].astype(np.int64)
    n_lanes = max(lane_index.values(), default=-1) + 1

    # the range of values per lane (or one for all), with a little room
    ylim = np.full((n_lanes, 2), np.nan)
    finite = np.isfinite(v_s)
    fixed = rec.ylim if isinstance(rec.ylim, dict) else {}
    if rec.ylim is not None and not isinstance(rec.ylim, dict):
        ylim[:] = rec.ylim
    elif finite.any():
        if rec.scale == "shared":
            ylim[:] = (float(v_s[finite].min()), float(v_s[finite].max()))
        else:
            # per lane; a lane in several groups (its key (group, lane)) has one range in all
            bounds = np.searchsorted(lane_s, np.arange(n_lanes + 1), side="left")
            name_of = {i: _lane_name(k) for k, i in lane_index.items()}
            by_name: dict[Any, tuple[float, float]] = {}
            for ln in range(n_lanes):
                seg = v_s[bounds[ln] : bounds[ln + 1]]
                seg = seg[np.isfinite(seg)]
                if len(seg):
                    lo, hi = by_name.get(name_of[ln], (np.inf, -np.inf))
                    by_name[name_of[ln]] = (min(lo, float(seg.min())), max(hi, float(seg.max())))
            for ln in range(n_lanes):
                if bounds[ln + 1] > bounds[ln] and name_of[ln] in by_name:
                    ylim[ln] = by_name[name_of[ln]]
        # a range that starts near zero starts at zero (rates, counts, percentages)
        low, high = ylim[:, 0], ylim[:, 1]
        near_zero = (low >= 0) & (low <= (high - low) * 0.5)
        ylim[:, 0] = np.where(near_zero, 0.0, low)
    # ranges given per lane (by its name: in every group)
    for key, i in lane_index.items():
        if _lane_name(key) in fixed:
            ylim[i] = fixed[_lane_name(key)]

    c = rec.color
    samples = Samples(
        time=t_s,
        value=v_s,
        run_starts=run_starts,
        run_lane=lane_s[run_first].astype(np.uint32),
        run_color=c.values[perm][run_first]
        if c.values is not None
        else np.zeros((len(run_first), 4), np.uint8),
        series=[str(s) for s in rec.series[perm][run_first].tolist()]
        if rec.series is not None
        else None,
        ylim=ylim,
    )
    rows = np.zeros(0, dtype=np.int64) if levelled else None
    spec, buffers = encode_samples(rec, samples, rows)
    extent = (float(t_s.min()), float(t_s.max())) if n else None
    return Layout(spec, buffers, t_s, t_s, lane_s, [], extent, samples)


def encode_samples(
    rec: ValuesRecord, samples: Samples, rows: np.ndarray | None = None
) -> tuple[dict[str, Any], list[Encoded]]:
    """The spec and buffers of the layer's samples, or of some of them (``rows``: indices into
    ``samples``, in order: a level's or a window's, with ``index``, each one's index)."""
    buffers: list[Encoded] = []

    def put(enc: Encoded) -> dict[str, Any]:
        buffers.append(enc)
        return enc.descriptor

    s = samples
    if rows is None:
        t, v, starts = s.time, s.value, s.run_starts
    else:
        t, v = s.time[rows], s.value[rows]
        run_of = np.searchsorted(s.run_starts, rows, side="right") - 1
        starts = np.searchsorted(run_of, np.arange(len(s.run_lane) + 1), side="left")
    c = rec.color
    spec: dict[str, Any] = {
        "type": "values",
        "name": rec.name,
        "count": len(t),
        "time": put(encode(t, "float64")),
        "value": put(encode(v, "float32")),
        "runs": {
            "starts": put(encode(starts, "uint32")),
            "lane": put(encode(s.run_lane, "uint32")),
            "color": put(encode(s.run_color, "uint8", components=4)),
            "count": len(s.run_lane),
        },
        "series": s.series,
        "series_title": rec.series_title,
        "ylim": put(encode(s.ylim, "float64", components=2)),
        "kind": rec.kind,
        "width": rec.width,
        "hover": rec.hover,
        "select": False,
        "dropped": rec.dropped,
        "color": {"solid": c.value, "alpha": c.extra.get("alpha", 255), "legend": c.legend},
        "tooltip": list(rec.tooltip),
    }
    if rows is not None and len(rows):
        spec["index"] = put(encode(rows, "uint32"))
    return spec, buffers


def m4(samples: Samples, rows: np.ndarray, grid: Any, k: int) -> np.ndarray:
    """Of the samples ``rows`` (in order), those that draw them per bin of level ``k`` as the
    browser draws a pixel column: each run's first, lowest, highest and last value in each bin,
    and its first gap (NaN) there; in order."""
    if not len(rows):
        return rows
    t, v = samples.time[rows], samples.value[rows].astype(np.float64)
    run = np.searchsorted(samples.run_starts, rows, side="right") - 1
    j = np.floor((t - grid.x0) / grid.width(k)).astype(np.int64)
    n = len(rows)
    brk = np.empty(n, dtype=bool)
    brk[0] = True
    brk[1:] = (j[1:] != j[:-1]) | (run[1:] != run[:-1])
    starts = np.flatnonzero(brk)
    ends = np.append(starts[1:], n)
    seg = np.repeat(np.arange(len(starts)), ends - starts)
    idx = np.arange(n)
    nan = np.isnan(v)
    low = np.where(nan, np.inf, v)
    high = np.where(nan, -np.inf, v)
    lowest = np.minimum.reduceat(low, starts)
    highest = np.maximum.reduceat(high, starts)
    at_low = np.minimum.reduceat(np.where(low == lowest[seg], idx, n), starts)
    at_high = np.minimum.reduceat(np.where(high == highest[seg], idx, n), starts)
    at_gap = np.minimum.reduceat(np.where(nan, idx, n), starts)
    kept = np.concatenate([starts, ends - 1, at_low, at_high, at_gap])
    return rows[np.unique(kept[kept < n])]


def window_rows(samples: Samples, a: float, b: float) -> np.ndarray:
    """The samples from ``a`` to ``b``, and each run's one before and one after (its line goes
    on to them), in order."""
    parts = []
    starts = samples.run_starts
    for r in range(len(starts) - 1):
        lo, hi = int(starts[r]), int(starts[r + 1])
        seg = samples.time[lo:hi]
        i0 = max(0, int(np.searchsorted(seg, a, "left")) - 1)
        i1 = min(hi - lo, int(np.searchsorted(seg, b, "right")) + 1)
        if i1 > i0:
            parts.append(np.arange(lo + i0, lo + i1))
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.int64)


def _lane_name(key: Any) -> Any:
    """A lane key's lane: the lane itself, or of (group, lane) the lane."""
    return key[1] if isinstance(key, tuple) and len(key) == 2 else key
