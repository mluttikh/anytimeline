"""The intervals layer: a bar per row from its start to its end, on lanes (Gantt charts,
schedules, spans).

``build`` reads a table into an ``IntervalsRecord``; ``layout`` sorts the bars by lane and
start, packs overlapping bars of a lane into sub-rows, and encodes the buffers the browser
draws. A bar whose start equals its end is a milestone (drawn as a diamond); a bar without an
end is open (it runs to the end of the plot).
"""

from __future__ import annotations

import heapq
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, get_args

import numpy as np

from anytimeline import data as tables
from anytimeline import styling
from anytimeline import tree as trees
from anytimeline.codec import Encoded, encode, encode_strings
from anytimeline.layers.common import lexsort, numbers, texts
from anytimeline.timebase import UNITS, TimeBase, Times, times
from anytimeline.types import BarOverlap

OVERLAPS = get_args(BarOverlap)

KIND_MILESTONE = 1
KIND_OPEN = 2
KIND_MERGED = 3  # short bars merged (a level's)


@dataclass
class IntervalsRecord:
    """An intervals layer as read from its table (rows with a start only)."""

    name: str
    rows: np.ndarray
    starts: Times
    ends: Times  # missing where a bar is open
    lanes: np.ndarray
    lane_title: str
    lane_declared: list[Any] | None
    color: styling.Encoding
    text: list[str] | None
    tooltip: dict[str, np.ndarray]
    progress: np.ndarray | None
    links: np.ndarray  # (k, 2) pairs of positions in ``rows``: from → to
    overlap: BarOverlap
    height: float
    hover: bool
    select: bool
    dropped: int
    tree: trees.Tree | None = None
    expand: trees.Expand = "auto"
    critical: bool = False
    durations: bool = False
    fade_open: bool = True  # an open bar fades out at its end (states: it does not)
    chained: bool = False  # states: each bar ends where its lane's next one starts
    states: list[str] | None = None  # states: each bar's state, as text (for the tooltip)
    state_title: str = ""
    perm: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    lane_groups: np.ndarray | None = None  # each row's group (group=), or None
    lane_group_declared: list[Any] | None = None

    @property
    def time_columns(self) -> list[Times]:
        return [self.starts, self.ends]


