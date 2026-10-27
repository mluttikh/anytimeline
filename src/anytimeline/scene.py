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
from anytimeline import levels as lv
from anytimeline.codec import Encoded, encode
from anytimeline.lanes import LaneSort
from anytimeline.layers import events as ev
from anytimeline.layers import intervals as iv
from anytimeline.layers import values as vl
from anytimeline.layers.common import lexsort
from anytimeline.parts import Marker
from anytimeline.timebase import TimeBase, time_base

Record = ev.EventsRecord | iv.IntervalsRecord | vl.ValuesRecord
Layout = ev.Layout | iv.Layout | vl.Layout


@dataclass
class Detail:
    """A layer sent as levels: what Python needs to cut its windows."""

    record: ev.EventsRecord
    layout: ev.Layout
    x: dict[str, np.ndarray]  # each mark's position per scale ("time", "order")
    grids: dict[str, lv.Grid]
    look: lv.Look


@dataclass
class ValueDetail:
    """A values layer sent as levels: what Python needs to cut its windows."""

    record: vl.ValuesRecord
    layout: vl.Layout
    grid: lv.Grid


@dataclass
class BarDetail:
    """An intervals layer sent as levels: what Python needs to cut its windows."""

    record: iv.IntervalsRecord
    bars: iv.Bars
    rank: np.ndarray  # (n, 2): each bar's start and end in the order
    x: dict[str, tuple[np.ndarray, np.ndarray]]  # each bar's ends per scale
    grids: dict[str, lv.Grid]
    unit_ns: int


@dataclass
class Scene:
    """The plot as the browser gets it, and what Python needs to answer it (a box's rows,
    a window)."""

    spec: dict[str, Any]
    buffers: dict[str, bytes]  # by content id
    base: TimeBase | None
    laid: dict[str, Layout]
    ranks: dict[str, np.ndarray]  # per layer: each mark's place(s) in the order
    detail: dict[str, Detail | ValueDetail | BarDetail] = dataclasses.field(default_factory=dict)
    sequence: np.ndarray | None = None  # every instant's time, in the order

    def full_bytes(self) -> int:
        """About how many bytes the layers sent as levels take with every event (the order's
        times included)."""
        total = 8 * (len(self.sequence) if self.sequence is not None else 0)
        for d in self.detail.values():
            if isinstance(d, ValueDetail):
                total += 12 * len(d.layout.samples.time)
                continue
            if isinstance(d, BarDetail):
                b = d.bars
                total += len(b.lo) * (46 + (4 if b.rgba is not None else 0))
                total += sum(len(t) for t in b.text) if b.text else 0
                continue
            m = d.layout.marks
            per = 16 + sum(4 for a in (m.rgba, m.size, m.importance) if a is not None)
            per += 1 if m.symbol is not None else 0
            total += per * len(m.primary) + (sum(len(t) for t in m.text) if m.text else 0)
        return total

    def window(
        self, name: str, scale: str, a: float, b: float, k: int | None
    ) -> tuple[dict[str, Any], list[Encoded]]:
        """A window of a layer sent as levels: its marks from ``a`` to ``b`` (positions on
        ``scale``), or with ``k`` its bins of level ``k`` there; at most WINDOW_MARKS (a
        wider range is cut to its middle). The answer says the range it covers, and has the
        exact times of the order there (``sequence``: from rank ``offset``)."""
        d = self.detail[name]
        if isinstance(d, ValueDetail):
            return _value_window(d, a, b, k)
        if isinstance(d, BarDetail):
            answer, buffers = _bar_window(d, scale, a, b, k)
            self._sequence_slice(answer, buffers, scale, *answer["range"])
            return answer, buffers
        x = d.x[scale]
        lay = d.layout
        starts = np.searchsorted(lay.marks.lane, np.arange(lay.n_lanes + 1), side="left")
        count = lv.count_in(x, starts)
        a, b = lv.fit_range(count, a, b, lv.WINDOW_MARKS)
        rows = lv.window_rows(x, starts, a, b)
        if k is None:
            spec, buffers = ev.encode_marks(
                d.record, lay.marks, lay.n_lanes, rows, has_time=self.base is not None
            )
            instants = len(self.sequence) if self.sequence is not None else 0
            rank = encode(self.ranks[name][rows, 0], "float32" if instants < 2**24 else "float64")
            for enc, key in ((rank, "rank"), (encode(rows, "uint32"), "index")):
                buffers.append(enc)
                spec[key] = enc.descriptor
        else:
            bins = lv.bin_marks(
                x[rows],
                lay.marks.lane[rows],
                lay.n_lanes,
                d.grids[scale],
                k,
                importance=_take(lay.marks.importance, rows),
                codes=_take(d.look.codes, rows),
                n_codes=d.look.n_codes,
            )
            spec, buffers = lv.encode_bins(bins, d.grids[scale], d.look, rows=rows, window=(a, b))
        answer: dict[str, Any] = {"spec": spec, "range": [a, b], "scale": scale, "k": k}
        if len(rows):
            self._sequence_slice(answer, buffers, scale, a, b)
        return answer, buffers

    def _sequence_slice(
        self, answer: dict[str, Any], buffers: list[Encoded], scale: str, a: float, b: float
    ) -> None:
        """Put in a window's answer the exact times of the order from ``a`` to ``b``."""
        if self.sequence is not None:
            if scale == "order":
                r0, r1 = int(np.floor(a + 0.5)), int(np.ceil(b + 0.5))
            else:
                r0 = int(np.searchsorted(self.sequence, a, "left"))
                r1 = int(np.searchsorted(self.sequence, b, "right"))
            r0, r1 = max(0, r0 - 1), min(len(self.sequence), r1 + 1)
            if r1 - r0 <= 2 * lv.WINDOW_MARKS:
                enc = encode(self.sequence[r0:r1], "float64")
                buffers.append(enc)
                answer["sequence"] = {"times": enc.descriptor, "offset": r0}


