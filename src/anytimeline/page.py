"""Plots as HTML that works without Python: a page of their own (``save_html``,
``to_html``), a notebook output (``display="html"``), an element for a page of your own
(``to_html(full_html=False)``) and the documentation's embeds. None needs a widget.

Each holds the plot's spec and buffers (base64), its settings and its tooltip columns as
JSON in a ``<script type="application/json">``, which ``standalone.js`` draws.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
from collections.abc import Iterable
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from anytimeline.styling import label

if TYPE_CHECKING:
    from anytimeline.plot import Timeline

TOOLTIP_CELLS = 1_000_000
"""Pages without Python (save_html, the docs) get a layer's tooltip columns up to this many
values (events × columns)."""
HTML_WARN_BYTES = 20_000_000
"""A plot shown as HTML (``display="html"``) whose data is larger than this warns: the
notebook file holds it."""
FULL_BYTES = 20_000_000
"""A page of a plot with layers sent as levels holds every event when they come to at most
this many bytes; else only the levels (zoomed in, it shows their finest bins)."""

_STATIC = Path(__file__).parent / "static"


def save_html(
    path: str | PathLike[str], *plots: Timeline | Iterable[Timeline], title: str | None = None
) -> Path:
    """Write plots to one HTML file that opens in any browser, without Python or a network:
    their data, the drawing code and the styles are all in the file. Pan, zoom, hover (with
    the ``tooltip`` columns), Time / Order, folding and full screen work, and linked plots stay
    linked; selecting does not (it needs Python). One plot fills the window; several are shown
    one above the other.

    Args:
        path: The file to write (``.html``).
        plots: The plots, in order (or lists of plots).
        title: The page's title; by default the first plot's title.

    Returns:
        The path written.
    """
    from anytimeline.plot import Timeline

    shown: list[Timeline] = []
    for p in plots:
        shown.extend([p] if isinstance(p, Timeline) else list(p))
    out = Path(path)
    out.write_text(page(shown, title), encoding="utf-8")
    return out


def page(shown: list[Timeline], title: str | None) -> str:
    """A page of its own with ``shown``, one above the other (one plot fills the window)."""
    if not shown:
        raise ValueError("no plots to save")
    for p in shown:
        if not p.layers:
            raise ValueError("a plot has no layers yet: add some before saving it")
    style = (_STATIC / "widget.css").read_text(encoding="utf-8")
    name = title if title is not None else (shown[0].title or "anytimeline")
    fill = ' data-fill="window"' if len(shown) == 1 else ""
    embeds = "\n".join(
        f'<div class="anytimeline-embed"{fill}>\n'
        f'<script type="application/json">{data(p)}</script>\n</div>'
        for p in shown
    )
    return _PAGE.format(title=html.escape(name), style=style, plots=embeds, script=script())


def fragment(plot: Timeline, note: str) -> str:
    """The plot as HTML to put in a page (a notebook output, ``to_html(full_html=False)``):
    the plot's CSS, its data, and ``standalone.js``, which then starts this plot, with a
    note (``note``, after the plot's repr) for where scripts do not run.

    Every fragment has the script: an earlier one may be cleared or not run. A page runs
    each version of it once (``window.anytimelineEmbeds``, by a hash of the script): a
    notebook whose tab drew plots before anytimeline was updated draws new ones with the
    new script, and its older plots keep theirs."""
    code = script()
    version = hashlib.sha256(code.encode()).hexdigest()[:16]
    style = (_STATIC / "widget.css").read_text(encoding="utf-8")
    return (
        f"<style>{style}</style>"
        '<div class="anytimeline-embed"><p class="anytimeline-note">'
        f"{html.escape(repr(plot))}: {html.escape(note)}</p>"
        f'<script type="application/json">{data(plot)}</script></div>'
        "<script>(function(s){var r=window.anytimelineEmbeds=window.anytimelineEmbeds||{};"
        f'if(!r["{version}"]){{{code};\nr["{version}"]=window.anytimelineEmbed}}'
        f'r["{version}"].add(s&&s.previousElementSibling)}})(document.currentScript)'
        "</script>"
    )


def embed(plot: Timeline) -> str:
    """The plot as an HTML fragment for a page that loads ``standalone.js`` and
    ``widget.css`` once (the documentation): any number of plots per page, each drawn
    when it comes near the screen, with all its data in the page."""
    return (
        '<div class="anytimeline-embed">'
        f'<script type="application/json">{data(plot)}</script></div>'
    )


def data(plot: Timeline) -> str:
    """The plot's spec, data and settings as JSON that is safe inside a <script>."""
    zoom = plot._zoom.get("range")
    spec, buffers = plot._page_data()
    payload = {
        "spec": spec,
        "buffers": {i: base64.b64encode(b).decode("ascii") for i, b in buffers.items()},
        "height": plot.height,
        "renderer": plot.renderer,
        "title": plot.title,
        "xscale": plot.xscale,
        "tool": plot.tool,
        "legend": plot.legend,
        "hover": plot.hover,
        "font_size": plot.font_size,
        "mark_scale": plot.mark_scale,
        "dodge": plot.dodge,
        "zoom": zoom,
        "lanes": plot._zoom.get("lanes"),
        "marks": {k: base64.b64encode(v).decode("ascii") for k, v in plot._marks.items()},
        "marked": {k: base64.b64encode(v).decode("ascii") for k, v in plot._marked.items()},
        "summary": plot._summary,
        "notes": plot._notes,
        "tooltips": tooltip_tables(plot),
        "link": plot._link or None,
    }
    # inside <script>, "</script" or "<!--" in the data would change how the page parses;
    # JSON has no "<" left after this (< means the same)
    return json.dumps(payload, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c")


def tooltip_tables(plot: Timeline) -> dict[str, dict[str, Any]]:
    """Per layer, its tooltip columns as text in the order the browser has the events,
    for pages without Python; left out for layers larger than TOOLTIP_CELLS."""
    out: dict[str, dict[str, Any]] = {}
    for name, rec in plot._layers.items():
        if not rec.tooltip or len(rec.perm) * len(rec.tooltip) > TOOLTIP_CELLS:
            continue
        out[name] = {
            "columns": list(rec.tooltip),
            "values": [
                [text(v) for v in values[rec.perm].tolist()] for values in rec.tooltip.values()
            ],
        }
    return out


def text(value: Any) -> str:
    """A table value as a tooltip shows it."""
    if value is None:
        return "–"
    if isinstance(value, np.datetime64):
        return str(value)
    if isinstance(value, float | np.floating):
        return "–" if value != value else f"{float(value):.6g}"
    return label(value)


def script() -> str:
    """``standalone.js``, ready to go inside a ``<script>`` element."""
    path = _STATIC / "standalone.js"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing: build the JavaScript first (npm run build in js/)"
        )
    # "</script" in the code would end the element early
    return path.read_text(encoding="utf-8").replace("</script", "<\\/script")


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="anytimeline">
<title>{title}</title>
<style>
:root {{ color-scheme: light dark; }}
html, body {{ margin: 0; height: 100%; }}
body {{ background: #ffffff; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
@media (prefers-color-scheme: dark) {{ body {{ background: #12171d; }} }}
.anytimeline-embed {{ padding: 12px 16px; box-sizing: border-box; }}
.anytimeline-embed + .anytimeline-embed {{ padding-top: 0; }}
</style>
<style>
{style}
</style>
</head>
<body>
{plots}
<script>
{script}
</script>
</body>
</html>
"""