def build(
    data: Any,
    *,
    name: str,
    start: str,
    end: str | None,
    duration: str | None,
    lane: str | None,
    id: str | None,
    depends: str | None,
    color: str | None,
    colormap: str | Sequence[str] | None,
    clim: Any,
    palette: Mapping[Any, str] | Sequence[str] | None,
    opacity: float,
    text: str | None,
    tooltip: Sequence[str] | None,
    progress: str | None,
    overlap: BarOverlap,
    height: float,
    time_unit: str | None,
    duration_unit: str | None,
    hover: bool,
    select: bool,
    parent: str | None = None,
    label: str | None = None,
    expand: trees.Expand = "auto",
    critical_path: bool = False,
    durations: bool = False,
) -> IntervalsRecord:
    """Read an intervals layer from a table."""
    if parent is not None and lane is not None:
        raise ValueError("parent= gives each bar its own lane (under its parent): leave out lane=")
    if parent is not None and id is None:
        raise ValueError("parent= needs id=: the column that names each bar")
    if critical_path and parent is None:
        raise ValueError("critical_path= needs parent=: the path runs through a tree of bars")
    if (end is None) == (duration is None):
        raise ValueError("pass end= (a column of times) or duration= (a column of durations)")
    if overlap not in OVERLAPS:
        raise ValueError(f"overlap must be one of {OVERLAPS}, got {overlap!r}")
    if not 0 < height <= 1:
        raise ValueError(f"height is a fraction of the lane, above 0 and at most 1; got {height}")
    table = tables.frame(data)
    names = tables.column_names(table)
    n = len(tables.column(table, names[0])) if names else 0

    s = times(
        tables.column(table, start),
        timezone=tables.time_zone(table, start),
        unit=time_unit,
        column=start,
    )
    if end is not None:
        e = times(
            tables.column(table, end),
            timezone=tables.time_zone(table, end),
            unit=time_unit,
            column=end,
        )
        if e.kind == "duration" and s.kind == "datetime":
            raise TypeError(
                f"end column {end!r} holds durations, not times: pass it as "
                f"duration={end!r} (with end=None)"
            )
        if e.kind != s.kind:
            raise TypeError(f"start and end must be of one kind, got {s.kind} and {e.kind}")
    else:
        assert duration is not None
        e = _add(s, tables.column(table, duration), duration, duration_unit)
    keep = s.valid.copy()
    rows = np.flatnonzero(keep)
    s, e = s.take(rows), e.take(rows)
    if s.raw is not None and e.raw is not None:
        backwards = e.valid & (_as_ns(e) < _as_ns(s))
    else:
        assert s.values is not None
        assert e.values is not None
        backwards = e.valid & (e.values < s.values)
    if backwards.any():
        first = int(rows[np.flatnonzero(backwards)[0]])
        raise ValueError(
            f"{int(backwards.sum())} rows end before they start (the first is row {first}); "
            "check the start and end columns"
        )

    def col(arg: str | None) -> np.ndarray | None:
        return tables.column(table, arg)[rows] if arg is not None else None

    tree = None
    lane_values = col(lane)
    if parent is not None:
        assert id is not None
        tables.check(table, [id, parent] + ([label] if label else []))
        ids = col(id)
        assert ids is not None
        lane_values = ids.astype(object)
        if tables.is_missing(lane_values).any():
            raise ValueError(f"every bar of a tree needs an id, but {id!r} has missing values")
        key = _as_ns(s) if s.raw is not None else s.values
        parents = col(parent)
        shown = col(label) if label is not None else lane_values
        assert key is not None
        assert parents is not None
        assert shown is not None
        tree = trees.build(lane_values, parents, key, [_label(v) for v in shown], id)
    elif lane_values is None:
        lane_values = np.full(len(rows), name, dtype=object)
    else:
        lane_values = lane_values.astype(object)
        lane_values[tables.is_missing(lane_values)] = "(missing)"

    color_is_column = color is not None and color in names
    if color is not None and not color_is_column and not styling.is_color(color):
        raise tables.NotFoundError(
            f"color={color!r} is neither a column nor a colour; columns: {names}"
        )
    color_enc = styling.colors(
        col(color) if color_is_column else None,
        solid=None if color_is_column else color,
        title=color if color_is_column else "",
        declared=tables.categories(table, color) if color_is_column and color else None,
        colormap=colormap,
        clim=clim,
        palette=palette,
        opacity=opacity,
    )
    prog = None
    if progress is not None:
        values = numbers(col(progress), progress)  # ty: ignore[invalid-argument-type]
        prog = np.where(np.isfinite(values), np.clip(values, 0, 1), -1.0)
    tip_cols = list(tooltip) if tooltip is not None else []
    tables.check(table, tip_cols)
    links = np.zeros((0, 2), dtype=np.int64)
    if depends is not None:
        ids = col(id) if id is not None else lane_values
        links = _links(ids, col(depends), id or lane or "lane")  # ty: ignore[invalid-argument-type]
    return IntervalsRecord(
        name=name,
        rows=rows,
        starts=s,
        ends=e,
        lanes=lane_values,
        lane_title=(label or id or "") if tree is not None else (lane or ""),
        lane_declared=tables.categories(table, lane) if lane else None,
        color=color_enc,
        text=texts(table, text, rows) if text is not None else None,
        tooltip={c: tables.column(table, c)[rows] for c in tip_cols},
        progress=prog,
        links=links,
        overlap=overlap,
        height=float(height),
        hover=hover,
        select=select,
        dropped=int(n - len(rows)),
        tree=tree,
        expand=expand,
        critical=critical_path,
        durations=durations,
    )


def _label(value: Any) -> str:
    return (
        "(missing)"
        if value is None or (isinstance(value, float) and value != value)
        else styling.label(value)
    )


def _as_ns(t: Times) -> np.ndarray:
    """Comparable values of a datetime/duration column (its raw ticks in ns, as float)."""
    assert t.raw is not None
    return t.raw.astype(np.float64) * t.per


def _add(start: Times, values: np.ndarray, name: str, unit: str | None) -> Times:
    """The ends of bars: their starts plus a duration column (durations, or numbers in
    ``unit``; numbers in the start's own units when the starts are plain numbers)."""
    if start.kind == "number":
        assert start.values is not None
        d = numbers(values, name)
        valid = start.valid & np.isfinite(d)
        return Times("number", None, np.where(valid, start.values + np.nan_to_num(d), 0.0), valid)
    numeric = values.dtype.kind in "iuf"
    if numeric and unit is None:
        raise ValueError(
            f"duration column {name!r} holds numbers: say what one is with duration_unit= "
            '("d", "h", "min", "s", "ms", "us" or "ns")'
        )
    d = times(values, unit=unit if numeric else None)
    if d.kind != "duration" or d.raw is None:
        raise TypeError(f"duration column {name!r} must hold durations or numbers, got {d.kind}")
    assert start.raw is not None
    per = start.per
    step = np.round(d.raw.astype(np.float64) * d.per / per).astype(np.int64)
    valid = start.valid & d.valid
    raw = np.where(valid, start.raw + step, 0)
    return Times(start.kind, raw, None, valid, start.timezone, per)


