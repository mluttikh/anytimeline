"""Lanes: the rows of a timeline, shared by its layers, in one order."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, get_args

import numpy as np

from anytimeline.styling import label, natural_key
from anytimeline.types import LaneSort

LANE_SORTS = get_args(LaneSort)


def lane_order(
    values: Sequence[np.ndarray],
    *,
    declared: Sequence[list[Any] | None] = (),
    order: Sequence[Any] | None = None,
    sort: LaneSort | None = None,
    primary: Sequence[np.ndarray] = (),
) -> list[Any]:
    """The lanes of a plot, top to bottom.

    Args:
        values: Each layer's lane value per event.
        declared: Each layer's declared lane order (Enum, Categorical), or None.
        order: Lanes to put first, in this order (``lane_order=``).
        sort: ``"name"`` (natural sort, the default without a declared order), ``"first"`` /
            ``"last"`` (by the time of a lane's first / last event), ``"count"`` (most events
            first), ``"table"`` (in the order they first appear in the tables). Lanes in
            ``order`` stay first.
        primary: Each layer's time (or order) per event, for ``"first"`` and ``"last"``.
    """
    distinct = list(dict.fromkeys(v for arr in values for v in arr.tolist()))
    head = [v for v in (order or []) if v in distinct]
    rest = [v for v in distinct if v not in head]
    if sort == "table":
        return head + rest
    if sort in ("first", "last", "count"):
        stats: dict[Any, list[float]] = {}
        for arr, t in zip(values, primary, strict=True):
            for v, x in zip(arr.tolist(), t.tolist(), strict=True):
                s = stats.setdefault(v, [np.inf, -np.inf, 0.0])
                s[0], s[1], s[2] = min(s[0], x), max(s[1], x), s[2] + 1
        if sort == "count":
            rest.sort(key=lambda v: (-stats[v][2], natural_key(v)))
        else:
            k = 0 if sort == "first" else 1
            rest.sort(key=lambda v: (stats[v][k], natural_key(v)))
        return head + rest
    if sort not in (None, "name"):
        raise ValueError(f"sort must be one of {LANE_SORTS}, got {sort!r}")
    declared_order = [v for d in declared if d for v in d if v in rest]
    declared_order = list(dict.fromkeys(declared_order))
    if sort is None and declared_order:
        rest = declared_order + sorted(
            (v for v in rest if v not in declared_order), key=natural_key
        )
    else:
        rest.sort(key=natural_key)
    return head + rest


def lane_labels(lanes: Sequence[Any]) -> list[str]:
    return [label(v) for v in lanes]
