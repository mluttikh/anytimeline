"""The notes on a plot (``Timeline.notes``: annotations, connections, measures) as the
browser draws them (``_notes``: ticks, places in the order, lane indices), and the measured
times as a table (``Timeline.measured``).

An end of a note is an ``Edge`` (a mark's start or end, found where the mark is laid out) or
a time. On the Order scale a time is placed between the instants around it, an edge at its
mark's own place, so a measure from a bar's start to its end spans its own instants.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from anytimeline.data import NotFoundError
from anytimeline.parts import Annotation, Connection, Edge, Measure, Note
from anytimeline.timebase import TimeBase


@dataclass
class Context:
    """What resolving a note needs from the plot as laid out."""

    base: TimeBase | None
    lane_names: Sequence[str]
    order: np.ndarray | None  # every instant's time, in the order
    mark_at: Callable[[str, int], dict[str, Any]]  # ``Timeline._mark_at``
    layer_named: Callable[[str | None], str]  # ``Timeline._layer_named``


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
        return {
            "x": m["x"] if first else m["x2"],
            "r": m["r"] if first else m["r2"],
            "lane": m["lane"],
            "side": end.side,
            "layer": layer,
            "row": end.row,
            "index": m["index"],
        }
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
    return out


def arrow(ctx: Context, c: Connection) -> dict[str, Any]:
    """A connection: an arrow from one edge to another."""
    a, b = end_of(ctx, c.a), end_of(ctx, c.b)
    return {"a": _browser_end(a), "b": _browser_end(b), "text": c.text, "color": c.color}


def measure(ctx: Context, m: Measure) -> dict[str, Any]:
    """A measure: its ends, the time between (``span``, ticks, b − a) and the instants
    between (``events``; None without an order)."""
    a, b = end_of(ctx, m.a), end_of(ctx, m.b)
    return {
        "a": _browser_end(a),
        "b": _browser_end(b),
        "span": b["x"] - a["x"],
        "events": between(a["r"], b["r"]),
        "lane": lane_index(ctx, m.lane, "measure in"),
        "text": m.text,
        "color": m.color,
    }


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
        if not isinstance(n, Measure):
            continue
        try:
            a, b = end_of(ctx, n.a), end_of(ctx, n.b)
        except (LookupError, ValueError, TypeError):
            continue
        rows.append({"note": i, "text": n.text, "a": a, "b": b})
    base = ctx.base
    cols: dict[str, Any] = {
        "note": np.asarray([r["note"] for r in rows], dtype=np.int64),
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
    for key in ("a", "b"):
        cols[f"{key}_layer"] = np.asarray([r[key].get("layer") for r in rows], dtype=object)
        cols[f"{key}_row"] = np.asarray([r[key].get("row", -1) for r in rows], dtype=np.int64)
        cols[f"{key}_side"] = np.asarray([r[key]["side"] for r in rows], dtype=object)
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
