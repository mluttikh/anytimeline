"""Find and step: what the plot's search box (``/``, Ctrl/Cmd+F) matches, and the mark the
keys ``.`` and ``,`` step to, answered from every mark the plot has (the browser may hold
only some: layers sent as levels).

A match is a mark whose text (``text=``, a state) holds the query, ignoring case, or a lane
whose name does. Marks come in time order (on the order scale: in the order); stepping goes
to the next or previous mark of a lane, of any events or bars layer, ties broken by layer
and then by the mark's index.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from anytimeline.layers import events as ev
from anytimeline.layers import intervals as iv

MAX_MATCHES = 1000
"""The most matches a search answers (the earliest); the count tells how many there are."""


@dataclass
class Marks:
    """The events and bars of one layer that search and stepping see, in the browser's
    order: each one's place on both scales, its lane and its text."""

    layer: str
    rank: int  # the layer's place among the plot's (breaks ties)
    x: np.ndarray  # ticks: an event's time, a bar's start
    x2: np.ndarray  # a bar's end (an event: its time)
    r: np.ndarray  # place in the order
    r2: np.ndarray
    lanes: np.ndarray
    text: list[str] | None


def marks_of(
    records: Mapping[str, Any], laid: Mapping[str, Any], ranks: Mapping[str, np.ndarray]
) -> list[Marks]:
    out = []
    for k, (name, rec) in enumerate(records.items()):
        if not isinstance(rec, ev.EventsRecord | iv.IntervalsRecord):
            continue
        lay = laid[name]
        rk = ranks.get(name)
        r = rk[:, 0] if rk is not None and len(rk) else np.asarray(lay.lo, dtype=np.float64)
        r2 = rk[:, -1] if rk is not None and len(rk) else r
        text = None
        own = rec.text if rec.text is not None else getattr(rec, "states", None)
        if own is not None:
            text = [own[p] for p in rec.perm.tolist()]
        out.append(
            Marks(
                name, k, np.asarray(lay.lo, np.float64), np.asarray(lay.hi, np.float64),
                np.asarray(r, np.float64), np.asarray(r2, np.float64), np.asarray(lay.lanes), text,
            )
        )  # fmt: skip
    return out


def _match(m: Marks, i: int) -> dict[str, Any]:
    return {
        "layer": m.layer,
        "index": i,
        "x": float(m.x[i]),
        "x2": float(m.x2[i]),
        "r": float(m.r[i]),
        "r2": float(m.r2[i]),
        "lane": int(m.lanes[i]),
        "text": m.text[i] if m.text is not None else "",
    }


def search(
    marks: Sequence[Marks], lane_names: Sequence[str], query: str, scale: str
) -> dict[str, Any]:
    """The lanes whose names hold ``query``, and the marks whose text does (in time order,
    or in the order with ``scale="order"``; the first MAX_MATCHES), and how many marks
    match."""
    q = query.strip().casefold()
    if not q:
        return {"lanes": [], "matches": [], "total": 0}
    lanes = [i for i, n in enumerate(lane_names) if q in str(n).casefold()]
    found: list[tuple[float, int, int, Marks]] = []
    total = 0
    for m in marks:
        if m.text is None:
            continue
        hits = [i for i, t in enumerate(m.text) if t and q in t.casefold()]
        total += len(hits)
        at = m.r if scale == "order" else m.x
        found += [(float(at[i]), m.rank, i, m) for i in hits]
    found.sort(key=lambda f: f[:3])
    return {
        "lanes": lanes,
        "matches": [_match(m, i) for _, _, i, m in found[:MAX_MATCHES]],
        "total": total,
    }


