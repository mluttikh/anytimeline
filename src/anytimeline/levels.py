"""Levels of detail: a large layer as counts per lane and bin, at bin widths a factor of 4
apart, so that the browser draws millions of marks from a few megabytes; and windows: the
marks of a range (or finer bins of it), which the browser asks for as it zooms in.

Level ``k`` has bins of width ``top / 4**k``, counted from the extent's start ``x0``: bin
``j`` covers ``[x0 + j w, x0 + (j + 1) w)``. The grid is the same for every level, so a bin
of level ``k`` holds exactly four of level ``k + 1``. Each bin that holds marks keeps its
first and last position, its count, its representative mark (the most important, by
``importance=``; else its first) and its colour (its most frequent colour category; else
its representative's). Bins are kept per lane, in order: lane ``l``'s are
``lane_starts[l] .. lane_starts[l + 1]``.

Positions are ticks on the Time scale and ranks on the Order scale: each scale has levels of
its own, as a layer's marks are in a different order on each (ranks are exact; bins of
ranks are cheaper than bins of time, as ranks are evenly spread).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from anytimeline.codec import Encoded, encode

LEVELS_FROM: int = 250_000
"""A layer with more marks than this is sent as levels, and its marks in windows."""
RAW_MARKS: int = 200_000
"""The most marks in view that the browser draws one by one (with fewer, it asks for them)."""
TOP_BINS: int = 256
"""Level 0 has the extent in this many bins (at least 4 px each on a plot 1000 px wide)."""
LEVEL_BINS: int = 1 << 17
"""The levels sent with the plot hold at most this many bins each; finer ones come in
windows."""
LEVEL_SAMPLES: int = 1 << 18
"""A values layer's finest level has at most this many samples (its coarsest may have more)."""
WINDOW_MARKS: int = 1_000_000
"""A window holds at most this many marks (or bins); a wider range is cut to its middle."""
SEQUENCE_STEP_TO: int = 1 << 16
"""A plot with levels sends the times of the order (the Order scale) at most this many,
every ``step``-th; windows bring the exact times of their range."""


@dataclass(frozen=True)
class Grid:
    """Where the bins of every level are: from ``x0``, ``top / 4**k`` wide at level ``k``."""

    x0: float
    top: float

    @staticmethod
    def over(extent: tuple[float, float]) -> Grid:
        span = float(extent[1] - extent[0])
        return Grid(float(extent[0]), span / TOP_BINS if span > 0 else 1.0)

    def width(self, k: int) -> float:
        return self.top / 4.0**k

    def spec(self) -> dict[str, float]:
        return {"x0": self.x0, "top": self.top}


@dataclass
class Bins:
    """The bins of one level (of all marks, or of a window's), per lane in order."""

    k: int
    lo: np.ndarray  # first position in the bin
    hi: np.ndarray  # last
    count: np.ndarray
    top: np.ndarray  # the representative mark (index into the marks binned)
    lane_starts: np.ndarray  # per lane: its first bin (n_lanes + 1)
    dominant: np.ndarray | None  # the most frequent colour category, or None

    def __len__(self) -> int:
        return len(self.lo)


def bin_marks(
    x: np.ndarray,
    lane: np.ndarray,
    n_lanes: int,
    grid: Grid,
    k: int,
    *,
    importance: np.ndarray | None = None,
    codes: np.ndarray | None = None,
    n_codes: int = 0,
) -> Bins:
    """The bins of level ``k`` of marks at ``x`` in ``lane`` (sorted by lane, then x)."""
    n = len(x)
    if n == 0:
        empty = np.zeros(0)
        return Bins(k, empty, empty, empty.astype(np.int64), empty.astype(np.int64),
                    np.zeros(n_lanes + 1, dtype=np.int64), None)  # fmt: skip
    j = np.floor((x - grid.x0) / grid.width(k)).astype(np.int64)
    brk = np.empty(n, dtype=bool)
    brk[0] = True
    np.not_equal(j[1:], j[:-1], out=brk[1:])
    brk[1:] |= lane[1:] != lane[:-1]
    starts = np.flatnonzero(brk)
    ends = np.append(starts[1:], n)
    count = ends - starts
    if importance is not None:
        imp = np.where(np.isnan(importance), -np.inf, importance)
        best = np.maximum.reduceat(imp, starts)
        seg = np.repeat(np.arange(len(starts)), count)
        top = np.minimum.reduceat(np.where(imp == best[seg], np.arange(n), n), starts)
    else:
        top = starts
    dominant = None
    if codes is not None and n_codes and len(starts) * n_codes <= 1 << 24:
        seg = np.repeat(np.arange(len(starts)), count)
        counts = np.bincount(seg * n_codes + codes, minlength=len(starts) * n_codes)
        dominant = counts.reshape(len(starts), n_codes).argmax(axis=1)
    lane_starts = np.searchsorted(lane[starts], np.arange(n_lanes + 1), side="left")
    return Bins(k, x[starts], x[ends - 1], count, top, lane_starts, dominant)


def pyramid(
    x: np.ndarray,
    lane: np.ndarray,
    n_lanes: int,
    grid: Grid,
    **kw: Any,
) -> list[Bins]:
    """The levels sent with the plot: from level 0 (coarser ones, k < 0, when level 0 has too
    many bins: many lanes) down to the finest with at most LEVEL_BINS bins, or the first
    whose bins hold one mark each."""
    out: list[Bins] = []
    k = 0
    first = bin_marks(x, lane, n_lanes, grid, 0, **kw)
    while len(first) > LEVEL_BINS and k > -8:
        k -= 1
        first = bin_marks(x, lane, n_lanes, grid, k, **kw)
    level = first
    while True:
        out.append(level)
        if not len(level) or int(level.count.max()) <= 1 or k >= 30:
            break
        k += 1
        level = bin_marks(x, lane, n_lanes, grid, k, **kw)
        if len(level) > LEVEL_BINS:
            break
    return out


