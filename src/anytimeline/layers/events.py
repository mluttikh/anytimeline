"""The events layer: one mark per event at the moment it happened, without a duration.

``build`` reads a table into an ``EventsRecord`` (everything except the plot's shared time
base and lanes). ``layout`` then sorts the events by lane, time and order, and encodes the
buffers the browser draws.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

import numpy as np

from anytimeline import data as tables
from anytimeline import styling
from anytimeline.codec import Encoded, encode, encode_strings
from anytimeline.layers.common import lexsort, numbers, texts
from anytimeline.parts import STEM_SHAPES, Route
from anytimeline.timebase import TimeBase, Times, times
from anytimeline.types import EventOverlap, StemShape

Labels = Literal["beside", "stems"]
LABELS = get_args(Labels)
OVERLAPS = get_args(EventOverlap)


@dataclass
class EventsRecord:
    """An events layer as read from its table (rows with a time, or an order, only)."""

    name: str
    rows: np.ndarray  # table row of each kept event
    times: Times | None  # None: order only
    order: np.ndarray | None  # float64 tie-break / sequence
    lanes: np.ndarray  # lane value per event (object)
    lane_title: str
    lane_declared: list[Any] | None
    color: styling.Encoding
    symbol: styling.Encoding
    size: styling.Encoding
    text: list[str] | None
    tooltip: dict[str, np.ndarray]
    route: Route | None
    groups: np.ndarray | None
    overlap: EventOverlap
    importance: np.ndarray | None
    labels: Labels
    stem_shape: StemShape
    label_width: float | None
    hover: bool
    select: bool
    dropped: int
    perm: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    lane_groups: np.ndarray | None = None  # each row's group (group=), or None
    lane_group_declared: list[Any] | None = None
    """Event index in the browser (sorted) → index into ``rows``; set by ``layout``."""

    @property
    def time_columns(self) -> list[Times]:
        return [self.times] if self.times is not None else []


def build(
    data: Any,
    *,
    name: str,
    time: str | None,
    lane: str | None,
    order: str | None,
    color: str | None,
    colormap: str | Sequence[str] | None,
    clim: Any,
    palette: Mapping[Any, str] | Sequence[str] | None,
    opacity: float,
    symbol: str | None,
    symbols: Mapping[Any, str] | Sequence[str] | None,
    size: float | str | None,
    size_range: tuple[float, float],
    text: str | None,
    tooltip: Sequence[str] | None,
    route: Route | str | None,
    overlap: EventOverlap,
    labels: Labels = "beside",
    stem_shape: StemShape = "straight",
    label_width: float | None = None,
    importance: str | None,
    time_unit: str | None,
    hover: bool,
    select: bool,
) -> EventsRecord:
    """Read an events layer from a table."""
    if time is None and order is None:
        raise ValueError("pass time= (a column of datetimes, durations or numbers) or order=")
    if overlap not in OVERLAPS:
        raise ValueError(f"overlap must be one of {OVERLAPS}, got {overlap!r}")
    if labels not in LABELS:
        raise ValueError(f"labels must be one of {LABELS}, got {labels!r}")
    if stem_shape not in STEM_SHAPES:
        raise ValueError(f"stem_shape must be one of {STEM_SHAPES}, got {stem_shape!r}")
    if label_width is not None and not label_width >= 0:
        raise ValueError(f"label_width is a width in pixels (0: no limit), got {label_width!r}")
    if labels == "stems" and text is None:
        raise ValueError('labels="stems" places the events\' text: pass text= as well')
    table = tables.frame(data)
    names = tables.column_names(table)
    route_ = Route.of(route)

    def col(arg: str | None) -> np.ndarray | None:
        return tables.column(table, arg) if arg is not None else None

    n = len(tables.column(table, names[0])) if names else 0
    keep = np.ones(n, dtype=bool)
    t: Times | None = None
    if time is not None:
        t = times(
            tables.column(table, time),
            timezone=tables.time_zone(table, time),
            unit=time_unit,
            column=time,
        )
        keep &= t.valid
    order_values = None
    if order is not None:
        order_values = numbers(tables.column(table, order), order)
        keep &= np.isfinite(order_values)
    rows = np.flatnonzero(keep)
    if t is not None:
        t = t.take(rows)

    def pick(arr: np.ndarray | None) -> np.ndarray | None:
        return arr[rows] if arr is not None else None

    lane_values = pick(col(lane))
    if lane_values is None:
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
        pick(col(color)) if color_is_column else None,
        solid=None if color_is_column else color,
        title=color if color_is_column else "",
        declared=tables.categories(table, color) if color_is_column and color else None,
        colormap=colormap,
        clim=clim,
        palette=palette,
        opacity=opacity,
    )
    symbol_is_column = symbol is not None and symbol in names
    symbol_enc = styling.symbols(
        pick(col(symbol)) if symbol_is_column else None,
        solid=symbol if (symbol is not None and not symbol_is_column) else "circle",
        title=symbol or "",
        declared=tables.categories(table, symbol) if symbol_is_column and symbol else None,
        mapping=symbols,
    )
    if isinstance(size, str):
        size_enc = styling.sizes(
            numbers(pick(col(size)), size),  # ty: ignore[invalid-argument-type]
            solid=styling.DEFAULT_SIZE,
            title=size,
            size_range=size_range,
        )
    else:
        size_enc = styling.sizes(
            None, solid=float(size) if size is not None else styling.DEFAULT_SIZE, title=""
        )

    text_values = texts(table, text, rows) if text is not None else None
    tip_cols = list(tooltip) if tooltip is not None else []
    tables.check(table, tip_cols)
    tips = {c: tables.column(table, c)[rows] for c in tip_cols}
    groups = None
    if route_ is not None:
        groups = pick(col(route_.group))
    imp = pick(col(importance))
    return EventsRecord(
        name=name,
        rows=rows,
        times=t,
        order=order_values[rows] if order_values is not None else None,
        lanes=lane_values,
        lane_title=lane or "",
        lane_declared=tables.categories(table, lane) if lane else None,
        color=color_enc,
        symbol=symbol_enc,
        size=size_enc,
        text=text_values,
        tooltip=tips,
        route=route_,
        groups=groups,
        overlap=overlap,
        labels=labels,
        stem_shape=stem_shape,
        label_width=label_width,
        importance=numbers(imp, importance or "") if imp is not None else None,
        hover=hover,
        select=select,
        dropped=int(n - len(rows)),
    )


@dataclass
class Sorted:
    """An events layer's marks in the browser's order (by lane, time and order), kept for
    the windows of a layer sent as levels."""

    primary: np.ndarray  # ticks, or the order without times
    order: np.ndarray
    lane: np.ndarray
    rgba: np.ndarray | None
    symbol: np.ndarray | None
    size: np.ndarray | None
    text: list[str] | None
    importance: np.ndarray | None
    groups: np.ndarray | None  # route=: each mark's group


@dataclass
class Layout:
    """An events layer laid out on the plot's time base and lanes: its spec and buffers."""

    spec: dict[str, Any]
    buffers: list[Encoded]
    lo: np.ndarray  # sorted: the events' ticks (or order, without times)
    hi: np.ndarray  # the same (an event has no duration)
    lanes: np.ndarray
    instants: list[tuple[np.ndarray, np.ndarray]]  # (ticks, tie-break) for the order
    marks: Sorted
    n_lanes: int


