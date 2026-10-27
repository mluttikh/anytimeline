"""Encodings: colours, symbols and sizes per event, decided in Python and sent as bytes.

The argument names follow one vocabulary on every layer: ``color=`` (a column or one
colour), ``colormap=``, ``clim=``, ``palette=``, ``opacity=``, ``symbol=``, ``symbols=``,
``size=``, ``size_range=``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, get_args

import numpy as np

from anytimeline.data import is_missing
from anytimeline.types import Symbol

TAB10 = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]  # fmt: skip
"""matplotlib's tab10: the categorical colours, in order."""

MISSING_COLOR = "#a8adb3"
"""Rows without a colour value."""

SYMBOLS = get_args(Symbol)
"""The shapes of events; a category column gets them in this order."""

DEFAULT_SIZE = 8.0
"""Diameter of a mark in CSS pixels."""

_COLORMAPS = {
    "viridis": [
        "#440154", "#472d7b", "#3b528b", "#2c728e", "#21918c",
        "#28ae80", "#5ec962", "#addc30", "#fde725",
    ],
    "magma": [
        "#000004", "#1c1044", "#4f127b", "#812581", "#b5367a",
        "#e55064", "#fb8761", "#fec287", "#fcfdbf",
    ],
    "Blues": [
        "#f7fbff", "#deebf7", "#c6dbef", "#9dcae1", "#6aaed6",
        "#4191c6", "#2070b4", "#08509b", "#08306b",
    ],
    "Reds": [
        "#fff5f0", "#fee0d2", "#fcbba1", "#fc9272", "#fb694a",
        "#ee3a2c", "#ca181d", "#a30f15", "#67000d",
    ],
    "RdBu": [
        "#67001f", "#b2182b", "#d6604d", "#f4a582", "#fddbc7", "#f7f7f7",
        "#d1e5f0", "#92c5de", "#4393c3", "#2166ac", "#053061",
    ],
}  # fmt: skip
_COLORMAPS["RdBu_r"] = _COLORMAPS["RdBu"][::-1]

_NAMED = {
    "black": "#000000", "white": "#ffffff", "gray": "#808080", "grey": "#808080",
    "red": "#d62728", "green": "#2ca02c", "blue": "#1f77b4", "orange": "#ff7f0e",
    "purple": "#9467bd", "brown": "#8c564b", "pink": "#e377c2", "olive": "#bcbd22",
    "cyan": "#17becf", "yellow": "#ffd43b", "teal": "#0ca678", "navy": "#1c3d78",
    "transparent": "#00000000",
}  # fmt: skip
_NAMED.update({f"tab:{n}": c for n, c in zip(
    ("blue", "orange", "green", "red", "purple", "brown", "pink", "gray", "olive", "cyan"),
    TAB10, strict=True,
)})  # fmt: skip
_HEX = re.compile(r"^#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def rgba(color: str) -> tuple[int, int, int, int]:
    """A CSS hex colour or a basic name as RGBA bytes."""
    text = _NAMED.get(color.strip().lower(), color.strip())
    m = _HEX.match(text)
    if not m:
        raise ValueError(
            f"unknown colour {color!r}; use a hex colour such as '#1f77b4' or a basic name"
        )
    h = m.group(1)
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h)
    if len(h) == 6:
        h += "ff"
    r, g, b, a = (int(h[i : i + 2], 16) for i in range(0, 8, 2))
    return r, g, b, a


def is_color(text: str) -> bool:
    try:
        rgba(text)
    except ValueError:
        return False
    return True


def hex_of(color: tuple[int, int, int, int] | Sequence[int]) -> str:
    return "#" + "".join(f"{int(c):02x}" for c in color[:3])


def colormap_colors(name: str | Sequence[str]) -> list[str]:
    """The anchor colours of a colormap: a built-in name, a matplotlib name, or a list."""
    if not isinstance(name, str):
        return list(name)
    if name in _COLORMAPS:
        return _COLORMAPS[name]
    try:
        import matplotlib as mpl  # ty: ignore[unresolved-import]
    except ImportError:
        raise ValueError(
            f"unknown colormap {name!r}; built in: {sorted(_COLORMAPS)} (any matplotlib name "
            "works when matplotlib is installed)"
        ) from None
    try:
        cmap = mpl.colormaps[name]
    except KeyError:
        raise ValueError(f"unknown colormap {name!r}") from None
    return [hex_of([round(255 * v) for v in cmap(i / 15)]) for i in range(16)]


