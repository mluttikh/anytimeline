"""Traces in depth: the spans of many traces merged into one flame graph, and two traces
compared span by span.

Both take a table with a row per span (as [`read_otlp`][anytimeline.otel.read_otlp],
[`read_jaeger`][anytimeline.jaeger.read_jaeger] and
[`read_chrome`][anytimeline.chrome.read_chrome] return it) and return a table of the same
shape, which plots with [`Timeline.spans`][anytimeline.Timeline.spans]::

    from anytimeline import Timeline, compare_traces
    from anytimeline.traces import merge

    Timeline().spans(merge(traces.spans), layout="flame", color="service")
    compare_traces(before.spans, after.spans)

A span's path is the names of the spans from its root down to it (by default its service and
name, ``by=``): spans with the same path are the same call, in any trace.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from anytimeline import data as tables
from anytimeline import tree as trees
from anytimeline.axis import format_duration
from anytimeline.timebase import times

CHANGES = ("added", "removed", "slower", "faster", "same")
"""What ``compare`` says of a span, in the order of its legend."""

CHANGE_COLORS = {
    "added": "#2ca02c",
    "removed": "#d62728",
    "slower": "#ff7f0e",
    "faster": "#1f77b4",
    "same": "#a0a0a0",
}


@dataclass
class _Spans:
    """A table of spans read for merging and comparing: in the tree's depth-first order."""

    keys: list[tuple[Any, ...]]  # per span: its by-values
    by: list[str]
    parent: np.ndarray  # per span (in this order): its parent's position, or -1
    start: np.ndarray  # int64 ns (datetimes, durations) or float64 (numbers)
    end: np.ndarray
    kind: str  # "time" (ns) or "number"


def _read(
    data: Any, id: str, parent: str, start: str, end: str, by: Sequence[str] | None
) -> _Spans:
    table = tables.frame(data)
    names = tables.column_names(table)
    if by is None:
        by = [c for c in ("service", "name") if c in names] or ["name"]
    by = list(by)
    tables.check(table, [id, parent, start, end, *by])
    s = times(tables.column(table, start), column=start)
    e = times(tables.column(table, end), column=end)
    if s.kind != e.kind:
        raise TypeError(f"start and end must be of one kind, got {s.kind} and {e.kind}")
    if not (s.valid & e.valid).all():
        raise ValueError("every span needs a start and an end")
    if s.raw is not None and e.raw is not None:
        lo, hi, kind = s.raw * s.per, e.raw * e.per, "time"
    else:
        assert s.values is not None
        assert e.values is not None
        lo, hi, kind = s.values, e.values, "number"
    if (hi < lo).any():
        raise ValueError("some spans end before they start; check the start and end columns")
    ids = tables.column(table, id).astype(object)
    tree = trees.build(ids, tables.column(table, parent), lo, ids.tolist(), id)
    order = tree.order
    pos = np.empty(len(order), dtype=np.int64)
    pos[order] = np.arange(len(order))
    up = tree.parent[order]
    columns = [tables.column(table, c) for c in by]
    return _Spans(
        keys=[tuple(_cell(c[i]) for c in columns) for i in order.tolist()],
        by=by,
        parent=np.where(up >= 0, pos[np.maximum(up, 0)], -1),
        start=lo[order],
        end=hi[order],
        kind=kind,
    )


def _cell(value: Any) -> Any:
    return None if value is None or (isinstance(value, float) and value != value) else value


def _paths(spans: _Spans, occurrence: bool) -> tuple[np.ndarray, list[tuple[Any, ...]]]:
    """Each span's path number, and the paths: (parent path, by-values[, k]), where k counts
    the spans of one parent with the same by-values, in start order (``occurrence``)."""
    index: dict[tuple[Any, ...], int] = {}
    paths: list[tuple[Any, ...]] = []
    node = np.empty(len(spans.keys), dtype=np.int64)
    seen: dict[tuple[Any, ...], int] = {}
    for i, key in enumerate(spans.keys):  # parents come before their children
        up = int(node[spans.parent[i]]) if spans.parent[i] >= 0 else -1
        path: tuple[Any, ...] = (up, key)
        if occurrence:
            k = seen.get(path, 0)
            seen[path] = k + 1
            path = (up, key, k)
        j = index.get(path)
        if j is None:
            j = index[path] = len(paths)
            paths.append(path)
        node[i] = j
    return node, paths


def _own_time(spans: _Spans) -> np.ndarray:
    """Per span: its duration less the time its children cover (they may overlap)."""
    dur = (spans.end - spans.start).astype(np.float64)
    own = dur.copy()
    kids: dict[int, list[int]] = {}
    for i, p in enumerate(spans.parent.tolist()):
        if p >= 0:
            kids.setdefault(p, []).append(i)
    for p, ks in kids.items():
        a, b = float(spans.start[p]), float(spans.end[p])
        covered = 0.0
        reach = a
        for c in sorted(ks, key=lambda c: spans.start[c]):
            lo, hi = max(float(spans.start[c]), reach), min(float(spans.end[c]), b)
            if hi > lo:
                covered += hi - lo
                reach = hi
        own[p] = max(0.0, dur[p] - covered)
    return own


