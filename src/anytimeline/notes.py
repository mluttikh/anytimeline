"""The notes on a plot (``Timeline.notes``: annotations, connections, measures) as the
browser draws them (``_notes``: ticks, places in the order, lane indices), and the measured
times as a table (``Timeline.measured``).

A rule of measures (``MeasureEach``, ``MeasureGaps``, ``MeasureChain``, ``MeasureFrom``) is one
note that makes many: it is worked out here, again each time the notes are sent, so it
follows the data. Its measures share its index (``id``) and have their own ``part``; a chain
and a baseline are a ``group`` the layout keeps together (each with its offset in levels).

An end of a note is an ``Edge`` (a mark's start or end, found where the mark is laid out) or
a time. On the Order scale a time is placed between the instants around it, an edge at its
mark's own place, so a measure from a bar's start to its end spans its own instants. A
sample of a values layer is a mark whose start and end are its time; a measure between two
samples of one layer has the change in value too.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from anytimeline import measuring
from anytimeline.data import NotFoundError
from anytimeline.layers.values import places
from anytimeline.parts import (
    Annotation,
    Connection,
    Edge,
    Measure,
    MeasureChain,
    MeasureEach,
    MeasureFrom,
    MeasureGaps,
    MeasureRule,
    Note,
    ValueAt,
)
from anytimeline.timebase import UNITS, TimeBase

MAX_RULE = 20_000
"""The most measures one rule makes; beyond that the plot would be lines only."""


@dataclass
class Context:
    """What resolving a note needs from the plot as laid out."""

    base: TimeBase | None
    lane_names: Sequence[str]
    order: np.ndarray | None  # every instant's time, in the order
    mark_at: Callable[[str, int], dict[str, Any]]  # ``Timeline._mark_at``
    layer_named: Callable[[str | None], str]  # ``Timeline._layer_named``
    values_layers: Sequence[str] = ()  # the names of the values layers
    # a template of a layer's columns ("{col:%H:%M}") filled in with rows of its table
    row_texts: Callable[[str, np.ndarray, str], list[str]] | None = None
    # the marks of a layer (all, or of some table rows), by their index in the browser:
    # index, x, x2, r, r2, lane, row (``Timeline._marks_in``)
    marks_of: Callable[[str, np.ndarray | None], dict[str, np.ndarray]] | None = None
    # a column of a layer's table, by table row
    column: Callable[[str, str], np.ndarray] | None = None
    # a layer's kind: "events", "intervals", "values", ...
    kind_of: Callable[[str], str] | None = None


def place(ctx: Context, x: float) -> float | None:
    """A time's place on the Order scale: between the instants before and after it (None:
    no order)."""
    if ctx.order is None or not len(ctx.order):
        return None
    return float(np.searchsorted(ctx.order, x, "left")) - 0.5


def ticks(ctx: Context, value: Any) -> float:
    if ctx.base is None:
        raise ValueError("notes at a time need layers with times")
    return ctx.base.to_ticks(value)


def end_of(ctx: Context, end: Any) -> dict[str, Any]:
    """An end: an edge (its mark's time on that side, its place in the order, its lane) or
    a time (no lane, no side)."""
    if isinstance(end, Edge):
        layer = ctx.layer_named(end.layer)
        m = ctx.mark_at(layer, end.row)
        first = end.side == "start"
        out = {
            "x": m["x"] if first else m["x2"],
            "r": m["r"] if first else m["r2"],
            "lane": m["lane"],
            "side": end.side,
            "layer": layer,
            "row": end.row,
            "index": m["index"],
        }
        if "value" in m:  # a sample: its place between the instants, and its value
            at = places(ctx.order, np.asarray([out["x"]]))
            out["r"] = None if at is None else float(at[0])
            out["value"] = m["value"]
        return out
    x = ticks(ctx, end)
    return {"x": x, "r": place(ctx, x), "lane": None, "side": None}


def lane_index(ctx: Context, lane: Any, what: str) -> int | None:
    if lane is None:
        return None
    names = [str(n) for n in ctx.lane_names]
    if str(lane) not in names:
        raise NotFoundError(f"no lane {lane!r} to {what}")
    return names.index(str(lane))


def between(ra: float | None, rb: float | None) -> int | None:
    """How many instants of the order lie strictly between two places (None: no order)."""
    if ra is None or rb is None:
        return None
    lo, hi = min(ra, rb), max(ra, rb)
    return max(0, math.ceil(hi) - math.floor(lo) - 1)


def band(ctx: Context, a: Annotation) -> dict[str, Any]:
    """An annotation: a band from ``x0`` to ``x1`` (``point``: a line at ``x0``), in a lane
    or across all (``lane`` None)."""
    s = end_of(ctx, a.start)
    e = s if a.end is None else end_of(ctx, a.end)
    if e["x"] < s["x"]:
        raise ValueError(f"an annotation ends before it starts: {a.start!r} to {a.end!r}")
    return {
        "x0": s["x"],
        "x1": e["x"],
        "r0": s["r"],
        "r1": e["r"],
        "point": a.end is None,
        "lane": lane_index(ctx, a.lane, "annotate"),
        "text": a.text,
        "color": a.color,
    }


def _browser_end(e: Mapping[str, Any]) -> dict[str, Any]:
    out = {"x": e["x"], "r": e["r"], "lane": e["lane"], "side": e["side"]}
    if "layer" in e:
        out["layer"] = e["layer"]
        out["index"] = e["index"]
    if "value" in e:
        out["value"] = e["value"]
    return out


def arrow(ctx: Context, c: Connection) -> dict[str, Any]:
    """A connection: an arrow from one edge to another."""
    a, b = end_of(ctx, c.a), end_of(ctx, c.b)
    return {"a": _browser_end(a), "b": _browser_end(b), "text": c.text, "color": c.color}


def change(a: Mapping[str, Any], b: Mapping[str, Any]) -> float | None:
    """The change in value from end a to end b: both samples of one values layer (None:
    not, or a gap)."""
    va, vb = a.get("value"), b.get("value")
    if va is None or vb is None or a.get("layer") != b.get("layer"):
        return None
    return vb - va


def measure(ctx: Context, m: Measure) -> dict[str, Any]:
    """A measure: its ends, the time between (``span``, ticks, b − a), the instants between
    (``events``; None without an order) and, between samples, the change in value; and where
    its line goes (``at``: a place, or ``{"value", "layer"}``), its ``level`` (None: the
    first free) and ``nudge`` (pixels), its ``label``, ``ends`` and ``extend``; ``over``
    when it is longer than its ``limit``. The text has ``{a.col}`` and ``{b.col}`` filled
    in (``raw``: as written, when that differs)."""
    a, b = end_of(ctx, m.a), end_of(ctx, m.b)
    text = None if m.text is None else columns_of(ctx, m.text, [a], [b])[0]
    limit = limit_ticks(ctx, m.limit)
    return _shown(ctx, m, a, b, lane_index(ctx, m.lane, "measure in"), text, limit, full=True)


def _shown(
    ctx: Context,
    m: Measure | MeasureRule,
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    lane: int | None,
    text: str | None,
    limit: float | None,
    *,
    full: bool,
) -> dict[str, Any]:
    """A measure as the browser draws it; ``full``: with the keys left at their defaults
    too (a rule's many measures leave them out)."""
    span = b["x"] - a["x"]
    out: dict[str, Any] = {
        "a": _browser_end(a),
        "b": _browser_end(b),
        "span": span,
        "events": between(a["r"], b["r"]),
        "change": change(a, b),
        "lane": lane,
        "text": text,
        "color": m.color,
    }
    look = {
        "at": at_of(ctx, m, a, b),
        "level": m.level,
        "nudge": m.nudge,
        "label": m.label,
        "ends": m.ends,
        "extend": m.extend,
    }
    defaults = {"at": "auto", "level": None, "nudge": 0.0, "label": "auto", "ends": "arrows"}
    out |= {k: v for k, v in look.items() if full or v != defaults.get(k, "mark")}
    if text != m.text:
        out["raw"] = m.text
    if limit is not None and abs(span) > limit:
        out["over"] = True
    return out


def limit_ticks(ctx: Context, value: Any) -> float | None:
    """A duration (``limit=``, ``min=``, ``max=``) in ticks (None: none)."""
    if value is None:
        return None
    base = ctx.base
    if base is None:
        raise ValueError("a duration needs layers with times")
    ns = measuring.duration_ns(value)
    if base.kind == "number":
        if ns is not None:
            raise TypeError(f"a plot of numbers takes a number, not a duration: {value!r}")
        return float(value)
    if ns is None:
        raise TypeError(
            f"a duration on a plot of times is text ('200ms', '1.5 h') or a timedelta, got "
            f"{value!r}"
        )
    return ns / UNITS[base.unit or "ns"]


def columns_of(
    ctx: Context, text: str, a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]]
) -> list[str]:
    """``{a.col}`` and ``{b.col}`` in a measure's text, for each pair of ends: a column of
    the row of an end that is a mark, with Python's format (``{a.start:%H:%M}``); "–" for an
    end that is a time. Each template is filled in once for all the rows of a layer."""
    if not measuring.COLUMN.search(text):
        return [text] * len(a)
    ends = {"a": a, "b": b}
    filled: dict[tuple[str, str], list[str]] = {}
    row_texts = ctx.row_texts

    def texts(end: str, template: str) -> list[str]:
        key = (end, template)
        if key not in filled:
            got = ["–"] * len(ends[end])
            by_layer: dict[str, list[int]] = {}
            for k, e in enumerate(ends[end]):
                if "row" in e and row_texts is not None:
                    by_layer.setdefault(e["layer"], []).append(k)
            for layer, ks in by_layer.items():
                rows = np.asarray([ends[end][k]["row"] for k in ks], dtype=np.int64)
                for k, t in zip(ks, row_texts(layer, rows, template), strict=True):  # ty: ignore[call-non-callable]
                    got[k] = t
            filled[key] = got
        return filled[key]

    return [
        measuring.fill_columns(text, lambda end, template, k=k: texts(end, template)[k])
        for k in range(len(a))
    ]