def _links(ids: np.ndarray, depends: np.ndarray, id_name: str) -> np.ndarray:
    """Pairs (predecessor, successor) of positions, from each row's list of predecessor ids."""
    index: dict[Any, int] = {}
    for i, v in enumerate(ids.tolist()):
        if v in index:
            raise ValueError(
                f"dependencies need a unique id per bar, but {v!r} is in {id_name!r} twice; "
                "pass id= with a column of unique names"
            )
        index[v] = i
    pairs: list[tuple[int, int]] = []
    unknown: list[Any] = []
    for j, v in enumerate(depends.tolist()):
        for before in _ids_in(v, index):
            if before in index:
                pairs.append((index[before], j))
            else:
                unknown.append(before)
    if unknown:
        raise ValueError(
            f"depends names bars that are not there: {sorted({str(u) for u in unknown})[:5]}"
        )
    return np.array(pairs, dtype=np.int64).reshape(-1, 2)


def _ids_in(value: Any, index: Mapping[Any, int]) -> list[Any]:
    """The ids in one cell of a depends column: none, one, a list, or "a, b" text."""
    if value is None or (isinstance(value, float) and value != value):
        return []
    if isinstance(value, list | tuple | set | np.ndarray):
        return [v for v in value if v is not None]
    if isinstance(value, str) and value not in index and "," in value:
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, str) and not value.strip():
        return []
    return [value]


@dataclass
class Bars:
    """An intervals layer's bars in the browser's order (by lane, start and end), kept for the
    levels and windows of a layer sent as levels."""

    lo: np.ndarray  # start ticks
    hi: np.ndarray  # end ticks (open bars: the plot's last time)
    lane: np.ndarray
    lane_starts: np.ndarray
    row: np.ndarray  # sub-row, and the number of sub-rows of the bar's lane
    rows: np.ndarray
    kind: np.ndarray
    rgba: np.ndarray | None
    progress: np.ndarray | None
    text: list[str] | None
    states: list[str] | None
    links: np.ndarray  # (m, 2): pairs of bars
    critical: np.ndarray | None  # (m, 3): bar, from, to (instants: 2 × bar, + 1 for its end)


@dataclass
class Merged:
    """Short bars merged into one bar per lane and bin (a level's), as tall as the lane: the
    extent of its bars in time and in the order, how many it holds, how much of the lane over
    that extent they fill, and its longest bar (whose colour and state it takes)."""

    lo: np.ndarray
    hi: np.ndarray
    rank: np.ndarray  # (g, 2)
    lane: np.ndarray
    row: np.ndarray
    rows: np.ndarray
    n: np.ndarray
    cover: np.ndarray  # 0 .. 1
    longest: np.ndarray  # a bar's index

    def __len__(self) -> int:
        return len(self.n)


@dataclass
class Layout:
    """An intervals layer laid out on the plot's time base and lanes."""

    spec: dict[str, Any]
    buffers: list[Encoded]
    lo: np.ndarray  # sorted: start ticks
    hi: np.ndarray  # end ticks (open bars: the plot's last time)
    lanes: np.ndarray
    instants: list[tuple[np.ndarray, np.ndarray]]  # the starts and the ends, for the order
    following: np.ndarray | None = None  # chained: the next bar of the same lane, or -1
    bars: Bars | None = None


