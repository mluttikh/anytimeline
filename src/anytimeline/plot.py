"""The plot: ``Timeline``, its layers and settings. A plain Python object; the widget that
shows it in a notebook (``plot.widget``, ``widget.py``) is made only when it is shown, and
pages and images need none (``page.py``)."""

from __future__ import annotations

import copy
import uuid
import warnings
import weakref
from collections.abc import Callable, Iterable, Mapping, Sequence
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self, get_args

import numpy as np
from ipywidgets import CallbackDispatcher

from anytimeline import data as tables
from anytimeline import find, grouping, image, page, scene
from anytimeline import summary as summaries
from anytimeline.data import NotFoundError
from anytimeline.lanes import LANE_SORTS
from anytimeline.layers import common
from anytimeline.layers import events as ev
from anytimeline.layers import intervals as iv
from anytimeline.layers import states as st
from anytimeline.layers import values as vl
from anytimeline.parts import Annotation, Connection, Marker, Route, Stem
from anytimeline.renamed import gone, gone_method, renamed
from anytimeline.settings import (
    at_least,
    between,
    flag,
    hooks,
    mapping,
    observes,
    one_of,
    same,
    setting,
    text,
    text_or_none,
    validates,
    values_or_none,
    whole,
)
from anytimeline.timebase import TimeBase
from anytimeline.types import (
    Align,
    BarOverlap,
    Clim,
    Display,
    EventOverlap,
    Expand,
    LaneSort,
    Renderer,
    SelectionMode,
    StemShape,
    Tool,
    ValuesKind,
    ValuesScale,
    XScale,
)
from anytimeline.view import View

if TYPE_CHECKING:
    from anytimeline.widget import TimelineWidget

RENDERERS = get_args(Renderer)
SELECTION_MODES = (*get_args(SelectionMode), None)
XSCALES = get_args(XScale)
TOOLS = get_args(Tool)
DISPLAYS = get_args(Display)
ALIGNS = get_args(Align)
FONT_SIZES = (8, 24)
WINDOW_KEEP = 8
UNDO_STEPS = 50
"""How many changes of the selection ``undo_selection`` can take back."""
MARKED = 100_000
"""Of an events layer sent as levels, the browser shows at most this many selected events over
its bins (all of them once zoomed in to its events)."""
"""How many windows' buffers a plot keeps for the browser to ask for (layers sent as levels)."""
"""The smallest and largest text size, in pixels."""

_LAYOUT = ("markers", "timezone", "lane_order", "sort", "group_order", "align", "lane_names")
"""Settings that change how the layers are laid out: the plot is laid out again."""
_NOT_COPIED = ("_widget", "_watchers", "_select_handlers", "_snapshot_paths")
"""What a pickled or copied plot leaves out (``__getstate__``)."""


def _annotations(value: Any, name: str) -> list[Annotation]:
    if isinstance(value, Annotation) or not isinstance(value, Sequence | tuple):
        raise TypeError(f"{name} must be a list of Annotations, got {value!r}")
    for a in value:
        if not isinstance(a, Annotation):
            raise TypeError(f"{name} must be a list of Annotations, got {a!r} among them")
    return list(value)


def _connections(value: Any, name: str) -> list[Connection]:
    if isinstance(value, Connection) or not isinstance(value, Sequence | tuple):
        raise TypeError(f"{name} must be a list of Connections, got {value!r}")
    for c in value:
        if not isinstance(c, Connection):
            raise TypeError(f"{name} must be a list of Connections, got {c!r} among them")
    return list(value)


def _xscale(value: Any, name: str) -> Any:
    if value == "sequence":
        raise ValueError(f"{name}='order' is the Order scale ('sequence' was 0.4's)")
    return one_of(XSCALES)(value, name)


def _selection_mode(value: Any, name: str) -> Any:
    if value == "none":
        raise ValueError(f"{name}=None: nothing can be selected ('none' was 0.4's)")
    return one_of(SELECTION_MODES)(value, name)


def _markers(value: Any, name: str) -> list[Marker]:
    if isinstance(value, Marker) or not isinstance(value, Sequence | tuple):
        raise TypeError(f"{name} must be a list of Markers, got {value!r}")
    for m in value:
        if not isinstance(m, Marker):
            raise TypeError(f"{name} must be a list of Markers, got {m!r} among them")
    return list(value)