def _value_window(
    d: ValueDetail, a: float, b: float, k: int | None
) -> tuple[dict[str, Any], list[Encoded]]:
    """A window of a values layer sent as levels (times ``a`` to ``b``): its samples there
    when at most RAW_MARKS, else (``k``) those that draw them at level ``k``, and the answer
    says which (``k`` None: every sample)."""
    s = d.layout.samples
    count = lv.count_in(s.time, s.run_starts)
    a, b = lv.fit_range(count, a, b, lv.WINDOW_MARKS)
    rows = vl.window_rows(s, a, b)
    if k is not None and len(rows) > lv.RAW_MARKS:
        rows = vl.m4(s, rows, d.grid, k)
    else:
        k = None
    spec, buffers = vl.encode_samples(d.record, s, rows)
    if k is not None:
        spec["k"] = k
    return {"spec": spec, "range": [a, b], "scale": "time", "k": k}, buffers


def _bar_window(
    d: BarDetail, scale: str, a: float, b: float, k: int | None
) -> tuple[dict[str, Any], list[Encoded]]:
    """A window of an intervals layer sent as levels (``a`` to ``b`` on ``scale``): the bars
    that reach into it when at most RAW_MARKS, else (``k``) those of level ``k`` there; the
    answer says which (``k`` None: every bar)."""
    x_lo, x_hi = d.x[scale]
    bars = d.bars
    count = lv.count_in(x_lo, bars.lane_starts)
    a, b = lv.fit_range(count, a, b, lv.WINDOW_MARKS)
    rows = iv.window_rows(x_lo, x_hi, bars.lane_starts, a, b)
    merged = None
    if k is not None and len(rows) > lv.RAW_MARKS:
        grid = d.grids[scale]
        rows, merged = iv.merge(bars, d.rank, x_lo, x_hi, rows, grid.width(k), grid.x0)
    else:
        k = None
    spec, buffers = iv.encode_bars(
        d.record, bars, rows, unit_ns=d.unit_ns, merged=merged, rank=d.rank
    )
    if k is not None:
        spec["k"] = k
    return {"spec": spec, "range": [a, b], "scale": scale, "k": k}, buffers