def in_range(x: np.ndarray, lane_starts: np.ndarray, a: float, b: float) -> list[tuple[int, int]]:
    """Per lane, the marks (or bins, by their first position) from ``a`` to ``b``: their
    first and end index (x sorted within each lane)."""
    out = []
    for lo, hi in zip(lane_starts[:-1].tolist(), lane_starts[1:].tolist(), strict=True):
        if hi <= lo:
            out.append((lo, lo))
            continue
        seg = x[lo:hi]
        i0, i1 = np.searchsorted(seg, [a, b], "left")[0], np.searchsorted(seg, b, "right")
        out.append((lo + int(i0), lo + int(i1)))
    return out


def fit_range(
    count: Callable[[float, float], int], a: float, b: float, most: int
) -> tuple[float, float]:
    """``(a, b)``, or its middle part, cut so that ``count(a, b) <= most``."""
    if count(a, b) <= most:
        return a, b
    mid = (a + b) / 2
    lo, hi = 0.0, (b - a) / 2
    for _ in range(40):
        h = (lo + hi) / 2
        if count(mid - h, mid + h) <= most:
            lo = h
        else:
            hi = h
    return mid - lo, mid + lo


def window_rows(x: np.ndarray, lane_starts: np.ndarray, a: float, b: float) -> np.ndarray:
    """The marks from ``a`` to ``b`` (per lane, x sorted), in their order."""
    parts = [np.arange(i0, i1) for i0, i1 in in_range(x, lane_starts, a, b) if i1 > i0]
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.int64)


def count_in(x: np.ndarray, lane_starts: np.ndarray) -> Callable[[float, float], int]:
    return lambda a, b: sum(i1 - i0 for i0, i1 in in_range(x, lane_starts, a, b))


@dataclass
class Look:
    """What a bin shows of its marks: their colours (per mark, or a palette by category),
    symbols and sizes (None: one for all, as the layer says)."""

    rgba: np.ndarray | None = None  # (n, 4) per mark
    palette: np.ndarray | None = None  # (categories, 4), with codes per mark
    codes: np.ndarray | None = None
    symbol: np.ndarray | None = None
    size: np.ndarray | None = None

    @property
    def n_codes(self) -> int:
        return len(self.palette) if self.palette is not None else 0


def encode_bins(
    bins: Bins,
    grid: Grid,
    look: Look,
    *,
    rows: np.ndarray | None = None,
    window: tuple[float, float] | None = None,
) -> tuple[dict[str, Any], list[Encoded]]:
    """A level's spec and buffers. ``rows``: the marks binned, when a window's (``top`` is
    then mapped to the layer's mark indices); ``window``: the range a window covers."""
    buffers: list[Encoded] = []

    def put(enc: Encoded) -> dict[str, Any]:
        buffers.append(enc)
        return enc.descriptor

    top = bins.top if rows is None else rows[bins.top]
    if look.palette is not None and bins.dominant is not None:
        rgba = look.palette[bins.dominant]
    elif look.rgba is not None:
        rgba = look.rgba[top]
    else:
        rgba = None
    spec = {
        "k": bins.k,
        "width": grid.width(bins.k),
        "count": len(bins),
        "most": int(bins.count.max()) if len(bins) else 0,
        "lane_starts": put(encode(bins.lane_starts, "uint32")),
        "lo": put(encode(bins.lo, "float64")),
        "hi": put(encode(bins.hi, "float64")),
        "n": put(encode(bins.count, "uint32")),
        "top": put(encode(top, "uint32")),
        "rgba": put(encode(rgba, "uint8", components=4)) if rgba is not None else None,
        "symbol": put(encode(look.symbol[top], "uint8")) if look.symbol is not None else None,
        "size": put(encode(look.size[top], "float32")) if look.size is not None else None,
        "range": list(window) if window is not None else None,
    }
    return spec, buffers


def coarse_sequence(times: np.ndarray) -> tuple[np.ndarray, int]:
    """Every ``step``-th time of the order (and the last), at most SEQUENCE_STEP_TO."""
    step = max(1, -(-len(times) // SEQUENCE_STEP_TO))
    picked = times[::step]
    if (len(times) - 1) % step:
        picked = np.append(picked, times[-1])
    return picked, step


def gaps(times: np.ndarray) -> np.ndarray:
    """Long gaps between consecutive instants of the order: ``(at, span)`` rows, at rank
    ``k + 0.5`` where the time from instant ``k`` to ``k + 1`` is over 20× the median gap;
    at most one per 50 instants (the longest). The browser's ``findGaps``, for plots whose
    sequence it does not have in full."""
    if len(times) < 3:
        return np.zeros((0, 2))
    diffs = np.diff(times)
    ordered = np.sort(diffs)
    median = ordered[len(ordered) // 2]
    mean = float(ordered.mean())
    threshold = median * 20 if median > 0 else mean * 10
    most = max(1, len(diffs) // 50)
    if len(ordered) > most:
        threshold = max(threshold, ordered[len(ordered) - most - 1])
    if not threshold > 0:
        return np.zeros((0, 2))
    at = np.flatnonzero(diffs > threshold)
    return np.stack([at + 0.5, diffs[at]], axis=1)