def sample_colormap(name: str | Sequence[str], positions: np.ndarray) -> np.ndarray:
    """RGB bytes of a colormap at positions in [0, 1], interpolated between its anchors."""
    anchors = np.array([rgba(c)[:3] for c in colormap_colors(name)], dtype=np.float64)
    x = np.clip(positions, 0, 1) * (len(anchors) - 1)
    lo = np.floor(x).astype(int).clip(0, len(anchors) - 2)
    f = (x - lo)[:, None]
    return np.round(anchors[lo] * (1 - f) + anchors[lo + 1] * f).astype(np.uint8)


def natural_key(value: Any) -> tuple[Any, ...]:
    """Numbers before text, numbers by value, text with its digits compared as numbers."""
    if isinstance(value, bool | np.bool_):
        return (0, float(value))
    if isinstance(value, int | float | np.integer | np.floating):
        return (0, float(value))
    parts = re.split(r"(\d+)", str(value))
    return (1, *((0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts if p))


def label(value: Any) -> str:
    """A value as text: whole numbers without ".0", other numbers to 6 significant digits."""
    if isinstance(value, bool | np.bool_):
        return str(bool(value))
    if isinstance(value, float | np.floating):
        return f"{float(value):g}"
    return str(value)


def ordered_categories(
    values: np.ndarray, declared: list[Any] | None = None, order: Sequence[Any] | None = None
) -> list[Any]:
    """The distinct present values: ``order`` first, then the declared order (Enum,
    Categorical), then the rest sorted naturally."""
    present = values[~is_missing(values)]
    distinct = list(dict.fromkeys(present.tolist()))
    head = [v for v in (order or []) if v in distinct]
    head += [v for v in (declared or []) if v in distinct and v not in head]
    rest = sorted((v for v in distinct if v not in head), key=natural_key)
    return head + rest


def is_continuous(values: np.ndarray) -> bool:
    return values.dtype.kind == "f" or (values.dtype.kind in "iu" and len(np.unique(values)) > 12)


@dataclass
class Encoding:
    """Per-event values of one encoding, and its legend (None: none to show)."""

    values: np.ndarray | None = None  # per event, None when one value for all
    value: Any = None  # one value for all
    legend: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def colors(
    values: np.ndarray | None,
    *,
    solid: str | None,
    title: str,
    declared: list[Any] | None = None,
    colormap: str | Sequence[str] | None = None,
    clim: Any = None,
    palette: Mapping[Any, str] | Sequence[str] | None = None,
    opacity: float = 1.0,
) -> Encoding:
    """RGBA bytes per event from a column (categories or numbers), or one colour."""
    alpha = round(255 * max(0.0, min(1.0, opacity)))
    if values is None:
        if solid is None:
            return Encoding(value="theme", extra={"alpha": alpha})
        r, g, b, a = rgba(solid)
        return Encoding(value=hex_of((r, g, b)), extra={"alpha": round(a * alpha / 255)})
    out = np.zeros((len(values), 4), dtype=np.uint8)
    missing = is_missing(values)
    out[missing] = rgba(MISSING_COLOR)
    if palette is None and is_continuous(values):
        nums = values.astype(np.float64)
        ok = ~missing & np.isfinite(nums)
        lo, hi = _limits(nums[ok], clim)
        span = hi - lo or 1.0
        name = colormap or "viridis"
        out[ok, :3] = sample_colormap(name, (nums[ok] - lo) / span)
        out[ok, 3] = 255
        legend = {
            "kind": "continuous",
            "title": title,
            "colors": colormap_colors(name),
            "clim": [lo, hi],
        }
    else:
        # a palette given as a dict also gives the order (legend first to last)
        cats = ordered_categories(
            values, declared, list(palette) if isinstance(palette, Mapping) else None
        )
        if isinstance(palette, Mapping):
            mapped = {k: palette[k] for k in cats if k in palette}
            rest = [k for k in cats if k not in mapped]
            auto = [c for c in TAB10 if c not in mapped.values()] or TAB10
            mapped.update({k: auto[i % len(auto)] for i, k in enumerate(rest)})
        else:
            pal = list(palette) if palette is not None else TAB10
            mapped = {k: pal[i % len(pal)] for i, k in enumerate(cats)}
        lookup = {k: rgba(c) for k, c in mapped.items()}
        for i, v in enumerate(values.tolist()):
            if not missing[i]:
                out[i] = lookup[v]
        items = [{"label": label(k), "color": hex_of(lookup[k])} for k in cats]
        if missing.any():
            items.append({"label": "missing", "color": MISSING_COLOR})
        legend = {"kind": "categories", "title": title, "items": items}
    out[:, 3] = (out[:, 3].astype(np.uint16) * alpha // 255).astype(np.uint8)
    return Encoding(values=out, legend=legend)


def _limits(values: np.ndarray, clim: Any) -> tuple[float, float]:
    if values.size == 0:
        return 0.0, 1.0
    if clim is None:
        return float(values.min()), float(values.max())
    if clim == "robust":
        lo, hi = np.percentile(values, [0.5, 99.5])
        return float(lo), float(hi)
    if isinstance(clim, Sequence) and len(clim) == 2:
        return float(clim[0]), float(clim[1])
    raise ValueError(f"clim must be None, 'robust' or (low, high), got {clim!r}")


def symbols(
    values: np.ndarray | None,
    *,
    solid: str,
    title: str,
    declared: list[Any] | None = None,
    mapping: Mapping[Any, str] | Sequence[str] | None = None,
) -> Encoding:
    """A symbol index per event (into ``SYMBOLS``) from a category column, or one symbol."""
    if values is None:
        if solid not in SYMBOLS:
            raise ValueError(f"unknown symbol {solid!r}; use one of {list(SYMBOLS)}")
        return Encoding(value=solid)
    cats = ordered_categories(values, declared)
    if isinstance(mapping, Mapping):
        names = {k: mapping.get(k, SYMBOLS[i % len(SYMBOLS)]) for i, k in enumerate(cats)}
    else:
        seq = list(mapping) if mapping is not None else list(SYMBOLS)
        names = {k: seq[i % len(seq)] for i, k in enumerate(cats)}
    bad = [s for s in names.values() if s not in SYMBOLS]
    if bad:
        raise ValueError(f"unknown symbol {bad[0]!r}; use one of {list(SYMBOLS)}")
    index = {k: SYMBOLS.index(s) for k, s in names.items()}
    missing = is_missing(values)
    out = np.zeros(len(values), dtype=np.uint8)
    for i, v in enumerate(values.tolist()):
        if not missing[i]:
            out[i] = index[v]
    items = [{"label": label(k), "symbol": names[k]} for k in cats]
    return Encoding(values=out, legend={"title": title, "items": items})


def sizes(
    values: np.ndarray | None,
    *,
    solid: float,
    title: str,
    size_range: tuple[float, float] = (4.0, 16.0),
) -> Encoding:
    """A diameter in pixels per event, area-proportional to a numeric column, or one size."""
    if values is None:
        return Encoding(value=float(solid))
    nums = values.astype(np.float64)
    ok = np.isfinite(nums)
    lo, hi = (float(nums[ok].min()), float(nums[ok].max())) if ok.any() else (0.0, 1.0)
    span = hi - lo or 1.0
    a0, a1 = size_range[0] ** 2, size_range[1] ** 2
    frac = np.where(ok, (nums - lo) / span, 0.0)
    out = np.sqrt(a0 + frac * (a1 - a0)).astype(np.float32)
    samples = [lo, (lo + hi) / 2, hi] if hi > lo else [lo]
    items = [
        {"label": label(v), "size": float(np.sqrt(a0 + (v - lo) / span * (a1 - a0)))}
        for v in samples
    ]
    return Encoding(values=out, legend={"title": title, "items": items})