def layout(
    rec: EventsRecord,
    base: TimeBase | None,
    lane_index: Mapping[Any, int],
    *,
    levelled: bool = False,
) -> Layout:
    """Sort the events by lane, time and order, and encode their buffers (``levelled``: none;
    the plot sends levels, and the events in windows)."""
    n = len(rec.rows)
    ticks = base.ticks(rec.times) if (base is not None and rec.times is not None) else None
    order = rec.order if rec.order is not None else np.zeros(n)
    lane = np.array([lane_index[v] for v in rec.lanes.tolist()], dtype=np.uint32)
    primary = ticks if ticks is not None else order
    perm = lexsort((order, primary, lane))
    rec.perm = perm
    c, s, z = rec.color, rec.symbol, rec.size
    marks = Sorted(
        primary=primary[perm],
        order=order[perm],
        lane=lane[perm],
        rgba=c.values[perm] if c.values is not None else None,
        symbol=s.values[perm] if s.values is not None else None,
        size=z.values[perm] if z.values is not None else None,
        text=[rec.text[i] for i in perm] if rec.text else None,
        importance=rec.importance[perm] if rec.importance is not None else None,
        groups=rec.groups[perm] if rec.route is not None and rec.groups is not None else None,
    )
    n_lanes = max(lane_index.values(), default=-1) + 1
    rows = np.zeros(0, dtype=np.int64) if levelled else None
    spec, buffers = encode_marks(rec, marks, n_lanes, rows, has_time=ticks is not None)
    return Layout(
        spec,
        buffers,
        marks.primary,
        marks.primary,
        marks.lane,
        [(marks.primary, marks.order)],
        marks,
        n_lanes,
    )


