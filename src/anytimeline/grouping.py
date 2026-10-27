"""Groups of lanes: a plot of several groups (hosts, regions, days), each a header lane with
its own lanes under it, in one plot with one time axis, toolbar and legend.

Layers take ``group=``: a row's lane is then (its group, its lane), shown under the group's
header. The lanes are in the same order in every group, so the groups compare row by row; a
group folds like a span. A tree of spans (``spans``) in a group sits under its header.

With ``Timeline(align="start")`` each group's times start at 0: groups of different periods
(days, runs, traces) compare from their start.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from anytimeline import styling
from anytimeline.lanes import LaneSort, lane_order
from anytimeline.timebase import Times

MISSING = "(missing)"


@dataclass(frozen=True)
class Header:
    """The key of a group's header lane."""

    group: Any


@dataclass
class LanePlan:
    """The plot's lanes, top to bottom."""

    keys: list[Any]
    names: list[str]
    tree: dict[str, Any] | None  # {depth, size, open, header, compact}
    title: str


def row_keys(lanes: np.ndarray, groups: np.ndarray | None, tree_ids: set[Any]) -> np.ndarray:
    """Each row's lane key: its lane, or (group, lane) when grouped (a span's id stays its
    own key, so events go on spans in any group)."""
    if groups is None:
        return lanes
    out = np.empty(len(lanes), dtype=object)
    for i, (g, v) in enumerate(zip(groups.tolist(), lanes.tolist(), strict=True)):
        out[i] = v if v in tree_ids else (g, v)
    return out


def plan(
    records: Sequence[Any],
    primary: Sequence[np.ndarray],
    *,
    tree_record: Any,
    lane_order_: Sequence[Any] | None,
    sort: LaneSort | None,
    group_order: Sequence[Any] | None,
) -> LanePlan:
    """The lanes of the plot: ungrouped lanes first (a tree's in its order), then each group:
    its header, its trees, its lanes in the plot's lane order."""
    tree = tree_record.tree if tree_record is not None else None
    tree_ids = set(tree_record.lanes.tolist()) if tree is not None else set()
    grouped = [r for r in records if getattr(r, "lane_groups", None) is not None]
    # a tree names its lanes; else the first layer that names them
    title = (tree_record.lane_title if tree is not None else "") or next(
        (r.lane_title for r in records if r.lane_title), ""
    )

    # ungrouped: a tree first (when the tree is not grouped), then the other lanes
    head: list[Any] = []
    head_depth: list[int] = []
    head_open: list[bool] = []
    labels: dict[Any, str] = {}
    tree_open = tree.open(tree_record.expand) if tree is not None else None
    tree_lanes = tree_record.lanes[tree.order].tolist() if tree is not None else []
    if tree is not None:
        assert tree_open is not None
        labels.update(zip(tree_lanes, tree.labels, strict=True))
    if tree is not None and tree_record not in grouped:
        assert tree_open is not None
        head = list(tree_lanes)
        head_depth = tree.depth.tolist()
        head_open = tree_open.tolist()
    plain = [
        (r, p)
        for r, p in zip(records, primary, strict=True)
        if r not in grouped and r is not tree_record
    ]
    rest_values = [
        np.array([v for v in r.lanes.tolist() if v not in tree_ids], dtype=object) for r, _ in plain
    ]
    rest_primary = [p[[v not in tree_ids for v in r.lanes.tolist()]] for r, p in plain]
    rest = lane_order(
        rest_values,
        declared=[r.lane_declared for r, _ in plain],
        order=lane_order_,
        sort=sort,
        primary=rest_primary,
    )
    keys = head + rest
    depth = head_depth + [0] * len(rest)
    is_open = head_open + [False] * len(rest)
    headers: list[int] = []

    if grouped:
        # groups: of the rows that make lanes in them (not of rows on a span's lane), and of
        # the trees' roots; in the given order, then declared (Enum, Categorical), then natural
        parts = []
        for r in grouped:
            if r is tree_record:
                assert tree is not None
                roots = tree.order[tree.depth == 0]
                parts.append(r.lane_groups[roots])
            else:
                parts.append(r.lane_groups[[v not in tree_ids for v in r.lanes.tolist()]])
        all_groups = np.concatenate(parts) if parts else np.zeros(0, dtype=object)
        declared = next((r.lane_group_declared for r in grouped if r.lane_group_declared), None)
        groups = styling.ordered_categories(all_groups, declared, list(group_order or []) or None)
        # one lane order for all groups
        lanes_by: list[np.ndarray] = []
        prim_by: list[np.ndarray] = []
        for r in grouped:
            if r is tree_record:
                continue
            p = primary[list(records).index(r)]
            keep = np.array([v not in tree_ids for v in r.lanes.tolist()], dtype=bool)
            lanes_by.append(r.lanes[keep])
            prim_by.append(p[keep])
        order = lane_order(
            lanes_by,
            declared=[r.lane_declared for r in grouped if r is not tree_record],
            order=lane_order_,
            sort=sort,
            primary=prim_by,
        )
        present: dict[Any, set[Any]] = {}
        for r in grouped:
            if r is tree_record:
                continue
            for g, v in zip(r.lane_groups.tolist(), r.lanes.tolist(), strict=True):
                if v not in tree_ids:
                    present.setdefault(g, set()).add(v)
        # each tree root's group: its row's
        roots_of: dict[Any, list[tuple[int, int]]] = {}
        if tree is not None and tree_record in grouped:
            assert tree_open is not None
            row_group = tree_record.lane_groups[tree.order].tolist()
            lane = 0
            while lane < len(tree_lanes):
                size = int(tree.size[lane])
                roots_of.setdefault(row_group[lane], []).append((lane, size))
                lane += size
        for g in groups:
            start = len(keys)
            headers.append(start)
            keys.append(Header(g))
            labels[Header(g)] = styling.label(g)
            depth.append(0)
            is_open.append(True)
            for lane, size in roots_of.get(g, []):
                assert tree is not None
                assert tree_open is not None
                keys.extend(tree_lanes[lane : lane + size])
                depth.extend((tree.depth[lane : lane + size] + 1).tolist())
                is_open.extend(tree_open[lane : lane + size].tolist())
            for v in order:
                if v in present.get(g, ()):
                    keys.append((g, v))
                    labels[(g, v)] = styling.label(v)
                    depth.append(1)
                    is_open.append(False)

    names = [labels.get(k, styling.label(k)) for k in keys]
    if tree is None and not grouped:
        return LanePlan(keys, names, None, title)
    size = _sizes(depth)
    return LanePlan(
        keys,
        names,
        {
            "depth": depth,
            "size": size,
            "open": is_open,
            "header": headers,
            # spans: compact lanes (folding moves the lanes below); groups of lanes fill the plot
            "compact": tree is not None,
        },
        title,
    )


