"""What the layers share: reading numbers and text from columns, and picking rows (a click
on a mark, a box over time and lanes) in a layer as it is laid out."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

import numpy as np

from anytimeline import data as tables
from anytimeline import styling
from anytimeline.codec import Encoded


class Record(Protocol):
    """A layer as read from its table: what the plot needs of every kind."""

    name: str
    rows: np.ndarray  # the table row of each kept mark
    perm: np.ndarray  # the browser's order of the marks → positions in ``rows``
    select: bool
    tooltip: dict[str, np.ndarray]


class Layout(Protocol):
    """A layer laid out on the plot's time base and lanes, in the browser's order."""

    spec: dict[str, Any]
    buffers: list[Encoded]  # the buffers its spec names (by content id)
    lo: np.ndarray  # each mark's start (an event: its time) in ticks
    hi: np.ndarray  # each mark's end
    lanes: np.ndarray  # each mark's lane (an index into the plot's lanes)


def numbers(values: np.ndarray, name: str) -> np.ndarray:
    """A column as float64; a missing value as NaN."""
    if values.dtype.kind in "iufb":
        return values.astype(np.float64)
    if values.dtype.kind == "O":
        try:
            return np.array([np.nan if v is None else float(v) for v in values])
        except (TypeError, ValueError):
            pass
    raise TypeError(f"column {name!r} must hold numbers, got {values.dtype}")


def texts(table: Any, template: str, rows: np.ndarray) -> list[str]:
    """A column name, or a template such as ``"{event} ({user})"``, per kept row."""
    names = tables.column_names(table)
    if template in names:
        return [
            styling.label(v) if v is not None else "" for v in tables.column(table, template)[rows]
        ]
    used = [n for n in names if "{" + n in template]
    if not used:
        raise tables.NotFoundError(
            f"text={template!r} names no column; use a column name or a template such as "
            f"'{{{names[0] if names else 'column'}}}'; columns: {names}"
        )
    cols = {n: tables.column(table, n)[rows] for n in used}
    for n, col in cols.items():
        if col.dtype.kind == "M":  # datetimes: Python's, so "{time:%H:%M}" formats them
            cols[n] = col.astype("datetime64[us]").astype(object)
    out = []
    for i in range(len(rows)):
        values = {n: ("–" if cols[n][i] is None else cols[n][i]) for n in used}
        out.append(template.format_map(values))
    return out


def clicked(rec: Record, index: int) -> set[int] | None:
    """The table row of the mark the browser has at ``index``; None: not selectable."""
    if not rec.select or not 0 <= index < len(rec.perm):
        return None
    return {int(rec.rows[rec.perm[index]])}


def in_box(
    rec: Record,
    lay: Layout,
    x: tuple[float, float],
    lanes: tuple[int, int] | Sequence[int],
    ranks: np.ndarray | None = None,
) -> set[int]:
    """The table rows of the marks that reach into a box: from ``x[0]`` to ``x[1]`` (ticks,
    or ranks with ``ranks``: the order scale), over the lanes ``lanes`` (first and last, or
    with folded lanes the lanes in the box that show)."""
    if not rec.select:
        return set()
    lo, hi = (ranks[:, 0], ranks[:, -1]) if ranks is not None else (lay.lo, lay.hi)
    if isinstance(lanes, tuple):
        in_lanes = (lay.lanes >= lanes[0]) & (lay.lanes <= lanes[1])
    else:
        in_lanes = np.isin(lay.lanes, np.asarray(lanes, dtype=np.int64))
    inside = np.flatnonzero((hi >= x[0]) & (lo <= x[1]) & in_lanes)
    return {int(r) for r in rec.rows[rec.perm[inside]]}