def at_of(
    ctx: Context, m: Measure | MeasureRule, a: Mapping[str, Any], b: Mapping[str, Any]
) -> Any:
    """Where a measure's line goes: its place, or a value on a values layer (the layer
    named, else that of its ends when they are samples, else the plot's one values layer)."""
    if not isinstance(m.at, ValueAt):
        return m.at
    layer = m.at.layer
    if layer is None:
        layer = next((e["layer"] for e in (a, b) if "value" in e), None)
    if layer is None:
        if len(ctx.values_layers) != 1:
            raise ValueError(
                "atl.value(...) needs a values layer: name it (atl.value(80, layer=...)); "
                f"values layers: {list(ctx.values_layers)}"
            )
        layer = ctx.values_layers[0]
    layer = ctx.layer_named(layer)
    if layer not in ctx.values_layers:
        raise ValueError(f"atl.value(...) is a value on a values layer; {layer!r} is not one")
    return {"value": m.at.value, "layer": layer}


# ---------------------------------------------------------------------- rules


def _edges(layer: str, marks: Mapping[str, np.ndarray], js: np.ndarray, side: str) -> list[dict]:
    """Ends at a side of marks ``js`` of ``marks`` (as ``end_of`` gives an edge)."""
    first = side == "start"
    xs = marks["x" if first else "x2"][js].tolist()
    rs = marks["r" if first else "r2"][js].tolist()
    lanes = marks["lane"][js].tolist()
    rows = marks["row"][js].tolist()
    index = marks["index"][js].tolist()
    return [
        {
            "x": x,
            "r": r,
            "lane": lane,
            "side": side,
            "layer": layer,
            "row": row,
            "index": i,
        }
        for x, r, lane, row, i in zip(xs, rs, lanes, rows, index, strict=True)
    ]


