"""Pictures of a plot drawn in Python (``Timeline.save_image``, ``Timeline.to_svg``): an SVG
of what the browser draws in one view, from the same spec and buffers; a PNG of it through
the optional ``resvg-py``.

The layout follows the browser's (``js/src/core``: ``view.ts`` for sizes, ``rendering.ts``
for the frame, ``drawing.ts`` for the axis, names, labels and markers, ``bars.ts``,
``values.ts``, ``levels.ts``, ``legend.ts``); the time axis is a port of its own
(``axis``). Layers sent as levels are drawn as the browser draws them at that zoom: their
bins, or their marks there when few enough (cut from Python's, as windows are).

The SVG keeps to elements PowerPoint and Keynote import as shapes (``rect``, ``path``,
``line``, ``text``, ``g``, ``linearGradient``): no clip paths, CSS, filters or masks; what
the browser clips to the plot is cut here. Text is measured with Helvetica's widths, so it
fits where the viewer's font is about as wide.
"""

from __future__ import annotations

import itertools
import math
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import escape

import numpy as np

from anytimeline import axis as ax
from anytimeline import scene as sc
from anytimeline import stems as st
from anytimeline.codec import DTYPES, decode_strings
from anytimeline.layers import intervals as iv
from anytimeline.styling import SYMBOLS

if TYPE_CHECKING:
    from anytimeline.plot import Timeline
    from anytimeline.view import View

# the browser's sizes (js/src/core/common.ts, levels.ts, dodge.ts, legend.ts): kept equal by
# tests/test_image.py against tests/fixtures/twins.json
PAD_RIGHT = 10
PAD_BOTTOM = 8
MIN_LANE = 18
AUTO_LANE = 30
LABEL_BUDGET = 3000
ROUTE_BUDGET = 60_000
GAP_PX = 28
BIN_PX = 4
BIN_FILL = 0.8
MERGE_PX = 2
MAX_ROWS = 101
MIN_STEP = 0.6
LEGEND_ITEMS = 16

KIND_MILESTONE = 1
KIND_OPEN = 2
KIND_MERGED = 3
MERGED = 0xFFFFFFFF

FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


@dataclass(frozen=True)
class Theme:
    """The plot's colours (``js/src/widget.css``)."""

    bg: str
    text: str
    muted: str
    grid: str
    band: str
    select: str
    accent: str
    panel: tuple[str, float]
    border: str


THEMES = {
    "light": Theme(
        "#ffffff", "#1b2430", "#5e6875", "#e6e9ed", "#f7f8fa", "#e8590c", "#1f77b4",
        ("#ffffff", 0.9), "#dde1e6",
    ),
    "dark": Theme(
        "#12171d", "#e5e9ed", "#98a3af", "#252d37", "#161c23", "#ff922b", "#4dabf7",
        ("#12171d", 0.9), "#2b3440",
    ),
}  # fmt: skip

# ---------------------------------------------------------------------- text

_WIDTHS = [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
]  # fmt: skip
"""Helvetica's advance widths (1/1000 em) of the characters 32 to 126."""


def text_width(text: str, size: float, bold: bool = False) -> float:
    """About how wide ``text`` is at ``size`` px in a sans-serif font."""
    total = 0
    for c in text:
        o = ord(c)
        if 32 <= o <= 126:
            total += _WIDTHS[o - 32]
        elif unicodedata.east_asian_width(c) in "WF" or c == "…":
            total += 1000
        elif c == "\u2009":  # a thin space (digit groups)
            total += 200
        else:
            total += 556
    # a little wider than Helvetica, as the system fonts of browsers (San Francisco, Segoe UI)
    return total * size / 1000 * 1.04 * (1.06 if bold else 1)


def _ellipsize(text: str, width: float, size: float, bold: bool = False) -> str:
    """``text``, cut with … to fit ``width`` px; "" when not even … fits (``ellipsize``)."""
    if text_width(text, size, bold) <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) >> 1
        if text_width(text[:mid] + "…", size, bold) <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…"


def _fit(text: str, width: float, size: float) -> str:
    """As ``_ellipsize``, but "" when not one letter fits (bars' ``fit``)."""
    cut = _ellipsize(text, width, size)
    return "" if cut == "…" else cut


# ---------------------------------------------------------------------- SVG


def _f(v: float) -> str:
    """A coordinate: at most two decimals."""
    text = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.strip().lstrip("#")
    if len(h) in (3, 4):
        h = "".join(c + c for c in h[:3])
    v = int(h[:6], 16)
    return (v >> 16) & 255, (v >> 8) & 255, v & 255


def _hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


class _Svg:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.defs: list[str] = []

    def add(self, text: str) -> None:
        self.parts.append(text)

    def rect(
        self, x: float, y: float, w: float, h: float, fill: str, opacity: float = 1, **extra: Any
    ) -> None:
        attrs = _attrs({"fill-opacity": opacity if opacity < 1 else None, **extra})
        self.add(
            f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" fill="{fill}"{attrs}/>'
        )

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        stroke: str,
        width: float = 1,
        **extra: Any,
    ) -> None:
        attrs = _attrs(extra)
        self.add(
            f'<line x1="{_f(x1)}" y1="{_f(y1)}" x2="{_f(x2)}" y2="{_f(y2)}" stroke="{stroke}" '
            f'stroke-width="{_f(width)}"{attrs}/>'
        )

    def path(self, d: str, **attrs: Any) -> None:
        if d:
            self.add(f'<path d="{d}"{_attrs(attrs)}/>')

    def text(
        self,
        text: str,
        x: float,
        y: float,
        size: float,
        fill: str,
        *,
        anchor: str = "start",
        middle: bool = False,
        bold: bool = False,
        weight: int | None = None,
        halo: str | None = None,
    ) -> None:
        """Text at (x, y): its baseline there, or with ``middle`` its middle."""
        if not text:
            return
        if middle:
            y += size * 0.35
        attrs = f'x="{_f(x)}" y="{_f(y)}" font-size="{_f(size)}"'
        if anchor != "start":
            attrs += f' text-anchor="{anchor}"'
        if bold or weight:
            attrs += f' font-weight="{weight or 600}"'
        body = escape(text)
        if halo:
            self.add(
                f'<text {attrs} fill="none" stroke="{halo}" stroke-width="3" '
                f'stroke-linejoin="round">{body}</text>'
            )
        self.add(f'<text {attrs} fill="{fill}">{body}</text>')

    def gradient(self, x0: float, x1: float, stops: list[tuple[float, str, float]]) -> str:
        """A horizontal gradient from x0 to x1 (stops: offset, colour, opacity); its url."""
        gid = f"g{len(self.defs)}"
        body = "".join(
            f'<stop offset="{_f(o)}" stop-color="{c}" stop-opacity="{_f(a)}"/>' for o, c, a in stops
        )
        self.defs.append(
            f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{_f(x0)}" y1="0" '
            f'x2="{_f(x1)}" y2="0">{body}</linearGradient>'
        )
        return f"url(#{gid})"


def _path(points: Sequence[tuple[float, float]], *, close: bool = False) -> str:
    """Path data through ``points``."""
    head, *rest = points
    d = f"M{_f(head[0])} {_f(head[1])}" + "".join(f"L{_f(x)} {_f(y)}" for x, y in rest)
    return d + "Z" if close else d


def _attrs(attrs: Mapping[str, Any]) -> str:
    out = ""
    for k, v in attrs.items():
        if v is None:
            continue
        out += f' {k.replace("_", "-")}="{_f(v) if isinstance(v, float) else v}"'
    return out


def symbol_path(s: int, x: float, y: float, r: float) -> str:
    """Symbol ``s`` of radius ``r`` at (x, y) as SVG path data (``tracePath``)."""
    b = s - 8 if s >= 8 else s

    def poly(pts: list[tuple[float, float]]) -> str:
        head = f"M{_f(x + pts[0][0])} {_f(y + pts[0][1])}"
        return head + "".join(f"L{_f(x + u)} {_f(y + v)}" for u, v in pts[1:]) + "Z"

    if b == 0:
        return (
            f"M{_f(x + r)} {_f(y)}A{_f(r)} {_f(r)} 0 1 0 {_f(x - r)} {_f(y)}"
            f"A{_f(r)} {_f(r)} 0 1 0 {_f(x + r)} {_f(y)}Z"
        )
    if b == 1:
        h = r * 0.886
        return poly([(-h, -h), (h, -h), (h, h), (-h, h)])
    if b == 2:
        h = r * 1.25
        return poly([(0, -h), (h, 0), (0, h), (-h, 0)])
    if b in (3, 4):
        big = r * 1.1
        up = -1 if b == 3 else 1
        ry = big * 2 / math.sqrt(3)
        return poly([(0, up * ry), (big, -up * ry / 2), (-big, -up * ry / 2)])
    if b == 5:
        return poly(_plus(r, r * 0.3))
    if b == 6:
        q = math.sqrt(0.5)
        return poly([((u - v) * q, (u + v) * q) for u, v in _plus(r * 1.1, r * 0.28)])
    w = max(0.8, r * 0.2)
    return poly([(-w, -r * 1.2), (w, -r * 1.2), (w, r * 1.2), (-w, r * 1.2)])


def _plus(arm: float, w: float) -> list[tuple[float, float]]:
    return [
        (-w, -arm), (w, -arm), (w, -w), (arm, -w), (arm, w), (w, w), (w, arm), (-w, arm),
        (-w, w), (-arm, w), (-arm, -w), (-w, -w),
    ]  # fmt: skip


# ---------------------------------------------------------------------- the browser's maths


def bar_box(
    lane: float,
    row: float,
    rows: float,
    lane_top: float,
    lane_h: float,
    fill: float,
    max_bar: float,
    progress: float = -1,
) -> tuple[float, float]:
    """Where a bar is drawn: centre y and height (``barBox``)."""
    pitch = lane_h * fill / max(1, rows)
    h = min(pitch * (0.85 if rows > 1.5 else 1), max_bar)
    if progress < -1.5:
        h *= -progress - 2
    return lane_top + (lane + 0.5) * lane_h + (row - (rows - 1) * 0.5) * pitch, h


def spacing(lane_h: float, size: float, pairs: float) -> float:
    """The distance between sub-rows of dodged marks (``dodge.ts``)."""
    lo = max(2.5, size * MIN_STEP)
    hi = size + 1
    if pairs <= 0:
        return hi
    margin = max(3, lane_h * 0.1)
    room = (lane_h / 2 - size / 2 - margin) / pairs
    return max(lo, min(hi, room))


def rows_for(lane_h: float, size: float, step: float) -> int:
    pairs = math.floor((lane_h / 2 - size / 2 - 1) / step)
    return max(1, min(MAX_ROWS, 1 + 2 * max(0, pairs)))


def _row_offset(r: int) -> float:
    return 0 if r == 0 else -(r + 1) / 2 if r % 2 == 1 else r / 2


def dodge(xs: np.ndarray, min_dist: float, rows: int) -> np.ndarray:
    """Each mark's sub-row offset (in steps), greedily from left to right (``dodge``)."""
    last = [-math.inf] * max(1, rows)
    out = np.zeros(len(xs))
    for i, x in enumerate(xs.tolist()):
        chosen = -1
        for r, at in enumerate(last):
            if x - at >= min_dist:
                chosen = r
                break
        if chosen < 0:
            chosen = min(range(len(last)), key=last.__getitem__)
        last[chosen] = x
        out[i] = _row_offset(chosen)
    return out


def events_level(top: float, scale: float) -> int:
    """The finest level of an events layer whose bins are at least BIN_PX wide."""
    bins = top * scale / BIN_PX
    return math.floor(math.log(bins) / math.log(4)) if bins > 0 else 0


def values_level(top: float, px: float) -> int:
    """The coarsest level of a values layer whose bins are at most a pixel wide."""
    bins = top * px
    return math.ceil(math.log(bins) / math.log(4)) if bins > 1 else 0


def bars_level(top: float, scale: float) -> int:
    """The coarsest level of an intervals layer whose bins are at most MERGE_PX wide."""
    bins = top * scale / MERGE_PX
    return math.ceil(math.log(bins) / math.log(4)) if bins > 1 else 0