def step(
    marks: Sequence[Marks],
    lane: int,
    after: tuple[float, str | None, int],
    forward: bool,
    scale: str,
) -> dict[str, Any] | None:
    """The mark of lane ``lane`` next after (``forward``) or before ``after``: a place on
    the scale, a layer (None: before or after every layer at that place) and an index."""
    x0, layer, i0 = after
    ranks = {m.layer: m.rank for m in marks}
    if layer is None or layer not in ranks:
        k0, i0 = (-1, -1) if forward else (2**31, 2**62)
    else:
        k0 = ranks[layer]
    best: tuple[tuple[float, int, int], Marks, int] | None = None
    for m in marks:
        at = m.r if scale == "order" else m.x
        idx = np.flatnonzero(m.lanes == lane)
        if not len(idx):
            continue
        xs = at[idx]
        if forward:
            later = (xs > x0) | ((xs == x0) & ((m.rank > k0) | ((m.rank == k0) & (idx > i0))))
            pick = idx[later]
            if not len(pick):
                continue
            i = int(pick[np.lexsort((pick, at[pick]))[0]])
        else:
            earlier = (xs < x0) | ((xs == x0) & ((m.rank < k0) | ((m.rank == k0) & (idx < i0))))
            pick = idx[earlier]
            if not len(pick):
                continue
            i = int(pick[np.lexsort((pick, at[pick]))[-1]])
        key = (float(at[i]), m.rank, i)
        if best is None or (key < best[0] if forward else key > best[0]):
            best = (key, m, i)
    return _match(best[1], best[2]) if best is not None else None


def _edge(m: Marks, i: int, side: str) -> dict[str, Any]:
    first = side == "start"
    return {
        "layer": m.layer,
        "index": i,
        "side": side,
        "x": float(m.x[i] if first else m.x2[i]),
        "r": float(m.r[i] if first else m.r2[i]),
        "lane": int(m.lanes[i]),
    }


def _sides(m: Marks, scale: str) -> tuple[tuple[str, np.ndarray], tuple[str, np.ndarray]]:
    """A layer's starts and ends on the scale shown."""
    order = scale == "order"
    return ("start", m.r if order else m.x), ("end", m.r2 if order else m.x2)


def nearest_edge(
    marks: Sequence[Marks], lane: int, at: float, within: float, scale: str
) -> dict[str, Any] | None:
    """The start or end of a mark of lane ``lane`` nearest to ``at`` on the scale, no
    farther than ``within`` (ties: the earlier layer, then the lower index, start first);
    None when there is none that near. What a measure's end snaps to (key ``m``)."""
    best: tuple[tuple[float, int, int, int], Marks, int, str] | None = None
    for m in marks:
        idx = np.flatnonzero(m.lanes == lane)
        if not len(idx):
            continue
        for k, (side, xs) in enumerate(_sides(m, scale)):
            d = np.abs(xs[idx] - at)
            j = int(np.argmin(d))
            if d[j] > within:
                continue
            key = (float(d[j]), m.rank, int(idx[j]), k)
            if best is None or key < best[0]:
                best = (key, m, int(idx[j]), side)
    return _edge(best[1], best[2], best[3]) if best is not None else None


def step_edge(
    marks: Sequence[Marks], lane: int, at: float, forward: bool, scale: str
) -> dict[str, Any] | None:
    """The start or end of a mark of lane ``lane`` next after (``forward``) or before the
    place ``at`` on the scale: where the keys ``>`` and ``<`` move a measure's end."""
    best: tuple[tuple[float, int, int, int], Marks, int, str] | None = None
    for m in marks:
        idx = np.flatnonzero(m.lanes == lane)
        if not len(idx):
            continue
        for k, (side, xs) in enumerate(_sides(m, scale)):
            v = xs[idx]
            ok = v > at if forward else v < at
            if not ok.any():
                continue
            cand = np.flatnonzero(ok)
            j = int(cand[np.argmin(v[cand])] if forward else cand[np.argmax(v[cand])])
            x = float(v[j])
            key = (x if forward else -x, m.rank, int(idx[j]), k)
            if best is None or key < best[0]:
                best = (key, m, int(idx[j]), side)
    return _edge(best[1], best[2], best[3]) if best is not None else None