def encode_marks(
    rec: EventsRecord,
    marks: Sorted,
    n_lanes: int,
    rows: np.ndarray | None = None,
    *,
    has_time: bool,
) -> tuple[dict[str, Any], list[Encoded]]:
    """The spec and buffers of the layer's events, or of some of them (``rows``: indices into
    ``marks``, in order; a window). The rank comes from the plot's order."""
    buffers: list[Encoded] = []

    def put(enc: Encoded) -> dict[str, Any]:
        buffers.append(enc)
        return enc.descriptor

    def take(values: Any) -> Any:
        if values is None or rows is None:
            return values
        if isinstance(values, list):
            return [values[i] for i in rows.tolist()]
        return values[rows]

    primary, order, lane = take(marks.primary), take(marks.order), take(marks.lane)
    starts = np.searchsorted(lane, np.arange(n_lanes + 1), side="left").astype(np.uint32)
    spec: dict[str, Any] = {
        "type": "events",
        "name": rec.name,
        "count": len(primary),
        "time": put(encode(primary, "float64")),
        "lane": put(encode(lane, "uint32")),
        "lane_starts": put(encode(starts, "uint32")),
        "overlap": rec.overlap,
        "labels": rec.labels,
        "stem_shape": rec.stem_shape,
        "label_width": rec.label_width,
        "hover": rec.hover,
        "select": rec.select,
        "dropped": rec.dropped,
        "has_time": has_time,
    }
    c, s, z = rec.color, rec.symbol, rec.size
    rgba, symbol, size = take(marks.rgba), take(marks.symbol), take(marks.size)
    spec["color"] = {
        "rgba": put(encode(rgba, "uint8", components=4)) if rgba is not None else None,
        "solid": c.value,
        "alpha": c.extra.get("alpha", 255),
        "legend": c.legend,
    }
    spec["symbol"] = {
        "values": put(encode(symbol, "uint8")) if symbol is not None else None,
        "value": s.value,
        "names": list(styling.SYMBOLS),
        "legend": s.legend,
    }
    spec["size"] = {
        "values": put(encode(size, "float32")) if size is not None else None,
        "value": z.value,
        "legend": z.legend,
    }
    text = take(marks.text)
    spec["text"] = put(encode_strings(text)) if rec.text and text is not None else None
    imp = take(marks.importance)
    spec["importance"] = put(encode(imp, "float32")) if imp is not None else None
    spec["tooltip"] = list(rec.tooltip)
    spec["route"] = None
    groups = take(marks.groups)
    if rec.route is not None and groups is not None:
        segments = _segments(groups, primary, order)
        spec["route"] = {
            "segments": put(encode(segments, "uint32", components=2)),
            "count": len(segments),
            "color": rec.route.color,
            "width": rec.route.width,
        }
    return spec, buffers


def _segments(groups: np.ndarray, primary: np.ndarray, order: np.ndarray) -> np.ndarray:
    """Pairs of event indices (sorted space) joining each group's events in time order."""
    keep = ~tables.is_missing(groups)
    idx = np.flatnonzero(keep)
    if len(idx) < 2:
        return np.zeros((0, 2), dtype=np.uint32)
    _, codes = np.unique(groups[idx].astype(str), return_inverse=True)
    seq = idx[np.lexsort((idx, order[idx], primary[idx], codes))]
    code_s = codes[np.lexsort((idx, order[idx], primary[idx], codes))]
    same = code_s[1:] == code_s[:-1]
    return np.stack([seq[:-1][same], seq[1:][same]], axis=1).astype(np.uint32)
