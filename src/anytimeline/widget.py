"""The widget that shows a plot in a notebook (``plot.widget``): a scene specification plus
binary buffers, drawn in the browser. This module is the protocol between them.

Its synced traits are the plot's settings (``Timeline._set``): the plot sends each change
(``show``), and a change made in the browser goes back to the plot, which checks and keeps
it (``Timeline._set(..., shown=True)``).

* ``_spec`` (synced): a small JSON description of the plot. Layers refer to buffers by
  content id, with dtype and count.
* The browser asks for buffers it does not have: ``{"type": "need", "ids": [...]}``, and
  Python answers with ``{"type": "put", "id", "chunk", "chunks", "offset", ...}`` messages,
  each with one binary chunk of at most ``CHUNK_BYTES``.
* ``{"type": "tooltip", "request", "layer", "index"}`` asks for the tooltip columns of one
  event; Python answers ``{"type": "answer", "request", "rows"}``.
* ``{"type": "view", "range", "lanes"}`` reports the visible time range and the lanes in
  sight (debounced), for ``plot.view``.
* ``{"type": "perf", "update"}`` reports the renderer and timings (``plot.dev.perf``); not a
  synced trait, so in marimo timings re-run no cells. ``{"type": "benchmark"}`` asks for a
  benchmark, whose result comes back as perf.
* ``{"type": "snapshot", "request"}`` asks a view for a PNG, which comes back as
  ``{"type": "image", "request"}`` with the bytes (``save_png``).
* Gestures (clicks, boxes) arrive in the synced ``_pick``; Python resolves them to table rows
  (``selection``) and sends back ``_marks``: per layer, the selected events' indices.

Bulk data never goes into synced traits, so it is not saved into the notebook and only sent
to views that ask for it.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anywidget
import traitlets

if TYPE_CHECKING:
    from anytimeline.plot import Timeline

CHUNK_BYTES = 4 * 1024 * 1024

_STATIC = Path(__file__).parent / "static"


class TimelineWidget(anywidget.AnyWidget):
    """The widget that shows a plot: [`plot.widget`][anytimeline.Timeline.widget]. Its
    traits are the plot's settings; set them on the plot."""

    _esm = _STATIC / "widget.js"
    _css = _STATIC / "widget.css"

    _spec = traitlets.Dict().tag(sync=True)
    renderer = traitlets.Unicode("auto").tag(sync=True)
    height = traitlets.Int(0).tag(sync=True)
    title = traitlets.Unicode("").tag(sync=True)
    xscale = traitlets.Unicode("time").tag(sync=True)
    hover = traitlets.Bool(True).tag(sync=True)
    legend = traitlets.Bool(True).tag(sync=True)
    selection_mode = traitlets.Unicode("multiple", allow_none=True).tag(sync=True)
    font_size = traitlets.Int(12).tag(sync=True)
    mark_scale = traitlets.Float(1.0).tag(sync=True)
    dodge = traitlets.Bool(True).tag(sync=True)
    tool = traitlets.Unicode("pan").tag(sync=True)
    selection = traitlets.Dict().tag(sync=True)
    _pick = traitlets.Dict().tag(sync=True)
    _marks = traitlets.Dict().tag(sync=True)
    _zoom = traitlets.Dict().tag(sync=True)
    _link = traitlets.Dict().tag(sync=True)

    def __init__(self, plot: Timeline, state: dict[str, Any]) -> None:
        self._plot = plot
        self._showing = False  # the plot is setting a trait: not passed back to it
        super().__init__(**state)
        self.observe(self._changed, names=list(state))
        self.on_msg(self._on_msg)

    def show(self, name: str, value: Any) -> None:
        """Set a trait to the plot's setting (``Timeline._set``)."""
        self._showing = True
        try:
            setattr(self, name, value)
        finally:
            self._showing = False

    def _changed(self, change: Any) -> None:
        """A change made in the browser: the plot's setting."""
        if not self._showing:
            self._plot._set(change["name"], change["new"], shown=True)

    def _on_msg(self, _widget: Any, content: dict[str, Any], buffers: Any) -> None:
        plot = self._plot
        kind = content.get("type")
        if kind == "need":
            for buffer_id in content.get("ids", []):
                self._send_buffer(str(buffer_id))
        elif kind == "tooltip":
            answer: dict[str, Any] = {"type": "answer", "request": content.get("request")}
            try:
                answer["rows"] = plot._tooltip(str(content.get("layer")), int(content["index"]))
            except Exception as err:  # the browser shows what it has; the kernel carries on
                answer["error"] = str(err)
            self.send(answer)
        elif kind == "view":
            plot._shown(content)
        elif kind == "image":
            plot._receive_image(content, buffers)
        elif kind == "perf":
            update = content.get("update")
            if isinstance(update, dict):
                plot._perf = {**plot._perf, **update}

    def _send_buffer(self, buffer_id: str) -> None:
        data = self._plot._buffers.get(buffer_id)
        if data is None:
            self.send({"type": "missing", "id": buffer_id})
            return
        chunks = max(1, -(-len(data) // CHUNK_BYTES))
        t_send = time.time()
        for i in range(chunks):
            part = data[i * CHUNK_BYTES : (i + 1) * CHUNK_BYTES]
            self.send(
                {
                    "type": "put",
                    "id": buffer_id,
                    "chunk": i,
                    "chunks": chunks,
                    "offset": i * CHUNK_BYTES,
                    "byteLength": len(data),
                    "t_send": t_send,
                },
                buffers=[part],
            )

    def __repr__(self) -> str:
        return f"TimelineWidget of {self._plot!r}"