def find_gaps(times: np.ndarray | None) -> list[tuple[float, float]]:
    """Long gaps between consecutive instants on the Order scale (``findGaps``)."""
    if times is None or len(times) < 3:
        return []
    diffs = np.diff(times)
    ordered = np.sort(diffs)
    median = ordered[len(ordered) // 2]
    mean = ordered.sum() / len(ordered)
    threshold = median * 20 if median > 0 else mean * 10
    most = max(1, len(diffs) // 50)
    if len(ordered) > most:
        threshold = max(threshold, ordered[len(ordered) - most - 1])
    if not threshold > 0:
        return []
    at = np.nonzero(diffs > threshold)[0]
    return [(float(i) + 0.5, float(diffs[i])) for i in at]


class _Sequence:
    """Every instant's time, in the order (the Order scale)."""

    def __init__(self, times: np.ndarray) -> None:
        self.times = times
        self.count = len(times)

    def time(self, r: int) -> float:
        return float(self.times[r])

    def lower(self, t: float) -> int:
        return int(np.searchsorted(self.times, t, "left"))

    def upper(self, t: float) -> int:
        return int(np.searchsorted(self.times, t, "right"))

    def position(self, t: np.ndarray) -> np.ndarray:
        """The x of times on the Order scale (``Sequence.position``)."""
        n = self.count
        times = self.times
        j = np.searchsorted(times, t, "left")
        out = np.empty(len(t))
        jc = np.minimum(j, n - 1)
        exact = (j < n) & (times[jc] == t)
        t0 = times[np.clip(j - 1, 0, n - 1)]
        t1 = times[jc]
        with np.errstate(divide="ignore", invalid="ignore"):
            frac = np.where(t1 > t0, (t - t0) / (t1 - t0), 1.0)
        out[:] = j - 1 + frac
        out[j == 0] = -0.5
        out[j >= n] = n - 0.5
        out[exact] = j[exact]
        return out


# ---------------------------------------------------------------------- the picture


@dataclass
class _Frame:
    width: int
    height: int  # the stage's (the plot without its title)
    fs: int
    axis_h: int
    gutter: float
    pad_right: float
    lane_h: float
    scroll: float
    left: float
    right: float
    lane_at: list[int]
    slot: np.ndarray
    order: bool
    theme: Theme
    mark_scale: float
    dodge: bool
    fade: bool
    marks: dict[str, np.ndarray] = field(default_factory=dict)
    plot: tuple[float, float, float, float] = (0, 0, 0, 0)
    scale: float = 1.0
    lane_top: float = 0.0

    def __post_init__(self) -> None:
        w = max(10, self.width - self.gutter - self.pad_right)
        self.plot = (self.gutter, self.axis_h, w, max(10, self.height - self.axis_h - PAD_BOTTOM))
        self.scale = w / (self.right - self.left)
        self.lane_top = self.axis_h - self.scroll

    def px(self, x: Any) -> Any:
        return self.plot[0] + (x - self.left) * self.scale

    def rows(self) -> tuple[int, int]:
        _, py, _, ph = self.plot
        l0 = max(0, math.floor((py - self.lane_top) / self.lane_h))
        l1 = min(len(self.lane_at) - 1, math.floor((py + ph - self.lane_top) / self.lane_h))
        return l0, l1

    def font(self, delta: int) -> int:
        return max(6, self.fs + delta)


class _Buffers:
    """The buffers of a spec: the plot's, and those of windows cut for the picture."""

    def __init__(self, buffers: Mapping[str, bytes]) -> None:
        self.buffers = dict(buffers)

    def add(self, encoded: list[Any]) -> None:
        for enc in encoded:
            self.buffers[enc.id] = enc.data

    def arr(self, ref: Mapping[str, Any]) -> np.ndarray:
        return np.frombuffer(self.buffers[ref["id"]], dtype=DTYPES[ref["dtype"]])

    def strings(self, ref: Mapping[str, Any]) -> list[str]:
        return decode_strings(dict(ref), self.buffers[ref["id"]])


def svg(
    plot: Timeline,
    *,
    width: int = 960,
    height: int | None = None,
    view: View | None = None,
    theme: str = "light",
) -> str:
    """The plot as an SVG document (``Timeline.to_svg``)."""
    if theme not in THEMES:
        raise ValueError(f"theme must be one of {list(THEMES)}, got {theme!r}")
    if not isinstance(width, int) or isinstance(width, bool) or width < 120:
        raise ValueError(f"width must be a whole number of pixels, at least 120, got {width!r}")
    if height is not None and (
        not isinstance(height, int) or isinstance(height, bool) or height < 0
    ):
        raise ValueError(f"height must be a whole number of pixels or None, got {height!r}")
    made = plot._scene
    if made is None or not made.spec.get("layers"):
        raise ValueError("the plot has no layers to draw")
    return _Picture(
        plot, made, width, plot.height if height is None else height, view, THEMES[theme]
    ).draw()


class _Picture:
    def __init__(
        self,
        plot: Timeline,
        made: sc.Scene,
        width: int,
        height: int,
        view: View | None,
        theme: Theme,
    ) -> None:
        self.plot = plot
        self.scene = made
        self.spec = made.spec
        self.data = _Buffers(made.buffers)
        self.theme = theme
        self.svg = _Svg()
        spec = self.spec
        self.time_axis = ax.TimeAxis(spec["time"])
        seq = made.sequence
        if seq is None and spec.get("sequence"):
            seq = np.asarray(self.data.arr(spec["sequence"]["times"]), dtype=np.float64)
        self.seq = (
            _Sequence(np.asarray(seq, dtype=np.float64)) if seq is not None and len(seq) else None
        )
        self.order = plot.xscale == "order" and self.seq is not None
        if spec["time"]["kind"] == "order":
            self.order = False  # its time is the order already
        fs = plot.font_size
        self.title = plot.title
        self.title_h = ax.js_round(fs * 2.4) if self.title else 0
        names = [str(n) for n in spec["lanes"]["names"]]
        self.names = names
        tree = spec["lanes"].get("tree")
        self.tree = tree
        is_open = list(tree["open"]) if tree else []
        if view is None:
            view = plot.view
        top_lane = view.lanes[0] if view.lanes else None
        if top_lane is not None and tree and top_lane in names:
            lane = names.index(top_lane)
            for k in range(min(lane, len(tree["size"]))):
                if k + tree["size"][k] > lane:
                    is_open[k] = True
        self.is_open = is_open
        lane_at, slot = self._rows(len(names))
        # sizes, as the browser's layout
        axis_h = ax.js_round(44 * fs / 12)
        min_lane = max(MIN_LANE, ax.js_round(fs * 1.5))
        self.legend = self._legend_rows(fs) if plot.legend else []
        legend_w = self._legend_width(fs)
        if spec["lanes"].get("show_names") is False:
            gutter = 12.0
        else:
            w = 0.0
            for i, n in enumerate(names[:2000]):
                indent = (
                    self._indent(fs, tree["depth"][i]) if tree and i < len(tree["depth"]) else 0
                )
                w = max(w, indent + text_width(n, fs))
            gutter = float(ax.js_round(min(width * (0.35 if tree else 0.3), max(48, w + 20))))
        self.legend_column = bool(self.legend) and width - gutter - legend_w - 24 >= 360
        pad_right = legend_w + 20 if self.legend_column else PAD_RIGHT
        rows = max(1, len(lane_at))
        if height:
            stage_h = max(120, height - self.title_h)
        else:
            plot_h = max(min(560, max(80, rows * AUTO_LANE)), rows * min_lane)
            stage_h = axis_h + PAD_BOTTOM + plot_h
        plot_h = max(10, stage_h - axis_h - PAD_BOTTOM)
        lane_h = max(min_lane, plot_h / rows)
        if tree and tree.get("compact"):
            lane_h = max(min_lane, min(lane_h, ax.js_round(fs * 2.4)))
        scroll = 0.0
        if top_lane is not None and top_lane in names:
            scroll = max(0, int(slot[names.index(top_lane)])) * lane_h
        scroll = max(0.0, min(max(0.0, rows * lane_h - plot_h), scroll))
        marks = {k: np.frombuffer(v, dtype="<i4") for k, v in plot._marks.items()}
        left, right = self._range(view)
        self.f = _Frame(
            width=width, height=stage_h, fs=fs, axis_h=axis_h, gutter=gutter, pad_right=pad_right,
            lane_h=lane_h, scroll=scroll, left=left, right=right, lane_at=lane_at, slot=slot,
            order=self.order, theme=theme, mark_scale=plot.mark_scale, dodge=plot.dodge,
            fade=any(len(m) for m in marks.values()), marks=marks,
        )  # fmt: skip
        self.in_view = 0
        """Marks in view, as the browser counts them: labels only below LABEL_BUDGET."""
        self.raw_layers: list[tuple[dict[str, Any], dict[str, Any]]] = []
        """Events layers drawn mark by mark (their labels go beside them)."""
        self.binned: set[str] = set()
        """Events layers drawn as bins (their selection as rings over them)."""
        self.values_drawn: list[tuple[np.ndarray, np.ndarray]] = []
        """Per values layer drawn: its runs' lanes and its lanes' bands (the scales)."""
        self.stems_fit: set[str] = set()
        """Stems layers whose text is in boxes on stems (else beside the marks)."""

    # -- rows, sizes and range

    def _rows(self, n: int) -> tuple[list[int], np.ndarray]:
        tree = self.tree
        slot = np.full(n, -1, dtype=np.int64)
        at: list[int] = []
        lane = 0
        while lane < n:
            slot[lane] = len(at)
            at.append(lane)
            folds = tree and lane < len(tree["size"]) and not self.is_open[lane]
            lane += tree["size"][lane] if folds else 1
        return at, slot

    def _indent(self, fs: int, depth: int) -> float:
        return 6 + depth * ax.js_round(fs * 0.9) + ax.js_round(fs * 1.1)

    def _range(self, view: View) -> tuple[float, float]:
        """The view's x range: the view set (or shown), else the whole timeline."""
        plot = self.plot
        lo, hi = (float(v) for v in self.spec["time"]["extent"])
        if view.start is None and view.end is None:
            if self.order:
                assert self.seq is not None
                lo, hi = -0.5, max(0.5, self.seq.count - 0.5)
            return _fit_range(lo, hi, 0.03, self.spec["time"])
        a = plot._ticks(view.start) if view.start is not None else lo
        b = plot._ticks(view.end) if view.end is not None else hi
        if self.order:
            assert self.seq is not None
            a, b = self.seq.lower(a) - 0.5, self.seq.upper(b) - 0.5
        return _fit_range(a, b, 0.0, self.spec["time"])

    # -- drawing

    def draw(self) -> str:
        f = self.f
        t = self.theme
        s = self.svg
        width, total_h = f.width, f.height + self.title_h
        s.rect(0, 0, width, total_h, t.bg)
        if self.title:
            s.text(self.title, 10, self.title_h / 2 + 2, f.fs + 2, t.text, middle=True, bold=True)
        s.add(f'<g transform="translate(0 {self.title_h})">' if self.title_h else "<g>")
        l0, l1 = f.rows()
        ticks = self._axis_ticks()
        gaps = self._visible_gaps(ticks.pinned) if f.order else []
        self._bands(l0, l1)
        self._grid(ticks, gaps)
        if any(ly.get("labels") == "stems" for ly in self._layers("events")):
            px, _, pw, _ = f.plot
            for r in range(l0, l1 + 1):
                y = ax.js_round(f.lane_top + (r + 0.5) * f.lane_h) - 1
                self._clipped_rect(px, y, pw, 2, t.muted, 0.5)
        for spec in self._layers("values"):
            self._values(spec, l0, l1)
        bars = [self._bars_of(spec) for spec in self._layers("intervals")]
        for b in bars:
            if b is not None:
                self._draw_bars(b, l0, l1)
        for spec in self._layers("events"):
            self._events(spec, l0, l1)
        # the front: axis, names, text, markers
        self._axis(ticks)
        self._lanes(l0, l1)
        for b in bars:
            if b is not None:
                self._bar_front(b, l0, l1, self.in_view <= LABEL_BUDGET)
        for spec, data in self.raw_layers:
            if spec.get("labels") == "stems" and self._stems(spec, data, l0, l1):
                self.stems_fit.add(spec["name"])
        self._marked(l0, l1)
        if self.in_view <= LABEL_BUDGET:
            self._labels(l0, l1)
        self._notes()
        self._markers()
        self._value_scales(l0, l1)
        if gaps:
            self._gap_marks(gaps)
        self._draw_legend()
        s.add("</g>")
        defs = f"<defs>{''.join(s.defs)}</defs>" if s.defs else ""
        head = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{total_h}" '
            f'viewBox="0 0 {width} {total_h}" font-family="{FONT}">'
        )
        title = f"<title>{escape(self.title)}</title>" if self.title else ""
        return head + title + defs + "".join(s.parts) + "</svg>\n"

    def _layers(self, kind: str) -> list[dict[str, Any]]:
        return [ly for ly in self.spec["layers"] if ly["type"] == kind]

    def _clipped_rect(
        self, x: float, y: float, w: float, h: float, fill: str, opacity: float = 1
    ) -> None:
        """A rectangle cut to the plot."""
        px, py, pw, ph = self.f.plot
        x0, x1 = max(x, px), min(x + w, px + pw)
        y0, y1 = max(y, py), min(y + h, py + ph)
        if x1 > x0 and y1 > y0:
            self.svg.rect(x0, y0, x1 - x0, y1 - y0, fill, opacity)

    def _bands(self, l0: int, l1: int) -> None:
        f, t = self.f, self.theme
        _, py, _, ph = f.plot
        headers = set(self.tree.get("header") or []) if self.tree else set()
        for r in range(l0, l1 + 1):
            y = f.lane_top + r * f.lane_h
            y0, y1 = max(y, py), min(y + f.lane_h, py + ph)
            if y1 <= y0:
                continue
            if f.lane_at[r] in headers:
                self.svg.rect(0, y0, f.width, y1 - y0, t.grid, 0.55)
                if y >= py:
                    self.svg.rect(0, round(y), f.width, 1, t.muted)
            elif r % 2 == 1:
                self.svg.rect(0, y0, f.width, y1 - y0, t.band)

    def _axis_ticks(self) -> ax.AxisTicks:
        f = self.f
        width = f.plot[2]
        target = width * 11 / (f.fs - 1)
        kind = self.spec["time"]["kind"]
        if f.order or kind == "order":
            order = ax.TimeAxis(
                {"kind": "order", "unit": "", "origin_ns": "0", "origin": 0, "timezone": "UTC"}
            )
            t = order.ticks(f.left, f.right, target)
            if self.seq is not None and self.seq.count and kind != "order":
                i = max(0, min(self.seq.count - 1, math.ceil(f.left)))
                t.pinned = f"from {self.time_axis.format_full(self.seq.time(i))}"
            return t
        return self.time_axis.ticks(f.left, f.right, target)

    def _grid(self, ticks: ax.AxisTicks, gaps: list[tuple[float, str | None]]) -> None:
        f, t = self.f, self.theme
        _, py, _, ph = f.plot
        for x, _label in gaps:
            gx = round(x) + 0.5
            self.svg.line(gx, py, gx, py + ph, t.grid, stroke_dasharray="2 3")
        for tick in ticks.minor:
            x = round(f.px(tick.x)) + 0.5
            self.svg.line(x, py, x, py + ph, t.grid)

    def _axis(self, ticks: ax.AxisTicks) -> None:
        f, t, s = self.f, self.theme, self.svg
        px, _, pw, _ = f.plot
        s.rect(0, 0, f.width, f.axis_h, t.bg)
        s.line(px, f.axis_h - 0.5, px + pw, f.axis_h - 0.5, t.muted)
        size = f.font(-1)
        last_end = -math.inf
        marks: list[str] = []
        for tick in ticks.minor:
            x = f.px(tick.x)
            mx = round(x) + 0.5
            if px <= mx <= px + pw:
                marks.append(f"M{_f(mx)} {f.axis_h - 5}V{f.axis_h}")
            if x < px or x > px + pw:
                continue
            w = text_width(tick.label, size)
            cx = min(px + pw - w / 2, max(px + w / 2, x))
            if cx - w / 2 > last_end + 6:
                s.text(
                    tick.label,
                    cx,
                    f.axis_h - ax.js_round(f.fs * 0.75),
                    size,
                    t.text,
                    anchor="middle",
                )
                last_end = cx + w / 2
        s.path("".join(marks), stroke=t.muted, fill="none")
        # context row: boundaries, and the unit of the left edge pinned there
        y = ax.js_round(f.fs * 1.25)
        pinned_end = px + 4 + text_width(ticks.pinned, size)
        first = f.px(ticks.context[0].x) if ticks.context else math.inf
        if ticks.pinned and first > pinned_end + 8:
            s.text(_ellipsize(ticks.pinned, pw - 4, size), px + 4, y, size, t.muted)
        for c in ticks.context:
            x = f.px(c.x)
            if x < px - 1 or x > px + pw:
                continue
            s.rect(round(x), 4, 1, ax.js_round(f.fs * 1.17), t.muted)
            room = px + pw - (x + 4)
            if room > 8:
                s.text(_ellipsize(c.label, room, size), x + 4, y, size, t.muted)

    def _lanes(self, l0: int, l1: int) -> None:
        f, t, s = self.f, self.theme, self.svg
        px, py, _, ph = f.plot
        lanes = self.spec["lanes"]
        if lanes.get("show_names") is not False:
            tree = self.tree
            headers = set(tree.get("header") or []) if tree else set()
            tri = max(3, ax.js_round(f.fs * 0.32))
            for r in range(l0, l1 + 1):
                lane = f.lane_at[r]
                y = f.lane_top + (r + 0.5) * f.lane_h
                if y < py or y > py + ph:
                    continue
                name = self.names[lane]
                if not tree or lane >= len(tree["depth"]):
                    s.text(
                        _ellipsize(name, px - 12, f.fs),
                        px - 8,
                        y,
                        f.fs,
                        t.text,
                        anchor="end",
                        middle=True,
                    )
                    continue
                x = self._indent(f.fs, tree["depth"][lane])
                folded = not self.is_open[lane]
                if tree["size"][lane] > 1:
                    cx = x - ax.js_round(f.fs * 0.6)
                    if folded:
                        pts = [
                            (cx - tri * 0.6, y - tri),
                            (cx + tri * 0.8, y),
                            (cx - tri * 0.6, y + tri),
                        ]
                    else:
                        pts = [
                            (cx - tri, y - tri * 0.6),
                            (cx + tri, y - tri * 0.6),
                            (cx, y + tri * 0.8),
                        ]
                    d = "M" + "L".join(f"{_f(a)} {_f(b)}" for a, b in pts) + "Z"
                    s.path(d, fill=t.muted)
                bold = lane in headers
                room = px - 8 - x
                shown = _ellipsize(name, room, f.fs, bold)
                if folded and tree["size"][lane] > 1:
                    more = f" +{ax.fmt_number(tree['size'][lane] - 1)}"
                    if text_width(name + more, f.fs, bold) <= room and shown == name:
                        s.text(name, x, y, f.fs, t.text, middle=True, bold=bold)
                        s.text(
                            more, x + text_width(name, f.fs, bold), y, f.fs, t.muted, middle=True
                        )
                        continue
                s.text(shown, x, y, f.fs, t.text, middle=True, bold=bold)
        if lanes.get("title"):
            size = f.font(-1)
            title = _ellipsize(lanes["title"], px - 12, size)
            s.text(title, px - 8, f.axis_h - ax.js_round(f.fs * 0.75), size, t.muted, anchor="end")
        total = len(f.lane_at) * f.lane_h
        if total > ph + 1:  # a scroll bar: there are more lanes than the picture shows
            s.rect(f.width - 5, py, 3, ph, t.grid)
            s.rect(f.width - 5, py + f.scroll / total * ph, 3, max(12, ph / total * ph), t.muted)

    # -- events

    def _events(self, spec: dict[str, Any], l0: int, l1: int) -> None:
        name = spec["name"]
        levels = spec.get("levels")
        if levels:
            got = self._event_window(spec, levels, l0, l1)
            if got is None:
                return
            if got[0] == "bins":
                self._bins(spec, got[1], l0, l1)
                return
            data = self._decode_events(got[1])
            index = self.data.arr(got[1]["index"])
        else:
            data = self._decode_events(spec)
            index = None
        selected = self._selected(name, data["count"], index)
        self._draw_events(spec, data, selected, l0, l1)

    def _event_window(
        self, spec: dict[str, Any], levels: dict[str, Any], l0: int, l1: int
    ) -> tuple[str, dict[str, Any]] | None:
        """What the browser draws of an events layer sent as levels: ("events", a window's
        spec) when few enough are in view, else ("bins", a level's)."""
        f = self.f
        scale = "order" if f.order else "time"
        d = self.scene.detail.get(spec["name"])
        if not isinstance(d, sc.Detail):
            return None
        x = d.x[scale]
        lane = d.layout.marks.lane
        count = 0
        for r in range(l0, l1 + 1):
            i0 = int(np.searchsorted(lane, f.lane_at[r], "left"))
            i1 = int(np.searchsorted(lane, f.lane_at[r], "right"))
            seg = x[i0:i1]
            count += int(
                np.searchsorted(seg, f.right, "right") - np.searchsorted(seg, f.left, "left")
            )
        if count <= levels["raw"]:
            answer, buffers = self.scene.window(spec["name"], scale, f.left, f.right, None)
            self.data.add(buffers)
            return "events", answer["spec"]
        pyramid = levels[scale]
        want = events_level(pyramid["top"], f.scale)
        sent = pyramid["levels"]
        if sent and want > sent[-1]["k"] and levels["windows"]:
            answer, buffers = self.scene.window(spec["name"], scale, f.left, f.right, want)
            if answer["range"][0] <= f.left and answer["range"][1] >= f.right:
                self.data.add(buffers)
                return "bins", answer["spec"]
        if not sent:
            return None
        at = 0
        for i, level in enumerate(sent):
            if level["k"] <= want:
                at = i
        return "bins", sent[at]

    def _decode_events(self, spec: dict[str, Any]) -> dict[str, Any]:
        d = self.data
        n = spec["count"]
        x = d.arr(spec["rank"] if self.f.order else spec["time"]).astype(np.float64)
        size = (
            d.arr(spec["size"]["values"]).astype(np.float64)
            if spec["size"]["values"]
            else np.full(n, float(spec["size"]["value"] or 8))
        ) * self.f.mark_scale
        symbol = (
            d.arr(spec["symbol"]["values"]).astype(np.int64)
            if spec["symbol"]["values"]
            else np.full(
                n, max(0, _symbol_index(spec["symbol"]["value"] or "circle")), dtype=np.int64
            )
        )
        return {
            "count": n,
            "x": x,
            "lane": d.arr(spec["lane"]).astype(np.int64),
            "starts": d.arr(spec["lane_starts"]).astype(np.int64),
            "size": size,
            "color": self._colors(spec["color"], d, n),
            "symbol": symbol,
            "text": d.strings(spec["text"]) if spec.get("text") else None,
            "importance": d.arr(spec["importance"]) if spec.get("importance") else None,
            "segments": d.arr(spec["route"]["segments"]) if spec.get("route") else None,
        }

    def _colors(self, color: dict[str, Any], d: _Buffers, n: int) -> np.ndarray:
        """RGBA bytes per mark: its own, the layer's colour, or the theme's accent."""
        if color.get("rgba"):
            return d.arr(color["rgba"]).reshape(-1, 4).astype(np.int64)
        solid = color.get("solid")
        hex_color = self.theme.accent if not solid or solid == "theme" else solid
        out = np.empty((n, 4), dtype=np.int64)
        out[:, :3] = _rgb(hex_color)
        out[:, 3] = color.get("alpha", 255)
        return out

    def _selected(self, name: str, n: int, index: np.ndarray | None) -> np.ndarray:
        """Which of these marks are selected (``index``: each one's among the layer's)."""
        marks = self.f.marks.get(name)
        if marks is None or not len(marks):
            return np.zeros(n, dtype=bool)
        if index is None:
            out = np.zeros(n, dtype=bool)
            out[marks[(marks >= 0) & (marks < n)]] = True
            return out
        return np.isin(index.astype(np.int64), marks.astype(np.int64))

    def _cull(
        self, x: np.ndarray, starts: np.ndarray, l0: int, l1: int, a: float, b: float
    ) -> np.ndarray:
        """The marks of the lanes on rows l0..l1 from a to b."""
        f = self.f
        parts = []
        for r in range(max(0, l0), min(l1, len(f.lane_at) - 1) + 1):
            lane = f.lane_at[r]
            if lane + 1 >= len(starts):
                continue
            s0, s1 = int(starts[lane]), int(starts[lane + 1])
            i0 = s0 + int(np.searchsorted(x[s0:s1], a, "left"))
            i1 = i0 + int(np.searchsorted(x[i0:s1], b, "right"))
            parts.append(np.arange(i0, i1))
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.int64)

    def _draw_events(
        self, spec: dict[str, Any], data: dict[str, Any], selected: np.ndarray, l0: int, l1: int
    ) -> None:
        f, t = self.f, self.theme
        px, py, pw, ph = f.plot
        x, size = data["x"], data["size"]
        margin = 12 / f.scale
        vis = self._cull(x, data["starts"], l0, l1, f.left - margin, f.left + pw / f.scale + margin)
        self.in_view += len(vis)
        dy = np.zeros(data["count"])
        if spec.get("overlap") == "dodge" and f.dodge and spec.get("labels") != "stems":
            dy = self._dodge(data, l0, l1)
        rows = f.slot[data["lane"][vis]]
        xs = f.px(x[vis])
        ys = f.lane_top + (rows + 0.5) * f.lane_h + dy[vis]
        rs = size[vis] / 2
        col = data["color"][vis]
        alpha = col[:, 3] / 255 * np.where(f.fade & ~selected[vis], 0.2, 1)
        # the browser clips marks at the plot's edges; a picture leaves out those whose centre
        # is outside it
        keep = (ys >= py) & (ys <= py + ph) & (xs >= px) & (xs <= px + pw)
        groups: dict[tuple[int, int, int, float, bool], list[str]] = {}
        sym = data["symbol"][vis]
        for j in np.nonzero(keep)[0].tolist():
            c = col[j]
            key = (int(c[0]), int(c[1]), int(c[2]), round(float(alpha[j]), 2), bool(sym[j] >= 8))
            groups.setdefault(key, []).append(
                symbol_path(int(sym[j]), float(xs[j]), float(ys[j]), float(rs[j]))
            )
        for (r, g, b, a, hollow), paths in groups.items():
            color = _hex(r, g, b)
            opacity = a if a < 1 else None
            if hollow:
                self.svg.path(
                    "".join(paths),
                    fill="none",
                    stroke=color,
                    stroke_width=1.6,
                    stroke_opacity=opacity,
                )
            else:
                self.svg.path("".join(paths), fill=color, fill_opacity=opacity)
        rings = [
            symbol_path(0, float(xs[j]), float(ys[j]), float(rs[j]) + 2)
            for j in np.nonzero(keep & selected[vis])[0].tolist()
        ]
        if rings:
            self.svg.path("".join(rings), fill="none", stroke=t.select, stroke_width=1.8)
        self._routes(spec, data, dy, l0, l1)
        self.raw_layers.append(
            (
                spec,
                {
                    **data,
                    "vis": vis[keep],
                    "xs": xs[keep] - px,
                    "ys": ys[keep],
                    "selected": selected,
                },
            )
        )

    def _dodge(self, data: dict[str, Any], l0: int, l1: int) -> np.ndarray:
        """Each mark's vertical offset: those that would overlap spread over sub-rows
        (``dodgeLayer``), over three views of time as the browser does."""
        f = self.f
        x, sizes, starts = data["x"], data["size"], data["starts"]
        span = f.right - f.left
        a, b = f.left - span, f.right + span
        dy = np.zeros(data["count"])
        ranges = []
        max_size = 1.0
        for r in range(max(0, l0 - 2), min(l1 + 2, len(f.lane_at) - 1) + 1):
            lane = f.lane_at[r]
            if lane + 1 >= len(starts):
                continue
            s0, s1 = int(starts[lane]), int(starts[lane + 1])
            i0 = s0 + int(np.searchsorted(x[s0:s1], a, "left"))
            i1 = i0 + int(np.searchsorted(x[i0:s1], b, "right"))
            if i1 > i0:
                max_size = max(max_size, float(sizes[i0:i1].max()))
            ranges.append((i0, i1))
        rows = rows_for(f.lane_h, max_size, spacing(f.lane_h, max_size, math.inf))
        for i0, i1 in ranges:
            dy[i0:i1] = dodge((x[i0:i1] - f.left) * f.scale, max_size * 0.85, rows)
        pairs = max((float(np.abs(dy[i0:i1]).max()) for i0, i1 in ranges if i1 > i0), default=0.0)
        return dy * spacing(f.lane_h, max_size, pairs)

    def _routes(
        self, spec: dict[str, Any], data: dict[str, Any], dy: np.ndarray, l0: int, l1: int
    ) -> None:
        route = spec.get("route")
        seg = data["segments"]
        if not route or seg is None or not route["count"]:
            return
        f, t = self.f, self.theme
        pw = f.plot[2]
        x, lane, col = data["x"], data["lane"], data["color"]
        right = f.left + pw / f.scale
        solid = route.get("color")
        color = (t.text if solid == "theme" else solid) if solid else None
        by_color: dict[str, list[str]] = {}
        n = 0
        for k in range(route["count"]):
            if n >= ROUTE_BUDGET:
                break
            i, j = int(seg[2 * k]), int(seg[2 * k + 1])
            xa, xb = x[i], x[j]
            if (xa < f.left and xb < f.left) or (xa > right and xb > right):
                continue
            la, lb = int(f.slot[lane[i]]), int(f.slot[lane[j]])
            if la < 0 or lb < 0 or (la < l0 and lb < l0) or (la > l1 and lb > l1):
                continue
            ya = f.lane_top + (la + 0.5) * f.lane_h + dy[i]
            yb = f.lane_top + (lb + 0.5) * f.lane_h + dy[j]
            cut = _clip_segment(f.px(xa), ya, f.px(xb), yb, f.plot)
            if cut is None:
                continue
            c = color or _hex(int(col[i][0]), int(col[i][1]), int(col[i][2]))
            by_color.setdefault(c, []).append(
                f"M{_f(cut[0])} {_f(cut[1])}L{_f(cut[2])} {_f(cut[3])}"
            )
            n += 1
        for c, parts in by_color.items():
            self.svg.path(
                "".join(parts),
                fill="none",
                stroke=c,
                stroke_width=float(route["width"]),
                stroke_opacity=0.55,
            )

    def _bins(self, layer: dict[str, Any], spec: dict[str, Any], l0: int, l1: int) -> None:
        """A level's bins: of many events a bar from the first to the last, as tall as its
        count (on a log scale); of one event that event (``BinsLayer``)."""
        f, d = self.f, self.data
        px, py, pw, ph = f.plot
        n = spec["count"]
        starts = d.arr(spec["lane_starts"]).astype(np.int64)
        lo, hi = d.arr(spec["lo"]), d.arr(spec["hi"])
        counts = d.arr(spec["n"]).astype(np.int64)
        lanes = np.repeat(np.arange(len(starts) - 1), np.diff(starts))
        color = self._colors({**layer["color"], "rgba": spec.get("rgba")}, d, n)
        symbol = (
            d.arr(spec["symbol"]).astype(np.int64)
            if spec.get("symbol")
            else np.full(n, max(0, _symbol_index(layer["symbol"]["value"] or "circle")))
        )
        size = (
            d.arr(spec["size"]).astype(np.float64)
            if spec.get("size")
            else np.full(n, float(layer["size"]["value"] or 8))
        ) * f.mark_scale
        top = math.log1p(max(2, spec["most"]))
        vis = []
        for r in range(l0, l1 + 1):
            lane = f.lane_at[r]
            if lane + 1 >= len(starts):
                continue
            s0, s1 = int(starts[lane]), int(starts[lane + 1])
            i0 = s0 + int(np.searchsorted(hi[s0:s1], f.left, "left"))
            i1 = i0 + int(np.searchsorted(lo[i0:s1], f.right, "right"))
            vis.extend(range(i0, i1))
        self.in_view += int(counts[vis].sum()) if vis else 0
        marks: dict[tuple[int, int, int, float], list[str]] = {}
        for i in vis:
            row = int(f.slot[lanes[i]])
            c = color[i]
            if counts[i] > 1:
                x0, x1 = f.px(lo[i]), f.px(hi[i])
                x1 = max(x1, x0 + 1)
                cy, h = bar_box(
                    row,
                    0,
                    1,
                    f.lane_top,
                    f.lane_h,
                    BIN_FILL,
                    1e6,
                    -2 - max(0.22, math.log1p(counts[i]) / top),
                )
                a0 = max(x0, px - 8)
                b0 = min(max(x1 - (1 if x1 - x0 > 3 else 0), x0 + 1), px + pw + 8)
                self._clipped_rect(
                    a0, cy - h / 2, max(1, b0 - a0), h, _hex(*c[:3].tolist()), c[3] / 255
                )
            else:
                x = f.px(lo[i])
                y = f.lane_top + (row + 0.5) * f.lane_h
                r = size[i] / 2
                if px <= x <= px + pw and py <= y <= py + ph:
                    key = (int(c[0]), int(c[1]), int(c[2]), round(c[3] / 255, 2))
                    marks.setdefault(key, []).append(symbol_path(int(symbol[i]), x, y, r))
        for (r, g, b, a), paths in marks.items():
            self.svg.path("".join(paths), fill=_hex(r, g, b), fill_opacity=a if a < 1 else None)
        self.binned.add(layer["name"])

    def _marked(self, l0: int, l1: int) -> None:
        """The selected events of layers drawn as bins: rings over the bins (``drawMarked``)."""
        f = self.f
        px, py, pw, ph = f.plot
        r = max(2.5, min(5, f.lane_h * 0.22))
        rings = []
        for name in self.binned:
            at = self.plot._marked.get(name)
            if not at:
                continue
            rows = np.frombuffer(at, dtype="<f8").reshape(-1, 3)
            for t, order, lane in rows.tolist():
                row = int(f.slot[int(lane)])
                if row < l0 or row > l1 or row < 0:
                    continue
                x = f.px(order if f.order else t)
                y = f.lane_top + (row + 0.5) * f.lane_h
                if px - r <= x <= px + pw + r and py <= y <= py + ph:
                    rings.append(symbol_path(0, x, y, r))
        if rings:
            self.svg.path("".join(rings), fill="none", stroke=self.theme.select, stroke_width=2)

    def _labels(self, l0: int, l1: int) -> None:
        """Events' text beside their marks, the more important first, none over another."""
        f, t = self.f, self.theme
        px, py, pw, ph = f.plot
        size = f.font(-1)
        half = f.fs / 2
        for spec, data in self.raw_layers:
            text = data["text"]
            if not text or spec["name"] in self.stems_fit:
                continue
            vis, xs, ys = data["vis"], data["xs"], data["ys"]
            order = list(range(len(vis)))
            imp = data["importance"]
            if imp is not None:
                order.sort(key=lambda j: (-float(imp[vis[j]]), float(xs[j])))
            taken: list[tuple[float, float, float, float]] = []
            for j in order:
                label = text[int(vis[j])]
                if not label:
                    continue
                x = px + float(xs[j]) + float(data["size"][vis[j]]) / 2 + 3
                y = float(ys[j])
                w = text_width(label, size)
                box = (x, y - half, x + w, y + half)
                if any(
                    box[0] < q[2] + 2 and box[2] + 2 > q[0] and box[1] < q[3] and box[3] > q[1]
                    for q in taken
                ):
                    continue
                taken.append(box)
                if y < py or y > py + ph or x > px + pw:
                    continue
                shown = _ellipsize(label, px + pw - x, size)
                self.svg.text(shown, x, y, size, t.text, middle=True, halo=t.bg)
                if len(taken) > LABEL_BUDGET:
                    break

    def _stems(self, spec: dict[str, Any], data: dict[str, Any], l0: int, l1: int) -> bool:
        """The text of a stems layer in boxes above and below its lanes' lines, joined to the
        events by stems; events without room for a box counted in badges ("+N")
        (``drawStems``). False when the lanes have no room for a level of boxes."""
        f, t, s = self.f, self.theme, self.svg
        text = data["text"]
        if not text:
            return False
        px, _, pw, _ = f.plot
        shape = "curved" if spec.get("stem_shape") == "curved" else "straight"
        line_h = ax.js_round(f.fs * 1.3)
        pad_x, pad_y, gap = 9, 5, 7
        sizes = data["size"]
        mark_r = max(2.0, float(sizes[:1000].max()) / 2) if len(sizes) else 2.0
        start = mark_r + (26 if shape == "curved" else 12)
        title_size, time_size, badge_size = max(6, f.fs - 1), max(6, f.fs - 2.5), max(6, f.fs - 2)
        width = spec.get("label_width")
        max_w = math.inf if width == 0 else float(width) if width is not None else 16.0 * f.fs
        x, starts, imp = data["x"], data["starts"], data["importance"]
        lines_of: dict[int, list[tuple[str, bool]]] = {}
        per_row: dict[int, list[st.StemItem]] = {}
        most = 1
        # laid out over the view (the browser lays them out over three, to pan)
        for r in range(max(0, l0 - 1), min(l1 + 1, len(f.lane_at) - 1) + 1):
            lane = f.lane_at[r]
            if lane + 1 >= len(starts):
                continue
            s0, s1 = int(starts[lane]), int(starts[lane + 1])
            i0 = s0 + int(np.searchsorted(x[s0:s1], f.left, "left"))
            i1 = i0 + int(np.searchsorted(x[i0:s1], f.right, "right"))
            items = []
            for i in range(i0, i1):
                if not text[i]:
                    continue
                parts = text[i].split("\n")
                head = parts[0] if len(parts) > 1 else None
                body = " ".join(parts if head is None else parts[1:])
                inner = max_w - 2 * pad_x
                lines = (
                    [(h, True) for h in st.wrap_text(head, inner, 1, _measure(time_size))]
                    if head is not None
                    else []
                )
                lines += [(b, False) for b in st.wrap_text(body, inner, 2, _measure(title_size))]
                lines_of[i] = lines
                most = max(most, len(lines))
                w = max(text_width(tx, time_size if hd else title_size) for tx, hd in lines)
                importance = float(imp[i]) if imp is not None else 0.0
                items.append(
                    st.StemItem(
                        i, float(x[i] - f.left) * f.scale, math.ceil(w) + 2 * pad_x, importance
                    )
                )
            per_row[r] = items
        box_h = most * line_h + 2 * pad_y
        levels = st.levels_for(f.lane_h, box_h, gap, start)
        if levels <= 0:
            return False
        if f.order and self.seq is not None:
            ext = (-0.5, self.seq.count - 0.5)
        else:
            ext = tuple(self.spec["time"]["extent"])
        left = (max(f.left, ext[0]) - f.left) * f.scale
        right = max(left, (min(f.right, ext[1]) - f.left) * f.scale)
        space = {
            "levels": levels,
            "gap": gap,
            "inset": 12,
            "left": left,
            "right": right,
            "shape": shape,
        }
        placed: dict[int, list[st.StemPlaced]] = {}
        clusters: dict[int, tuple[int, int, float, float]] = {}  # badge: n, row, px0, px1
        on_line: list[int] = []
        badge_index = -1
        for r, items in per_row.items():
            first = st.place_stems(items, **space)
            boxed = {p.index for p in first}
            hidden = [(it.index, it.x) for it in items if it.index not in boxed]
            if not hidden:
                placed[r] = first
                continue
            badges = []
            boxed_xs = [it.x for it in items if it.index in boxed]
            for c in st.cluster_hidden(hidden, 48, boxed_xs):
                w = math.ceil(text_width(f"+{len(c.indices)}", badge_size, bold=True)) + 16
                badges.append(st.StemItem(badge_index, (c.x0 + c.x1) / 2, w, -math.inf, badge=True))
                clusters[badge_index] = (len(c.indices), r, c.x0, c.x1)
                badge_index -= 1
            every = st.place_stems([*items, *badges], **space)
            placed[r] = every
            put = {p.index for p in every}
            on_line += [b.index for b in badges if b.index not in put]
        bg, ink, muted = _rgb(t.bg), _rgb(t.text), _rgb(t.muted)
        color = data["color"]

        def rgb(i: int) -> tuple[float, ...]:
            return (
                tuple(float(v) for v in muted) if i < 0 else tuple(float(v) for v in color[i][:3])
            )

        def mix(a: Sequence[float], b: Sequence[float], k: float) -> str:
            return _hex(*(ax.js_round(u + (v - u) * k) for u, v in zip(a, b, strict=True)))

        shown = []
        for r, boxes in placed.items():
            if r < l0 or r > l1:
                continue
            cy = f.lane_top + (r + 0.5) * f.lane_h
            for p in boxes:
                x0 = px + p.x0
                if x0 > px + pw or x0 + p.w < px:
                    continue
                shown.append(
                    (p, cy, x0, cy + st.level_offset(p.level, box_h, gap, start) - box_h / 2)
                )
        badge_h = line_h + 4
        for p, cy, _x0, top in shown:
            up = p.level > 0
            badge = p.index < 0
            ex, cx = px + p.x, px + p.cx
            y0 = cy + (-mark_r - 2 if up else mark_r + 2)
            y1 = (
                top + box_h / 2 + (badge_h / 2 if up else -badge_h / 2)
                if badge
                else top + box_h
                if up
                else top
            )
            d = f"M{_f(ex)} {_f(y0)}"
            if abs(cx - ex) > 0.5:  # an S-curve next to the line, then straight to the box
                bend = cy + (-start + 4 if up else start - 4)
                mid = (y0 + bend) / 2
                d += f"C{_f(ex)} {_f(mid)} {_f(cx)} {_f(mid)} {_f(cx)} {_f(bend)}"
            d += f"L{_f(cx)} {_f(y1)}"
            s.path(
                d,
                fill="none",
                stroke=mix(rgb(p.index), rgb(p.index), 0),
                stroke_opacity=0.7 if badge else 0.85,
                stroke_width=1.0 if badge else 1.4,
                stroke_linecap="round",
                stroke_dasharray="2 3" if badge else None,
            )
        rings = [
            symbol_path(0, px + p.x, cy, mark_r + 1) for p, cy, _x0, _top in shown if p.index >= 0
        ]
        s.path("".join(rings), fill="none", stroke=t.bg, stroke_width=2)
        for p, _cy, x0, top in shown:
            i = p.index
            if i < 0:
                n = clusters[i][0]
                by = round(top + box_h / 2 - badge_h / 2) + 0.5
                bx = round(x0) + 0.5
                s.rect(
                    bx,
                    by,
                    p.w,
                    badge_h,
                    mix(bg, muted, 0.12),
                    rx=_f(badge_h / 2),
                    stroke=mix(bg, muted, 0.5),
                )
                s.text(
                    f"+{n}",
                    x0 + p.w / 2,
                    by + badge_h / 2,
                    badge_size,
                    t.muted,
                    anchor="middle",
                    middle=True,
                    bold=True,
                )
                continue
            c = rgb(i)
            selected = bool(data["selected"][i])
            bx, by = round(x0) + 0.5, round(top) + 0.5
            s.rect(bx, by + 1.5, p.w, box_h, "#0f172a", 0.06, rx=6)  # a soft shadow
            edge = t.select if selected else mix(bg, c, 0.45)
            width = 2 if selected else None
            s.rect(bx, by, p.w, box_h, mix(bg, c, 0.09), rx=6, stroke=edge, stroke_width=width)
            for k, (line, head) in enumerate(lines_of.get(i, [])):
                fill = mix(c, ink, 0.35) if head else t.text
                y = top + pad_y + line_h * (k + 0.5)
                s.text(
                    line,
                    x0 + pad_x,
                    y,
                    time_size if head else title_size,
                    fill,
                    middle=True,
                    weight=500,
                )
        for index in on_line:  # badges on the line: a capsule around their events, "+N" after
            n, row, c0, c1 = clusters[index]
            if row < l0 or row > l1:
                continue
            cy = f.lane_top + (row + 0.5) * f.lane_h
            label = f"+{n}"
            h = max(2 * mark_r + 8, f.fs + 4)
            x0 = px + c0 - mark_r - 5
            x1 = px + c1 + mark_r + 7 + text_width(label, badge_size, bold=True) + 6
            if x1 < px or x0 > px + pw:
                continue
            s.rect(
                round(x0) + 0.5,
                round(cy - h / 2) + 0.5,
                x1 - x0,
                h,
                "none",
                rx=_f(h / 2),
                stroke=mix(bg, muted, 0.6),
            )
            s.text(
                label, x1 - 6, cy + 0.5, badge_size, t.muted, anchor="end", middle=True, bold=True
            )
        return True

    # -- bars

    def _bars_of(self, spec: dict[str, Any]) -> dict[str, Any] | None:
        """The bars the browser draws of an intervals layer: all of them, or for a layer sent
        as levels a level's or a window's."""
        levels = spec.get("levels")
        if not levels:
            return self._decode_bars(spec)
        f = self.f
        scale = "order" if f.order else "time"
        pyramid = levels[scale]
        sent = pyramid["levels"]
        if not sent:
            return None
        want = bars_level(pyramid["top"], f.scale)
        at = len(sent) - 1
        for i in range(len(sent) - 1, -1, -1):
            if sent[i]["k"] >= want:
                at = i
        d = self.scene.detail.get(spec["name"])
        few = False
        if isinstance(d, sc.BarDetail):
            x_lo, x_hi = d.x[scale]
            rows = iv.window_rows(x_lo, x_hi, d.bars.lane_starts, f.left, f.right)
            few = 0 < len(rows) <= levels["raw"]
        if levels["windows"] and (want > sent[-1]["k"] or few):
            k = max(want, sent[-1]["k"] + 1)
            answer, buffers = self.scene.window(spec["name"], scale, f.left, f.right, k)
            if answer["range"][0] <= f.left and answer["range"][1] >= f.right:
                self.data.add(buffers)
                return self._decode_bars(answer["spec"])
        return self._decode_bars(sent[at])

    def _decode_bars(self, spec: dict[str, Any]) -> dict[str, Any]:
        d = self.data
        n = spec["count"]
        rank = d.arr(spec["rank"]).astype(np.float64).reshape(-1, 2) if n else np.zeros((0, 2))
        if self.f.order:
            lo, hi = rank[:, 0].copy(), rank[:, 1].copy()
        else:
            lo, hi = d.arr(spec["start"]).astype(np.float64), d.arr(spec["end"]).astype(np.float64)
        lane = d.arr(spec["lane"]).astype(np.int64)
        starts = d.arr(spec["lane_starts"]).astype(np.int64)
        color = self._colors(spec["color"], d, n)
        if spec.get("alpha"):
            a = d.arr(spec["alpha"]).astype(np.int64)
            color[:, 3] = np.floor(color[:, 3] * a / 255 + 0.5).astype(np.int64)
        max_dur = np.zeros(max(0, len(starts) - 1))
        if n:
            np.maximum.at(max_dur, lane, hi - lo)
        index = d.arr(spec["index"]).astype(np.int64) if spec.get("index") else None
        return {
            "spec": spec,
            "count": n,
            "lo": lo,
            "hi": hi,
            "lane": lane,
            "starts": starts,
            "row": d.arr(spec["row"]).astype(np.float64),
            "rows": d.arr(spec["rows"]).astype(np.float64),
            "kind": d.arr(spec["kind"]).astype(np.int64),
            "color": color,
            "progress": d.arr(spec["progress"]) if spec.get("progress") else None,
            "text": d.strings(spec["text"]) if spec.get("text") else None,
            "links": d.arr(spec["links"]["pairs"]) if spec.get("links") else None,
            "critical": d.arr(spec["critical"]["segments"])
            if (spec.get("critical") or {}).get("count")
            else None,
            "max_dur": max_dur,
            "selected": self._selected(
                spec["name"], n, np.where(index == MERGED, -1, index) if index is not None else None
            ),
            "start": d.arr(spec["start"]).astype(np.float64),
            "end": d.arr(spec["end"]).astype(np.float64),
        }

    def _bar_cull(self, b: dict[str, Any], l0: int, l1: int) -> np.ndarray:
        f = self.f
        a, z = f.left - 2 / f.scale, f.right + 2 / f.scale
        lo, hi, starts = b["lo"], b["hi"], b["starts"]
        parts = []
        for r in range(l0, l1 + 1):
            lane = f.lane_at[r]
            if lane + 1 >= len(starts):
                continue
            s0, s1 = int(starts[lane]), int(starts[lane + 1])
            i0 = s0 + int(np.searchsorted(lo[s0:s1], a - b["max_dur"][lane], "left"))
            i1 = i0 + int(np.searchsorted(lo[i0:s1], z, "right"))
            idx = np.arange(i0, i1)
            parts.append(idx[hi[idx] >= a])
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.int64)

    def _max_bar(self, b: dict[str, Any]) -> float:
        return 1e6 if b["spec"]["height"] >= 0.99 else max(16, ax.js_round(self.f.fs * 2.2))

    def _box(self, b: dict[str, Any], i: int) -> tuple[float, float, float, float, bool]:
        f = self.f
        x0, x1 = f.px(b["lo"][i]), f.px(b["hi"][i])
        cy, h = bar_box(
            int(f.slot[b["lane"][i]]),
            b["row"][i],
            b["rows"][i],
            f.lane_top,
            f.lane_h,
            b["spec"]["height"],
            self._max_bar(b),
        )
        return x0, max(x1, x0 + 1), cy, h, bool(b["kind"][i] == KIND_MILESTONE)

    def _draw_bars(self, b: dict[str, Any], l0: int, l1: int) -> None:
        """Bars in view (``drawBars``): rectangles, milestones as diamonds, the part past the
        progress lighter, open bars fading out, selected ones outlined."""
        f, t, s = self.f, self.theme, self.svg
        px, py, pw, ph = f.plot
        vis = self._bar_cull(b, l0, l1)
        b["vis"] = vis
        self.in_view += len(vis)
        bg = _rgb(t.bg)
        fades = b["spec"].get("fade_open") is not False
        outlines: list[str] = []
        for i in vis.tolist():
            x0, x1, cy, h, milestone = self._box(b, i)
            c = b["color"][i]
            selected = bool(b["selected"][i])
            a = c[3] / 255 * (0.22 if f.fade and not selected else 1)
            rgb = _hex(*c[:3].tolist())
            if milestone:
                r = h * 0.62
                if x0 + r < px or x0 - r > px + pw or cy + r < py or cy - r > py + ph:
                    continue
                d = _path([(x0, cy - r), (x0 + r, cy), (x0, cy + r), (x0 - r, cy)], close=True)
                s.path(d, fill=rgb, fill_opacity=a if a < 1 else None)
                if selected:
                    outlines.append(d)
                continue
            # the browser's ends (a little past the plot), then cut to it
            a0 = max(x0, px - 8)
            w = max(1, min(max(x1 - (1 if x1 - x0 > 3 else 0), x0 + 1), px + pw + 8) - a0)
            c0, c1 = max(a0, px), min(a0 + w, px + pw)
            y0, y1 = max(cy - h / 2, py), min(cy + h / 2, py + ph)
            if c1 <= c0 or y1 <= y0:
                continue
            fill = rgb
            opacity = a
            if b["kind"][i] == KIND_OPEN and fades:
                stops = [(0, rgb, a), (max(0, 1 - 48 / w), rgb, a), (1, rgb, a * 0.12)]
                fill, opacity = s.gradient(a0, a0 + w, stops), 1
            s.rect(c0, y0, c1 - c0, y1 - y0, fill, opacity)
            p = b["progress"][i] if b["progress"] is not None else -1
            if p >= 0:
                cut = max(c0, min(c1, x0 + p * (x1 - x0)))
                light = tuple(
                    ax.js_round(v * 0.45 + bg[k] * 0.55) for k, v in enumerate(c[:3].tolist())
                )
                if c1 > cut:
                    s.rect(cut, y0, c1 - cut, y1 - y0, _hex(*light), a)
            if selected:
                o0, o1 = max(a0 - 1.5, px - 2), min(a0 + w + 1.5, px + pw + 2)
                outlines.append(
                    f"M{_f(o0)} {_f(cy - h / 2 - 1.5)}H{_f(o1)}V{_f(cy + h / 2 + 1.5)}H{_f(o0)}Z"
                )
        if outlines:
            s.path("".join(outlines), fill="none", stroke=t.select, stroke_width=1.8)

    def _bar_front(self, b: dict[str, Any], l0: int, l1: int, labels: bool) -> None:
        self._links(b, l0, l1)
        self._critical(b, l0, l1)
        if labels:
            self._bar_labels(b)

    def _links(self, b: dict[str, Any], l0: int, l1: int) -> None:
        """Arrows of dependencies (``drawLinks``)."""
        pairs = b["links"]
        if pairs is None:
            return
        f, t = self.f, self.theme
        px, _, pw, _ = f.plot
        lo, hi = b["lo"], b["hi"]
        right = f.left + pw / f.scale
        lines, heads = [], []
        for k in range(len(pairs) // 2):
            i, j = int(pairs[2 * k]), int(pairs[2 * k + 1])
            ra, rb = int(f.slot[b["lane"][i]]), int(f.slot[b["lane"][j]])
            if ra < 0 or rb < 0 or (ra < l0 and rb < l0) or (ra > l1 and rb > l1):
                continue
            if (hi[i] < f.left and lo[j] < f.left) or (hi[i] > right and lo[j] > right):
                continue
            pa, pb = self._box(b, i), self._box(b, j)
            axx = pa[0] + pa[3] * 0.62 if pa[4] else pa[1]
            bx = pb[0] - pb[3] * 0.62 if pb[4] else pb[0]
            ay, by = pa[2], pb[2]
            if bx - axx >= 14:
                pts = [(axx, ay), (axx + 6, ay), (axx + 6, by), (bx - 1, by)]
            else:
                if by > ay:
                    my = max(ay + pa[3] / 2 + 3, by - pb[3] / 2 - 3)
                else:
                    my = min(ay - pa[3] / 2 - 3, by + pb[3] / 2 + 3)
                pts = [
                    (axx, ay),
                    (axx + 6, ay),
                    (axx + 6, my),
                    (bx - 8, my),
                    (bx - 8, by),
                    (bx - 1, by),
                ]
            if all(x < px or x > px + pw for x, _ in pts):
                continue
            lines.append("M" + "L".join(f"{_f(x)} {_f(y)}" for x, y in pts))
            if px <= bx <= px + pw:
                heads.append(
                    f"M{_f(bx)} {_f(by)}L{_f(bx - 6)} {_f(by - 3.5)}L{_f(bx - 6)} {_f(by + 3.5)}Z"
                )
        self.svg.path("".join(lines), fill="none", stroke=t.muted, stroke_width=1.2)
        self.svg.path("".join(heads), fill=t.muted)

    def _critical(self, b: dict[str, Any], l0: int, l1: int) -> None:
        """The critical path: a line through each part of a bar on it (``drawCritical``)."""
        seg = b["critical"]
        if seg is None:
            return
        f = self.f
        px, _, pw, _ = f.plot
        right = f.left + pw / f.scale
        parts = []
        for k in range(0, len(seg) - 2, 3):
            i = int(seg[k])
            row = int(f.slot[b["lane"][i]])
            if row < l0 or row > l1:
                continue
            code_a, code_b = int(seg[k + 1]), int(seg[k + 2])
            ta = (b["lo"] if code_a & 1 == 0 else b["hi"])[code_a >> 1]
            tb = (b["lo"] if code_b & 1 == 0 else b["hi"])[code_b >> 1]
            if tb < f.left or ta > right:
                continue
            cy = self._box(b, i)[2]
            x0 = f.px(ta)
            x1 = max(x0 + 1, f.px(tb))
            parts.append(
                f"M{_f(max(x0, px - 2) + 1)} {_f(cy)}L{_f(min(x1, px + pw + 2) - 1)} {_f(cy)}"
            )
        self.svg.path(
            "".join(parts),
            fill="none",
            stroke=self.theme.text,
            stroke_width=2,
            stroke_linecap="round",
        )

    def _bar_labels(self, b: dict[str, Any]) -> None:
        """Text in bars where it fits, milestones' beside them, durations right of the bars
        (``BarLayer.drawLabels``)."""
        f, t = self.f, self.theme
        px, py, pw, ph = f.plot
        size = f.font(-1)
        text = b["text"]
        vis = b.get("vis", np.zeros(0, dtype=np.int64)).tolist()
        if b["spec"].get("durations"):
            for i in vis:
                if b["kind"][i] in (KIND_OPEN, KIND_MERGED):
                    continue
                x0, x1, cy, h, milestone = self._box(b, i)
                if not py <= cy <= py + ph or (text and text[i] and milestone):
                    continue
                label = self.time_axis.format_span(b["end"][i] - b["start"][i])
                w = text_width(label, size)
                reach = h * 0.62 if milestone else 0
                x = (x0 if milestone else x1) + reach + 5
                if x + w > px + pw:
                    x = x0 - reach - 5 - w
                if x < px or x + w > px + pw:
                    right = min(x1, px + pw) - 5
                    if milestone or (text and text[i]) or h < 9 or right - w < max(x0, px) + 5:
                        continue
                    self.svg.text(label, right - w, cy, size, self._ink_on(b, i), middle=True)
                    continue
                self.svg.text(label, x, cy, size, t.muted, middle=True)
        if not text:
            return
        for i in vis:
            label = text[i]
            if not label:
                continue
            x0, x1, cy, h, milestone = self._box(b, i)
            if not py <= cy <= py + ph:
                continue
            if milestone:
                x = x0 + h * 0.62 + 4
                if px <= x < px + pw:
                    self.svg.text(
                        _ellipsize(label, px + pw - x, size),
                        x,
                        cy,
                        size,
                        t.text,
                        middle=True,
                        halo=t.bg,
                    )
                continue
            left = max(x0, px) + 4
            room = min(x1, px + pw) - 4 - left
            if room < 16 or h < 9:
                continue
            fitted = _fit(label, room, size)
            if fitted:
                self.svg.text(fitted, left, cy, size, self._ink_on(b, i), middle=True)

    def _ink_on(self, b: dict[str, Any], i: int) -> str:
        c = b["color"][i]
        if c[3] < 150:
            return self.theme.text
        lum = (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255
        return "#1b2430" if lum > 0.55 else "#ffffff"

    # -- values

    def _values(self, spec: dict[str, Any], l0: int, l1: int) -> None:
        """A values layer's lines in their lanes' bands (``ValueLayer.draw``)."""
        f = self.f
        got = self._value_samples(spec)
        if got is None:
            return
        d = self.data
        time = d.arr(got["time"]).astype(np.float64)
        value = d.arr(got["value"]).astype(np.float64)
        runs = got["runs"]
        run_starts = d.arr(runs["starts"]).astype(np.int64)
        run_lane = d.arr(runs["lane"]).astype(np.int64)
        run_color = d.arr(runs["color"]).reshape(-1, 4).astype(np.int64)
        ylim = d.arr(got["ylim"]).astype(np.float64)
        color = spec["color"]
        theme_color = not color.get("legend") and (
            not color.get("solid") or color["solid"] == "theme"
        )
        xs = self.seq.position(time) if f.order and self.seq is not None else time
        px, _, pw, _ = f.plot
        right = f.left + pw / f.scale
        kind = spec["kind"]
        for k in range(len(run_starts) - 1):
            lane = int(run_lane[k])
            row = int(f.slot[lane])
            if row < l0 or row > l1 or row < 0:
                continue
            a, b = int(run_starts[k]), int(run_starts[k + 1])
            i0 = max(a, a + int(np.searchsorted(xs[a:b], f.left, "left")) - 1)
            i1 = min(b, i0 + int(np.searchsorted(xs[i0:b], right, "right")) + 1)
            if i1 <= i0:
                continue
            lo, hi = float(ylim[2 * lane]), float(ylim[2 * lane + 1])
            y_of = self._y_of(lo, hi, row)
            lines = self._points(xs, value, i0, i1, y_of, kind == "step")
            if not lines:
                continue
            if theme_color:
                rgb, alpha = self.theme.accent, 1.0
            elif color.get("solid") and not color.get("legend"):
                rgb, alpha = color["solid"], color.get("alpha", 255) / 255
            else:
                c = run_color[k]
                rgb, alpha = _hex(*c[:3].tolist()), (c[3] or 255) / 255
            clipped = [p for line in lines for p in _clip_polyline(line, px, px + pw)]
            if kind == "area":
                base = y_of(0 if lo <= 0 <= hi else lo)
                area = "".join(
                    f"M{_f(line[0][0])} {_f(base)}" + "".join(f"L{_f(x)} {_f(y)}" for x, y in line)
                    + f"L{_f(line[-1][0])} {_f(base)}Z"
                    for line in clipped
                )  # fmt: skip
                self.svg.path(area, fill=rgb, fill_opacity=0.22 * alpha)
            d_line = "".join(
                f"M{_f(line[0][0])} {_f(line[0][1])}"
                + "".join(f"L{_f(x)} {_f(y)}" for x, y in line[1:])
                for line in clipped
            )
            self.svg.path(
                d_line, fill="none", stroke=rgb, stroke_width=float(spec["width"]),
                stroke_opacity=alpha if alpha < 1 else None, stroke_linejoin="round",
            )  # fmt: skip
        self.values_drawn.append((run_lane, ylim))

    def _value_samples(self, spec: dict[str, Any]) -> dict[str, Any] | None:
        """The samples the browser draws of a values layer: all, or of one sent as levels
        those of the level the zoom needs (a window's when finer than those sent)."""
        levels = spec.get("levels")
        if not levels:
            return spec
        f = self.f
        ta, tb = f.left, f.right
        if f.order and self.seq is not None:
            n = self.seq.count
            ta = self.seq.time(max(0, min(n - 1, math.floor(f.left))))
            tb = self.seq.time(max(0, min(n - 1, math.ceil(f.right))))
        px_per = (f.right - f.left) * f.scale / (tb - ta) if tb > ta else f.scale
        want = values_level(levels["top"], px_per)
        sent = levels["levels"]
        if not sent:
            return None
        if want > sent[-1]["k"] and levels["windows"]:
            answer, buffers = self.scene.window(spec["name"], "time", ta, tb, want)
            if answer["range"][0] <= ta and answer["range"][1] >= tb:
                self.data.add(buffers)
                return answer["spec"]
        at = len(sent) - 1
        for i in range(len(sent) - 1, -1, -1):
            if sent[i]["k"] >= want:
                at = i
        return sent[at]

    def _y_of(self, lo: float, hi: float, row: int) -> Any:
        f = self.f
        pad = max(2, f.lane_h * 0.14)
        top = f.lane_top + row * f.lane_h + pad
        h = max(1, f.lane_h - 2 * pad)
        if not hi > lo:
            return lambda _v: top + h / 2
        return lambda v: top + h - (v - lo) / (hi - lo) * h

    def _points(
        self, xs: np.ndarray, val: np.ndarray, i0: int, i1: int, y_of: Any, step: bool
    ) -> list[list[tuple[float, float]]]:
        """Polylines of samples i0..i1 (a missing value starts a new one); where samples are
        denser than pixels, each pixel column's first, lowest, highest and last (``points``)."""
        f = self.f
        px_of = f.px(xs[i0:i1])
        ys = y_of(val[i0:i1])
        finite = np.isfinite(val[i0:i1])
        lines: list[list[tuple[float, float]]] = []
        line: list[tuple[float, float]] = []
        if i1 - i0 <= f.plot[2] * 2:
            last_y = math.nan
            for x, y, ok in zip(
                px_of.tolist(),
                np.broadcast_to(ys, px_of.shape).tolist(),
                finite.tolist(),
                strict=True,
            ):
                if not ok:
                    if line:
                        lines.append(line)
                    line, last_y = [], math.nan
                    continue
                if step and line:
                    line.append((x, last_y))
                line.append((x, y))
                last_y = y
            if line:
                lines.append(line)
            return lines
        col = math.nan
        first = lo = hi = last = 0.0

        def flush() -> None:
            if math.isnan(col):
                return
            line.append((col, first))
            if lo != first:
                line.append((col, lo))
            if hi != lo:
                line.append((col, hi))
            if last != hi:
                line.append((col, last))

        cols = np.floor(px_of + 0.5)
        for c, y, ok in zip(
            cols.tolist(), np.broadcast_to(ys, px_of.shape).tolist(), finite.tolist(), strict=True
        ):
            if not ok:
                flush()
                col = math.nan
                if line:
                    lines.append(line)
                line = []
                continue
            if c != col:
                flush()
                col = c
                first = lo = hi = last = y
            else:
                lo, hi, last = min(lo, y), max(hi, y), y
        flush()
        if line:
            lines.append(line)
        return lines

    def _value_scales(self, l0: int, l1: int) -> None:
        """Each values lane's high and low, small at the left of its band."""
        f = self.f
        if f.lane_h < f.fs * 3:
            return
        px = f.plot[0]
        size = f.font(-3)
        for run_lane, ylim in self.values_drawn:
            seen: set[int] = set()
            for lane in run_lane.tolist():
                row = int(f.slot[lane])
                if row < l0 or row > l1 or row < 0 or lane in seen:
                    continue
                seen.add(lane)
                lo, hi = float(ylim[2 * lane]), float(ylim[2 * lane + 1])
                if not hi >= lo:
                    continue
                y_of = self._y_of(lo, hi, row)
                self.svg.text(
                    ax.fmt_number(hi, 3), px + 3, y_of(hi), size, self.theme.muted, middle=True
                )
                if hi > lo:
                    self.svg.text(
                        ax.fmt_number(lo, 3), px + 3, y_of(lo), size, self.theme.muted, middle=True
                    )

    # -- annotations and connections

    def _place(self, t: float) -> float | None:
        """A time (ticks) on the scale drawn: itself, or its place in the order."""
        if not self.f.order:
            return t
        if self.seq is None or not self.seq.count:
            return None
        return self.seq.lower(t) - 0.5

    def _note_label(self, text: str, x: float, y: float, color: str) -> None:
        f, t = self.f, self.theme
        px, py, pw, ph = f.plot
        size = f.font(-1)
        w = text_width(text, size) + 8
        lx = max(px + 1, min(x, px + pw - w - 1))
        if y + f.fs + 4 > py + ph or lx + w > px + pw + 1:
            return
        self.svg.rect(lx, y, w, f.fs + 4, t.bg, 0.9)
        self.svg.text(text, lx + 4, y + f.fs, size, color)

    def _notes(self) -> None:
        """Annotations (bands, or a line at one time) and connections (arrows), as
        ``notes.ts`` draws them, cut to the plot."""
        notes = self.plot._notes or {}
        f, t = self.f, self.theme
        px, py, pw, ph = f.plot
        plot = f.plot
        for n in notes.get("bands") or []:
            a, b = self._place(n["x0"]), self._place(n["x1"])
            if a is None or b is None:
                continue
            y0, y1 = py, py + ph
            if n["lane"] is not None:
                row = int(f.slot[n["lane"]]) if n["lane"] < len(f.slot) else -1
                if row < 0:
                    continue
                y0 = f.lane_top + row * f.lane_h + 1
                y1 = y0 + f.lane_h - 2
            xa = f.px(a)
            xb = xa if n["point"] else max(f.px(b), xa + 1)
            if xb < px - 200 or xa > px + pw or y1 < py or y0 > py + ph:
                continue
            color = n.get("color") or t.accent
            if n["point"]:
                x = round(xa) + 0.5
                seg = _clip_segment(x, y0, x, y1, plot)
                if seg:
                    self.svg.line(*seg, color, 1.5, stroke_dasharray="2 3")
            else:
                self._clipped_rect(xa, y0, xb - xa, y1 - y0, color, 0.1)
                x0, x1, top, bottom = xa + 0.5, xb - 0.5, y0 + 0.5, y1 - 0.5
                for seg in (
                    _clip_segment(x0, top, x1, top, plot),
                    _clip_segment(x0, bottom, x1, bottom, plot),
                    _clip_segment(x0, top, x0, bottom, plot),
                    _clip_segment(x1, top, x1, bottom, plot),
                ):
                    if seg:
                        self.svg.line(*seg, color, 1, stroke_opacity=0.7)
            if n.get("text"):
                self._note_label(n["text"], xa + 3, max(py, y0) + 2, color)
        for n in notes.get("arrows") or []:
            ends = []
            for key, at in (("a", "x2"), ("b", "x")):
                e = n[key]
                lane = e["lane"]
                row = int(f.slot[lane]) if lane < len(f.slot) else -1
                if row < 0:
                    break
                x = f.px(e[("r2" if at == "x2" else "r")] if f.order else e[at])
                ends.append((x, f.lane_top + (row + 0.5) * f.lane_h))
            if len(ends) < 2:
                continue
            (xa, ya), (xb, yb) = ends
            if max(xa, xb) < px or min(xa, xb) > px + pw:
                continue
            color = n.get("color") or t.accent
            bend = max(24, min(160, abs(xb - xa) / 2))
            ex = xb - 3
            # the curve as a polyline, cut to the plot (no clip paths: slides keep shapes)
            pts = []
            for k in range(25):
                u = k / 24
                v = 1 - u
                x = (
                    v**3 * xa
                    + 3 * v * v * u * (xa + bend)
                    + 3 * v * u * u * (ex - bend)
                    + u**3 * ex
                )
                y = v**3 * ya + 3 * v * v * u * ya + 3 * v * u * u * yb + u**3 * yb
                pts.append((x, y))
            run: list[tuple[float, float]] = []
            for (x0, y0), (x1, y1) in itertools.pairwise(pts):
                seg = _clip_segment(x0, y0, x1, y1, plot)
                if seg and (not run or run[-1] == (seg[0], seg[1])):
                    run = run or [(seg[0], seg[1])]
                    run.append((seg[2], seg[3]))
                    continue
                if len(run) > 1:
                    self.svg.path(_path(run), fill="none", stroke=color, stroke_width=1.5)
                run = [(seg[0], seg[1]), (seg[2], seg[3])] if seg else []
            if len(run) > 1:
                self.svg.path(_path(run), fill="none", stroke=color, stroke_width=1.5)
            if px <= xb <= px + pw and py + 4 <= yb <= py + ph - 4:
                head = [(xb, yb), (xb - 8, yb - 4), (xb - 8, yb + 4)]
                self.svg.path(_path(head, close=True), fill=color)
            if n.get("text"):
                w = text_width(n["text"], f.font(-1)) + 8
                self._note_label(
                    n["text"], (xa + xb) / 2 - w / 2, (ya + yb) / 2 - f.fs / 2 - 2, color
                )

    # -- markers and gaps

    def _markers(self) -> None:
        f, t = self.f, self.theme
        px, py, pw, ph = f.plot
        size = f.font(-1)
        for m in self.spec.get("markers") or []:
            at = m["x"]
            if f.order:
                if self.seq is None or not self.seq.count:
                    continue
                at = self.seq.lower(at) - 0.5
            x = round(f.px(at)) + 0.5
            if x < px - 1 or x > px + pw + 1:
                continue
            color = m.get("color") or t.select
            self.svg.line(x, py, x, py + ph, color, 1.5, stroke_dasharray="5 3")
            if m.get("label"):
                w = text_width(m["label"], size) + 8
                lx = min(x + 3, px + pw - w)
                self.svg.rect(lx, py + 3, w, f.fs + 4, t.bg)
                self.svg.text(m["label"], lx + 4, py + 3 + f.fs, size, color)

    def _visible_gaps(self, pinned: str) -> list[tuple[float, str | None]]:
        """The long gaps to show on the Order scale, the longest first (``visibleGaps``)."""
        f = self.f
        seq = self.spec.get("sequence") or {}
        if seq.get("gaps"):
            rows = self.data.arr(seq["gaps"]).astype(np.float64)
            gaps = [(float(rows[i]), float(rows[i + 1])) for i in range(0, len(rows) - 1, 2)]
        else:
            gaps = find_gaps(self.seq.times if self.seq is not None else None)
        px, _, pw, _ = f.plot
        size = f.font(-1)
        candidates = [(f.px(at), span) for at, span in gaps if f.left <= at <= f.right]
        candidates = [(x, span) for x, span in candidates if px + 4 < x < px + pw - 4]
        candidates.sort(key=lambda c: -c[1])
        labels_from = px + 4 + text_width(pinned, size) + 12 if pinned else px
        shown: list[tuple[float, str | None]] = []
        labelled: list[tuple[float, float]] = []
        for x, span in candidates:
            if any(abs(g[0] - x) < GAP_PX for g in shown):
                continue
            text = self.time_axis.format_span(span)
            half = text_width(text, size) / 2 + 4
            fits = (
                x - half >= labels_from
                and x + half <= px + pw
                and not any(x - half < b and x + half > a for a, b in labelled)
            )
            if fits:
                labelled.append((x - half, x + half))
            shown.append((x, text if fits else None))
            if len(shown) >= 60:
                break
        return shown

    def _gap_marks(self, gaps: list[tuple[float, str | None]]) -> None:
        f, t = self.f, self.theme
        y = f.axis_h - 1
        d = "".join(
            _path([(x - 4, y + 3), (x - 1, y - 3)]) + _path([(x + 1, y + 3), (x + 4, y - 3)])
            for x, _ in gaps
        )
        self.svg.path(d, fill="none", stroke=t.muted, stroke_width=1.2)
        top = ax.js_round(f.fs * 1.25)
        for x, label in gaps:
            if label:
                self.svg.text(label, x, top, f.font(-1), t.muted, anchor="middle")

    # -- the legend

    def _legend_rows(self, fs: int) -> list[tuple[str, Any]]:
        """The legend as rows (``buildLegend``): ("layer", name), ("title", text),
        ("item", (icon, label)), ("more", text), ("ramp", (colours, lo, hi)), ("gap", px)."""
        layers = self.spec["layers"]
        out: list[tuple[str, Any]] = []
        for layer in layers:
            blocks: list[list[tuple[str, Any]]] = []
            color = layer["color"].get("legend")
            if color and color["kind"] == "categories":
                block: list[tuple[str, Any]] = [("title", color["title"])] if color["title"] else []
                symbol = None
                if layer["type"] == "events":
                    symbol = (
                        "circle"
                        if layer["symbol"]["values"]
                        else (layer["symbol"]["value"] or "circle")
                    )
                for item in color["items"][:LEGEND_ITEMS]:
                    icon = (
                        ("symbol", symbol, item["color"], 10)
                        if symbol
                        else ("line" if layer["type"] == "values" else "bar", item["color"])
                    )
                    block.append(("item", (icon, item["label"])))
                if len(color["items"]) > LEGEND_ITEMS:
                    block.append(("more", f"+{len(color['items']) - LEGEND_ITEMS} more"))
                blocks.append(block)
            elif color and color["kind"] == "continuous":
                block = [("title", color["title"])] if color["title"] else []
                lo, hi = color["clim"]
                block.append(
                    ("ramp", (color["colors"], ax.fmt_number(lo, 3), ax.fmt_number(hi, 3)))
                )
                blocks.append(block)
            if layer["type"] == "events":
                sym = layer["symbol"].get("legend")
                if sym:
                    rgba = layer["color"].get("rgba")
                    solid = layer["color"].get("solid")
                    ink = (
                        self.theme.muted
                        if rgba
                        else solid
                        if solid and solid != "theme"
                        else self.theme.accent
                    )
                    block = [("title", sym["title"])] if sym["title"] else []
                    for item in sym["items"][:LEGEND_ITEMS]:
                        block.append(("item", (("symbol", item["symbol"], ink, 10), item["label"])))
                    if len(sym["items"]) > LEGEND_ITEMS:
                        block.append(("more", f"+{len(sym['items']) - LEGEND_ITEMS} more"))
                    blocks.append(block)
                size = layer["size"].get("legend")
                if size:
                    block = [("title", size["title"])] if size["title"] else []
                    for item in size["items"]:
                        block.append(
                            (
                                "item",
                                (
                                    ("symbol", "circle", self.theme.muted, item["size"]),
                                    item["label"],
                                ),
                            )
                        )
                    blocks.append(block)
            if not blocks:
                continue
            if len(layers) > 1:
                out.append(("layer", layer["name"]))
            for k, block in enumerate(blocks):
                if k:
                    out.append(("gap", 6))
                out.extend(block)
        return out

    def _legend_width(self, fs: int) -> float:
        if not self.legend:
            return 0
        widest = 0.0
        for kind, value in self.legend:
            if kind == "item":
                icon, label = value
                widest = max(widest, _icon_size(icon) + 4 + text_width(label, fs))
            elif kind == "ramp":
                widest = max(widest, 120)
            elif kind in ("title", "more"):
                widest = max(widest, text_width(value, fs))
            elif kind == "layer":
                widest = max(widest, text_width(value, fs, bold=True))
        return math.ceil(widest) + 18  # padding and border

    def _draw_legend(self) -> None:
        if not self.legend:
            return
        f, t, s = self.f, self.theme, self.svg
        fs = f.fs
        line = fs * 1.35
        heights = []
        for kind, value in self.legend:
            if kind == "item":
                heights.append(max(line, _icon_size(value[0])))
            elif kind == "ramp":
                heights.append(8 + line)
            elif kind == "gap":
                heights.append(value)
            elif kind == "layer":
                heights.append(line + 4)
            else:
                heights.append(line + (2 if kind == "title" else 0))
        w = self._legend_width(fs)
        h = sum(heights) + 14
        right = f.width - (8 if self.legend_column else 14)
        x0, y0 = right - w, f.axis_h
        if not self.legend_column:
            fill, opacity = t.panel
            s.rect(x0, y0, w, h, fill, opacity, rx=4, stroke=t.border)
        x, y = x0 + 9, y0 + 7
        for (kind, value), rh in zip(self.legend, heights, strict=True):
            if kind == "layer":
                s.text(value, x, y + 4 + line / 2, fs, t.text, middle=True, bold=True)
            elif kind == "title" or kind == "more":
                s.text(value, x, y + line / 2, fs, t.muted, middle=True)
            elif kind == "item":
                icon, label = value
                size = _icon_size(icon)
                self._icon(icon, x, y + (rh - size) / 2)
                s.text(label, x + size + 4, y + rh / 2, fs, t.text, middle=True)
            elif kind == "ramp":
                colors, lo, hi = value
                stops = [(i / max(1, len(colors) - 1), c, 1.0) for i, c in enumerate(colors)]
                s.rect(x, y, 120, 8, s.gradient(x, x + 120, stops), rx=2)
                s.text(lo, x, y + 8 + line / 2, fs, t.muted, middle=True)
                s.text(hi, x + 120, y + 8 + line / 2, fs, t.muted, anchor="end", middle=True)
            y += rh

    def _icon(self, icon: tuple[Any, ...], x: float, y: float) -> None:
        s = self.svg
        if icon[0] == "symbol":
            _, name, color, size = icon
            box = size + 6
            index = max(0, _symbol_index(name))
            hollow = index >= 5
            d = symbol_path(index, x + box / 2, y + box / 2, size / 2)
            if hollow:
                s.path(d, fill="none", stroke=color, stroke_width=1.5)
            else:
                s.path(d, fill=color)
        elif icon[0] == "bar":
            s.rect(x + 1, y + 4.5, 14, 7, icon[1], rx=1.5)
        else:
            d = _path([(x + 1, y + 11), (x + 5, y + 6.5), (x + 9, y + 9.5), (x + 15, y + 4)])
            s.path(
                d,
                fill="none",
                stroke=icon[1],
                stroke_width=2,
                stroke_linejoin="round",
                stroke_linecap="round",
            )


def _measure(size: float) -> Callable[[str], float]:
    return lambda text: text_width(text, size)


def _icon_size(icon: tuple[Any, ...]) -> float:
    return icon[3] + 6 if icon[0] == "symbol" else 16


def _symbol_index(name: str) -> int:
    return SYMBOLS.index(name) if name in SYMBOLS else -1


def _fit_range(a: float, b: float, margin: float, time: Mapping[str, Any]) -> tuple[float, float]:
    """The range shown for a to b with a margin each side (``TimeCamera.fit``)."""
    lo, hi = a, b
    if not hi > lo:
        per = ax.UNIT_NS.get(time.get("unit") or "", 1)
        least = 0.05 / per if time["kind"] in ("datetime", "duration") else 1e-9
        pad = max(abs(lo) * 1e-6, least) * 50
        lo, hi = lo - pad, hi + pad
    pad = (hi - lo) * margin
    return lo - pad, hi + pad


def _clip_segment(
    x0: float, y0: float, x1: float, y1: float, plot: tuple[float, float, float, float]
) -> tuple[float, float, float, float] | None:
    """A segment cut to the plot (Liang–Barsky), or None when outside it."""
    px, py, pw, ph = plot
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - px), (dx, px + pw - x0), (-dy, y0 - py), (dy, py + ph - y0)):
        if p == 0:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            return None
    return x0 + t0 * dx, y0 + t0 * dy, x0 + t1 * dx, y0 + t1 * dy