def _sizes(depth: list[int]) -> list[int]:
    """Lanes in each lane's subtree, itself included (lanes in depth-first order)."""
    size = [1] * len(depth)
    stack: list[int] = []
    for lane, d in enumerate(depth):
        while stack and depth[stack[-1]] >= d:
            stack.pop()
        for parent in stack:
            size[parent] += 1
        stack.append(lane)
    return size


def shift_to_start(records: Sequence[Any]) -> list[Any]:
    """Copies of the records with each group's times starting at 0 (``align="start"``):
    datetimes become durations since the group's first time; ungrouped layers start at the
    first time of all of them."""
    starts: dict[Any, int | float] = {}

    def each(rec: Any) -> list[tuple[Times, np.ndarray]]:
        groups = getattr(rec, "lane_groups", None)
        keys = groups if groups is not None else np.full(len(rec.rows), None, dtype=object)
        return [(t, keys) for t in rec.time_columns]

    for rec in records:
        for t, keys in each(rec):
            for g in dict.fromkeys(keys.tolist()):
                mine = t.valid & (keys == g)
                if not mine.any():
                    continue
                first = _first(t, mine)
                starts[g] = min(starts.get(g, first), first)
    if None in starts:  # ungrouped layers start with the earliest of everything
        starts[None] = min(starts.values())
    out = []
    for rec in records:
        groups = getattr(rec, "lane_groups", None)
        keys = groups if groups is not None else np.full(len(rec.rows), None, dtype=object)
        offset = np.array([starts.get(g, 0) for g in keys.tolist()], dtype=object)
        changes = {
            name: _shift(getattr(rec, name), offset)
            for name in ("times", "starts", "ends")
            if isinstance(getattr(rec, name, None), Times)
        }
        out.append(dataclasses.replace(rec, **changes))
    return out


def _first(t: Times, rows: np.ndarray) -> int | float:
    """The first time of ``rows`` (ns as an exact int, or a number)."""
    if t.raw is not None:
        return int(t.raw[rows].min()) * t.per
    assert t.values is not None
    return float(t.values[rows].min())


def _shift(t: Times, offset: np.ndarray) -> Times:
    """``t`` minus each row's offset: durations (or numbers) since its group's start."""
    if t.raw is None:
        assert t.values is not None
        return Times("number", None, t.values - offset.astype(np.float64), t.valid)
    shift = np.array([int(o) // t.per for o in offset.tolist()], dtype=np.int64)
    raw = np.where(t.valid, t.raw - shift, 0)
    return Times("duration", raw, None, t.valid, None, t.per)