def _marks(ctx: Context, layer: str | None, kinds: tuple[str, ...], what: str) -> tuple:
    if ctx.marks_of is None or ctx.kind_of is None:
        raise ValueError(f"{what} needs a plot with layers")
    name = ctx.layer_named(layer)
    kind = ctx.kind_of(name)
    if kind not in kinds:
        raise ValueError(f"{what} measures {' or '.join(kinds)}; layer {name!r} is {kind}")
    return name, kind


def _each(ctx: Context, rule: MeasureEach) -> tuple[list[dict], list[dict]]:
    layer, _ = _marks(ctx, rule.layer, ("intervals",), "measure_each")
    rows = None if rule.rows is None else np.asarray(rule.rows, dtype=np.int64)
    assert ctx.marks_of is not None
    m = ctx.marks_of(layer, rows)
    js = np.flatnonzero(m["x2"] > m["x"])  # milestones have no length
    js = js[np.argsort(m["row"][js], kind="stable")]
    return _edges(layer, m, js, "start"), _edges(layer, m, js, "end")


def _gaps(ctx: Context, rule: MeasureGaps) -> tuple[list[dict], list[dict]]:
    layer, _ = _marks(ctx, rule.layer, ("events", "intervals"), "measure_gaps")
    assert ctx.marks_of is not None
    m = ctx.marks_of(layer, None)
    if rule.by is None:
        key = m["lane"]
    else:
        assert ctx.column is not None
        values = ctx.column(layer, rule.by)[m["row"]]
        _, key = np.unique(np.asarray([str(v) for v in values], dtype=object), return_inverse=True)
    lo = limit_ticks(ctx, rule.min)
    hi = limit_ticks(ctx, rule.max)
    order = np.lexsort((m["x2"], m["x"], key))
    keys, xs, x2s = key[order].tolist(), m["x"][order].tolist(), m["x2"][order].tolist()
    a: list[int] = []
    b: list[int] = []
    last, reach, who = None, -math.inf, -1
    for p, (k, x, x2) in enumerate(zip(keys, xs, x2s, strict=True)):
        if k != last:
            last, reach, who = k, x2, p
            continue
        gap = x - reach
        if gap > 0 and (lo is None or gap >= lo) and (hi is None or gap <= hi):
            a.append(who)
            b.append(p)
        if x2 >= reach:
            reach, who = x2, p
    ja, jb = order[np.asarray(a, dtype=np.int64)], order[np.asarray(b, dtype=np.int64)]
    return _edges(layer, m, ja, "end"), _edges(layer, m, jb, "start")


