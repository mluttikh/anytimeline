"""The states layer: a lane that is in one state at a time (up / degraded / down, a feature
flag, a phase), read from a table of changes: from each row's time on, its lane is in its
state, until the lane's next change.

``build`` turns the changes into bars and returns an ``IntervalsRecord``, so states lay out,
draw, hover and select like intervals. Rows that repeat the state their lane is already in
are joined to the bar before; a missing state is a gap (nothing known); a lane's last state
runs to ``end``, or to the plot's last time.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from anytimeline import data as tables
from anytimeline import styling
from anytimeline.events import _texts
from anytimeline.intervals import IntervalsRecord
from anytimeline.timebase import Times, times


def build(
    data: Any,
    *,
    name: str,
    time: str,
    state: str,
    lane: str | None,
    end: Any,
    color: str | None,
    palette: Mapping[Any, str] | Sequence[str] | None,
    opacity: float,
    text: bool | str,
    tooltip: Sequence[str] | None,
    height: float,
    time_unit: str | None,
    hover: bool,
    select: bool,
) -> IntervalsRecord:
    """Read a states layer from a table of changes."""
    if not 0 < height <= 1:
        raise ValueError(f"height is a fraction of the lane, above 0 and at most 1; got {height}")
    table = tables.frame(data)
    names = tables.column_names(table)
    tables.check(table, [time, state] + ([lane] if lane else []) + list(tooltip or []))
    n = len(tables.column(table, time))
    t = times(tables.column(table, time), timezone=tables.time_zone(table, time), unit=time_unit)
    valid = np.flatnonzero(t.valid)
    states_all = tables.column(table, state).astype(object)
    lanes_all = (
        tables.column(table, lane).astype(object)
        if lane is not None
        else np.full(n, name, dtype=object)
    )
    if lane is not None:
        lanes_all[tables.is_missing(lanes_all)] = "(missing)"

    # by lane (in the order lanes first appear), then time, then table order
    key = _comparable(t)
    first = {v: i for i, v in reversed(list(enumerate(lanes_all[valid].tolist())))}
    lane_rank = np.array([first[v] for v in lanes_all[valid].tolist()], dtype=np.int64)
    order = valid[np.lexsort((valid, key[valid], lane_rank))]
    lanes_o = lanes_all[order]
    states_o = states_all[order]
    missing_o = tables.is_missing(states_o)
    same_lane = np.zeros(len(order), dtype=bool)
    same_lane[1:] = lanes_o[1:] == lanes_o[:-1]
    same_state = np.zeros(len(order), dtype=bool)
    same_state[1:] = same_lane[1:] & (
        (states_o[1:] == states_o[:-1]) | (missing_o[1:] & missing_o[:-1])
    )
    # a change: the first row of a lane, or a different state than the row before
    change = order[~same_state]
    lanes_c = lanes_all[change]
    has_next = np.zeros(len(change), dtype=bool)
    has_next[:-1] = lanes_c[1:] == lanes_c[:-1]
    nxt = np.minimum(np.arange(len(change)) + 1, max(len(change) - 1, 0))

    starts = t.take(change)
    ends = _ends(starts, t.take(change[nxt]) if len(change) else starts, has_next, end)
    keep = ~tables.is_missing(states_all[change])  # a missing state: a gap
    # a state that ends where it starts (two changes at one time) is not drawn
    keep &= ~(ends.valid & (_comparable(ends) == _comparable(starts)))
    if end is not None and len(change):
        early = ~has_next & (_comparable(ends) < _comparable(starts))
        if early.any():
            raise ValueError(f"end={end!r} is before the last change of {int(early.sum())} lanes")
    rows = change[keep]
    starts, ends = starts.take(np.flatnonzero(keep)), ends.take(np.flatnonzero(keep))
    values = states_all[rows]

    color_is_column = color is None or color in names
    if color is not None and not color_is_column and not styling.is_color(color):
        raise tables.NotFoundError(
            f"color={color!r} is neither a column nor a colour; columns: {names}"
        )
    column = state if color is None else color
    color_enc = styling.colors(
        tables.column(table, column)[rows] if color_is_column else None,
        solid=None if color_is_column else color,
        title=column if color_is_column else "",
        declared=tables.categories(table, column) if color_is_column else None,
        colormap=None,
        clim=None,
        palette=palette,
        opacity=opacity,
    )
    if text is True:
        labels = [styling.label(v) for v in values.tolist()]
    elif text:
        labels = _texts(table, text, rows)
    else:
        labels = None
    tip_cols = list(tooltip) if tooltip is not None else []
    return IntervalsRecord(
        name=name,
        rows=rows,
        starts=starts,
        ends=ends,
        lanes=lanes_all[rows],
        lane_title=lane or "",
        lane_declared=tables.categories(table, lane) if lane else None,
        color=color_enc,
        text=labels,
        tooltip={state: tables.column(table, state)[rows]}
        | {c: tables.column(table, c)[rows] for c in tip_cols},
        progress=None,
        links=np.zeros((0, 2), dtype=np.int64),
        overlap="overlay",
        height=float(height),
        hover=hover,
        select=select,
        dropped=int(n - len(valid)),
        fade_open=False,
        chained=True,
    )


def _comparable(t: Times) -> np.ndarray:
    if t.raw is not None:
        return t.raw.astype(np.float64) * t.per
    assert t.values is not None
    return t.values


def _ends(starts: Times, following: Times, has_next: np.ndarray, end: Any) -> Times:
    """Each state's end: the time of its lane's next change; for a lane's last state, ``end``
    (one time for all lanes) or none (it runs to the plot's last time)."""
    valid = has_next.copy()
    if starts.values is not None:
        assert following.values is not None
        out = np.where(has_next, following.values, 0.0)
        if end is not None:
            out = np.where(has_next, out, float(end))
            valid[:] = True
        return Times(starts.kind, None, out, valid, starts.timezone, starts.per)
    assert starts.raw is not None
    assert following.raw is not None
    raw = np.where(has_next, following.raw * following.per // starts.per, 0)
    if end is not None:
        e = times(np.asarray([end]) if not isinstance(end, np.ndarray) else end.reshape(1))
        if e.kind != starts.kind or e.raw is None:
            raise TypeError(f"end must be a time of the same kind as the times ({starts.kind})")
        raw = np.where(has_next, raw, int(e.raw[0]) * e.per // starts.per)
        valid[:] = True
    return Times(starts.kind, raw.astype(np.int64), None, valid, starts.timezone, starts.per)
