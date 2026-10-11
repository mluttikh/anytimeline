"""The notebook widget: a scene specification plus binary buffers, drawn in the browser.

Protocol:

* ``_spec`` (synced): a small JSON description of the plot. Layers refer to buffers by
  content id, with dtype and count.
* The browser asks for buffers it does not have: ``{"type": "need", "ids": [...]}``, and
  Python answers with ``{"type": "put", "id", "chunk", "chunks", "offset", ...}`` messages,
  each with one binary chunk of at most ``CHUNK_BYTES``.
* ``{"type": "tooltip", "request", "layer", "index"}`` asks for the tooltip columns of one
  event; Python answers ``{"type": "answer", "request", "rows"}``.
* ``{"type": "view", "range"}`` reports the visible time range (debounced), for ``range``.
* Gestures (clicks, boxes) arrive in the synced ``_pick``; Python resolves them to table rows
  (``selection``) and sends back ``_marks``: per layer, the selected events' indices.

Bulk data never goes into synced traits, so it is not saved into the notebook and only sent
to views that ask for it.
"""

from __future__ import annotations

import base64
import dataclasses
import html
import json
import time
import uuid
import weakref
from collections.abc import Callable, Iterable, Mapping, Sequence
from os import PathLike
from pathlib import Path
from typing import Any, Literal, Self

import anywidget
import numpy as np
import traitlets
from ipywidgets import CallbackDispatcher

from anytimeline import data as tables
from anytimeline import events as ev
from anytimeline import grouping
from anytimeline import intervals as iv
from anytimeline import states as st
from anytimeline import values as vl
from anytimeline.codec import Encoded, encode
from anytimeline.data import NotFoundError
from anytimeline.lanes import LANE_SORTS, LaneSort
from anytimeline.styling import label
from anytimeline.timebase import TimeBase, time_base

CHUNK_BYTES = 4 * 1024 * 1024
RENDERERS = ("auto", "webgpu", "webgl2", "canvas2d")
SELECTION_MODES = ("single", "multiple", "none")
XSCALES = ("time", "sequence")
TOOLS = ("pan", "zoom", "select")
TOOLTIP_CELLS = 1_000_000
"""Pages without Python (save_html, the docs) get a layer's tooltip columns up to this many
values (events × columns)."""
FONT_SIZES = (8, 24)
"""The smallest and largest text size, in pixels."""

_STATIC = Path(__file__).parent / "static"