def rule_parts(ctx: Context, rule: MeasureRule) -> tuple[list[dict], list[dict], list[int]]:
    """A rule's measures: their ends a and b, and each one's offset in levels in its group
    (-1: no group): a chain's on one level, a baseline's a level apart, the shortest first."""
    if isinstance(rule, MeasureEach):
        a, b = _each(ctx, rule)
        return a, b, [-1] * len(a)
    if isinstance(rule, MeasureGaps):
        a, b = _gaps(ctx, rule)
        return a, b, [-1] * len(a)
    if isinstance(rule, MeasureChain):
        ends = [end_of(ctx, e) for e in rule.through]
        return ends[:-1], ends[1:], [0] * (len(ends) - 1)
    if isinstance(rule, MeasureFrom):
        origin = end_of(ctx, rule.origin)
        to = [end_of(ctx, e) for e in rule.to]
        spans = [abs(e["x"] - origin["x"]) for e in to]
        rank = sorted(range(len(to)), key=lambda k: (spans[k], k))
        offset = [0] * len(to)
        for n, k in enumerate(rank):
            offset[k] = n
        return [origin] * len(to), to, offset
    raise TypeError(f"not a rule of measures: {rule!r}")


def _rule_lane(ctx: Context, rule: MeasureRule, a: list[dict], b: list[dict]) -> int | None:
    """The lane of a chain's or a baseline's measures: the one given, else the upper of all
    its ends' (so they share a row); a rule of marks: each measure's own (None)."""
    if not isinstance(rule, MeasureChain | MeasureFrom):
        return None
    if rule.lane is not None:
        return lane_index(ctx, rule.lane, "measure in")
    lanes = [e["lane"] for e in (*a, *b) if e["lane"] is not None]
    return min(lanes) if lanes else None