def _as_time(values: np.ndarray, kind: str, missing: np.ndarray | None = None) -> np.ndarray:
    """Offsets or durations in ns as timedelta64[ns] (numbers stay numbers); NaT/NaN where
    ``missing``."""
    if kind == "number":
        out = values.astype(np.float64)
        if missing is not None:
            out[missing] = np.nan
        return out
    out = np.round(values.astype(np.float64)).astype(np.int64).astype("timedelta64[ns]")
    if missing is not None:
        out[missing] = np.timedelta64("NaT", "ns")
    return out


def merge(
    spans: Any,
    *,
    id: str = "span_id",
    parent: str = "parent_id",
    start: str = "start",
    end: str = "end",
    by: Sequence[str] | None = None,
) -> dict[str, np.ndarray]:
    """Merge the spans of traces into one flame graph: a span per path (the same call in any
    trace, or many times in one), as wide as the time spent in it, its children side by side
    in it, the heaviest first (a left-heavy flame graph).

    Plot it with ``Timeline().spans(merged, layout="flame")``. Its axis is time spent, from
    0, not time of day. Children that ran in parallel can take more time together than
    their parent; they then share its width (in proportion), while ``total`` says the time
    each took.

    Args:
        spans: A table with a row per span, of one trace or of many.
        id: The column of span ids, unique in the table.
        parent: The column of parent span ids (missing for a root).
        start: The column of start times (datetimes, durations or numbers).
        end: The column of end times.
        by: The columns that name a call: by default ``service`` and ``name`` (those of
            them in the table).

    Returns:
        A row per path, as a dict of columns: ``span_id``, ``parent_id``, the ``by``
        columns, ``path`` (the names from the root, as text), ``count`` (spans merged),
        ``total`` (their time), ``self`` (of it, the time not in a child), and ``start``
        and ``end``, its place in the flame graph.
    """
    s = _read(spans, id, parent, start, end, by)
    node, paths = _paths(s, occurrence=False)
    m = len(paths)
    dur = (s.end - s.start).astype(np.float64)
    count = np.bincount(node, minlength=m)
    total = np.bincount(node, weights=dur, minlength=m)
    own = np.bincount(node, weights=_own_time(s), minlength=m)
    up = np.array([p[0] for p in paths], dtype=np.int64)
    # left-heavy: children of each path by total, the heaviest first; scaled into the parent
    kids: dict[int, list[int]] = {}
    for j in range(m):
        kids.setdefault(int(up[j]), []).append(j)
    lo = np.zeros(m)
    width = np.zeros(m)
    stack = [-1]
    while stack:
        p = stack.pop()
        ks = sorted(kids.get(p, []), key=lambda j: (-total[j], j))
        if not ks:
            continue
        room = width[p] if p >= 0 else float(sum(total[j] for j in ks))
        need = float(sum(total[j] for j in ks))
        scale = min(1.0, room / need) if need > 0 else 0.0
        x = lo[p] if p >= 0 else 0.0
        for j in ks:
            lo[j] = x
            width[j] = total[j] * scale
            x += width[j]
        stack.extend(ks)
    out: dict[str, np.ndarray] = {
        "span_id": np.arange(m, dtype=np.int64),
        "parent_id": np.array([int(u) if u >= 0 else None for u in up.tolist()], dtype=object),
    }
    for c, name in enumerate(s.by):
        out[name] = np.array([p[1][c] for p in paths], dtype=object)
    labels = [" ".join(str(v) for v in p[1] if v is not None) for p in paths]
    full: list[str] = []
    for j in range(m):
        full.append(labels[j] if up[j] < 0 else f"{full[up[j]]} › {labels[j]}")
    out["path"] = np.array(full, dtype=object)
    out["count"] = count.astype(np.int64)
    out["total"] = _as_time(total, s.kind)
    out["self"] = _as_time(own, s.kind)
    out["start"] = _as_time(lo, s.kind)
    out["end"] = _as_time(lo + width, s.kind)
    return out