class Timeline(anywidget.AnyWidget):
    """An interactive timeline: layers of events on lanes, drawn on the GPU.

    Add layers with [`events`][anytimeline.Timeline.events]; show the plot by making it the
    last expression of a notebook cell. Click into the plot, then scroll to zoom time; drag
    to pan; double-click to reset.

    Args:
        height: Height in pixels; 0 sizes the plot to its lanes (at most 640 px).
        title: Shown above the plot.
        xscale: ``"time"`` (events at their time) or ``"sequence"`` (events by rank, evenly
            spaced: the order in which they happened).
        timezone: Time zone to show datetimes in (an IANA name such as
            ``"Europe/Amsterdam"``). Default: the time column's own, else UTC.
        time_unit: For numeric time columns: what one unit is (``"s"``, ``"ms"``, ``"us"``,
            ``"ns"``); the numbers are then durations. Without it they are plain numbers.
        lane_order: Lanes to show first, top to bottom.
        sort: Lane order: ``"name"`` (natural sort), ``"first"`` / ``"last"`` (time of a
            lane's first / last event) or ``"count"`` (most events first).
        lane_names: Show the lanes' names left of the plot (False: a plot of one lane, a
            story, without the column of names).
        group_order: Groups (layers' ``group=``) to show first, top to bottom; the others
            follow in natural order.
        align: ``"time"``: all at their time; ``"start"``: each group's times from its first
            time (durations since then), so groups of different periods (days, runs,
            traces) compare from their start.
        renderer: ``"auto"`` (WebGPU, then WebGL2, then Canvas 2D), or one of them.
        tool: The tool the plot starts with: ``"pan"``, ``"zoom"`` or ``"select"``.
        font_size: The size of the plot's text in pixels (8 to 24).
        mark_scale: The size of event marks, as a factor of the layers' own (0.25 to 4).
        dodge: Spread events that would overlap over the lane's height (default), or draw
            them on the lane's line.
    """

    _esm = _STATIC / "widget.js"
    _css = _STATIC / "widget.css"

    _spec = traitlets.Dict().tag(sync=True)
    renderer = traitlets.Enum(RENDERERS, default_value="auto").tag(sync=True)
    """The drawing backend; ``"auto"`` picks the first that works."""
    height = traitlets.Int(0).tag(sync=True)
    """Height in pixels; 0 sizes the plot to its lanes."""
    title = traitlets.Unicode("").tag(sync=True)
    """Shown above the plot."""
    xscale = traitlets.Enum(XSCALES, default_value="time").tag(sync=True)
    """``"time"`` or ``"sequence"``; also the Time / Order switch in the plot."""
    hover = traitlets.Bool(True).tag(sync=True)
    """Show a tooltip for the event under the pointer."""
    legend = traitlets.Bool(True).tag(sync=True)
    """Show the legend."""
    selection_mode = traitlets.Enum(SELECTION_MODES, default_value="multiple").tag(sync=True)
    """``"multiple"``: boxes, and Shift/Ctrl/Cmd-clicks that add; ``"single"``: one event;
    ``"none"``: no selection (the Select tool is not offered)."""
    font_size = traitlets.Int(12).tag(sync=True)
    """The size of the plot's text in pixels (8 to 24): lane names, the time axis, labels,
    legend, tooltips. Also in the toolbar's Display panel."""
    mark_scale = traitlets.Float(1.0).tag(sync=True)
    """The size of event marks, as a factor of the sizes the layers give them (0.25 to 4):
    smaller marks overlap less in dense data. Also in the toolbar's Display panel."""
    dodge = traitlets.Bool(True).tag(sync=True)
    """Spread events that would overlap over the lane's height (sub-rows), so ties and bursts
    stay countable; False draws every event on its lane's line. Layers with
    ``overlap="overlay"`` never spread. Also in the Display panel, and the key ``d``."""
    tool = traitlets.Enum(TOOLS, default_value="pan").tag(sync=True)
    """The plot's tool: ``"pan"`` (drag pans; Shift-drag zooms to a range; a plain click does
    nothing), ``"zoom"`` (drag zooms to a time range; click zooms in, Alt-click out) or
    ``"select"`` (drag selects a box; click selects an event). Also the toolbar and keys
    ``p``, ``z``, ``s``."""
    selection = traitlets.Dict().tag(sync=True)
    """The selected events: layer name → sorted table rows."""
    perf = traitlets.Dict()
    """Renderer and timings reported by the browser."""
    _pick = traitlets.Dict().tag(sync=True)
    _marks = traitlets.Dict().tag(sync=True)
    _zoom = traitlets.Dict().tag(sync=True)
    _link = traitlets.Dict().tag(sync=True)
    """The group of linked plots: ``{"group": id, "align": "time" | "start"}``, or empty."""

    def __init__(
        self,
        *,
        height: int = 0,
        title: str = "",
        xscale: Literal["time", "sequence"] = "time",
        timezone: str | None = None,
        time_unit: str | None = None,
        lane_order: Sequence[Any] | None = None,
        sort: LaneSort | None = None,
        group_order: Sequence[Any] | None = None,
        align: Literal["time", "start"] = "time",
        lane_names: bool = True,
        renderer: Literal["auto", "webgpu", "webgl2", "canvas2d"] = "auto",
        tool: Literal["pan", "zoom", "select"] = "pan",
        font_size: int = 12,
        mark_scale: float = 1.0,
        dodge: bool = True,
        **kwargs: Any,
    ) -> None:
        if sort is not None and sort not in LANE_SORTS:
            raise ValueError(f"sort must be one of {LANE_SORTS}, got {sort!r}")
        if align not in ("time", "start"):
            raise ValueError(f"align must be 'time' or 'start', got {align!r}")
        self._group_order = list(group_order) if group_order is not None else None
        self._lane_names = lane_names
        self._align = align
        self._layers: dict[str, ev.EventsRecord | iv.IntervalsRecord | vl.ValuesRecord] = {}
        self._laid: dict[str, ev.Layout | iv.Layout | vl.Layout] = {}
        self._markers: list[tuple[Any, str, str | None]] = []
        self._ranks: dict[str, np.ndarray] = {}
        self._buffers: dict[str, bytes] = {}
        self._base: TimeBase | None = None
        self._timezone = timezone
        self._time_unit = time_unit
        self._lane_order = list(lane_order) if lane_order is not None else None
        self._sort: LaneSort | None = sort
        self._view_range: tuple[float, float] | None = None
        self._select_handlers = CallbackDispatcher()
        self._tooltip_cache: dict[tuple[str, int], list[list[str]]] = {}
        self._snapshots = 0
        self._snapshot_paths: dict[str, Path] = {}
        super().__init__(
            height=height,
            title=title,
            xscale=xscale,
            renderer=renderer,
            tool=tool,
            font_size=font_size,
            mark_scale=mark_scale,
            dodge=dodge,
            **kwargs,
        )
        self.on_msg(self._on_frontend_msg)
        self._update_spec()

    # ------------------------------------------------------------------ layers

    def events(
        self,
        data: Any,
        time: str | None = "time",
        *,
        lane: str | None = None,
        order: str | None = None,
        color: str | None = None,
        colormap: str | Sequence[str] | None = None,
        clim: Any = None,
        palette: Mapping[Any, str] | Sequence[str] | None = None,
        opacity: float = 1.0,
        symbol: str | None = None,
        symbols: Mapping[Any, str] | Sequence[str] | None = None,
        size: float | str | None = None,
        size_range: tuple[float, float] = (4.0, 16.0),
        text: str | None = None,
        tooltip: Sequence[str] | None = None,
        route: ev.Route | str | None = None,
        overlap: Literal["dodge", "overlay"] = "dodge",
        labels: Literal["beside", "stems"] = "beside",
        importance: str | None = None,
        group: str | None = None,
        hover: bool = True,
        select: bool = True,
        name: str = "events",
    ) -> Self:
        """Add an event chart layer: one mark per event, at the moment it happened.

        Args:
            data: A table (Polars, pandas, PyArrow, DuckDB, ...) or a dict of arrays, one
                row per event.
            time: The column of times: datetimes, durations, or numbers. ``None`` with
                ``order=``: events with an order but no clock time.
            lane: The column whose values are the lanes (rows) of the plot.
            order: A column that orders events with equal times (a sequence number), or
                that is the only order there is (with ``time=None``).
            color: A column (categories, or numbers through ``colormap``) or one colour.
            colormap: For numbers: a colormap name (``"viridis"``, any matplotlib name) or a
                list of colours, lowest first.
            clim: For numbers: colour limits ``(low, high)``, or ``"robust"``.
            palette: For categories: colours in order, or a dict of value → colour.
            opacity: 0 to 1.
            symbol: A column of categories, or one of ``SYMBOLS`` (default ``"circle"``).
            symbols: For a symbol column: symbol names in order, or a dict value → name.
            size: A diameter in pixels, or a column of numbers (area over ``size_range``).
            size_range: Smallest and largest diameter in pixels for a size column.
            text: A column, or a template such as ``"{event}"``, shown beside marks
                where there is room.
            tooltip: Columns shown when hovering an event (its time and lane always are).
            route: A column (or a [`Route`][anytimeline.Route]) whose groups are joined by
                lines in the order their events happened.
            overlap: ``"dodge"``: events that would overlap are spread over sub-rows of the
                lane; ``"overlay"``: drawn on top of each other.
            labels: Where the text (``text=``) goes. ``"beside"``: right of each mark, left out
                where it would overlap another. ``"stems"``: in boxes above and below the
                lane's line, at as many levels as needed so no two overlap, each joined to its
                event by a line (a story timeline: few events, the text matters); the events
                stay on the line. A line break (``"{time:%H:%M}\\n{title}"``) gives a box
                two lines.
            importance: A numeric column; where labels (`text=`) would overlap, the more
                important events keep theirs.
            group: A column of groups (a host, a region, a day): each group gets a header
                lane with its own lanes under it, in the plot's lane order; groups fold.
            hover: Show tooltips for this layer.
            select: Whether its events can be selected.
            name: The layer's name; adding a layer with an existing name replaces it.
        """
        record = ev.build(
            data,
            name=name,
            time=time,
            lane=lane,
            order=order,
            color=color,
            colormap=colormap,
            clim=clim,
            palette=palette,
            opacity=opacity,
            symbol=symbol,
            symbols=symbols,
            size=size,
            size_range=size_range,
            text=text,
            tooltip=tooltip,
            route=route,
            overlap=overlap,
            labels=labels,
            importance=importance,
            time_unit=self._time_unit,
            hover=hover,
            select=select,
        )
        return self._add(record, data, group)

    def intervals(
        self,
        data: Any,
        start: str = "start",
        end: str | None = "end",
        *,
        duration: str | None = None,
        duration_unit: str | None = None,
        lane: str | None = None,
        id: str | None = None,
        depends: str | None = None,
        color: str | None = None,
        colormap: str | Sequence[str] | None = None,
        clim: Any = None,
        palette: Mapping[Any, str] | Sequence[str] | None = None,
        opacity: float = 1.0,
        text: str | None = None,
        tooltip: Sequence[str] | None = None,
        progress: str | None = None,
        overlap: Literal["pack", "overlay"] = "pack",
        height: float = 0.7,
        parent: str | None = None,
        label: str | None = None,
        expand: int | Literal["auto"] | None = "auto",
        critical_path: bool = False,
        durations: bool = False,
        group: str | None = None,
        hover: bool = True,
        select: bool = True,
        name: str = "intervals",
    ) -> Self:
        """Add a layer of intervals: a bar per row from its start to its end, on lanes (a
        Gantt chart, a schedule, spans). For a Gantt chart in one call, see
        [`gantt`][anytimeline.gantt].

        A row whose start equals its end is a milestone, drawn as a diamond. A row without an
        end is open: its bar runs to the plot's last time and fades out.

        Args:
            data: A table (Polars, pandas, PyArrow, DuckDB, ...) or a dict of arrays, one row
                per interval.
            start: The column of start times: datetimes, durations or numbers.
            end: The column of end times, of the same kind. Pass ``end=None`` with
                ``duration=``.
            duration: Instead of ``end``: a column of durations (timedelta), or of numbers in
                ``duration_unit``.
            duration_unit: What one unit of a numeric ``duration`` is: ``"d"``, ``"h"``,
                ``"min"``, ``"s"``, ``"ms"``, ``"us"`` or ``"ns"``. Not needed when the times
                are plain numbers (the durations are then in the same numbers).
            lane: The column whose values are the lanes (a task, a machine, a person).
            id: The column that names each bar, for ``depends``; by default the lane.
            depends: A column with, per bar, the bars it follows (their ids): one id, a list of
                ids, or ids separated by commas. An arrow runs from the end of each of them to
                the start of this bar.
            color: A column (categories, or numbers through ``colormap``) or one colour.
            colormap: For numbers: a colormap name or a list of colours, lowest first.
            clim: For numbers: colour limits ``(low, high)``, or ``"robust"``.
            palette: For categories: colours in order, or a dict of value → colour.
            opacity: 0 to 1.
            text: A column, or a template such as ``"{task}"``, written in each bar where it
                fits (milestones: next to the diamond).
            tooltip: Columns shown when hovering a bar (its lane, start, end and duration
                always are).
            progress: A column of how far each bar is done, 0 to 1: that part of the bar is
                filled, the rest drawn lighter.
            overlap: ``"pack"``: bars of a lane that overlap in time are stacked in sub-rows;
                ``"overlay"``: drawn on top of each other.
            height: The bars' height, as a fraction of the lane (above 0, at most 1).
            parent: A column with each bar's parent (its id; missing for a top bar): the bars
                form a tree, each bar on its own lane under its parent, which you can fold.
                Needs ``id=``; replaces ``lane=``. Bars whose parent is not in the table are
                shown at the top.
            label: With ``parent``: the column that names each bar's lane (by default its id).
            expand: With ``parent``: the levels shown at first (1: the top bars only), ``None``
                for all, or ``"auto"``: as many as keep about 200 lanes. Click a lane's name to
                fold or unfold it.
            critical_path: With ``parent``: mark the critical path of each top bar, the parts
                of bars its end waited for.
            durations: Write each bar's duration right of it.
            group: A column of groups (a host, a region, a day): each group gets a header
                lane with its own lanes under it, in the plot's lane order; groups fold.
            hover: Show tooltips for this layer.
            select: Whether its bars can be selected.
            name: The layer's name; adding a layer with an existing name replaces it.
        """
        record = iv.build(
            data,
            name=name,
            start=start,
            end=end,
            duration=duration,
            lane=lane,
            id=id,
            depends=depends,
            color=color,
            colormap=colormap,
            clim=clim,
            palette=palette,
            opacity=opacity,
            text=text,
            tooltip=tooltip,
            progress=progress,
            overlap=overlap,
            height=height,
            time_unit=self._time_unit,
            duration_unit=duration_unit,
            hover=hover,
            select=select,
            parent=parent,
            label=label,
            expand=expand,
            critical_path=critical_path,
            durations=durations,
        )
        return self._add(record, data, group)

    def states(
        self,
        data: Any,
        time: str = "time",
        state: str = "state",
        *,
        lane: str | None = None,
        end: Any = None,
        color: str | None = None,
        palette: Mapping[Any, str] | Sequence[str] | None = None,
        opacity: float = 1.0,
        text: bool | str = True,
        tooltip: Sequence[str] | None = None,
        height: float = 0.8,
        group: str | None = None,
        hover: bool = True,
        select: bool = True,
        name: str = "states",
    ) -> Self:
        """Add states: each lane is in one state at a time (a service up, degraded or down; a
        feature flag on or off; a phase), drawn as a band of colours.

        The table has a row per change: from its ``time`` on, its lane is in its ``state``,
        until the lane's next change. A row that repeats the state its lane is in changes
        nothing; a missing state is a gap (nothing known). A lane's last state runs to ``end``,
        or to the plot's last time.

        Args:
            data: A table (Polars, pandas, PyArrow, ...) or a dict of arrays: a row per change.
            time: The column of times the states start.
            state: The column of states.
            lane: The column of lanes (a service, a host); without it, one lane.
            end: When the lanes' last states end (one time); by default they run to the plot's
                last time.
            color: Colour by another column, or one colour; by default by the state.
            palette: Colours for the states: in order, or a dict of state → colour (which also
                sets their order in the legend).
            opacity: 0 to 1.
            text: Write each state's name in its band where it fits (``True``), a template such
                as ``"{state} ({reason})"``, or ``False``.
            tooltip: More columns shown when hovering a state (its state, start, end and
                duration always are).
            height: The band's height, as a fraction of the lane.
            group: A column of groups (a host, a region, a day): each group gets a header
                lane with its own lanes under it, in the plot's lane order; groups fold.
            hover: Show tooltips for this layer.
            select: Whether its states can be selected (as the rows that start them).
            name: The layer's name; adding a layer with an existing name replaces it.
        """
        record = st.build(
            data,
            name=name,
            time=time,
            state=state,
            lane=lane,
            end=end,
            color=color,
            palette=palette,
            opacity=opacity,
            text=text,
            tooltip=tooltip,
            height=height,
            time_unit=self._time_unit,
            hover=hover,
            select=select,
        )
        return self._add(record, data, group)

    def values(
        self,
        data: Any,
        time: str = "time",
        value: str = "value",
        *,
        lane: str | None = None,
        series: str | None = None,
        color: str | None = None,
        palette: Mapping[Any, str] | Sequence[str] | None = None,
        kind: Literal["line", "area", "step"] = "line",
        scale: Literal["lane", "shared"] = "lane",
        ylim: tuple[float, float] | Mapping[Any, tuple[float, float]] | None = None,
        width: float = 1.5,
        tooltip: Sequence[str] | None = None,
        group: str | None = None,
        hover: bool = True,
        name: str = "values",
    ) -> Self:
        """Add values: a number over time in each lane (CPU, queue length, an error rate),
        drawn as a small chart in the lane's band, behind its events and bars.

        Samples are not events: on the Order scale they take no places of their own, and
        are drawn between the events they fall between. Many samples are fine: each pixel
        column of a line shows the lowest and highest value in it.

        Args:
            data: A table (Polars, pandas, PyArrow, ...) or a dict of arrays: a row per sample.
            time: The column of sample times.
            value: The column of numbers; a missing value is a gap in the line.
            lane: The column of lanes, the same as other layers' to draw the values behind
                their events; without it, a lane named after ``value``.
            series: A column that splits a lane into several lines (p50 and p99, a host).
            color: One colour, or a column to colour the lines by; by default by ``series``
                (one colour per series), else the theme's.
            palette: Colours for the series: in order, or a dict of series → colour.
            kind: ``"line"``, ``"area"`` (filled below the line) or ``"step"`` (each value
                holds until the next sample: gauges, counters).
            scale: ``"lane"``: each lane from its own lowest to highest value; ``"shared"``:
                all lanes on one range.
            ylim: The range ``(low, high)`` for every lane, e.g. ``(0, 100)`` for percentages,
                or a dict of lane → range.
            width: The line's width in pixels.
            tooltip: Columns shown when hovering a sample (its time and value always are).
            group: A column of groups (a host, a region, a day): each group gets a header
                lane with its own lanes under it, in the plot's lane order; groups fold.
            hover: Show the value under the pointer.
            name: The layer's name; adding a layer with an existing name replaces it.
        """
        record = vl.build(
            data,
            name=name,
            time=time,
            value=value,
            lane=lane,
            series=series,
            color=color,
            palette=palette,
            kind=kind,
            scale=scale,
            ylim=ylim,
            width=width,
            tooltip=tooltip,
            time_unit=self._time_unit,
            hover=hover,
        )
        return self._add(record, data, group)

    def spans(
        self,
        data: Any,
        start: str = "start",
        end: str | None = "end",
        *,
        duration: str | None = None,
        duration_unit: str | None = None,
        id: str = "span_id",
        parent: str = "parent_id",
        label: str = "name",
        color: str | None = None,
        colormap: str | Sequence[str] | None = None,
        clim: Any = None,
        palette: Mapping[Any, str] | Sequence[str] | None = None,
        opacity: float = 1.0,
        text: str | None = None,
        tooltip: Sequence[str] | None = None,
        expand: int | Literal["auto"] | None = "auto",
        critical_path: bool = True,
        durations: bool = True,
        height: float = 0.6,
        group: str | None = None,
        hover: bool = True,
        select: bool = True,
        name: str = "spans",
    ) -> Self:
        """Add the spans of traces: a waterfall with a lane per span, under its parent span,
        its duration beside it and the critical path of each trace marked. Lanes fold: click
        a span's name.

        This is [`intervals`][anytimeline.Timeline.intervals] set up for traces (OpenTelemetry,
        Jaeger, Zipkin): read them with [`read_otlp`][anytimeline.otel.read_otlp], or pass
        any table with a row per span. Events (logs, errors) of the spans go on their lanes
        with ``events(..., lane="span_id")``.

        Args:
            data: A table with a row per span.
            start: The column of start times.
            end: The column of end times; or ``end=None`` with ``duration=``.
            duration: A column of durations, or of numbers in ``duration_unit``.
            duration_unit: What one unit of a numeric duration is (``"ms"``, ``"us"``, ...).
            id: The column of span ids, unique in the table.
            parent: The column of parent span ids (missing for the root of a trace).
            label: The column that names each span's lane.
            color: A column (the service, the status) or one colour.
            colormap: For numbers: a colormap name or a list of colours.
            clim: For numbers: colour limits ``(low, high)``, or ``"robust"``.
            palette: For categories: colours in order, or a dict of value → colour.
            opacity: 0 to 1.
            text: Written in each bar where it fits (a column or a template).
            tooltip: Columns shown when hovering a span.
            expand: The levels shown at first (1: the roots only), ``None`` for all, or
                ``"auto"``: as many as keep about 200 lanes.
            critical_path: Mark the critical path of each trace.
            durations: Write each span's duration right of it.
            height: The bars' height, as a fraction of the lane.
            group: A column of groups (a host, a region, a day): each group gets a header
                lane with its own lanes under it, in the plot's lane order; groups fold.
            hover: Show tooltips for this layer.
            select: Whether its spans can be selected.
            name: The layer's name.
        """
        return self.intervals(
            data,
            start=start,
            end=end,
            duration=duration,
            duration_unit=duration_unit,
            id=id,
            parent=parent,
            label=label,
            color=color,
            colormap=colormap,
            clim=clim,
            palette=palette,
            opacity=opacity,
            text=text,
            tooltip=tooltip,
            expand=expand,
            critical_path=critical_path,
            durations=durations,
            overlap="overlay",
            height=height,
            group=group,
            hover=hover,
            select=select,
            name=name,
        )

    def _add(self, record: Any, data: Any, group: str | None) -> Self:
        """Add (or replace) a layer, its rows' groups read from ``data``; the plot keeps the
        old layers when the new one does not fit."""
        if group is not None:
            table = tables.frame(data)
            tables.check(table, [group])
            groups = tables.column(table, group)[record.rows].astype(object)
            groups[tables.is_missing(groups)] = grouping.MISSING
            record.lane_groups = groups
            record.lane_group_declared = tables.categories(table, group)
        old = dict(self._layers)
        self._layers[record.name] = record
        try:
            self._update_spec()
        except Exception:
            self._layers = old
            raise
        return self

    def marker(self, time: Any, label: str = "", *, color: str | None = None) -> Self:
        """Draw a vertical line across the lanes at a time, such as now or a deadline.

        Args:
            time: A time of the data's kind (datetime, ISO text, duration or number).
            label: Written at the top of the line.
            color: The line's colour (default: the selection colour).
        """
        old = list(self._markers)
        self._markers.append((time, label, color))
        try:
            self._update_spec()
        except Exception:
            self._markers = old
            raise
        return self

    def clear_markers(self) -> Self:
        """Remove every marker."""
        self._markers.clear()
        self._update_spec()
        return self

    @property
    def layers(self) -> list[str]:
        """The layers' names, in drawing order."""
        return list(self._layers)

    def remove(self, name: str) -> Self:
        """Remove a layer."""
        if name not in self._layers:
            raise NotFoundError(f"no layer {name!r}; layers: {self.layers}")
        del self._layers[name]
        self.selection = {k: v for k, v in self.selection.items() if k != name}
        self._update_spec()
        return self

    def clear(self) -> Self:
        """Remove every layer."""
        self._layers.clear()
        self.selection = {}
        self._update_spec()
        return self

    # ------------------------------------------------------------------ time range

    @property
    def range(self) -> tuple[Any, Any] | None:
        """The visible time range, as the data's kind (datetime64, timedelta64 or numbers);
        None until the plot has been shown."""
        if self._view_range is None or self._base is None:
            return None
        return (self._base.to_value(self._view_range[0]), self._base.to_value(self._view_range[1]))

    def zoom_to(self, start: Any, end: Any) -> Self:
        """Show the time range from ``start`` to ``end`` (datetimes, ISO strings, durations or
        numbers, as the data)."""
        if self._base is None:
            raise ValueError("zoom_to needs a layer with times")
        t0, t1 = self._base.to_ticks(start), self._base.to_ticks(end)
        if not t1 > t0:
            raise ValueError("end must be after start")
        self._zoom = {"n": int(self._zoom.get("n", 0)) + 1, "range": [t0, t1]}
        return self

    # ------------------------------------------------------------------ spec

    def _update_spec(self) -> None:
        originals = list(self._layers.values())
        # align="start": each group's times from its start (copies; the layers keep theirs)
        records = grouping.shift_to_start(originals) if self._align == "start" else originals
        timed = [r for r in records if r.time_columns]
        if timed and len(timed) != len(records):
            raise ValueError("all layers need times, or none (order only)")
        columns = [c for r in timed for c in r.time_columns]
        base = time_base(columns, timezone=self._timezone) if timed else None
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
            lane_order_=self._lane_order,
            sort=self._sort,
            group_order=self._group_order,
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
        laid: dict[str, ev.Layout | iv.Layout | vl.Layout] = {
            r.name: iv.layout(r, base, index, last)
            if isinstance(r, iv.IntervalsRecord)
            else vl.layout(r, base, index)
            if isinstance(r, vl.ValuesRecord)
            else ev.layout(r, base, index)
            for r in records
        }
        buffers: list[Encoded] = [b for lay in laid.values() for b in lay.buffers]

        # the order of every instant of every layer (events; the starts and ends of bars):
        # the sequence scale
        ranks: dict[str, np.ndarray] = {}
        sequence = None
        parts = [
            (li, k, ticks, order)
            for li, lay in enumerate(laid.values())
            for k, (ticks, order) in enumerate(lay.instants)
        ]
        if parts and sum(len(p[2]) for p in parts):
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
            extent = (float(prim.min()), float(prim.max()))
        else:
            for lay in laid.values():
                enc = encode(np.zeros(0), "float32")
                buffers.append(enc)
                lay.spec["rank"] = enc.descriptor
            extent = (0.0, 1.0)
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
                "show_names": self._lane_names,
            },
            "layers": [lay.spec for lay in laid.values()],
            "sequence": sequence,
            "markers": self._marker_specs(base),
            "t": time.time(),
        }
        # the layers keep their order of rows (perm): selection and tooltips use it
        for orig, rec in zip(originals, records, strict=True):
            orig.perm = rec.perm
        self._base, self._laid, self._ranks = base, laid, ranks
        self._buffers = {b.id: b.data for b in buffers}
        self._tooltip_cache.clear()
        self._marks = self._marks_of(self.selection)
        self._spec = spec

    def _marker_specs(self, base: TimeBase | None) -> list[dict[str, Any]]:
        if not self._markers:
            return []
        if base is None:
            raise ValueError("markers need layers with times")
        return [
            {"x": base.to_ticks(t), "label": str(label), "color": color}
            for t, label, color in self._markers
        ]

    # ------------------------------------------------------------------ pages

    def save_html(self, path: str | PathLike[str], *, title: str | None = None) -> Path:
        """Write the plot to one HTML file that opens in any browser, without Python or a
        network: its data, the drawing code and the styles are all in the file. Pan, zoom,
        hover (with the ``tooltip`` columns), Time / Order, folding and full screen work;
        selecting does not (it needs Python).

        Args:
            path: The file to write (``.html``).
            title: The page's title; by default the plot's title.

        Returns:
            The path written.
        """
        return save_html(path, self, title=title)

    def link(self, *others: Timeline, align: Literal["time", "start"] = "time") -> Self:
        """Link this plot with others: zooming or panning one moves the others to the same
        time, the pointer's time shows as a line in all of them, and their lane names and
        legends take the same width, so their time axes line up when they are shown one
        above the other.

        Linking happens in the browser: it works between plots in a notebook, in a page from
        [`save_html`][anytimeline.save_html], and in documentation.

        Args:
            others: The plots to link with; plots linked with them already stay linked.
            align: ``"time"``: the same times line up; ``"start"``: each plot's first time
                lines up, so plots of different periods (two traces, this week and last)
                compare from their start.
        """
        if align not in ("time", "start"):
            raise ValueError(f"align must be 'time' or 'start', got {align!r}")
        members = {id(p): p for p in (self, *others)}
        for plot in list(members.values()):
            for other in plot.linked:
                members.setdefault(id(other), other)
        group = next((p._link["group"] for p in members.values() if p._link), None)
        group = group or f"atl-{uuid.uuid4().hex[:12]}"
        for plot in members.values():
            old = plot._link.get("group")
            if old and old != group:
                _LINKS.get(old, weakref.WeakSet()).discard(plot)
            _LINKS.setdefault(group, weakref.WeakSet()).add(plot)
            plot._link = {"group": group, "align": align}
        return self

    def unlink(self) -> Self:
        """Leave the group of linked plots (the others stay linked)."""
        group = self._link.get("group")
        if group:
            _LINKS.get(group, weakref.WeakSet()).discard(self)
        self._link = {}
        return self

    @property
    def linked(self) -> list[Timeline]:
        """The other plots this one is linked with."""
        group = self._link.get("group")
        return [p for p in _LINKS.get(group, ()) if p is not self] if group else []

    def save_png(self, path: str | PathLike[str]) -> None:
        """Save the plot as a PNG, as it is shown in the notebook (its view, zoom and folded
        lanes; title and legend; at twice the screen's resolution).

        The picture is drawn in the browser, so the plot must be on screen, and the file is
        written when the browser sends it: in Jupyter right after the cell has run, not
        during it. The toolbar's Save as PNG button does the same as a download; use this
        where downloads are blocked (VS Code) or from code.

        Args:
            path: The file to write (``.png``).
        """
        self._snapshots += 1
        self._snapshot_paths[str(self._snapshots)] = Path(path)
        self.send({"type": "snapshot", "request": str(self._snapshots)})

    def _receive_image(self, content: Mapping[str, Any], buffers: Any) -> None:
        path = self._snapshot_paths.pop(str(content.get("request")), None)
        if path is None:  # another view answered first
            return
        if content.get("error") or not buffers:
            raise RuntimeError(f"the plot could not be drawn as a PNG: {content.get('error')}")
        data = buffers[0]
        path.write_bytes(bytes(data.tobytes() if hasattr(data, "tobytes") else data))

    def _embed_html(self) -> str:
        """The plot as an HTML fragment for a page that loads ``standalone.js`` and
        ``widget.css`` once (the documentation): any number of plots per page, each drawn
        when it comes near the screen, with all its data in the page."""
        return (
            '<div class="anytimeline-embed">'
            f'<script type="application/json">{self._standalone_data()}</script></div>'
        )

    def _standalone_data(self) -> str:
        """The plot's spec, data and settings as JSON that is safe inside a <script>."""
        payload = {
            "spec": self._spec,
            "buffers": {
                i: base64.b64encode(data).decode("ascii") for i, data in self._buffers.items()
            },
            "height": self.height,
            "renderer": self.renderer,
            "title": self.title,
            "xscale": self.xscale,
            "tool": self.tool,
            "legend": self.legend,
            "hover": self.hover,
            "font_size": self.font_size,
            "mark_scale": self.mark_scale,
            "dodge": self.dodge,
            "zoom": self._zoom.get("range"),
            "marks": {k: base64.b64encode(v).decode("ascii") for k, v in self._marks.items()},
            "tooltips": self._tooltip_tables(),
            "link": self._link or None,
        }
        # "</" cannot close the script element it is in
        return json.dumps(payload, allow_nan=False, separators=(",", ":")).replace("</", "<\\/")

    def _tooltip_tables(self) -> dict[str, dict[str, Any]]:
        """Per layer, its tooltip columns as text in the order the browser has the events,
        for pages without Python; left out for layers larger than TOOLTIP_CELLS."""
        out: dict[str, dict[str, Any]] = {}
        for name, rec in self._layers.items():
            if not rec.tooltip or len(rec.perm) * len(rec.tooltip) > TOOLTIP_CELLS:
                continue
            out[name] = {
                "columns": list(rec.tooltip),
                "values": [
                    [_text(v) for v in values[rec.perm].tolist()] for values in rec.tooltip.values()
                ],
            }
        return out

    # ------------------------------------------------------------------ messages

    def _on_frontend_msg(self, _widget: Any, content: dict[str, Any], _buffers: Any) -> None:
        kind = content.get("type")
        if kind == "need":
            for buffer_id in content.get("ids", []):
                self._send_buffer(str(buffer_id))
        elif kind == "tooltip":
            answer: dict[str, Any] = {"type": "answer", "request": content.get("request")}
            try:
                answer["rows"] = self._tooltip(str(content.get("layer")), int(content["index"]))
            except Exception as err:  # the browser shows what it has; the kernel carries on
                answer["error"] = str(err)
            self.send(answer)
        elif kind == "view":
            r = content.get("range")
            if isinstance(r, list) and len(r) == 2:
                self._view_range = (float(r[0]), float(r[1]))
        elif kind == "image":
            self._receive_image(content, _buffers)
        elif kind == "perf":
            update = content.get("update")
            if isinstance(update, dict):
                self.perf = {**self.perf, **update}

    def _send_buffer(self, buffer_id: str) -> None:
        data = self._buffers.get(buffer_id)
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

    def _tooltip(self, layer: str, index: int) -> list[list[str]]:
        key = (layer, index)
        if key in self._tooltip_cache:
            return self._tooltip_cache[key]
        rec = self._layers[layer]
        pos = int(rec.perm[index])
        rows = [[name, _text(values[pos])] for name, values in rec.tooltip.items()]
        self._tooltip_cache[key] = rows
        return rows

    # ------------------------------------------------------------------ selection

    def on_select(
        self, callback: Callable[[dict[str, list[int]]], Any], *, remove: bool = False
    ) -> None:
        """Call ``callback(selection)`` after every change of the selection made in the plot.

        Pass ``remove=True`` to unregister it.
        """
        self._select_handlers.register_callback(callback, remove=remove)

    @traitlets.validate("font_size")
    def _check_font_size(self, proposal: dict[str, Any]) -> int:
        value = proposal["value"]
        lo, hi = FONT_SIZES
        if not lo <= value <= hi:
            raise traitlets.TraitError(f"font_size must be {lo} to {hi} pixels, got {value}")
        return value

    @traitlets.validate("mark_scale")
    def _check_mark_scale(self, proposal: dict[str, Any]) -> float:
        value = float(proposal["value"])
        if not 0.25 <= value <= 4:
            raise traitlets.TraitError(f"mark_scale must be 0.25 to 4, got {value}")
        return value

    @traitlets.validate("selection")
    def _check_selection(self, proposal: dict[str, Any]) -> dict[str, list[int]]:
        value = proposal["value"]
        unknown = [k for k in value if k not in self._layers]
        if unknown:
            raise traitlets.TraitError(f"no layer {unknown[0]!r}; layers: {self.layers}")
        return {k: sorted({int(r) for r in v}) for k, v in value.items() if len(v)}

    @traitlets.observe("selection")
    def _selection_changed(self, change: dict[str, Any]) -> None:
        self._marks = self._marks_of(change["new"])

    def _marks_of(self, selection: Mapping[str, list[int]]) -> dict[str, bytes]:
        """Per layer, the browser's indices of the selected rows, as int32 bytes."""
        marks: dict[str, bytes] = {}
        for name, rows in selection.items():
            rec = self._layers.get(name)
            if rec is None or not len(rows) or not len(rec.perm):
                continue
            pos_of_row = np.full(
                int(rec.rows.max()) + 1 if len(rec.rows) else 0, -1, dtype=np.int64
            )
            pos_of_row[rec.rows] = np.arange(len(rec.rows))
            wanted = np.asarray([r for r in rows if 0 <= r < len(pos_of_row)], dtype=np.int64)
            pos = pos_of_row[wanted]
            pos = pos[pos >= 0]
            inverse = np.empty(len(rec.perm), dtype=np.int64)
            inverse[rec.perm] = np.arange(len(rec.perm))
            marks[name] = np.sort(inverse[pos]).astype("<i4").tobytes()
        return marks

    @traitlets.observe("_pick")
    def _on_pick(self, change: dict[str, Any]) -> None:
        pick = change["new"] or {}
        kind = pick.get("kind")
        mode = pick.get("mode", "replace")
        if kind == "clear":
            new: dict[str, set[int]] = {}
        else:
            hits = self._resolve(pick)
            if hits is None:
                return
            if self.selection_mode == "single":
                hits = dict(list(hits.items())[:1])
                hits = {k: set(sorted(v)[:1]) for k, v in hits.items()}
                mode = "replace"
            old = {k: set(v) for k, v in self.selection.items()}
            if mode == "replace":
                new = hits
            elif mode == "add":
                new = {k: old.get(k, set()) | hits.get(k, set()) for k in old.keys() | hits.keys()}
            elif mode == "remove":
                new = {k: old.get(k, set()) - hits.get(k, set()) for k in old}
            else:  # toggle
                new = {k: old.get(k, set()) ^ hits.get(k, set()) for k in old.keys() | hits.keys()}
        selection = {k: sorted(v) for k, v in new.items() if v}
        if selection != self.selection:
            self.selection = selection
            self._select_handlers(self.selection)

    def _resolve(self, pick: Mapping[str, Any]) -> dict[str, set[int]] | None:
        """Table rows per layer that a click or a box picks."""
        kind = pick.get("kind")
        if kind == "click":
            name = str(pick.get("layer"))
            rec = self._layers.get(name)
            index = int(pick.get("index", -1))
            if rec is None or not rec.select or not 0 <= index < len(rec.perm):
                return None
            return {name: {int(rec.rows[rec.perm[index]])}}
        if kind == "box":
            x0, x1 = sorted(float(v) for v in pick["x"])
            l0, l1 = sorted(int(v) for v in pick["lanes"])
            shown = pick.get("shown")  # with folded lanes: the lanes in the box that show
            by_rank = pick.get("xscale") == "sequence"
            out: dict[str, set[int]] = {}
            for name, rec in self._layers.items():
                lay = self._laid[name]
                if not rec.select:
                    continue
                if by_rank:
                    lo, hi = self._ranks[name][:, 0], self._ranks[name][:, -1]
                else:
                    lo, hi = lay.lo, lay.hi
                lanes = lay.lanes
                in_lanes = (
                    np.isin(lanes, np.asarray(shown, dtype=np.int64))
                    if shown is not None
                    else (lanes >= l0) & (lanes <= l1)
                )
                inside = np.flatnonzero((hi >= x0) & (lo <= x1) & in_lanes)
                if len(inside):
                    out[name] = {int(r) for r in rec.rows[rec.perm[inside]]}
            return out
        return None