def _take(values: np.ndarray | None, rows: np.ndarray) -> np.ndarray | None:
    return values[rows] if values is not None else None


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
    levels: bool = True,
    windows: bool = True,
) -> Scene:
    """Lay the layers out together. Raises ValueError for layers that do not fit together
    (times and no times; two trees) or markers without times; the layers are unchanged
    then, except their ``perm``, which is set only when it all fits.

    ``levels``: send layers of more than LEVELS_FROM events as levels (False: every mark);
    ``windows``: and say that Python serves their windows (False: a page; levels only)."""
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
    levelled = {
        r.name
        for r in records
        if levels
        and len(r.rows) > lv.LEVELS_FROM
        and (
            (isinstance(r, ev.EventsRecord) and r.labels != "stems")
            or isinstance(r, vl.ValuesRecord)
            or (isinstance(r, iv.IntervalsRecord) and r.tree is None)
        )
    }
    laid: dict[str, Layout] = {
        r.name: iv.layout(r, base, index, last, levelled=r.name in levelled)
        if isinstance(r, iv.IntervalsRecord)
        else vl.layout(r, base, index, levelled=r.name in levelled)
        if isinstance(r, vl.ValuesRecord)
        else ev.layout(r, base, index, levelled=r.name in levelled)
        for r in records
    }
    buffers: list[Encoded] = [b for lay in laid.values() for b in lay.buffers]
    # (events and bars sent as levels make the order coarse; samples take no place in it)
    instants_levelled = {n for n in levelled if not isinstance(laid[n], vl.Layout)}
    ranks, sequence, extent, seq_times = _order(laid, buffers, instants_levelled)
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
    detail: dict[str, Detail | ValueDetail | BarDetail] = {}
    for r in records:
        if r.name in levelled and isinstance(r, iv.IntervalsRecord):
            lay = laid[r.name]
            assert isinstance(lay, iv.Layout)
            detail[r.name] = _bar_levels(r, lay, ranks[r.name], extent, len(seq_times),
                                         buffers, windows, base)  # fmt: skip
        if r.name in levelled and isinstance(r, vl.ValuesRecord):
            lay = laid[r.name]
            assert isinstance(lay, vl.Layout)
            detail[r.name] = _value_levels(r, lay, extent, buffers, windows)
        if r.name in levelled and isinstance(r, ev.EventsRecord):
            lay = laid[r.name]
            assert isinstance(lay, ev.Layout)
            detail[r.name] = _levels(r, lay, ranks[r.name][:, 0], extent, len(seq_times),
                                     buffers, windows)  # fmt: skip
    # the layers keep their order of rows (perm): selection and tooltips use it
    for orig, rec in zip(originals, records, strict=True):
        orig.perm = rec.perm
    return Scene(
        spec, {b.id: b.data for b in buffers}, base, laid, ranks, detail,
        seq_times if instants_levelled else None,
    )  # fmt: skip


def _levels(
    rec: ev.EventsRecord,
    lay: ev.Layout,
    rank: np.ndarray,
    extent: tuple[float, float],
    instants: int,
    buffers: list[Encoded],
    windows: bool,
) -> Detail:
    """Build an events layer's levels (Time and Order scales) into its spec."""
    marks = lay.marks
    color = rec.color
    look = lv.Look(
        rgba=marks.rgba,
        palette=color.extra.get("palette"),
        codes=color.extra["codes"][rec.perm] if "codes" in color.extra else None,
        symbol=marks.symbol,
        size=marks.size,
    )
    x = {"time": marks.primary, "order": rank}
    grids = {"time": lv.Grid.over(extent), "order": lv.Grid.over((-0.5, instants - 0.5))}
    scales: dict[str, Any] = {}
    for scale, xs in x.items():
        made = lv.pyramid(
            xs, marks.lane, lay.n_lanes, grids[scale],
            importance=marks.importance, codes=look.codes, n_codes=look.n_codes,
        )  # fmt: skip
        out = []
        for bins in made:
            spec, encoded = lv.encode_bins(bins, grids[scale], look)
            buffers.extend(encoded)
            out.append(spec)
        scales[scale] = {**grids[scale].spec(), "levels": out}
    lay.spec["levels"] = {
        "total": len(marks.primary),
        "raw": lv.RAW_MARKS,
        "windows": windows,
        "categories": color.extra.get("names"),
        **scales,
    }
    return Detail(rec, lay, x, grids, look)