def rule(ctx: Context, r: MeasureRule) -> list[dict[str, Any]]:
    """A rule's measures as the browser draws them, each with its ``part`` and, in a chain
    or a baseline, its ``group`` (its offset in levels); at most ``MAX_RULE``."""
    a, b, offset = rule_parts(ctx, r)
    if len(a) > MAX_RULE:
        warnings.warn(
            f"{type(r).__name__} makes {len(a):,} measures; the first {MAX_RULE:,} are drawn "
            "(narrow it: rows=, min=, by=)",
            stacklevel=2,
        )
        a, b, offset = a[:MAX_RULE], b[:MAX_RULE], offset[:MAX_RULE]
    texts = [None] * len(a) if r.text is None else columns_of(ctx, r.text, a, b)
    lane = _rule_lane(ctx, r, a, b)
    limit = limit_ticks(ctx, r.limit)
    kind = type(r).__name__.removeprefix("Measure").lower()
    out = []
    for k, (ea, eb, off, text) in enumerate(zip(a, b, offset, texts, strict=True)):
        d = _shown(ctx, r, ea, eb, lane, text, limit, full=False)
        d["rule"] = kind
        d["part"] = k
        if off >= 0:
            if r.level is None:
                d["group"] = off
            else:
                d["level"] = r.level + off
        out.append(d)
    return out


def payload(ctx: Context, notes: Sequence[Note]) -> dict[str, Any]:
    """``_notes``: the notes that can be drawn, each with its index in ``notes`` (``id``);
    those of lanes, layers and rows the plot no longer has are left out."""
    out: dict[str, list[dict[str, Any]]] = {"bands": [], "arrows": [], "measures": []}
    for i, n in enumerate(notes):
        try:
            if isinstance(n, Annotation):
                out["bands"].append({**band(ctx, n), "id": i})
            elif isinstance(n, Connection):
                out["arrows"].append({**arrow(ctx, n), "id": i})
            elif isinstance(n, MeasureRule):
                out["measures"].extend({**d, "id": i} for d in rule(ctx, n))
            else:
                out["measures"].append({**measure(ctx, n), "id": i})
        except (LookupError, ValueError, TypeError):
            continue
    return {k: v for k, v in out.items() if v}


def check(ctx: Context, note: Note) -> None:
    """Raise what is wrong with a note now (an unknown layer, row or lane, a wrong time)."""
    if isinstance(note, Annotation):
        band(ctx, note)
    elif isinstance(note, Connection):
        arrow(ctx, note)
    elif isinstance(note, MeasureRule):
        a, _, _ = rule_parts(ctx, note)
        if len(a) > MAX_RULE:
            raise ValueError(
                f"{type(note).__name__} makes {len(a):,} measures; at most {MAX_RULE:,} are "
                "drawn: narrow it (rows=, min=, by=)"
            )
        limit_ticks(ctx, note.limit)
        if note.text is not None and a:
            rule(ctx, note)  # its columns exist
    else:
        measure(ctx, note)


# ---------------------------------------------------------------------- the table


def _value(base: TimeBase | None, x: float) -> Any:
    if base is None:
        return x  # order only: a place
    return base.to_value(x)