def _text(value: Any) -> str:
    if value is None:
        return "–"
    if isinstance(value, np.datetime64):
        return str(value)
    if isinstance(value, float | np.floating):
        return "–" if value != value else f"{float(value):.6g}"
    return label(value)


_LINKS: dict[str, weakref.WeakSet[Timeline]] = {}
"""Groups of linked plots, by group id (``Timeline.link``)."""


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
    shown: list[Timeline] = []
    for p in plots:
        shown.extend([p] if isinstance(p, Timeline) else list(p))
    if not shown:
        raise ValueError("no plots to save")
    for p in shown:
        if not p._layers:
            raise ValueError("a plot has no layers yet: add some before saving it")
    script = (_STATIC / "standalone.js").read_text(encoding="utf-8")
    style = (_STATIC / "widget.css").read_text(encoding="utf-8")
    name = title if title is not None else (shown[0].title or "anytimeline")
    fill = ' data-fill="window"' if len(shown) == 1 else ""
    embeds = "\n".join(
        f'<div class="anytimeline-embed"{fill}>\n'
        f'<script type="application/json">{p._standalone_data()}</script>\n</div>'
        for p in shown
    )
    page = _PAGE.format(
        title=html.escape(name),
        style=style,
        plots=embeds,
        # "</script" in the code would end the element early
        script=script.replace("</script", "<\\/script"),
    )
    out = Path(path)
    out.write_text(page, encoding="utf-8")
    return out


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