def layout(
    rec: IntervalsRecord,
    base: TimeBase | None,
    lane_index: Mapping[Any, int],
    last: float,
    *,
    levelled: bool = False,
) -> Layout:
    """Sort the bars by lane, start and end; pack each lane; encode the buffers
    (``levelled``: no bars in the spec; the plot sends levels, and bars in windows)."""
    assert base is not None
    n = len(rec.rows)
    lo = base.ticks(rec.starts)
    hi = np.where(rec.ends.valid, base.ticks(rec.ends), np.maximum(last, lo))
    lane = np.array([lane_index[v] for v in rec.lanes.tolist()], dtype=np.uint32)
    perm = lexsort((hi, lo, lane))
    rec.perm = perm
    lo_s, hi_s, lane_s = lo[perm], hi[perm], lane[perm]
    open_s = ~rec.ends.valid[perm]
    kind = np.where(open_s, KIND_OPEN, np.where(hi_s == lo_s, KIND_MILESTONE, 0)).astype(np.uint8)
    n_lanes = max(lane_index.values(), default=-1) + 1
    starts = np.searchsorted(lane_s, np.arange(n_lanes + 1), side="left")
    row, rows = _pack(lo_s, hi_s, starts, rec.overlap == "pack")

    c = rec.color
    inverse = np.empty(n, dtype=np.int64)
    inverse[perm] = np.arange(n)
    links = inverse[rec.links] if len(rec.links) else np.zeros((0, 2), dtype=np.int64)
    critical = None
    if rec.critical and rec.tree is not None and n:
        tree = rec.tree
        # in the tree's order (its lanes may be spread over groups), then as sorted bars
        at = inverse[tree.order]  # tree lane k → its bar
        found = trees.critical_path(lo[tree.order], hi[tree.order], tree.depth, tree.size)
        critical = (
            np.column_stack(
                [
                    at[found[:, 0]],
                    2 * at[found[:, 1] // 2] + found[:, 1] % 2,
                    2 * at[found[:, 2] // 2] + found[:, 2] % 2,
                ]
            )
            if len(found)
            else found
        )
    bars = Bars(
        lo=lo_s,
        hi=hi_s,
        lane=lane_s,
        lane_starts=starts,
        row=row,
        rows=rows,
        kind=kind,
        rgba=c.values[perm] if c.values is not None else None,
        progress=rec.progress[perm] if rec.progress is not None else None,
        text=[rec.text[i] for i in perm] if rec.text else None,
        states=[rec.states[i] for i in perm] if rec.states is not None else None,
        links=links,
        critical=critical,
    )
    rows_sent = np.zeros(0, dtype=np.int64) if levelled else None
    spec, buffers = encode_bars(rec, bars, rows_sent, unit_ns=UNITS.get(base.unit, 1))
    zeros = np.zeros(n)
    if rec.chained:
        # a change takes one place in the order; a bar's end is its lane's next change
        following = np.full(n, -1, dtype=np.int64)
        same = lane_s[1:] == lane_s[:-1]
        following[:-1][same] = np.arange(1, n)[same]
        return Layout(spec, buffers, lo_s, hi_s, lane_s, [(lo_s, zeros)], following, bars)
    return Layout(spec, buffers, lo_s, hi_s, lane_s, [(lo_s, zeros), (hi_s, zeros + 1)], bars=bars)


def encode_bars(
    rec: IntervalsRecord,
    bars: Bars,
    rows: np.ndarray | None = None,
    *,
    unit_ns: int,
    merged: Merged | None = None,
    rank: np.ndarray | None = None,
) -> tuple[dict[str, Any], list[Encoded]]:
    """The spec and buffers of the layer's bars, or of some of them (``rows``: indices into
    ``bars``, in order: a level's or a window's) and short ones ``merged``, with each bar's
    ``index`` (merged ones: 0xFFFFFFFF) and how many bars it holds (``n``), and, with ``rank``
    (every bar's place in the order), the order of each bar's start and end. Dependencies and
    the critical path keep the parts between bars sent."""
    buffers: list[Encoded] = []

    def put(enc: Encoded) -> dict[str, Any]:
        buffers.append(enc)
        return enc.descriptor

    b = bars
    full = rows is None
    if rows is None:
        rows = np.arange(len(b.lo))
    g = merged if merged is not None else _no_merged()
    m = len(rows)
    lo = np.concatenate([b.lo[rows], g.lo])
    hi = np.concatenate([b.hi[rows], g.hi])
    lane = np.concatenate([b.lane[rows], g.lane]).astype(np.uint32)
    # merged bars go between the others by lane, start and end
    order = np.arange(m) if full else np.lexsort((np.arange(len(lo)), hi, lo, lane))
    lo, hi, lane = lo[order], hi[order], lane[order]
    real = order < m  # (else merged bar order - m)
    which = np.where(real, order, 0)
    mine = rows[which] if len(rows) else which  # each real bar's index among the layer's
    merged_at = np.where(real, 0, order - m)

    def pick(values: np.ndarray, merged_values: np.ndarray) -> np.ndarray:
        out = values[mine]
        if len(g):
            out[~real] = merged_values[merged_at[~real]]
        return out

    n_lanes = len(b.lane_starts) - 1
    starts = np.searchsorted(lane, np.arange(n_lanes + 1), side="left")
    kind = pick(b.kind, np.full(len(g), KIND_MERGED, np.uint8))
    c = rec.color
    rgba = None
    if b.rgba is not None:
        rgba = pick(b.rgba, b.rgba[g.longest] if len(g) else np.zeros((0, 4), np.uint8))
    # (positions in the bars sent of the layer's bars sent; -1: not sent)
    pos = np.full(len(b.lo), -1, dtype=np.int64)
    pos[mine[real]] = np.flatnonzero(real)
    links = b.links
    if not full and len(links):
        links = pos[links]
        links = links[(links >= 0).all(axis=1)]
    critical = b.critical
    if not full and critical is not None and len(critical):
        bar, a, z = pos[critical[:, 0]], pos[critical[:, 1] // 2], pos[critical[:, 2] // 2]
        keep = (bar >= 0) & (a >= 0) & (z >= 0)
        critical = np.column_stack([bar, 2 * a + critical[:, 1] % 2, 2 * z + critical[:, 2] % 2])[
            keep
        ]
    spec: dict[str, Any] = {
        "type": "intervals",
        "name": rec.name,
        "count": len(lo),
        "start": put(encode(lo, "float64")),
        "end": put(encode(hi, "float64")),
        "lane": put(encode(lane, "uint32")),
        "lane_starts": put(encode(starts.astype(np.uint32), "uint32")),
        "row": put(encode(pick(b.row, g.row), "float32")),
        "rows": put(encode(pick(b.rows, g.rows), "float32")),
        "kind": put(encode(kind, "uint8")),
        "height": rec.height,
        "overlap": rec.overlap,
        "hover": rec.hover,
        "select": rec.select,
        "dropped": rec.dropped,
        "color": {
            "rgba": put(encode(rgba, "uint8", components=4)) if rgba is not None else None,
            "solid": c.value,
            "alpha": c.extra.get("alpha", 255),
            "legend": c.legend,
        },
        "progress": put(encode(pick(b.progress, np.full(len(g), -1, np.float32)), "float32"))
        if b.progress is not None
        else None,
        "text": put(encode_strings(_pick_list(b.text, mine, real))) if b.text else None,
        "tooltip": list(rec.tooltip),
        "links": {"pairs": put(encode(links, "uint32", components=2)), "count": len(links)}
        if len(links)
        else None,
        "unit_ns": unit_ns,
        "durations": rec.durations,
        "fade_open": rec.fade_open,
        "states": {
            "values": put(encode_strings(_pick_list(b.states, mine, real, g.longest, merged_at))),
            "title": rec.state_title,
        }
        if b.states is not None
        else None,
        "critical": {
            "segments": put(encode(critical, "uint32", components=3)),
            "count": len(critical),
        }
        if critical is not None and len(critical)
        else None,
    }
    if not full:
        index = np.where(real, mine, 0xFFFFFFFF)
        n = np.where(real, 1, g.n[merged_at] if len(g) else 1)
        spec["index"] = put(encode(index, "uint32"))
        spec["n"] = put(encode(n, "uint32"))
        if len(g):
            # a merged bar is as opaque as its bars cover it (at least a little)
            alpha = np.where(real, 255, np.round(255 * np.clip(g.cover[merged_at], 0.3, 1.0)))
            spec["alpha"] = put(encode(alpha.astype(np.uint8), "uint8"))
        if rank is not None:
            r = rank[mine]
            if len(g):
                r[~real] = g.rank[merged_at[~real]]
            wide = len(rank) and float(rank.max()) >= 2**24
            spec["rank"] = put(encode(r, "float64" if wide else "float32", components=2))
    return spec, buffers


def _pick_list(
    values: list[str] | None,
    mine: np.ndarray,
    real: np.ndarray,
    longest: np.ndarray | None = None,
    merged_at: np.ndarray | None = None,
) -> list[str]:
    """``values`` of the bars sent (merged ones: their longest bar's, or "")."""
    assert values is not None
    out = []
    for i, r in zip(mine.tolist(), real.tolist(), strict=True):
        out.append(values[i] if r else "")
    if longest is not None and merged_at is not None and len(longest):
        for j in np.flatnonzero(~real).tolist():
            out[j] = values[int(longest[merged_at[j]])]
    return out


def _no_merged() -> Merged:
    z = np.zeros(0)
    i = np.zeros(0, dtype=np.int64)
    return Merged(z, z, np.zeros((0, 2)), i, z, z, i, z, i)


def merge(bars: Bars, rank: np.ndarray, x_lo: np.ndarray, x_hi: np.ndarray,
          rows: np.ndarray, width: float, x0: float) -> tuple[np.ndarray, Merged]:  # fmt: skip
    """A level of the bars ``rows`` (in order; on a scale: their ends ``x_lo``, ``x_hi``;
    bins of ``width`` from ``x0``): those at least ``width`` long, and the others merged per
    lane and bin of their start."""
    dur = x_hi[rows] - x_lo[rows]
    long = rows[dur >= width]
    members = rows[dur < width]
    if not len(members):
        return long, _no_merged()
    j = np.floor((x_lo[members] - x0) / width).astype(np.int64)
    lane = bars.lane[members]
    brk = np.ones(len(members), dtype=bool)
    brk[1:] = (lane[1:] != lane[:-1]) | (j[1:] != j[:-1])
    at = np.flatnonzero(brk)
    d = x_hi[members] - x_lo[members]
    seg = np.cumsum(brk) - 1
    longest_d = np.maximum.reduceat(d, at)
    first = np.minimum.reduceat(np.where(d == longest_d[seg], np.arange(len(d)), len(d)), at)
    xa = np.minimum.reduceat(x_lo[members], at)
    xb = np.maximum.reduceat(x_hi[members], at)
    span = (xb - xa) * bars.rows[members][at]  # (all of the lane's sub-rows)
    total = np.add.reduceat(d, at)
    cover = np.where(span > 0, np.minimum(total / np.where(span > 0, span, 1), 1.0), 1.0)
    return long, Merged(
        lo=np.minimum.reduceat(bars.lo[members], at),
        hi=np.maximum.reduceat(bars.hi[members], at),
        rank=np.column_stack(
            [np.minimum.reduceat(rank[members, 0], at), np.maximum.reduceat(rank[members, 1], at)]
        ),
        lane=lane[at],
        row=np.zeros(len(at), dtype=np.float32),
        rows=np.ones(len(at), dtype=np.float32),
        n=np.diff(np.append(at, len(members))),
        cover=cover,
        longest=members[first],
    )


def window_rows(x_lo: np.ndarray, x_hi: np.ndarray, lane_starts: np.ndarray,
                a: float, b: float) -> np.ndarray:  # fmt: skip
    """The bars that reach into ``a`` .. ``b`` (on a scale: their ends), in order."""
    parts = []
    for i0, i1 in zip(lane_starts[:-1].tolist(), lane_starts[1:].tolist(), strict=True):
        if i1 <= i0:
            continue
        longest = float((x_hi[i0:i1] - x_lo[i0:i1]).max())
        j0 = i0 + int(np.searchsorted(x_lo[i0:i1], a - longest, "left"))
        j1 = i0 + int(np.searchsorted(x_lo[i0:i1], b, "right"))
        if j1 > j0:
            idx = np.arange(j0, j1)
            parts.append(idx[x_hi[idx] >= a])
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.int64)


def _pack(
    lo: np.ndarray, hi: np.ndarray, starts: np.ndarray, pack: bool
) -> tuple[np.ndarray, np.ndarray]:
    """Sub-row per bar (bars of a lane that overlap in time go to different rows; the first row
    that is free) and the number of rows of each bar's lane."""
    n = len(lo)
    row = np.zeros(n, dtype=np.float32)
    rows = np.ones(n, dtype=np.float32)
    if not pack:
        return row, rows
    for a, b in zip(starts[:-1].tolist(), starts[1:].tolist(), strict=True):
        if b - a < 2:
            continue
        free: list[int] = []  # rows that are free again, smallest first
        busy: list[tuple[float, int]] = []  # (end, row) of bars still running
        used = 0
        for i in range(a, b):
            while busy and busy[0][0] <= lo[i]:
                heapq.heappush(free, heapq.heappop(busy)[1])
            if free:
                r = heapq.heappop(free)
            else:
                r = used
                used += 1
            row[i] = r
            heapq.heappush(busy, (float(hi[i]), r))
        rows[a:b] = max(used, 1)
    return row, rows