class Timeline:
    """An interactive timeline: layers of events on lanes, drawn on the GPU.

    Add layers with [`events`][anytimeline.Timeline.events]; show the plot by making it the
    last expression of a notebook cell. Click into the plot, then scroll to zoom time; drag
    to pan; double-click to reset.

    Every argument is also a setting of the same name (``plot.tool = "select"``), except
    ``time_unit``. A setting is checked when it is set: a value of the wrong kind raises a
    ``TypeError``, a wrong value a ``ValueError``.

    A plot is a Python object; the widget that shows it in a notebook
    ([`widget`][anytimeline.Timeline.widget]) is made when it is first shown, and pages and
    images ([`save_html`][anytimeline.Timeline.save_html]) need none. ``copy.copy``,
    ``copy.deepcopy`` and pickling give a plot of its own, with the layers, settings and
    view, and without the widget, links and ``on_select`` callbacks.

    Args:
        height: Height in pixels; 0 sizes the plot to its lanes (at most 640 px).
        title: Shown above the plot.
        xscale: ``"time"`` (events at their time) or ``"order"`` (events by the order in
            which they happened, evenly spaced).
        timezone: Time zone to show datetimes in (an IANA name such as
            ``"Europe/Amsterdam"``). Default: the time column's own, else UTC.
        time_unit: For numeric time columns: what one unit is (``"s"``, ``"ms"``, ``"us"``,
            ``"ns"``); the numbers are then durations. Without it they are plain numbers.
        lane_order: Lanes to show first, top to bottom.
        sort: Lane order: ``"name"`` (natural sort), ``"first"`` / ``"last"`` (time of a
            lane's first / last event), ``"count"`` (most events first) or ``"table"`` (as
            they first appear). Default: ``"name"``, or the table's order for a tree.
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
        hover: Show a tooltip for the mark under the pointer.
        legend: Show the legend.
        summary_panel: Show the selection in numbers (count, and for bars total and mean
            duration, by colour category and lane) in a panel while something is selected;
            [`summary`][anytimeline.Timeline.summary] gives them as a table.
        selection_mode: ``"multiple"``: boxes, and Shift/Ctrl/Cmd-clicks that add;
            ``"single"``: one mark; ``None``: nothing can be selected (no Select tool).
        display: How a notebook shows the plot: ``"widget"`` (default; connected to Python)
            or ``"html"`` (the page [`save_html`][anytimeline.Timeline.save_html] writes,
            which a saved or exported notebook shows without a kernel).
    """

    height: int = setting(0, at_least(0, unit=" pixels"))
    """Height in pixels; 0 sizes the plot to its lanes."""
    title: str = setting("", text)
    """Shown above the plot."""
    xscale: XScale = setting("time", _xscale)
    """``"time"`` or ``"order"``; also the Time / Order switch in the plot."""
    renderer: Renderer = setting("auto", one_of(RENDERERS))
    """The drawing backend; ``"auto"`` picks the first that works."""
    tool: Tool = setting("pan", one_of(TOOLS))
    """The plot's tool: ``"pan"`` (drag pans; Shift-drag zooms to a range; a plain click does
    nothing), ``"zoom"`` (drag zooms to a time range; click zooms in, Alt-click out) or
    ``"select"`` (drag selects a box; click selects an event). Also the toolbar and keys
    ``p``, ``z``, ``s``."""
    font_size: int = setting(12, between(*FONT_SIZES, kind=whole, unit=" pixels"))
    """The size of the plot's text in pixels (8 to 24): lane names, the time axis, labels,
    legend, tooltips. Also in the toolbar's Display panel."""
    mark_scale: float = setting(1.0, between(0.25, 4))
    """The size of event marks, as a factor of the sizes the layers give them (0.25 to 4):
    smaller marks overlap less in dense data. Also in the toolbar's Display panel."""
    dodge: bool = setting(True, flag)
    """Spread events that would overlap over the lane's height (sub-rows), so ties and bursts
    stay countable; False draws every event on its lane's line. Layers with
    ``overlap="overlay"`` never spread. Also in the Display panel, and the key ``d``."""
    hover: bool = setting(True, flag)
    """Show a tooltip for the mark under the pointer."""
    legend: bool = setting(True, flag)
    """Show the legend."""
    summary_panel: bool = setting(True, flag)
    """Show the selection in numbers in a panel while something is selected; see
    [`summary`][anytimeline.Timeline.summary]."""
    selection_mode: SelectionMode | None = setting("multiple", _selection_mode)
    """``"multiple"``: boxes, and Shift/Ctrl/Cmd-clicks that add; ``"single"``: one mark;
    ``None``: no selection (the Select tool is not offered)."""
    selection: dict[str, list[int]] = setting({}, mapping)
    """The selected marks: layer name → sorted table rows. Set it to select rows;
    [`selected`][anytimeline.Timeline.selected] gives them as a table."""
    display: Display = setting("widget", one_of(DISPLAYS), sync=False)
    """How a notebook shows the plot. ``"widget"``: connected to Python, so selections reach
    it and changes made in Python after it is shown reach the plot. ``"html"``: as the page
    [`save_html`][anytimeline.Timeline.save_html] writes, with its data in the output, so a
    saved, exported (nbconvert, Quarto) or shared notebook shows it without a kernel or
    saved widget state. Zoom, pan, hover, Time / Order, folding, full screen and linking
    work there; selecting does not, and a change made in Python shows when the plot is
    shown again."""
    markers: list[Marker] = setting([], _markers, sync=False)
    """The plot's [`Marker`][anytimeline.Marker]s: vertical lines across the lanes at a time.
    [`marker`][anytimeline.Timeline.marker] adds one; ``plot.markers = []`` removes them."""
    annotations: list[Annotation] = setting([], _annotations, sync=False)
    """The plot's [`Annotation`][anytimeline.Annotation]s: notes on a time range or a time,
    over a lane or all. [`annotate`][anytimeline.Timeline.annotate] adds one, as does the key
    ``a`` in the plot; ``plot.annotations = []`` removes them."""
    connections: list[Connection] = setting([], _connections, sync=False)
    """The plot's [`Connection`][anytimeline.Connection]s: arrows from one mark to another.
    [`connect`][anytimeline.Timeline.connect] adds one, as does the key ``c`` in the plot
    (on one mark, then on another); ``plot.connections = []`` removes them."""
    timezone: str | None = setting(None, text_or_none, sync=False)
    """The time zone datetimes are shown in; None: the time column's own, else UTC."""
    lane_order: list[Any] | None = setting(None, values_or_none, sync=False)
    """Lanes to show first, top to bottom."""
    sort: LaneSort | None = setting(None, one_of((*LANE_SORTS, None)), sync=False)
    """The order of the other lanes; None: by name (a tree: as in the table)."""
    group_order: list[Any] | None = setting(None, values_or_none, sync=False)
    """Groups to show first, top to bottom."""
    align: Align = setting("time", one_of(ALIGNS), sync=False)
    """``"time"`` or ``"start"``: groups compared from their first time."""
    lane_names: bool = setting(True, flag, sync=False)
    """Show the lanes' names left of the plot."""

    _spec: dict[str, Any] = setting({})
    _pick: dict[str, Any] = setting({})
    _marks: dict[str, bytes] = setting({})
    _marked: dict[str, bytes] = setting({})
    """Per events layer sent as levels: where its selected events are (time, order and lane,
    float64), so that they show over its bins; at most MARKED of them."""
    _notes: dict[str, Any] = setting({})
    """The annotations and connections as the browser draws them (ticks, lane indices)."""
    _summary: list[dict[str, Any]] = setting([])
    """What the summary panel shows: per layer with something selected, its numbers as text."""
    _zoom: dict[str, Any] = setting({})
    _link: dict[str, Any] = setting({})
    """The group of linked plots: ``{"group": id, "align": "time" | "start"}``, or empty."""

    # removed in 0.5: what replaced them
    range = gone("Timeline.range", "plot.view: its start and end")
    perf = gone("Timeline.perf", "plot.dev.perf")
    clear_markers = gone_method("Timeline.clear_markers", "plot.markers = []")
    observe = gone_method("Timeline.observe", "plot.widget.observe (the plot is no widget)")
    unobserve = gone_method("Timeline.unobserve", "plot.widget.unobserve")

    def __init__(
        self,
        *,
        height: int = 0,
        title: str = "",
        xscale: XScale = "time",
        timezone: str | None = None,
        time_unit: str | None = None,
        lane_order: Sequence[Any] | None = None,
        sort: LaneSort | None = None,
        group_order: Sequence[Any] | None = None,
        align: Align = "time",
        lane_names: bool = True,
        renderer: Renderer = "auto",
        tool: Tool = "pan",
        font_size: int = 12,
        mark_scale: float = 1.0,
        dodge: bool = True,
        hover: bool = True,
        legend: bool = True,
        summary_panel: bool = True,
        selection_mode: SelectionMode | None = "multiple",
        display: Display = "widget",
    ) -> None:
        self._settings: dict[str, Any] = hooks(type(self)).defaults()
        given = {
            "height": height,
            "title": title,
            "xscale": xscale,
            "timezone": timezone,
            "lane_order": lane_order,
            "sort": sort,
            "group_order": group_order,
            "align": align,
            "lane_names": lane_names,
            "renderer": renderer,
            "tool": tool,
            "font_size": font_size,
            "mark_scale": mark_scale,
            "dodge": dodge,
            "hover": hover,
            "legend": legend,
            "summary_panel": summary_panel,
            "selection_mode": selection_mode,
            "display": display,
        }
        self._time_unit = time_unit
        self._layers: dict[str, scene.Record] = {}
        self._tables: dict[str, Any] = {}
        """Each layer's table as read (a lazy table read once), for ``selected``."""
        self._laid: dict[str, scene.Layout] = {}
        self._ranks: dict[str, np.ndarray] = {}
        self._buffers: dict[str, bytes] = {}
        self._scene: scene.Scene | None = None
        self._page: tuple[dict[str, Any], dict[str, bytes]] | None = None
        """The spec and buffers of a page of the plot (with layers sent as levels: of its own)."""
        self._window_buffers: dict[str, bytes] = {}
        """The buffers of the windows sent last (layers sent as levels)."""
        self._windows: list[list[str]] = []  # each of those windows' buffer ids, oldest first
        self._base: TimeBase | None = None
        self._view = View()
        """The view set last (``plot.view``)."""
        self._view_shown: dict[str, Any] | None = None
        """What the browser reported it shows: ``{"range": (t0, t1), "lanes": [...]}``."""
        self._perf: dict[str, Any] = {}
        self._tooltip_cache: dict[tuple[str, int], list[list[str]]] = {}
        self._findable: list[find.Marks] | None = None
        """What search and stepping see (made when first asked; again after a change)."""
        self._undo: list[dict[str, list[int]]] = []
        """The selections before the last changes, the latest last (``undo_selection``)."""
        self._redo: list[dict[str, list[int]]] = []
        self._undoing = False
        self._snapshots = 0
        self._snapshot_paths: dict[str, Path] = {}
        self._widget: TimelineWidget | None = None
        self._watchers: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._select_handlers = CallbackDispatcher()
        for name, value in given.items():
            self._settings[name] = self._checked(name, value)
        self._update_spec()

    # ------------------------------------------------------------------ settings & widget

    def _checked(self, name: str, value: Any) -> Any:
        """A setting's value as kept: of its kind, and passed by its validators."""
        h = hooks(type(self))
        check = h.settings[name].check
        if check is not None:
            value = check(value, name)
        for fn in h.validators.get(name, []):
            value = fn(self, value, name)
        return value

    def _set(self, name: str, value: Any, *, shown: bool = False) -> None:
        """Set a setting: checked, kept, sent to the widget, and observed when it changed.
        ``shown``: the browser changed it, through the widget, which then gets it back only
        as checked (e.g. a selection sorted) or, when refused, as it was."""
        h = hooks(type(self))
        synced = self._widget is not None and h.settings[name].sync
        try:
            kept = self._checked(name, value)
        except (TypeError, ValueError):
            if shown and synced:
                self._show(name, self._settings[name])
            raise
        old = self._settings[name]
        self._settings[name] = kept
        if synced and not (shown and same(kept, value)):
            self._show(name, kept)
        if same(old, kept):
            return
        change = {"name": name, "old": old, "new": kept, "owner": self}
        for fn in h.observers.get(name, []):
            fn(self, change)
        for watcher in list(self._watchers.get(name, [])):
            watcher(change)

    def _show(self, name: str, value: Any) -> None:
        """Send a setting to the widget."""
        assert self._widget is not None
        self._widget.show(name, value)

    def _watch(self, name: str, fn: Callable[[dict[str, Any]], None]) -> None:
        """Call ``fn(change)`` after each change of a setting (``anytimeline.marimo``)."""
        self._watchers.setdefault(name, []).append(fn)

    def _unwatch(self, name: str, fn: Callable[[dict[str, Any]], None]) -> None:
        self._watchers[name] = [f for f in self._watchers.get(name, []) if f != fn]

    @property
    def widget(self) -> TimelineWidget:
        """The widget that shows the plot in a notebook: an
        [anywidget](https://anywidget.dev), made the first time the plot is shown or this is
        read, then the same one. Showing ``plot`` shows it; take it where a widget itself
        is needed:

        ```python
        ipywidgets.VBox([trace_plot.widget, metrics_plot.widget])  # Jupyter
        mo.ui.anywidget(plot.widget)  # marimo, bound to a name
        ```

        Its synced traits are the plot's settings: ``plot.widget.observe(fn, "tool")`` sees
        each change. A plot that is only saved or shown as HTML
        ([`to_html`][anytimeline.Timeline.to_html], ``display="html"``) never makes one.
        """
        if self._widget is None:
            from anytimeline.widget import TimelineWidget

            synced = hooks(type(self)).synced
            self._widget = TimelineWidget(self, {n: self._settings[n] for n in synced})
        return self._widget

    def _send(self, content: dict[str, Any], buffers: list[Any] | None = None) -> None:
        """A message to the plot in the browser (none without a widget)."""
        if self._widget is not None:
            self._widget.send(content, buffers=buffers)

    # a pickled or copied plot: its layers, settings and view, without its widget, its links
    # and its callbacks (on_select); shown, a copy makes a widget of its own
    def __getstate__(self) -> dict[str, Any]:
        state = {k: v for k, v in self.__dict__.items() if k not in _NOT_COPIED}
        state["_settings"] = {**self._settings, "_link": {}, "_pick": {}}
        state["_view_shown"] = None
        state["_window_buffers"], state["_windows"], state["_page"] = {}, [], None
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)
        self._widget = None
        self._watchers = {}
        self._select_handlers = CallbackDispatcher()
        self._snapshot_paths = {}

    # a copy of its own (as copy.deepcopy): a plot to change without changing this one
    def __copy__(self) -> Self:
        return copy.deepcopy(self)

    @property
    def time_unit(self) -> str | None:
        """For numeric time columns: what one unit is (set when the plot is made)."""
        return self._time_unit

    @observes(*_LAYOUT)
    def _layout_changed(self, change: dict[str, Any]) -> None:
        try:
            self._update_spec()
        except Exception:
            self._settings[change["name"]] = change["old"]
            self._update_spec()
            raise

    # ------------------------------------------------------------------ layers

    @renamed(
        labels="stems=True (labels='stems'), or leave it out (labels='beside')",
        stem_shape="stems=Stem(shape=...), or stems='curved'",
        label_width="stems=Stem(width=...)",
    )
    def events(
        self,
        data: Any,
        time: str | None = "time",
        *,
        lane: str | None = None,
        order: str | None = None,
        color: str | None = None,
        colormap: str | Sequence[str] | None = None,
        clim: Clim | None = None,
        palette: Mapping[Any, str] | Sequence[str] | None = None,
        opacity: float = 1.0,
        symbol: str | None = None,
        symbols: Mapping[Any, str] | Sequence[str] | None = None,
        size: float | str | None = None,
        size_range: tuple[float, float] = (4.0, 16.0),
        text: str | None = None,
        stems: Stem | StemShape | bool | None = None,
        importance: str | None = None,
        tooltip: str | Sequence[str] | None = None,
        route: Route | str | None = None,
        overlap: EventOverlap = "dodge",
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
            text: A column, or a template such as ``"{event}"``: each event's text, right of
                its mark where there is room (left out where it would overlap another).
            stems: Put the text in boxes above and below the lane's line instead, at as many
                levels as needed so no two overlap, each joined to its event by a line (a
                story timeline: few events, the text matters). ``True``, a shape
                (``"curved"``) or a [`Stem`][anytimeline.Stem]; ``None``: beside the marks.
                A line break (``"{time:%H:%M}\\n{title}"``) gives a box two lines.
            importance: A numeric column; where text would overlap, the more important
                events keep theirs. In a layer sent as levels (many events), each bin is
                shown by its most important event.
            tooltip: Columns shown when hovering an event (its time and lane always are).
            route: A column (or a [`Route`][anytimeline.Route]) whose groups are joined by
                lines in the order their events happened.
            overlap: ``"dodge"``: events that would overlap are spread over sub-rows of the
                lane; ``"overlay"``: drawn on top of each other.
            group: A column of groups (a host, a region, a day): each group gets a header
                lane with its own lanes under it, in the plot's lane order; groups fold.
            hover: Show tooltips for this layer.
            select: Whether its events can be selected.
            name: The layer's name; adding a layer with an existing name replaces it.
        """
        stem = Stem.of(stems)
        tooltip = _columns(tooltip, "tooltip")
        data = tables.read_once(data, *_arguments(locals()))
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
            labels="stems" if stem is not None else "beside",
            stem_shape=stem.shape if stem is not None else "straight",
            # the browser's label_width: None, 16 × the text size; 0, no limit
            label_width=None
            if stem is None or stem.width == "auto"
            else 0.0
            if stem.width is None
            else float(stem.width),
            importance=importance,
            time_unit=self._time_unit,
            hover=hover,
            select=select,
        )
        return self._add(record, data, group)

    @renamed(label="lane= (with parent=: the column that names each bar's lane)")
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
        parent: str | None = None,
        depends: str | None = None,
        color: str | None = None,
        colormap: str | Sequence[str] | None = None,
        clim: Clim | None = None,
        palette: Mapping[Any, str] | Sequence[str] | None = None,
        opacity: float = 1.0,
        text: str | None = None,
        tooltip: str | Sequence[str] | None = None,
        progress: str | None = None,
        overlap: BarOverlap = "pack",
        height: float = 0.7,
        expand: Expand = "auto",
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
            lane: The column whose values are the lanes (a task, a machine, a person). With
                ``parent``: the column that names each bar's own lane (by default its id).
            id: The column that names each bar, for ``depends`` and ``parent``; by default
                the lane.
            parent: A column with each bar's parent (its id; missing for a top bar): the bars
                form a tree, each bar on its own lane under its parent, which you can fold.
                Needs ``id=``. Bars whose parent is not in the table are shown at the top.
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
            expand: With ``parent``: the levels shown at first (1: the top bars only),
                ``"all"``, or ``"auto"``: as many as keep about 200 lanes. Click a lane's name
                to fold or unfold it.
            critical_path: With ``parent``: mark the critical path of each top bar, the parts
                of bars its end waited for.
            durations: Write each bar's duration right of it.
            group: A column of groups (a host, a region, a day): each group gets a header
                lane with its own lanes under it, in the plot's lane order; groups fold.
            hover: Show tooltips for this layer.
            select: Whether its bars can be selected.
            name: The layer's name; adding a layer with an existing name replaces it.
        """
        tooltip = _columns(tooltip, "tooltip")
        data = tables.read_once(data, *_arguments(locals()))
        record = iv.build(
            data,
            name=name,
            start=start,
            end=end,
            duration=duration,
            lane=None if parent is not None else lane,
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
            label=lane if parent is not None else None,
            expand=_expand(expand),
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
        text: str | Literal[True] | None = True,
        tooltip: str | Sequence[str] | None = None,
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
        or to the plot's last time. Hovering a state shows every lane's state at the
        pointer's time.

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
            text: What to write in each band where it fits: ``True`` (the state), a column or
                a template such as ``"{state} ({reason})"``, or ``None``.
            tooltip: More columns shown when hovering a state (its state, start, end and
                duration always are).
            height: The band's height, as a fraction of the lane.
            group: A column of groups (a host, a region, a day): each group gets a header
                lane with its own lanes under it, in the plot's lane order; groups fold.
            hover: Show tooltips for this layer.
            select: Whether its states can be selected (as the rows that start them).
            name: The layer's name; adding a layer with an existing name replaces it.
        """
        if text is False:
            raise TypeError("states(text=None) leaves the text out (text=False was 0.4's)")
        tooltip = _columns(tooltip, "tooltip")
        data = tables.read_once(data, *_arguments(locals()))
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
            text=text if text is not None else False,
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
        kind: ValuesKind = "line",
        scale: ValuesScale = "lane",
        ylim: tuple[float, float] | Mapping[Any, tuple[float, float]] | None = None,
        width: float = 1.5,
        tooltip: str | Sequence[str] | None = None,
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
        tooltip = _columns(tooltip, "tooltip")
        data = tables.read_once(data, *_arguments(locals()))
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

    @renamed(label="lane= (the column that names each span's lane)")
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
        lane: str = "name",
        color: str | None = None,
        colormap: str | Sequence[str] | None = None,
        clim: Clim | None = None,
        palette: Mapping[Any, str] | Sequence[str] | None = None,
        opacity: float = 1.0,
        text: str | None = None,
        tooltip: str | Sequence[str] | None = None,
        expand: Expand = "auto",
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
            lane: The column that names each span's lane.
            color: A column (the service, the status) or one colour.
            colormap: For numbers: a colormap name or a list of colours.
            clim: For numbers: colour limits ``(low, high)``, or ``"robust"``.
            palette: For categories: colours in order, or a dict of value → colour.
            opacity: 0 to 1.
            text: Written in each bar where it fits (a column or a template).
            tooltip: Columns shown when hovering a span.
            expand: The levels shown at first (1: the roots only), ``"all"``, or ``"auto"``:
                as many as keep about 200 lanes.
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
            lane=lane,
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
        old, old_tables = dict(self._layers), dict(self._tables)
        self._layers[record.name] = record
        self._tables[record.name] = data
        try:
            self._update_spec()
        except Exception:
            self._layers, self._tables = old, old_tables
            raise
        return self

    def marker(self, time: Any, label: str = "", *, color: str | None = None) -> Self:
        """Add a [`Marker`][anytimeline.Marker]: a vertical line across the lanes at a time,
        such as now or a deadline. ``plot.markers = []`` removes them all.

        Args:
            time: A time of the data's kind (datetime, ISO text, duration or number).
            label: Written at the top of the line.
            color: The line's colour (default: the selection colour).
        """
        self.markers = [*self.markers, Marker(time, label, color)]
        return self

    def annotate(
        self,
        start: Any,
        end: Any = None,
        text: str = "",
        *,
        lane: Any = None,
        color: str | None = None,
    ) -> Self:
        """Add an [`Annotation`][anytimeline.Annotation]: a note on a time range (or, without
        ``end``, at a time), over one lane or all of them. It shows in the plot, in pages
        and in images; ``plot.annotations = []`` removes them all. In the plot, the key
        ``a`` and then a drag over a range (or a click at a time) adds one too.

        Args:
            start: Where it starts: a time of the data's kind (datetime, ISO text, duration
                or number).
            end: Where it ends; ``None``: a note at one time.
            text: Written at its top.
            lane: The lane it is in (a lane's name); ``None``: across all lanes.
            color: Its colour (default: the accent colour).
        """
        note = Annotation(start, end, text, lane, color)
        if self._layers:
            self._note_of(note)  # wrong times and lanes raise here
        self.annotations = [*self.annotations, note]
        return self

    def connect(
        self,
        a: int | tuple[str, int],
        b: int | tuple[str, int],
        text: str = "",
        *,
        color: str | None = None,
    ) -> Self:
        """Add a [`Connection`][anytimeline.Connection]: an arrow from mark ``a`` to mark
        ``b`` (from an event or a bar's end, to an event or a bar's start), with ``text`` at
        its middle. It shows in the plot, in pages and in images;
        ``plot.connections = []`` removes them all. In the plot, the key ``c`` on one mark
        and then on another adds one too.

        Args:
            a: The mark it starts at: a row of the plot's one layer, or ``(layer, row)``.
            b: The mark it points to.
            text: Written at its middle.
            color: Its colour (default: the accent colour).
        """
        ends = []
        for end in (a, b):
            if isinstance(end, tuple):
                ends.append((str(end[0]), end[1]))
            else:
                ends.append((self._layer_named(None), end))
        link = Connection(ends[0], ends[1], text, color)
        for layer, row in ends:
            self._mark_at(layer, int(row))  # an unknown layer or row raises here
        self.connections = [*self.connections, link]
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
        del self._tables[name]
        self.selection = {k: v for k, v in self.selection.items() if k != name}
        self._update_spec()
        return self

    def clear(self) -> Self:
        """Remove every layer."""
        self._layers.clear()
        self._tables.clear()
        self.selection = {}
        self._update_spec()
        return self

    # ------------------------------------------------------------------ the view

    @property
    def view(self) -> View:
        """What the plot shows: a [`View`][anytimeline.View] with its ``start`` and ``end``
        (the time range in sight, as the data's kind: datetime64, timedelta64 or numbers)
        and its ``lanes`` (the lanes in sight, top to bottom). It follows zooming, panning
        and scrolling in the plot.

        Set it to show that view: ``plot.view = View("2026-10-12T08:30", "2026-10-12T08:45")``
        zooms to a quarter of an hour; ``View(lanes=["db"])`` scrolls the lane ``db`` to the
        top; ``plot.view = None`` shows the whole timeline from the top. A view read from one
        plot shows the same in another: ``plot_b.view = plot_a.view``.

        Before the plot is shown, or with ``display="html"``, it is the view set last.
        """
        shown = self._view_shown
        if shown is None:
            return self._view
        t0, t1 = shown["range"]
        if self._base is not None:
            t0, t1 = self._base.to_value(t0), self._base.to_value(t1)
        return View(t0, t1, tuple(shown["lanes"]) if shown.get("lanes") is not None else None)

    @view.setter
    def view(self, value: View | None) -> None:
        if value is None:
            value = View()
        if not isinstance(value, View):
            raise TypeError(f"view must be a View or None, got {type(value).__name__}")
        names = [str(n) for n in self._spec.get("lanes", {}).get("names", [])]
        missing = [n for n in value.lanes or () if n not in names]
        if missing:
            raise ValueError(f"no lane {missing[0]!r} in the plot; lanes: {names}")
        rng = None
        if value.start is not None or value.end is not None:
            lo, hi = self._spec["time"]["extent"]
            t0 = self._ticks(value.start) if value.start is not None else float(lo)
            t1 = self._ticks(value.end) if value.end is not None else float(hi)
            if not t1 > t0:
                raise ValueError("the view's end must be after its start")
            rng = [t0, t1]
        self._view = value
        self._view_shown = None
        lanes = value.lanes[0] if value.lanes else None
        self._zoom = {"n": int(self._zoom.get("n", 0)) + 1, "range": rng, "lanes": lanes}

    def zoom_to(self, start: Any, end: Any) -> Self:
        """Show the time range from ``start`` to ``end`` (datetimes, ISO strings, durations or
        numbers, as the data); the lanes in sight stay. Setting
        [`view`][anytimeline.Timeline.view] does this and more."""
        t0, t1 = self._ticks(start), self._ticks(end)
        if not t1 > t0:
            raise ValueError("end must be after start")
        self._view = View(start, end, self._view.lanes)
        self._view_shown = None
        self._zoom = {"n": int(self._zoom.get("n", 0)) + 1, "range": [t0, t1]}
        return self

    def _ticks(self, value: Any) -> float:
        if self._base is None:
            if not self._layers:
                raise ValueError("the view needs layers")
            if isinstance(value, int | float) and not isinstance(value, bool):
                return float(value)  # a plot of order only: positions
            raise TypeError(f"a plot without times takes positions (numbers), got {value!r}")
        return self._base.to_ticks(value)

    def _shown(self, content: Mapping[str, Any]) -> None:
        """What the browser reports it shows (``{"type": "view"}``)."""
        r = content.get("range")
        if not (isinstance(r, list) and len(r) == 2):
            return
        lanes = content.get("lanes")
        self._view_shown = {
            "range": (float(r[0]), float(r[1])),
            "lanes": [str(n) for n in lanes] if isinstance(lanes, list) else None,
        }

    @property
    def dev(self) -> Dev:
        """For developers of anytimeline: what the browser measured, and a benchmark; see
        [`Dev`][anytimeline.plot.Dev]."""
        return Dev(self)

    # ------------------------------------------------------------------ spec

    def _make(self, *, levels: bool = True, windows: bool = True) -> scene.Scene:
        return scene.make(
            self._layers,
            align=self.align,
            timezone=self.timezone,
            lane_order=self.lane_order,
            sort=self.sort,
            group_order=self.group_order,
            lane_names=self.lane_names,
            markers=self.markers,
            levels=levels,
            windows=windows,
        )

    def _update_spec(self) -> None:
        made = self._make()
        self._page = None
        self._base, self._laid, self._ranks = made.base, made.laid, made.ranks
        self._scene = made
        self._buffers = made.buffers
        self._window_buffers.clear()
        self._tooltip_cache.clear()
        self._marks = self._marks_of(self.selection)
        self._marked = self._marked_of(self._marks)
        self._summary = self._panel(self.selection)
        self._findable = None
        self._notes = self._notes_of()
        self._spec = made.spec

    # ------------------------------------------------------------------ pages

    def save_html(self, path: str | PathLike[str], *, title: str | None = None) -> Path:
        """Write the plot to one HTML file that opens in any browser, without Python or a
        network: its data, the drawing code and the styles are all in the file. Pan, zoom,
        hover (with the ``tooltip`` columns), Time / Order, folding and full screen work;
        selecting does not (it needs Python). For the HTML as text, see
        [`to_html`][anytimeline.Timeline.to_html].

        Args:
            path: The file to write (``.html``).
            title: The page's title; by default the plot's title.

        Returns:
            The path written.
        """
        return page.save_html(path, self, title=title)

    def to_html(self, *, title: str | None = None, full_html: bool = True) -> str:
        """The plot as interactive HTML that works without Python: the page
        [`save_html`][anytimeline.Timeline.save_html] writes, as text.

        Return it from a web app, put it in a report, or hand it to a component that shows
        HTML, such as Streamlit's ``components.html(plot.to_html(), height=500)``. With
        ``full_html=False`` it is an element for a page of your own (a template's
        ``{{ plot | safe }}``): the plot's styles, data and drawing code. A page can hold any
        number of them, and runs the drawing code once.

        Args:
            title: The page's title (``full_html`` only); by default the plot's title.
            full_html: ``True``: a whole page, from ``<!doctype html>``. ``False``: an element
                to put in a page's ``<body>``; the plot takes the width of the element it is
                in.

        Returns:
            The HTML.
        """
        if not full_html:
            if title is not None:
                raise ValueError("title is the page's title: it needs full_html=True")
            return page.fragment(self, "this plot is drawn by JavaScript, which did not run here.")
        return page.page([self], title)

    def _repr_mimebundle_(self, **kwargs: Any) -> Any:
        if self.display == "html":
            self._warn_if_large()
            return {"text/plain": repr(self), "text/html": self._notebook_html()}
        bundle = self.widget._repr_mimebundle_(**kwargs)
        if bundle is None:
            return None
        data = bundle[0] if isinstance(bundle, tuple) else bundle  # anywidget: (data, metadata)
        # what a notebook shows where the widget cannot be drawn (exported, or opened without
        # its kernel): say how to get the plot there
        data["text/plain"] = (
            f"{self!r}: an interactive plot. An exported or reopened notebook shows it when "
            'it is shown with display="html".'
        )
        return bundle

    def _display_(self) -> Any:
        """What marimo shows: the widget, or with ``display="html"`` the page, in a frame (its
        script runs only there), as high as ``height`` (else 480 px)."""
        import marimo as mo

        if self.display == "html":
            self._warn_if_large()
            return mo.iframe(self.to_html(), height=f"{self.height or 480}px")
        return mo.ui.anywidget(self.widget)

    def __repr__(self) -> str:
        parts = []
        for name, rec in self._layers.items():
            kind = {"EventsRecord": "events", "ValuesRecord": "samples"}.get(
                type(rec).__name__, "bars"
            )
            parts.append(f"{name}: {len(rec.rows):,} {kind}")
        return f"Timeline({'; '.join(parts) or 'no layers'})"

    def _page_data(self) -> tuple[dict[str, Any], dict[str, bytes]]:
        """The spec and buffers a page holds: those the widget gets; for a plot with layers
        sent as levels, every event when they come to at most ``page.FULL_BYTES``, else the
        levels alone (a page has no Python to send windows)."""
        if self._scene is None or not self._scene.detail:
            return self._spec, self._buffers
        if self._page is None:
            full = self._scene.full_bytes() <= page.FULL_BYTES
            made = self._make(levels=False) if full else self._make(windows=False)
            self._page = (made.spec, made.buffers)
        return self._page

    def _warn_if_large(self) -> None:
        size = sum(len(b) for b in self._page_data()[1].values())
        if size > page.HTML_WARN_BYTES:
            warnings.warn(
                f"this plot's data is {size / 1e6:.0f} MB, and with display='html' the "
                "notebook file holds all of it; show it as a widget (display='widget') or "
                "save it with save_html",
                stacklevel=3,
            )

    def _notebook_html(self) -> str:
        """The plot as a notebook output (``display="html"``): a fragment whose note says how
        to let its script run."""
        return page.fragment(
            self,
            "this plot is drawn by JavaScript, which did not run here. In JupyterLab, trust "
            "the notebook: Trust Notebook in the command palette.",
        )

    def _embed_html(self) -> str:
        """The plot for a page that loads ``standalone.js`` once (the documentation)."""
        return page.embed(self)

    # ------------------------------------------------------------------ linking

    def link(self, *others: Timeline, align: Align = "time") -> Self:
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
        one_of(ALIGNS)(align, "align")
        for other in others:
            if not isinstance(other, Timeline):
                raise TypeError(f"link takes plots, got {type(other).__name__}")
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

    # ------------------------------------------------------------------ pictures

    def save_image(
        self,
        path: str | PathLike[str],
        *,
        width: int = 960,
        height: int | None = None,
        view: View | None = None,
        theme: Literal["light", "dark"] = "light",
        scale: float = 2,
    ) -> Path:
        """Save a picture of the plot, drawn in Python: no browser, notebook or widget is
        needed, so it works in scripts, tests and CI. ``.svg`` gives an SVG that slides
        (PowerPoint, Keynote, Google Slides) import as shapes and text; ``.png`` needs the
        optional ``resvg-py`` (``pip install 'anytimeline[png]'``).

        The picture is the plot as the browser draws it at that size and view: the lanes,
        axis, marks, text, markers, annotations, legend and title, and the selection. Layers
        sent as levels show their bins, or their marks when the view is narrow enough.
        Folded lanes are folded as the plot starts; story timelines' text goes beside the
        marks.

        Args:
            path: The file to write: ``.svg`` or ``.png``.
            width: Its width in pixels.
            height: Its height in pixels; None: the plot's ``height`` (0: tall enough for
                every lane).
            view: What to show (a [`View`][anytimeline.View]); None: the plot's
                [`view`][anytimeline.Timeline.view], as shown or set last.
            theme: ``"light"`` or ``"dark"``.
            scale: For a PNG, pixels per pixel of the plot (2: sharp on a high-resolution
                screen or a slide).

        Returns:
            The path written.
        """
        target = Path(path)
        image.save(self, target, width=width, height=height, view=view, theme=theme, scale=scale)
        return target

    def to_svg(
        self,
        *,
        width: int = 960,
        height: int | None = None,
        view: View | None = None,
        theme: Literal["light", "dark"] = "light",
    ) -> str:
        """The picture [`save_image`][anytimeline.Timeline.save_image] saves, as SVG text."""
        return image.svg(self, width=width, height=height, view=view, theme=theme)

    def save_png(self, path: str | PathLike[str]) -> None:
        """Save the plot as a PNG, as it is shown in the notebook (its view, zoom and folded
        lanes; title and legend; at twice the screen's resolution). To draw it without a
        browser, see [`save_image`][anytimeline.Timeline.save_image].

        The picture is drawn in the browser, so the plot must be on screen, and the file is
        written when the browser sends it: in Jupyter right after the cell has run, not
        during it. The toolbar's Save as PNG button does the same as a download; use this
        where downloads are blocked (VS Code) or from code.

        Args:
            path: The file to write (``.png``).
        """
        if self._widget is None:
            raise RuntimeError("save_png draws the plot in the browser: show the plot first")
        self._snapshots += 1
        self._snapshot_paths[str(self._snapshots)] = Path(path)
        self._send({"type": "snapshot", "request": str(self._snapshots)})

    def _receive_image(self, content: Mapping[str, Any], buffers: Any) -> None:
        path = self._snapshot_paths.pop(str(content.get("request")), None)
        if path is None:  # another view answered first
            return
        if content.get("error") or not buffers:
            raise RuntimeError(f"the plot could not be drawn as a PNG: {content.get('error')}")
        data = buffers[0]
        path.write_bytes(bytes(data.tobytes() if hasattr(data, "tobytes") else data))

    # ------------------------------------------------------------------ levels

    def _window(self, content: Mapping[str, Any]) -> dict[str, Any]:
        """A window of a layer sent as levels (``{"type": "window"}``): its marks in a range,
        or its bins of a finer level there. Its buffers are kept for the browser to ask for,
        those of the last WINDOW_KEEP windows."""
        if self._scene is None:
            raise ValueError("the plot has no layers")
        name = str(content.get("layer"))
        if name not in self._scene.detail:
            raise ValueError(f"layer {name!r} has no levels")
        scale = "order" if content.get("scale") == "order" else "time"
        a, b = (float(v) for v in content["range"])
        k = content.get("k")
        answer, buffers = self._scene.window(name, scale, a, b, int(k) if k is not None else None)
        for enc in buffers:
            self._window_buffers[enc.id] = enc.data
        self._windows.append([enc.id for enc in buffers])
        while len(self._windows) > WINDOW_KEEP:
            oldest = self._windows.pop(0)
            kept = {i for ids in self._windows for i in ids}
            for i in oldest:
                if i not in kept:
                    self._window_buffers.pop(i, None)
        return answer

    def _bin_tooltip(self, content: Mapping[str, Any]) -> list[list[str]]:
        """What a bin of a layer sent as levels holds (``{"type": "tooltip", "bin"}``): its
        marks per colour category, the most first."""
        if self._scene is None:
            return []
        name = str(content.get("layer"))
        d = self._scene.detail.get(name)
        if not isinstance(d, scene.Detail) or d.look.codes is None:
            return []
        scale = "order" if content.get("scale") == "order" else "time"
        lane = int(content["lane"])
        a, b = (float(v) for v in content["range"])
        x = d.x[scale]
        marks = d.layout.marks
        i0 = int(np.searchsorted(marks.lane, lane, "left"))
        i1 = int(np.searchsorted(marks.lane, lane, "right"))
        j0 = i0 + int(np.searchsorted(x[i0:i1], a, "left"))
        j1 = i0 + int(np.searchsorted(x[i0:i1], b, "right"))
        counts = np.bincount(d.look.codes[j0:j1], minlength=d.look.n_codes)
        names = d.record.color.extra["names"]
        rows = [[names[c], f"{int(counts[c]):,}"] for c in np.argsort(-counts, kind="stable")]
        return [r for r in rows if r[1] != "0"][:8]

    # ------------------------------------------------------------------ annotations

    def _note_of(self, a: Annotation) -> dict[str, Any]:
        """An annotation as the browser draws it: ticks, and its lane's index (None: all)."""
        if self._scene is None:
            self._update_spec()
        if self._base is None:
            raise ValueError("annotations need layers with times")
        x0 = self._base.to_ticks(a.start)
        x1 = x0 if a.end is None else self._base.to_ticks(a.end)
        if x1 < x0:
            raise ValueError(f"an annotation ends before it starts: {a.start!r} to {a.end!r}")
        lane = None
        if a.lane is not None:
            names = [str(n) for n in self._spec["lanes"]["names"]]
            if str(a.lane) not in names:
                raise NotFoundError(f"no lane {a.lane!r} to annotate")
            lane = names.index(str(a.lane))
        return {
            "x0": x0,
            "x1": x1,
            "point": a.end is None,
            "lane": lane,
            "text": a.text,
            "color": a.color,
        }

    def _mark_at(self, layer: str, row: int) -> dict[str, Any]:
        """Where the mark of table row ``row`` is: its index in the browser, its start and
        end (ticks), its place in the order, and its lane."""
        layer = self._layer_named(layer)
        if self._scene is None:
            self._update_spec()
        rec = self._layers[layer]
        pos = summaries.positions(rec, [row])
        if not len(pos):
            raise NotFoundError(f"layer {layer!r} draws no row {row}")
        inverse = np.empty(len(rec.perm), dtype=np.int64)
        inverse[rec.perm] = np.arange(len(rec.perm))
        i = int(inverse[pos[0]])
        lay = self._laid[layer]
        ranks = self._ranks.get(layer)
        r = (
            (float(ranks[i, 0]), float(ranks[i, -1]))
            if ranks is not None and len(ranks)
            else (float(lay.lo[i]), float(lay.hi[i]))
        )
        return {
            "layer": layer,
            "index": i,
            "x": float(lay.lo[i]),
            "x2": float(lay.hi[i]),
            "r": r[0],
            "r2": r[1],
            "lane": int(lay.lanes[i]),
        }

    def _notes_of(self) -> dict[str, Any]:
        """``_notes``: the annotations and connections that can be drawn (those of lanes and
        rows the plot no longer has are left out)."""
        if not self._layers or (not self.annotations and not self.connections):
            return {}
        bands, arrows = [], []
        for a in self.annotations:
            try:
                bands.append(self._note_of(a))
            except (LookupError, ValueError, TypeError):
                continue
        for c in self.connections:
            try:
                ends = [self._mark_at(layer, int(row)) for layer, row in (c.a, c.b)]
            except (LookupError, ValueError):
                continue
            arrows.append({"a": ends[0], "b": ends[1], "text": c.text, "color": c.color})
        return {"bands": bands, "arrows": arrows}

    def _annotate_from(self, content: Mapping[str, Any]) -> None:
        """An annotation made in the plot (``{"type": "annotate"}``): ticks, a lane index."""
        if self._base is None:
            return
        x0 = float(content["x0"])
        x1 = content.get("x1")
        lane = content.get("lane")
        names = self._spec["lanes"]["names"]
        name = names[int(lane)] if lane is not None and 0 <= int(lane) < len(names) else None
        end = None if x1 is None else self._base.to_value(float(x1))
        self.annotate(self._base.to_value(x0), end, str(content.get("text", "")), lane=name)

    def _connect_from(self, content: Mapping[str, Any]) -> None:
        """A connection made in the plot (``{"type": "connect"}``): marks by their index."""
        ends = []
        for key in ("a", "b"):
            end = content[key]
            layer = str(end["layer"])
            rec = self._layers[layer]
            ends.append((layer, int(rec.rows[rec.perm[int(end["index"])]])))
        self.connect(ends[0], ends[1], str(content.get("text", "")))

    # ------------------------------------------------------------------ find and step

    def _marks_to_find(self) -> list[find.Marks]:
        if self._scene is None:
            self._update_spec()
        if self._findable is None:
            self._findable = find.marks_of(self._layers, self._laid, self._ranks)
        assert self._findable is not None
        return self._findable

    def _find(self, content: Mapping[str, Any]) -> dict[str, Any]:
        """The search box's matches (``{"type": "find"}``)."""
        marks = self._marks_to_find()
        names = [str(n) for n in self._spec["lanes"]["names"]]
        return find.search(marks, names, str(content.get("q", "")), str(content.get("scale")))

    def _step(self, content: Mapping[str, Any]) -> dict[str, Any]:
        """The mark ``.`` or ``,`` steps to (``{"type": "step"}``)."""
        after = content.get("after") or {}
        layer = after.get("layer")
        match = find.step(
            self._marks_to_find(),
            int(content["lane"]),
            (
                float(after.get("x", 0.0)),
                None if layer is None else str(layer),
                int(after.get("index", -1)),
            ),
            bool(content.get("forward", True)),
            str(content.get("scale")),
        )
        return {"match": match}

    # ------------------------------------------------------------------ tooltips

    def _tooltip(self, layer: str, index: int) -> list[list[str]]:
        key = (layer, index)
        if key in self._tooltip_cache:
            return self._tooltip_cache[key]
        rec = self._layers[layer]
        pos = int(rec.perm[index])
        rows = [[name, page.text(values[pos])] for name, values in rec.tooltip.items()]
        self._tooltip_cache[key] = rows
        return rows

    # ------------------------------------------------------------------ selection

    def selected(self, layer: str | None = None) -> Any:
        """The selected rows of a layer: the rows of its table that
        [`selection`][anytimeline.Timeline.selection] names, as a table of the type plotted
        (Polars, PyArrow, pandas with its index, or a dict of arrays). Nothing selected gives
        no rows, of the same type.

        A lazy table (a Polars ``LazyFrame``, a DuckDB relation, an Ibis table) is read once
        when its layer is added, with the columns the layer uses; its selected rows are
        those of that read (a Polars or PyArrow table), the rows drawn.

        Args:
            layer: The layer's name; may be left out when the plot has one layer.
        """
        layer = self._layer_named(layer)
        return tables.take(self._tables[layer], self.selection.get(layer, []))

    def summary(
        self, layer: str | None = None, *, rows: Literal["selected", "all"] = "selected"
    ) -> Any:
        """The selection in numbers: the selected marks of a layer counted by lane and by
        colour category (when its colour is a column of categories), as a table of the type
        plotted (Polars, PyArrow, pandas, or a dict of arrays), a row per lane and category
        in the plot's order.

        Bars (intervals and states) add ``total`` and ``mean``: their duration (durations,
        or numbers on a plot of numbers), and ``open``: bars without an end, which count but
        have no duration. Events add ``first`` and ``last``: their earliest and latest time.
        Values add ``mean``, ``min`` and ``max`` of their values. The plot shows the same
        numbers in a panel while something is selected
        ([`summary_panel`][anytimeline.Timeline.summary_panel]).

        Args:
            layer: The layer's name; may be left out when the plot has one layer.
            rows: ``"selected"``: the selected rows (none selected: a table without rows);
                ``"all"``: every row drawn.
        """
        layer = self._layer_named(layer)
        rec = self._layers[layer]
        if rows == "all":
            pos = np.arange(len(rec.rows), dtype=np.int64)
        elif rows == "selected":
            pos = summaries.positions(rec, self.selection.get(layer, []))
        else:
            raise ValueError(f'rows must be "selected" or "all", got {rows!r}')
        groups = self._groups(layer, pos)
        return summaries.table(groups, self._base, self._tables[layer])

    def _layer_named(self, layer: str | None) -> str:
        if layer is None:
            if len(self._layers) != 1:
                raise ValueError(f"name the layer: the plot has {len(self._layers)}: {self.layers}")
            return next(iter(self._layers))
        if layer not in self._layers:
            raise NotFoundError(f"no layer {layer!r}; layers: {self.layers}")
        return layer

    def _groups(self, layer: str, pos: np.ndarray) -> summaries.Groups:
        if self._scene is None:
            self._update_spec()
        names = [str(n) for n in self._spec["lanes"]["names"]]
        return summaries.group(self._layers[layer], self._laid[layer], names, pos)

    def _panel(self, selection: Mapping[str, list[int]]) -> list[dict[str, Any]]:
        """What the summary panel shows (``_summary``)."""
        if not self.summary_panel or self._scene is None:
            return []
        out = []
        for name, rows in selection.items():
            if name not in self._layers or not rows:
                continue
            pos = summaries.positions(self._layers[name], rows)
            if len(pos):
                out.append(summaries.panel(name, self._groups(name, pos), self._base))
        return out

    def undo_selection(self) -> bool:
        """Take back the last change of the selection (made in the plot or in Python), as
        Ctrl/Cmd+Z does in the plot; up to 50 changes. Returns False when there is none.
        [`on_select`][anytimeline.Timeline.on_select] callbacks hear of it."""
        return self._back(self._undo, self._redo)

    def redo_selection(self) -> bool:
        """Make again the change of the selection last taken back, as Ctrl/Cmd+Shift+Z
        does in the plot. Returns False when there is none."""
        return self._back(self._redo, self._undo)

    def _back(self, take: list[dict[str, list[int]]], keep: list[dict[str, list[int]]]) -> bool:
        while take:
            was = take.pop()
            was = {k: v for k, v in was.items() if k in self._layers}  # layers since removed
            if was == self.selection:
                continue
            keep.append(self.selection)
            del keep[:-UNDO_STEPS]
            self._undoing = True
            try:
                self.selection = was
            finally:
                self._undoing = False
            self._select_handlers(self.selection)
            return True
        return False

    def on_select(
        self, callback: Callable[[dict[str, list[int]]], Any], *, remove: bool = False
    ) -> None:
        """Call ``callback(selection)`` after every change of the selection made in the plot.

        Pass ``remove=True`` to unregister it.
        """
        self._select_handlers.register_callback(callback, remove=remove)

    @validates("selection")
    def _valid_selection(self, value: dict[str, Any], name: str) -> dict[str, list[int]]:
        unknown = [k for k in value if k not in self._layers]
        if unknown:
            raise ValueError(f"no layer {unknown[0]!r} to select in; layers: {self.layers}")
        out: dict[str, list[int]] = {}
        for k, rows in value.items():
            if isinstance(rows, str) or not isinstance(rows, Iterable):
                raise TypeError(f"selection[{k!r}] must be a list of rows, got {rows!r}")
            kept = sorted({int(r) for r in rows})
            if kept:
                out[str(k)] = kept
        return out

    @observes("selection")
    def _selection_changed(self, change: dict[str, Any]) -> None:
        if not self._undoing:
            self._undo = [*self._undo, change["old"]][-UNDO_STEPS:]
            self._redo = []
        self._marks = self._marks_of(change["new"])
        self._marked = self._marked_of(self._marks)
        self._summary = self._panel(change["new"])

    @observes("annotations", "connections")
    def _notes_changed(self, change: dict[str, Any]) -> None:
        if self._scene is not None:
            self._notes = self._notes_of()

    @observes("summary_panel")
    def _summary_panel_changed(self, change: dict[str, Any]) -> None:
        self._summary = self._panel(self.selection)

    def _marks_of(self, selection: Mapping[str, list[int]]) -> dict[str, bytes]:
        """Per layer, the browser's indices of the selected rows, as int32 bytes."""
        marks: dict[str, bytes] = {}
        for name, rows in selection.items():
            rec = self._layers.get(name)
            if rec is None or not len(rows) or not len(rec.perm):
                continue
            pos = summaries.positions(rec, rows)
            inverse = np.empty(len(rec.perm), dtype=np.int64)
            inverse[rec.perm] = np.arange(len(rec.perm))
            marks[name] = np.sort(inverse[pos]).astype("<i4").tobytes()
        return marks

    def _marked_of(self, marks: Mapping[str, bytes]) -> dict[str, bytes]:
        """Per events layer sent as levels, where its selected events are (``_marked``)."""
        out: dict[str, bytes] = {}
        if self._scene is None:
            return out
        for name, d in self._scene.detail.items():
            if not isinstance(d, scene.Detail) or name not in marks:
                continue
            index = np.frombuffer(marks[name], dtype="<i4")[:MARKED]
            m = d.layout.marks
            at = np.column_stack([m.primary[index], d.x["order"][index], m.lane[index]])
            out[name] = at.astype("<f8").tobytes()
        return out

    @observes("_pick")
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
            if rec is None:
                return None
            row = common.clicked(rec, int(pick.get("index", -1)))
            return {name: row} if row is not None else None
        if kind == "box":
            x0, x1 = sorted(float(v) for v in pick["x"])
            shown = pick.get("shown")  # with folded lanes: the lanes in the box that show
            lanes = shown if shown is not None else tuple(sorted(int(v) for v in pick["lanes"]))
            by_rank = pick.get("xscale") == "order"
            only = pick.get("layer")  # a bin of a layer sent as levels: that layer's events
            out: dict[str, set[int]] = {}
            for name, rec in self._layers.items():
                if only is not None and name != only:
                    continue
                rows = common.in_box(
                    rec,
                    self._laid[name],
                    (x0, x1),
                    lanes,
                    ranks=self._ranks.get(name) if by_rank else None,
                )
                if rows:
                    out[name] = rows
            return out
        return None


class Dev:
    """For developers of anytimeline (``plot.dev``): how the plot performs in the browser."""

    def __init__(self, plot: Timeline) -> None:
        self._plot = plot

    @property
    def perf(self) -> dict[str, Any]:
        """Filled in by the browser: the renderer used (and those skipped, with why), load
        and frame times, and the results of [`benchmark`][anytimeline.plot.Dev.benchmark]."""
        return self._plot._perf

    def benchmark(self, frames: int = 60) -> None:
        """Draw ``frames`` frames in every view of the plot, panning; the result appears in
        ``perf["benchmark"]``."""
        self._plot._send({"type": "benchmark", "frames": whole(frames, "frames")})


def _columns(value: str | Sequence[str] | None, name: str) -> list[str] | None:
    """Column names: one name, a list of names, or None."""
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if not all(isinstance(v, str) for v in value):
        raise TypeError(f"{name} takes column names, got {value!r}")
    return list(value)


def _expand(value: Any) -> Any:
    """``expand=`` as the tree reads it: a number, "auto", or None for every level."""
    if value is None:
        raise ValueError("expand='all' shows every level (expand=None was 0.4's)")
    if value == "all":
        return None
    if value == "auto" or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    raise ValueError(f"expand must be a number of levels, 'auto' or 'all', got {value!r}")


def _arguments(arguments: Mapping[str, Any]) -> list[Any]:
    """A layer method's arguments other than the plot and the table: what may name columns."""
    return [v for k, v in arguments.items() if k not in ("self", "data")]


_LINKS: dict[str, weakref.WeakSet[Timeline]] = {}
"""Groups of linked plots, by group id (``Timeline.link``)."""