def table(ctx: Context, notes: Sequence[Note], like: Any) -> Any:
    """The measures as a table of the type ``like`` is (Polars, PyArrow, pandas, or a dict
    of arrays): a row per measure that can be resolved, in the order of ``notes``."""
    rows: list[dict[str, Any]] = []
    for i, n in enumerate(notes):
        if not isinstance(n, Measure | MeasureRule):
            continue
        try:
            if isinstance(n, Measure):
                pairs = [(end_of(ctx, n.a), end_of(ctx, n.b))]
            else:
                a, b, _ = rule_parts(ctx, n)
                pairs = list(zip(a, b, strict=True))
            limit = limit_ticks(ctx, n.limit)
        except (LookupError, ValueError, TypeError):
            continue
        lane = n.lane if isinstance(n, Measure | MeasureChain | MeasureFrom) else None
        for k, (a, b) in enumerate(pairs):
            over = limit is not None and abs(b["x"] - a["x"]) > limit
            rows.append(
                {
                    "note": i,
                    "part": k,
                    "text": n.text,
                    "a": a,
                    "b": b,
                    "m": n,
                    "lane": lane,
                    "over": over,
                }
            )
    base = ctx.base
    cols: dict[str, Any] = {
        "note": np.asarray([r["note"] for r in rows], dtype=np.int64),
        "part": np.asarray([r["part"] for r in rows], dtype=np.int64),
        "text": np.asarray([r["text"] for r in rows], dtype=object),
    }
    for key in ("a", "b"):
        values = [_value(base, r[key]["x"]) for r in rows]
        cols[key] = _times(values, base)
    if base is None or base.kind == "number":
        cols["time"] = cols["b"] - cols["a"]
    else:
        cols["time"] = (cols["b"] - cols["a"]).astype("timedelta64[ns]")
    cols["events"] = np.asarray(
        [-1 if (e := between(r["a"]["r"], r["b"]["r"])) is None else e for r in rows],
        dtype=np.int64,
    )
    nan = float("nan")
    for key in ("a", "b"):
        cols[f"{key}_value"] = np.asarray(
            [nan if (v := r[key].get("value")) is None else v for r in rows], dtype=np.float64
        )
    cols["change"] = np.asarray(
        [nan if (c := change(r["a"], r["b"])) is None else c for r in rows], dtype=np.float64
    )
    for key in ("a", "b"):
        cols[f"{key}_layer"] = np.asarray([r[key].get("layer") for r in rows], dtype=object)
        cols[f"{key}_row"] = np.asarray([r[key].get("row", -1) for r in rows], dtype=np.int64)
        cols[f"{key}_side"] = np.asarray([r[key]["side"] for r in rows], dtype=object)
    cols["at"] = np.asarray(
        [r["m"].at if isinstance(r["m"].at, str) else "value" for r in rows], dtype=object
    )
    cols["lane"] = np.asarray(
        [None if r["lane"] is None else str(r["lane"]) for r in rows], dtype=object
    )
    cols["level"] = np.asarray(
        [-1 if r["m"].level is None else r["m"].level for r in rows], dtype=np.int64
    )
    cols["over"] = np.asarray([r["over"] for r in rows], dtype=bool)
    if isinstance(like, Mapping):
        return cols
    import narwhals as nw

    native = nw.from_native(like, eager_only=True)
    out = nw.from_dict(
        {k: v.tolist() if v.dtype == object else v for k, v in cols.items()},
        backend=nw.get_native_namespace(native),
    )
    zone = base.timezone if base is not None and base.kind == "datetime" else "UTC"
    if base is not None and base.kind == "datetime" and zone != "UTC":
        out = out.with_columns(
            nw.col(c).dt.replace_time_zone("UTC").dt.convert_time_zone(zone) for c in ("a", "b")
        )
    return out.to_native()


def _times(values: list[Any], base: TimeBase | None) -> np.ndarray:
    if base is None or base.kind == "number":
        return np.asarray(values, dtype=np.float64)
    unit = "datetime64[ns]" if base.kind == "datetime" else "timedelta64[ns]"
    return np.asarray(values, dtype=unit)
