"""Stem labels (events layers with ``labels="stems"``, a story timeline) laid out as the
browser lays them out (``js/src/core/stems.ts``), for pictures drawn in Python (``image``).

Each event stays on its lane's line; its text goes in a box above or below the line, joined
to the event by a stem. The boxes take levels, alternating above and below (+1, −1, +2, −2,
…), so none overlap: the most important first, then from left to right, each where it costs
least. No stem passes behind a box: a stem reserves a corridor in every level it crosses.

A port, kept line by line like the TypeScript and tested against the same cases
(``tests/fixtures/twins.json``): a change to one needs the same change to the other.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

CORRIDOR = 4
"""Room kept on each side of a stem passing a level (px)."""
MARGIN = 7
"""A stem meets its box at least this far from the box's ends (px)."""
LEVEL_COST = 60
"""What a level further from the line costs, against moving a stem sideways (px × 2)."""


@dataclass(frozen=True)
class StemItem:
    index: int
    """The event (an index into its layer; a badge's is negative)."""
    x: float
    """Where the event is (px)."""
    w: float
    """The box's width (px)."""
    importance: float
    badge: bool = False
    """A badge for events without a box: placed after every event."""


@dataclass(frozen=True)
class StemPlaced:
    index: int
    x: float
    cx: float
    """Where the stem meets the box (px): the event's x for a straight stem."""
    level: int
    """1, 2, … above the line, −1, −2, … below."""
    x0: float
    """The box's left edge (px)."""
    w: float


Span = tuple[float, float]


def level_order(levels: int) -> list[int]:
    """The order levels are tried in: +1, −1, +2, −2, …"""
    out: list[int] = []
    for k in range(1, levels + 1):
        out += [k, -k]
    return out


def _hits(spans: list[Span] | None, a: float, b: float, pad: float) -> bool:
    return bool(spans) and any(a < e + pad and b + pad > s for s, e in spans or ())


def _passes(level: int) -> list[int]:
    """The levels a stem to ``level`` passes on its way: 1 … level − 1 on its side."""
    sign = 1 if level > 0 else -1
    return [sign * k for k in range(1, abs(level))]


def place_stems(
    items: Sequence[StemItem],
    *,
    levels: int,
    gap: float,
    inset: float,
    left: float,
    right: float,
    shape: str,
) -> list[StemPlaced]:
    """Give each item a level and a box position; items that fit nowhere are left out."""
    order = sorted(items, key=lambda it: (it.badge, -it.importance, it.x, it.index))
    boxes: dict[int, list[Span]] = {}
    corridors: dict[int, list[Span]] = {}
    tries = level_order(levels)
    placed: list[StemPlaced] = []
    done: set[int] = set()
    for item in order:
        done.add(item.index)
        x, w = item.x, item.w
        # a curved stem (or a badge) may meet its box away from the event, up to about a
        # box's width
        reach = max(w, 120) if shape == "curved" or item.badge else 0
        lo = max(left - MARGIN, x - reach - (w - MARGIN))
        hi = min(right - w + MARGIN, x + reach - MARGIN)
        if hi < lo:
            continue
        want = max(lo, min(hi, x - inset))
        best: StemPlaced | None = None
        best_cost = math.inf
        for level in tries:
            here = [*boxes.get(level, []), *corridors.get(level, [])]
            starts = [want]
            for s, e in here:
                starts += [e + gap, s - gap - w]
            if reach > 0:
                for k in _passes(level):
                    for s, e in boxes.get(k, []):
                        r = e + CORRIDOR + 1
                        lft = s - CORRIDOR - 1
                        starts += [r - MARGIN, r - (w - MARGIN), lft - MARGIN, lft - (w - MARGIN)]
            for x0 in starts:
                if x0 < lo - 0.01 or x0 > hi + 0.01:
                    continue
                x1 = x0 + w
                if _hits(boxes.get(level), x0, x1, gap) or _hits(corridors.get(level), x0, x1, 1):
                    continue
                cx = max(x0 + MARGIN, min(x1 - MARGIN, x))
                if any(
                    _hits(boxes.get(k), cx - CORRIDOR, cx + CORRIDOR, 0) for k in _passes(level)
                ):
                    continue
                covered = sum(
                    1
                    for other in order
                    if not other.badge
                    and other.index not in done
                    and x0 - CORRIDOR < other.x < x1 + CORRIDOR
                )
                cost = (
                    covered * 1000
                    + abs(x0 - want) * 0.25
                    + abs(cx - x) * 2
                    + (abs(level) - 1) * LEVEL_COST
                )
                if cost < best_cost:
                    best_cost = cost
                    best = StemPlaced(item.index, x, cx, level, x0, w)
        if best is None:
            continue
        boxes.setdefault(best.level, []).append((best.x0, best.x0 + best.w))
        for k in _passes(best.level):
            corridors.setdefault(k, []).append((best.cx - CORRIDOR, best.cx + CORRIDOR))
        placed.append(best)
    return placed


def levels_for(lane_h: float, box_h: float, gap: float, start: float) -> int:
    """How many levels fit on each side of the line in a lane of ``lane_h`` px."""
    return max(0, math.floor((lane_h / 2 - 3 - start + gap) / (box_h + gap)))


def level_offset(level: int, box_h: float, gap: float, start: float) -> float:
    """The middle of a box at ``level`` (px from the line; negative: above)."""
    d = start + (abs(level) - 1) * (box_h + gap) + box_h / 2
    return -d if level > 0 else d


def wrap_text(
    text: str, width: float, max_lines: int, measure: Callable[[str], float]
) -> list[str]:
    """``text`` in lines no wider than ``width`` px, broken at spaces, at most ``max_lines``;
    the last line ends in "…" when text is left over. A word longer than the width is cut."""
    if not math.isfinite(width) or measure(text) <= width:
        return [text]

    def fit(s: str) -> str:
        if measure(s) <= width:
            return s
        lo, hi = 0, len(s)
        while lo < hi:
            mid = (lo + hi + 1) >> 1
            if measure(s[:mid] + "…") <= width:
                lo = mid
            else:
                hi = mid - 1
        return s[:lo].rstrip() + "…"

    if max_lines <= 1:
        return [fit(text)]
    words = [w for w in re.split(r"\s+", text) if w]
    lines: list[str] = []
    line = ""
    for k, word in enumerate(words):
        nxt = f"{line} {word}" if line else word
        if not line or measure(nxt) <= width:
            line = nxt
            continue
        lines.append(line)
        if len(lines) == max_lines - 1:
            line = " ".join(words[k:])  # the last line takes the rest
            break
        line = word
    lines.append(line)
    return [fit(s) for s in lines]


@dataclass
class StemCluster:
    """Events next to each other that got no box: a badge ("+N") stands for them."""

    indices: list[int]
    x0: float
    x1: float


def cluster_hidden(
    hidden: Sequence[tuple[int, float]], gap: float, boxed: Sequence[float] = ()
) -> list[StemCluster]:
    """Group the events (index, x) that got no box: neighbours closer than ``gap`` px go
    together, unless an event with a box (at ``boxed``) lies between them."""
    out: list[StemCluster] = []
    for index, x in sorted(hidden, key=lambda h: h[1]):
        last = out[-1] if out else None
        if last and x - last.x1 <= gap and not any(last.x1 < b < x for b in boxed):
            last.indices.append(index)
            last.x1 = x
        else:
            out.append(StemCluster([index], x, x))
    return out
