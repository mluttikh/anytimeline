"""The scene: the plot's layers laid out together, as the spec the browser draws and the
buffers it asks for.

Every layer is read into a record when it is added (``layers.<kind>.build``); ``make``
lays them all out each time the plot changes: one time base for all, the lanes (and groups,
and a tree), each layer's marks in the browser's order, and the order of every instant of
every layer (the Order scale).
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from anytimeline import grouping
from anytimeline.codec import Encoded, encode
from anytimeline.lanes import LaneSort
from anytimeline.layers import events as ev
from anytimeline.layers import intervals as iv
from anytimeline.layers import values as vl
from anytimeline.parts import Marker
from anytimeline.timebase import TimeBase, time_base

Record = ev.EventsRecord | iv.IntervalsRecord | vl.ValuesRecord
Layout = ev.Layout | iv.Layout | vl.Layout


@dataclass
class Scene:
    """The plot as the browser gets it, and what Python needs to answer it (a box's rows)."""

    spec: dict[str, Any]
    buffers: dict[str, bytes]  # by content id
    base: TimeBase | None
    laid: dict[str, Layout]
    ranks: dict[str, np.ndarray]  # per layer: each mark's place(s) in the order


def make(
    layers: Mapping[str, Record],
    *,
    align: str,
    timezone: str | None,
    lane_order: Sequence[Any] | None,
    sort: LaneSort | None,
    group_order: Sequence[Any] | None,
    lane_names: bool,
    markers: Sequence[Marker],
) -> Scene:
    """Lay the layers out together. Raises ValueError for layers that do not fit together
    (times and no times; two trees) or markers without times; the layers are unchanged
    then, except their ``perm``, which is set only when it all fits."""
    originals = list(layers.values())
    # align="start": each group's times from its start (copies; the layers keep theirs)
    records = grouping.shift_to_start(originals) if align == "start" else originals
    timed = [r for r in records if r.time_columns]
    if timed and len(timed) != len(records):
        raise ValueError("all layers need times, or none (order only)")
    columns = [c for r in timed for c in r.time_columns]
    base = time_base(columns, timezone=timezone) if timed else None
    last = (
        max(
            (float(base.ticks(c)[c.valid].max()) for c in columns if c.valid.any()),
            default=0.0,
        )
        if base is not None
        else 0.0
    )
    primary = []
    for r in records:
        if isinstance(r, iv.IntervalsRecord):
            primary.append(base.ticks(r.starts) if base is not None else np.zeros(len(r.rows)))
        elif base is not None and r.times is not None:
            primary.append(base.ticks(r.times))
        elif isinstance(r, ev.EventsRecord) and r.order is not None:
            primary.append(r.order)
        else:
            primary.append(np.zeros(len(r.rows)))
    trees = [r for r in records if isinstance(r, iv.IntervalsRecord) and r.tree is not None]
    if len(trees) > 1:
        raise ValueError(
            f"one layer with parent= per plot; {trees[0].name!r} and {trees[1].name!r} "
            "both have one"
        )
    tree = trees[0] if trees else None
    lane_plan = grouping.plan(
        records,
        primary,
        tree_record=tree,
        lane_order_=list(lane_order) if lane_order is not None else None,
        sort=sort,
        group_order=list(group_order) if group_order is not None else None,
    )
    index = {k: i for i, k in enumerate(lane_plan.keys)}
    tree_ids = set(tree.lanes.tolist()) if tree is not None else set()
    # the layouts place rows by their lane key: (group, lane) for grouped layers
    records = [
        dataclasses.replace(r, lanes=grouping.row_keys(r.lanes, r.lane_groups, tree_ids))
        if r.lane_groups is not None
        else r
        for r in records
    ]
    laid: dict[str, Layout] = {
        r.name: iv.layout(r, base, index, last)
        if isinstance(r, iv.IntervalsRecord)
        else vl.layout(r, base, index)
        if isinstance(r, vl.ValuesRecord)
        else ev.layout(r, base, index)
        for r in records
    }
    buffers: list[Encoded] = [b for lay in laid.values() for b in lay.buffers]
    ranks, sequence, extent = _order(laid, buffers)
    # samples (values layers) take no place in the order, but the time axis covers them
    spans = [lay.extent for lay in laid.values() if isinstance(lay, vl.Layout) and lay.extent]
    if spans:
        lows = [a for a, _ in spans] + ([extent[0]] if sequence else [])
        highs = [b for _, b in spans] + ([extent[1]] if sequence else [])
        extent = (min(lows), max(highs))

    if base is not None:
        time_spec = base.spec(extent)
    else:
        time_spec = {
            "kind": "order" if records else "number",
            "unit": "",
            "origin_ns": "0",
            "origin": 0.0,
            "timezone": "UTC",
            "extent": list(extent),
        }
    spec = {
        "version": 1,
        "time": time_spec,
        "lanes": {
            "names": lane_plan.names,
            "title": lane_plan.title,
            "tree": lane_plan.tree,
            "show_names": lane_names,
        },
        "layers": [lay.spec for lay in laid.values()],
        "sequence": sequence,
        "markers": _markers(markers, base),
        "t": time.time(),
    }
    # the layers keep their order of rows (perm): selection and tooltips use it
    for orig, rec in zip(originals, records, strict=True):
        orig.perm = rec.perm
    return Scene(spec, {b.id: b.data for b in buffers}, base, laid, ranks)


def _order(
    laid: Mapping[str, Layout], buffers: list[Encoded]
) -> tuple[dict[str, np.ndarray], dict[str, Any] | None, tuple[float, float]]:
    """The order of every instant of every layer (events; the starts and ends of bars): each
    layer's ranks (also put in its spec), the sequence of times, and their extent."""
    ranks: dict[str, np.ndarray] = {}
    parts = [
        (li, k, ticks, order)
        for li, lay in enumerate(laid.values())
        for k, (ticks, order) in enumerate(lay.instants)
    ]
    if not (parts and sum(len(p[2]) for p in parts)):
        for lay in laid.values():
            if isinstance(lay, vl.Layout):
                continue
            enc = encode(np.zeros(0), "float32")
            buffers.append(enc)
            lay.spec["rank"] = enc.descriptor
        return ranks, None, (0.0, 1.0)
    prim = np.concatenate([p[2] for p in parts])
    order = np.concatenate([p[3] for p in parts])
    which = np.concatenate([np.full(len(p[2]), i) for i, p in enumerate(parts)])
    idx = np.concatenate([np.arange(len(p[2])) for p in parts])
    perm = np.lexsort((idx, which, order, prim))
    rank = np.empty(len(perm), dtype=np.float64)
    rank[perm] = np.arange(len(perm))
    dtype = "float32" if len(perm) < 2**24 else "float64"
    start = 0
    comps: dict[int, list[np.ndarray]] = {}
    for li, _k, ticks, _order in parts:
        comps.setdefault(li, []).append(rank[start : start + len(ticks)])
        start += len(ticks)
    seq_times = prim[perm]
    for li, (name, lay) in enumerate(laid.items()):
        if isinstance(lay, vl.Layout):  # samples take no place in the order
            continue
        cols = comps.get(li, [np.zeros(0)])
        following = getattr(lay, "following", None)
        if following is not None and len(cols) == 1:
            # chained bars (states): each ends at its lane's next change; a lane's last
            # at its end time, or at the end of the order when it is still open
            start_rank = cols[0]
            last = np.searchsorted(seq_times, lay.hi, side="right") - 0.5
            cols = [start_rank, np.where(following >= 0, start_rank[following], last)]
        ranks[name] = np.stack(cols, axis=1)
        enc = encode(ranks[name] if len(cols) > 1 else cols[0], dtype, components=len(cols))
        buffers.append(enc)
        lay.spec["rank"] = enc.descriptor
    seq = encode(prim[perm], "float64")
    buffers.append(seq)
    sequence = {"times": seq.descriptor, "count": len(perm)}
    return ranks, sequence, (float(prim.min()), float(prim.max()))


def _markers(markers: Sequence[Marker], base: TimeBase | None) -> list[dict[str, Any]]:
    if not markers:
        return []
    if base is None:
        raise ValueError("markers need layers with times")
    return [{"x": base.to_ticks(m.time), "label": m.label, "color": m.color} for m in markers]
