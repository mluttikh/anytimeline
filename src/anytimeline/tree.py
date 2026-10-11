"""Trees of bars (spans of a trace, tasks with sub-tasks): the order of their lanes, which lanes
start folded, and the critical path.

Every bar of a tree gets its own lane. Lanes are in depth-first order (a bar, then its
children by start time), so the lanes below a bar are one contiguous block: folding a bar hides
the next ``size - 1`` lanes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

Expand = int | Literal["auto"] | None

AUTO_LANES = 200
"""``expand="auto"`` opens as many levels as keep at most this many lanes in view."""


@dataclass
class Tree:
    """The lanes of a tree, in depth-first order (positions into the layer's rows)."""

    order: np.ndarray
    depth: np.ndarray
    size: np.ndarray  # lanes in each subtree, itself included
    parent: np.ndarray  # per row: the parent's row, or -1 (a root)
    labels: list[str]
    roots: int
    orphans: int  # rows whose parent is not in the table: shown as roots

    def open(self, expand: Expand) -> np.ndarray:
        """Per lane: whether its children are shown at first."""
        if expand is None:
            levels = int(self.depth.max(initial=0)) + 1
        elif expand == "auto":
            counts = np.cumsum(np.bincount(self.depth))
            levels = max(1, int(np.searchsorted(counts, AUTO_LANES, side="right")))
        else:
            levels = max(1, int(expand))
        return self.depth < levels - 1


def build(
    ids: np.ndarray,
    parents: np.ndarray,
    starts: np.ndarray,
    labels: Sequence[Any] | np.ndarray,
    id_name: str,
) -> Tree:
    """The tree of rows ``ids`` → ``parents`` (ids; missing or unknown: a root), siblings by
    ``starts`` (comparable numbers), then by table order."""
    n = len(ids)
    index: dict[Any, int] = {}
    for i, v in enumerate(ids.tolist()):
        if v in index:
            raise ValueError(
                f"each bar of a tree needs a unique id, but {v!r} is in {id_name!r} twice"
            )
        index[v] = i
    parent = np.full(n, -1, dtype=np.int64)
    orphans = 0
    for i, p in enumerate(parents.tolist()):
        if p is None or (isinstance(p, float) and p != p) or p == "":
            continue
        j = index.get(p)
        if j is None:
            orphans += 1
        elif j == i:
            raise ValueError(f"{ids[i]!r} is its own parent")
        else:
            parent[i] = j

    # children of each row, by start then table order: a stable sort of all rows by start,
    # then grouped by parent
    by_start = np.argsort(starts, kind="stable")
    grouped = by_start[np.argsort(parent[by_start], kind="stable")]
    counts = np.bincount(parent[grouped] + 1, minlength=n + 1)
    first = np.concatenate([[0], np.cumsum(counts)])  # children of row r: first[r+1]..first[r+2]

    order = np.empty(n, dtype=np.int64)
    depth = np.empty(n, dtype=np.int64)
    size = np.ones(n, dtype=np.int64)
    k = 0
    stack: list[tuple[int, int]] = [
        (int(r), 0) for r in reversed(grouped[first[0] : first[1]].tolist())
    ]
    roots = len(stack)
    pos = np.full(n, -1, dtype=np.int64)
    while stack:
        r, d = stack.pop()
        pos[r] = k
        order[k] = r
        depth[k] = d
        k += 1
        kids = grouped[first[r + 1] : first[r + 2]]
        stack.extend((int(c), d + 1) for c in reversed(kids.tolist()))
    if k < n:
        stuck = int(np.flatnonzero(pos < 0)[0])
        raise ValueError(f"the parents of {ids[stuck]!r} form a cycle: no root above it")
    # subtree sizes: children are after their parent, so walk the lanes backwards
    lane_parent = np.where(parent[order] >= 0, pos[np.maximum(parent[order], 0)], -1)
    for lane in range(n - 1, 0, -1):
        p = lane_parent[lane]
        if p >= 0:
            size[p] += size[lane]
    return Tree(
        order=order,
        depth=depth,
        size=size,
        parent=parent,
        labels=[str(labels[i]) for i in order.tolist()],
        roots=roots,
        orphans=orphans,
    )


def critical_path(
    lo: np.ndarray, hi: np.ndarray, depth: np.ndarray, size: np.ndarray
) -> np.ndarray:
    """The critical path of each root: the parts of bars that its end waits for.

    Walk back from a bar's end: the child that ended last before that point is on the path
    (and, inside it, its own critical path); before it, the bar waited for whatever ended
    before that child started; time no child covers is the bar's own.

    Bars are lanes in depth-first order (``lo``, ``hi``: their start and end ticks). Returns
    ``(k, 3)`` rows ``(bar, from, to)``, where ``from`` and ``to`` are instants: ``2 * bar``
    for a bar's start, ``2 * bar + 1`` for its end.
    """
    n = len(lo)
    out: list[tuple[int, int, int]] = []
    # children of each lane, latest end first
    kids: list[list[int]] = [[] for _ in range(n)]
    stack: list[int] = []
    for lane in range(n):
        while stack and depth[stack[-1]] >= depth[lane]:
            stack.pop()
        if stack:
            kids[stack[-1]].append(lane)
        stack.append(lane)
    for k in kids:
        k.sort(key=lambda c: (-hi[c], -lo[c]))

    lane = 0
    while lane < n:  # each root
        # (bar, the time its part ends, that instant)
        work = [(lane, float(hi[lane]), 2 * lane + 1)]
        while work:
            bar, cur, cur_at = work.pop()
            begin = float(lo[bar])
            for c in kids[bar]:
                # a child that starts after this point, or ends before the bar starts (clocks
                # out of step), is not what the bar waited for
                if lo[c] >= cur or hi[c] <= begin or cur <= begin:
                    continue
                end, end_at = (float(hi[c]), 2 * c + 1) if hi[c] <= cur else (cur, cur_at)
                if end < cur:
                    out.append((bar, end_at, cur_at))
                work.append((c, end, end_at))
                if lo[c] <= begin:
                    cur, cur_at = begin, 2 * bar
                    break
                cur, cur_at = float(lo[c]), 2 * c
            if begin < cur:
                out.append((bar, 2 * bar, cur_at))
        lane += int(size[lane])
    return np.array(out, dtype=np.int64).reshape(-1, 3)