def compare(
    before: Any,
    after: Any,
    *,
    id: str = "span_id",
    parent: str = "parent_id",
    start: str = "start",
    end: str = "end",
    by: Sequence[str] | None = None,
    threshold: float = 0.1,
) -> dict[str, np.ndarray]:
    """Compare two traces span by span: which spans were added, removed, slower or faster.

    Spans are matched by their path (by default the service and name of each span from the
    root down) and, among spans of one parent with the same name, by their order. Times are
    from each trace's start, so the two line up. Plot the result with
    [`compare_traces`][anytimeline.compare_traces].

    Args:
        before: A table with a row per span of the first trace.
        after: A table with a row per span of the second trace.
        id: The column of span ids.
        parent: The column of parent span ids (missing for a root).
        start: The column of start times (datetimes, durations or numbers).
        end: The column of end times.
        by: The columns that name a span: by default ``service`` and ``name`` (those of
            them in the tables).
        threshold: How much longer (as a fraction: 0.1 is 10%) a span must take to be
            ``"slower"``; as much shorter, ``"faster"``.

    Returns:
        A row per span of either trace, as a dict of columns: ``span_id`` and ``parent_id``
        (a path's number), the ``by`` columns, ``change`` (``"added"``, ``"removed"``,
        ``"slower"``, ``"faster"`` or ``"same"``), ``start`` and ``end`` (the second
        trace's times, or the first's for a span removed), ``before_start`` and
        ``before_end`` (the first trace's; missing for a span added), ``before`` and
        ``after`` (the durations, missing where a trace has no such span), ``delta`` (after
        less before) and ``difference`` (that as text, with the change in percent).
    """
    if threshold < 0:
        raise ValueError(
            f"threshold is a fraction of a span's duration, at least 0; got {threshold}"
        )
    a = _read(before, id, parent, start, end, by)
    b = _read(after, id, parent, start, end, by)
    for name, t, s in (("before", before, a), ("after", after, b)):
        _one_trace(t, name)
        if not len(s.keys):
            raise ValueError(f"{name} has no spans")
    if a.kind != b.kind:
        raise TypeError("the two traces' times must be of one kind")
    if a.by != b.by:
        raise ValueError(f"the two traces name spans by other columns: {a.by} and {b.by}")
    node_a, paths_a = _paths(a, occurrence=True)
    node_b, paths_b = _paths(b, occurrence=True)

    # one numbering of the paths of both: the second trace's, then those only in the first
    # (a path is (parent path, key, k); parents' numbers differ per trace, so map them)
    union: dict[tuple[Any, ...], int] = {}
    up: list[int] = []
    keys: list[tuple[Any, ...]] = []
    of_b = np.empty(len(paths_b), dtype=np.int64)
    of_a = np.empty(len(paths_a), dtype=np.int64)
    for paths, of in ((paths_b, of_b), (paths_a, of_a)):
        for j, (p, key, k) in enumerate(paths):
            parent_u = int(of[p]) if p >= 0 else -1
            u = union.get((parent_u, key, k))
            if u is None:
                u = union[(parent_u, key, k)] = len(up)
                up.append(parent_u)
                keys.append(key)
            of[j] = u
    m = len(up)
    zero_a, zero_b = a.start.min(), b.start.min()
    nan = np.full(m, np.nan)
    a_lo, a_hi, b_lo, b_hi = nan.copy(), nan.copy(), nan.copy(), nan.copy()
    a_lo[of_a[node_a]] = (a.start - zero_a).astype(np.float64)
    a_hi[of_a[node_a]] = (a.end - zero_a).astype(np.float64)
    b_lo[of_b[node_b]] = (b.start - zero_b).astype(np.float64)
    b_hi[of_b[node_b]] = (b.end - zero_b).astype(np.float64)
    in_a, in_b = ~np.isnan(a_lo), ~np.isnan(b_lo)
    d_a, d_b = a_hi - a_lo, b_hi - b_lo
    change = np.full(m, "same", dtype=object)
    change[in_b & ~in_a] = "added"
    change[in_a & ~in_b] = "removed"
    both = in_a & in_b
    change[both & (d_b > d_a * (1 + threshold))] = "slower"
    change[both & (d_a > d_b * (1 + threshold))] = "faster"

    out: dict[str, np.ndarray] = {
        "span_id": np.arange(m, dtype=np.int64),
        "parent_id": np.array([u if u >= 0 else None for u in up], dtype=object),
    }
    for c, name in enumerate(b.by):
        out[name] = np.array([k[c] for k in keys], dtype=object)
    out["change"] = change
    out["start"] = _as_time(np.where(in_b, b_lo, a_lo), b.kind)
    out["end"] = _as_time(np.where(in_b, b_hi, a_hi), b.kind)
    out["before_start"] = _as_time(np.nan_to_num(a_lo), a.kind, ~in_a)
    out["before_end"] = _as_time(np.nan_to_num(a_hi), a.kind, ~in_a)
    out["before"] = _as_time(np.nan_to_num(d_a), a.kind, ~in_a)
    out["after"] = _as_time(np.nan_to_num(d_b), b.kind, ~in_b)
    delta = np.nan_to_num(d_b - d_a)
    out["delta"] = _as_time(delta, b.kind, ~both)
    out["difference"] = np.array(
        [
            _difference(float(delta[i]), float(d_a[i]), b.kind) if both[i] else str(change[i])
            for i in range(m)
        ],
        dtype=object,
    )
    return out


def _one_trace(data: Any, name: str) -> None:
    table = tables.frame(data)
    if "trace_id" in tables.column_names(table):
        found = {v for v in tables.column(table, "trace_id").tolist() if v is not None}
        if len(found) > 1:
            raise ValueError(
                f"{name} holds {len(found)} traces; compare takes one trace each (pick one by "
                "its trace_id)"
            )


def _difference(delta: float, before: float, kind: str) -> str:
    """A change in duration as text: "+12.3 ms (+35%)"."""
    sign = "+" if delta > 0 else ""
    amount = format_duration(delta, 0) if kind == "time" else f"{delta:.3g}"
    if before > 0:
        return f"{sign}{amount} ({sign}{delta / before:.0%})".replace("-", "−")
    return f"{sign}{amount}"