def _bar_levels(
    rec: iv.IntervalsRecord,
    lay: iv.Layout,
    rank: np.ndarray,
    extent: tuple[float, float],
    instants: int,
    buffers: list[Encoded],
    windows: bool,
    base: TimeBase | None,
) -> BarDetail:
    """Build an intervals layer's levels (Time and Order scales) into its spec: per level,
    its bars at least a bin long, and the others merged per lane and bin; from the
    coarsest down to the finest of at most LEVEL_BINS bars (and fewer than half the layer's)."""
    bars = lay.bars
    assert bars is not None
    unit_ns = iv.UNITS.get(base.unit, 1) if base is not None else 1
    x = {"time": (bars.lo, bars.hi), "order": (rank[:, 0], rank[:, 1])}
    grids = {"time": lv.Grid.over(extent), "order": lv.Grid.over((-0.5, instants - 0.5))}
    n = len(bars.lo)
    scales: dict[str, Any] = {}
    for scale, (x_lo, x_hi) in x.items():
        grid = grids[scale]
        every = np.arange(n)
        out = []
        k = 0
        while True:
            rows, merged = iv.merge(bars, rank, x_lo, x_hi, every, grid.width(k), grid.x0)
            count = len(rows) + len(merged)
            if out and (count > lv.LEVEL_BINS or count * 2 > n):
                break
            spec, encoded = iv.encode_bars(
                rec, bars, rows, unit_ns=unit_ns, merged=merged, rank=rank
            )
            buffers.extend(encoded)
            out.append({**spec, "k": k, "bin_width": grid.width(k)})
            k += 1
        scales[scale] = {**grid.spec(), "levels": out}
    lay.spec["levels"] = {
        "total": n,
        "raw": lv.RAW_MARKS,
        "windows": windows,
        **scales,
    }
    return BarDetail(rec, bars, rank, x, grids, unit_ns)


def _value_levels(
    rec: vl.ValuesRecord,
    lay: vl.Layout,
    extent: tuple[float, float],
    buffers: list[Encoded],
    windows: bool,
) -> ValueDetail:
    """Build a values layer's levels into its spec: per level, the samples that draw it at
    that level's bin width (M4), from the coarsest down to the finest of at most LEVEL_SAMPLES
    samples (and fewer than half the layer's)."""
    s = lay.samples
    grid = lv.Grid.over(extent)
    every = np.arange(len(s.time))
    out = []
    k = 0
    while True:
        rows = vl.m4(s, every, grid, k)
        if out and (len(rows) > lv.LEVEL_SAMPLES or len(rows) * 2 > len(every)):
            break
        spec, encoded = vl.encode_samples(rec, s, rows)
        buffers.extend(encoded)
        out.append({**spec, "k": k, "bin_width": grid.width(k)})
        if len(rows) * 4 > lv.LEVEL_SAMPLES:
            break
        k += 1
    lay.spec["levels"] = {
        "total": len(s.time),
        "raw": lv.RAW_MARKS,
        "windows": windows,
        **grid.spec(),
        "levels": out,
    }
    return ValueDetail(rec, lay, grid)


def _order(
    laid: Mapping[str, Layout], buffers: list[Encoded], levelled: set[str]
) -> tuple[dict[str, np.ndarray], dict[str, Any] | None, tuple[float, float], np.ndarray]:
    """The order of every instant of every layer (events; the starts and ends of bars): each
    layer's ranks (also put in its spec; not for a layer sent as levels), the sequence of
    times (with levels: every ``step``-th, and its long gaps), their extent, and every
    instant's time."""
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
        return ranks, None, (0.0, 1.0), np.zeros(0)
    prim = np.concatenate([p[2] for p in parts])
    order = np.concatenate([p[3] for p in parts])
    which = np.concatenate([np.full(len(p[2]), i) for i, p in enumerate(parts)])
    idx = np.concatenate([np.arange(len(p[2])) for p in parts])
    perm = lexsort((idx, which, order, prim))
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
        sent = ranks[name] if len(cols) > 1 else cols[0]
        if name in levelled:
            sent = sent[:0]
        enc = encode(sent, dtype, components=len(cols))
        buffers.append(enc)
        lay.spec["rank"] = enc.descriptor
    times = prim[perm]
    if levelled:
        coarse, step = lv.coarse_sequence(times)
        seq = encode(coarse, "float64")
        found = encode(lv.gaps(times), "float64", components=2)
        buffers += [seq, found]
        sequence = {"times": seq.descriptor, "count": len(perm), "step": step,
                    "gaps": found.descriptor}  # fmt: skip
    else:
        seq = encode(times, "float64")
        buffers.append(seq)
        sequence = {"times": seq.descriptor, "count": len(perm)}
    return ranks, sequence, (float(prim.min()), float(prim.max())), times


def _markers(markers: Sequence[Marker], base: TimeBase | None) -> list[dict[str, Any]]:
    if not markers:
        return []
    if base is None:
        raise ValueError("markers need layers with times")
    return [{"x": base.to_ticks(m.time), "label": m.label, "color": m.color} for m in markers]