def _clip_polyline(
    line: list[tuple[float, float]], a: float, b: float
) -> list[list[tuple[float, float]]]:
    """The parts of a polyline from x = a to x = b."""
    if len(line) == 1:
        return [line] if a <= line[0][0] <= b else []
    out: list[list[tuple[float, float]]] = []
    part: list[tuple[float, float]] = []
    for (x0, y0), (x1, y1) in itertools.pairwise(line):
        dx = x1 - x0
        if dx == 0:
            t_in, t_out = (0.0, 1.0) if a <= x0 <= b else (1.0, 0.0)
        else:
            ta, tb = (a - x0) / dx, (b - x0) / dx
            t_in, t_out = max(0.0, min(ta, tb)), min(1.0, max(ta, tb))
        if t_in > t_out:
            if part:
                out.append(part)
                part = []
            continue
        if not part or t_in > 0:
            if part:
                out.append(part)
            part = [(x0 + t_in * dx, y0 + t_in * (y1 - y0))]
        part.append((x0 + t_out * dx, y0 + t_out * (y1 - y0)))
        if t_out < 1:
            out.append(part)
            part = []
    if part:
        out.append(part)
    return out


def png(svg_text: str, scale: float = 2) -> bytes:
    """An SVG drawn as a PNG at ``scale`` pixels per pixel, with ``resvg-py``."""
    try:
        import resvg_py
    except ImportError:
        raise ImportError(
            "PNG images need resvg-py: pip install 'anytimeline[png]' (or save an .svg)"
        ) from None
    return bytes(resvg_py.svg_to_bytes(svg_string=svg_text, zoom=float(scale)))


def save(plot: Timeline, path: Any, **options: Any) -> None:
    """Write ``plot`` as ``path``: .svg, or .png (``scale`` pixels per pixel)."""
    from pathlib import Path

    target = Path(path)
    suffix = target.suffix.lower()
    scale = options.pop("scale", 2)
    if suffix not in (".svg", ".png"):
        raise ValueError(
            f"save_image writes .svg or .png files, not {suffix or 'files without a suffix'!r}"
        )
    text = svg(plot, **options)
    if suffix == ".svg":
        target.write_text(text, encoding="utf-8")
    else:
        target.write_bytes(png(text, scale))


__all__ = ["THEMES", "Theme", "png", "save", "svg", "text_width"]
