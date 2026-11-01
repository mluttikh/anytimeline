"""Parts of a layer whose settings only matter together, as frozen dataclasses: a
[`Route`][anytimeline.Route], a story's [`Stem`][anytimeline.Stem]; and the notes on a plot:
an [`Annotation`][anytimeline.Annotation], a [`Connection`][anytimeline.Connection], a
[`Measure`][anytimeline.Measure], whose ends may be [`Edge`][anytimeline.Edge]s. Route and
Stem have ``of()``, which also takes the short forms its argument accepts
(``route="request"``, ``stems=True``)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import KW_ONLY, dataclass, field, fields
from typing import Any, Literal, get_args

import numpy as np

from anytimeline import measuring
from anytimeline.types import MeasureEnds, MeasureExtend, MeasureLabel, MeasurePlace, StemShape

STEM_SHAPES = get_args(StemShape)
MEASURE_PLACES = get_args(MeasurePlace)
MEASURE_LABELS = get_args(MeasureLabel)
MEASURE_ENDS = get_args(MeasureEnds)
MEASURE_EXTENDS = get_args(MeasureExtend)


@dataclass(frozen=True)
class Route:
    """Lines joining the events of one group in the order they happened.

    Args:
        group: The column that names a group (a request, a user, a process).
        color: ``None``: each segment in the colour of the event it starts at; or one
            colour (``"theme"`` follows the plot's text colour).
        width: Line width in CSS pixels.
    """

    group: str
    color: str | None = None
    width: float = 1.5

    def __post_init__(self) -> None:
        if not isinstance(self.group, str):
            raise TypeError(f"Route's group is a column name, got {self.group!r}")
        if not _positive(self.width):
            raise ValueError(f"Route's width is in pixels, above 0; got {self.width!r}")

    @classmethod
    def of(cls, value: Route | str | None) -> Route | None:
        """A route from ``route=``: a Route, a column name (its groups), or None."""
        if value is None or isinstance(value, Route):
            return value
        if isinstance(value, str):
            return cls(group=value)
        raise TypeError(f"route must be a column name or a Route, got {type(value).__name__}")


@dataclass(frozen=True)
class Stem:
    """A story's boxes on stems (``events(stems=...)``, ``story(stems=...)``): each event's
    text in a box above or below its lane's line, joined to it by a line.

    Args:
        shape: ``"straight"``: each box over its event; ``"curved"``: a box may move aside
            when that gives it room, its stem bending near the line. No stem ever passes
            behind a box.
        width: The widest a box gets, in pixels; longer titles wrap onto two lines (then end
            in "…"). ``"auto"``: 16 × the text size; ``None``: no limit (one line).
    """

    shape: StemShape = "straight"
    width: float | Literal["auto"] | None = "auto"

    def __post_init__(self) -> None:
        if self.shape not in STEM_SHAPES:
            raise ValueError(f"Stem's shape must be one of {STEM_SHAPES}, got {self.shape!r}")
        if self.width not in ("auto", None) and not _positive(self.width):
            raise ValueError(
                f"Stem's width is in pixels, above 0 ('auto', or None: no limit); got "
                f"{self.width!r}"
            )

    @classmethod
    def of(cls, value: Stem | StemShape | bool | None) -> Stem | None:
        """Stems from ``stems=``: a Stem, ``True`` (straight), a shape, or None (no stems:
        the text beside the marks)."""
        if value is None or isinstance(value, Stem):
            return value
        if value is True:
            return cls()
        if value is False:
            raise TypeError("stems=None leaves the stems out (the text beside the marks)")
        if isinstance(value, str):
            return cls(shape=value)
        raise TypeError(f"stems must be True, a shape or a Stem, got {type(value).__name__}")


Side = Literal["start", "end"]
SIDES = get_args(Side)


@dataclass(frozen=True)
class Edge:
    """A mark's start or end: where a [`Measure`][anytimeline.Measure], a
    [`Connection`][anytimeline.Connection] or an [`Annotation`][anytimeline.Annotation] may
    begin or end, so that it stays on the mark. An event's start and end are its time, and
    so are a sample's (a row of a values layer). [`start`][anytimeline.start] and
    [`end`][anytimeline.end] make one.

    Args:
        row: The mark: a row of its layer's table.
        side: ``"start"`` or ``"end"``.
        layer: The mark's layer; ``None``: the plot's one layer.
    """

    row: int
    side: Side = "start"
    layer: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.row, bool) or not isinstance(self.row, int | np.integer):
            raise TypeError(f"Edge's row is a row of a table (an int), got {self.row!r}")
        if self.side not in SIDES:
            raise ValueError(f"Edge's side is 'start' or 'end', got {self.side!r}")
        if self.layer is not None and not isinstance(self.layer, str):
            raise TypeError(f"Edge's layer is a layer's name, got {self.layer!r}")
        object.__setattr__(self, "row", int(self.row))


def start(row: int, layer: str | None = None) -> Edge:
    """The start of a mark: an [`Edge`][anytimeline.Edge] (an event's or a sample's start is
    its time).

    Args:
        row: The mark: a row of its layer's table.
        layer: The mark's layer; ``None``: the plot's one layer.
    """
    return Edge(row, "start", layer)


def end(row: int, layer: str | None = None) -> Edge:
    """The end of a mark: an [`Edge`][anytimeline.Edge] (an event's or a sample's end is its
    time).

    Args:
        row: The mark: a row of its layer's table.
        layer: The mark's layer; ``None``: the plot's one layer.
    """
    return Edge(row, "end", layer)


@dataclass(frozen=True)
class Annotation:
    """A note on the plot: a time range (or one time) with text, over one lane or all of them
    ([`Timeline.annotate`][anytimeline.Timeline.annotate]). A note at one time across all
    lanes is a line from top to bottom, such as now or a deadline.

    Args:
        start: Where it starts: a time of the data's kind (a datetime, ISO text, a duration
            or a number), or an [`Edge`][anytimeline.Edge] (the note then stays on that mark).
        end: Where it ends (a time or an edge); ``None``: a note at one time (a line).
        text: Written at its top.
        lane: The lane it is in (a lane's name); ``None``: across all lanes.
        color: Its colour; ``None``: the accent colour (a line across all lanes: the
            selection colour).
    """

    start: Any
    end: Any = None
    text: str = ""
    lane: Any = None
    color: str | None = None

    def __post_init__(self) -> None:
        if self.start is None:
            raise TypeError("Annotation's start is a time or an Edge, got None")
        if not isinstance(self.text, str):
            raise TypeError(f"Annotation's text is text, got {self.text!r}")
        _check_color("Annotation", self.color)


@dataclass(frozen=True)
class Connection:
    """An arrow from one mark to another, with text
    ([`Timeline.connect`][anytimeline.Timeline.connect]): from an edge of one mark to an edge
    of another, so start to start, end to end, start to end and end to start (the four links
    of a Gantt chart) can all be drawn.

    Args:
        a: Where it starts: an [`Edge`][anytimeline.Edge], or ``(layer, row)``: that mark's
            end.
        b: Where it points to: an edge, or ``(layer, row)``: that mark's start.
        text: Written at its middle.
        color: Its colour; ``None``: the accent colour.
    """

    a: Edge | tuple[str, int]
    b: Edge | tuple[str, int]
    text: str = ""
    color: str | None = None

    def __post_init__(self) -> None:
        for key, side in (("a", "end"), ("b", "start")):
            end = getattr(self, key)
            if isinstance(end, Edge):
                continue
            ok = isinstance(end, tuple) and len(end) == 2 and isinstance(end[0], str)
            if not ok or isinstance(end[1], bool) or not isinstance(end[1], int | np.integer):
                raise TypeError(f"Connection's ends are Edges or (layer, row), got {end!r}")
            object.__setattr__(self, key, Edge(int(end[1]), side, end[0]))
        if not isinstance(self.text, str):
            raise TypeError(f"Connection's text is text, got {self.text!r}")
        _check_color("Connection", self.color)


@dataclass(frozen=True)
class ValueAt:
    """A height on a values layer's scale, where a [`Measure`][anytimeline.Measure]'s line
    goes (``at=``); [`value`][anytimeline.value] makes one.

    Args:
        value: The value, on the layer's scale.
        layer: The values layer; ``None``: the layer of the measure's ends when they are
            samples, else the plot's one values layer.
    """

    value: float
    layer: str | None = None

    def __post_init__(self) -> None:
        v = self.value
        if (
            isinstance(v, bool)
            or not isinstance(v, int | float | np.number)
            or not math.isfinite(v)
        ):
            raise TypeError(f"value's value is a number on the layer's scale, got {v!r}")
        if self.layer is not None and not isinstance(self.layer, str):
            raise TypeError(f"value's layer is a layer's name, got {self.layer!r}")
        object.__setattr__(self, "value", float(v))


def value(value: float, layer: str | None = None) -> ValueAt:
    """A height on a values layer's scale, for a measure's line (``at=atl.value(80)``): the
    measure is drawn at that value in the layer's lane, a threshold for instance.

    Args:
        value: The value, on the layer's scale.
        layer: The values layer; ``None``: the layer of the measure's ends when they are
            samples, else the plot's one values layer.
    """
    return ValueAt(value, layer)


@dataclass(frozen=True)
class Measure:
    """The time between two ends, drawn as a dimension line with the time at its middle
    ([`Timeline.measure`][anytimeline.Timeline.measure]). Each end is an
    [`Edge`][anytimeline.Edge] (a mark's start or end) or a time, so a measure may span the
    gap between two marks, start to start, a mark's own length, or a time to a mark.
    [`Timeline.measured`][anytimeline.Timeline.measured] gives the times as a table.

    Args:
        a: Where it starts: an edge, or a time of the data's kind (a datetime, ISO text, a
            duration or a number).
        b: Where it ends: an edge or a time.
        text: Written at its middle; ``None``: the time between (and, between two samples
            of a values layer, the change in value). Fields in it: ``{time}`` the time
            between, ``{events}`` the number of events between them in the order,
            ``{change}`` the change in value, ``{rate}`` that change per unit of time,
            ``{a}`` and ``{b}`` the ends' times, ``{a.col}`` and ``{b.col}`` a column of an
            end's row. A format after a colon: ``{time:ms}`` (a unit), ``{time:.2}`` (the
            digits), ``{change:+.2f}`` (as Python's), ``{a.start:%H:%M}``.
        lane: The lane it is drawn in (a lane's name); ``None``: the upper of its ends'
            lanes, or (two times) the header.
        color: Its colour; ``None``: the accent colour.
        at: Where its line goes in the lane: ``"auto"`` (the top; levels the lane cannot
            hold continue in the header), ``"top"``, ``"middle"``, ``"bottom"``,
            ``"between"`` (the border under the lane), ``"header"`` or ``"footer"`` (a band
            above or below the lanes), or a [`value`][anytimeline.value] on a values layer.
        level: Its level, 0 nearest the edge its place stacks from; ``None``: the first
            free one. The others are laid out around a measure with a level.
        nudge: Pixels to move its line down (up when negative) after it is laid out.
        label: Where its text goes: ``"auto"`` (on the line where it fits, else beside it
            where there is room, else when hovered), ``"on"``, ``"above"``, ``"below"``,
            ``"start"`` (before its earlier end), ``"end"`` (after its later end) or
            ``"hover"`` (only when hovered or selected).
        ends: What its line ends in: ``"arrows"``, ``"ticks"`` (oblique strokes, as in a
            drawing), ``"dots"`` or ``"none"``.
        extend: Its extension lines: ``"mark"`` (from each end's mark to the line),
            ``"lanes"`` (through every lane, as cursors) or ``"none"``.
        limit: A budget: a measure longer than it is drawn in the plot's "over" colour,
            and [`measured`][anytimeline.Timeline.measured] says so (``over``). A duration
            (``"200ms"``, ``"1.5 h"``, a timedelta); on a plot of numbers, a number.
    """

    a: Any
    b: Any
    text: str | None = None
    lane: Any = None
    color: str | None = None
    _: KW_ONLY
    at: MeasurePlace | ValueAt = "auto"
    level: int | None = None
    nudge: float = 0.0
    label: MeasureLabel = "auto"
    ends: MeasureEnds = "arrows"
    extend: MeasureExtend = "mark"
    limit: Any = None

    def __post_init__(self) -> None:
        for end in (self.a, self.b):
            _check_end("Measure", end)
        _check_look("Measure", self)


def _check_end(part: str, end: Any) -> None:
    if end is None or isinstance(end, bool | tuple | list):
        raise TypeError(f"{part}'s ends are Edges or times, got {end!r}")


def _check_look(part: str, m: Any) -> None:
    """Check what a measure and a rule of measures have alike: text, colour, place, level,
    nudge, label, ends, extension lines and limit (level and nudge made int and float)."""
    if m.text is not None and not isinstance(m.text, str):
        raise TypeError(f"{part}'s text is text or None, got {m.text!r}")
    _check_color(part, m.color)
    if not isinstance(m.at, ValueAt) and m.at not in MEASURE_PLACES:
        raise ValueError(
            f"{part}'s at must be one of {MEASURE_PLACES} or atl.value(...), got {m.at!r}"
        )
    level = m.level
    if level is not None:
        if isinstance(level, bool) or not isinstance(level, int | np.integer) or level < 0:
            raise TypeError(f"{part}'s level is a whole number from 0, or None; got {level!r}")
        object.__setattr__(m, "level", int(level))
    nudge = m.nudge
    if isinstance(nudge, bool) or not isinstance(nudge, int | float) or not math.isfinite(nudge):
        raise TypeError(f"{part}'s nudge is a number of pixels, got {nudge!r}")
    object.__setattr__(m, "nudge", float(nudge))
    for key, words in (
        ("label", MEASURE_LABELS),
        ("ends", MEASURE_ENDS),
        ("extend", MEASURE_EXTENDS),
    ):
        if getattr(m, key) not in words:
            raise ValueError(f"{part}'s {key} must be one of {words}, got {getattr(m, key)!r}")
    if m.text is not None:
        measuring.check(m.text)
    measuring.check_duration(f"{part}'s limit", m.limit)


@dataclass(frozen=True)
class MeasureRule:
    """Measures made by a rule, worked out again whenever the plot's data changes: one note
    in [`notes`][anytimeline.Timeline.notes], a row per measure it makes in
    [`measured`][anytimeline.Timeline.measured]. Made by
    [`measure_each`][anytimeline.Timeline.measure_each] ([`MeasureEach`][anytimeline.MeasureEach]),
    [`measure_gaps`][anytimeline.Timeline.measure_gaps] ([`MeasureGaps`][anytimeline.MeasureGaps]),
    [`measure_chain`][anytimeline.Timeline.measure_chain]
    ([`MeasureChain`][anytimeline.MeasureChain]) and
    [`measure_from`][anytimeline.Timeline.measure_from] ([`MeasureFrom`][anytimeline.MeasureFrom]).
    Its measures look as it says; the arguments are those of a
    [`Measure`][anytimeline.Measure]."""

    _: KW_ONLY
    text: str | None = None
    color: str | None = None
    at: MeasurePlace | ValueAt = "auto"
    level: int | None = None
    nudge: float = 0.0
    label: MeasureLabel = "auto"
    ends: MeasureEnds = "arrows"
    extend: MeasureExtend = "mark"
    limit: Any = None

    def __post_init__(self) -> None:
        _check_look(type(self).__name__, self)

    def __repr__(self) -> str:
        """What was set, the rule's own first: ``MeasureGaps(layer='jobs', min='50ms')``."""
        look = [f.name for f in fields(MeasureRule)]
        own = [f for f in fields(self) if f.name not in look]
        order = own + [f for f in fields(self) if f.name in look]
        shown = [
            f"{f.name}={getattr(self, f.name)!r}"
            for f in order
            if getattr(self, f.name) != f.default
        ]
        return f"{type(self).__name__}({', '.join(shown)})"


def _rows(part: str, rows: Any) -> tuple[int, ...] | None:
    """Rows of a table: ints, or a mask of booleans (the rows where it is true)."""
    if rows is None:
        return None
    if isinstance(rows, str | bytes | int | Mapping):
        raise TypeError(f"{part}'s rows are rows of a table (a list of ints), got {rows!r}")
    a = np.asarray(list(rows) if not hasattr(rows, "__array__") else rows)
    if a.dtype == bool:
        a = np.flatnonzero(a)
    if a.size and (a.dtype.kind not in "iu" or a.min() < 0):
        raise TypeError(f"{part}'s rows are rows of a table (ints from 0), got {rows!r}")
    return tuple(int(r) for r in a)


@dataclass(frozen=True, repr=False)
class MeasureEach(MeasureRule):
    """A measure of each bar of an intervals layer: its length, from its start to its end
    ([`Timeline.measure_each`][anytimeline.Timeline.measure_each]).

    Args:
        layer: The intervals layer; ``None``: the plot's one.
        rows: Rows of its table to measure (``plot.selection["jobs"]``); ``None``: all.
    """

    layer: str | None = None
    rows: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.layer is not None and not isinstance(self.layer, str):
            raise TypeError(f"MeasureEach's layer is a layer's name, got {self.layer!r}")
        object.__setattr__(self, "rows", _rows("MeasureEach", self.rows))


@dataclass(frozen=True, repr=False)
class MeasureGaps(MeasureRule):
    """A measure of each gap between the marks of a layer: from the end of the marks so far
    to the start of the next one, in each lane, or in each group of ``by``
    ([`Timeline.measure_gaps`][anytimeline.Timeline.measure_gaps]). Marks that overlap have
    no gap between them.

    Args:
        layer: The events or intervals layer; ``None``: the plot's one.
        by: A column of its table: the gaps within each of its values (a request, a
            job); ``None``: within each lane.
        min: Gaps shorter than this are left out (a duration such as ``"50ms"``; on a plot
            of numbers, a number); ``None``: none, but gaps of no time.
        max: Gaps longer than this are left out.
    """

    layer: str | None = None
    by: str | None = None
    min: Any = None
    max: Any = None

    def __post_init__(self) -> None:
        super().__post_init__()
        for key in ("layer", "by"):
            v = getattr(self, key)
            if v is not None and not isinstance(v, str):
                raise TypeError(f"MeasureGaps's {key} is a name, got {v!r}")
        measuring.check_duration("MeasureGaps's min", self.min)
        measuring.check_duration("MeasureGaps's max", self.max)


@dataclass(frozen=True, repr=False)
class MeasureChain(MeasureRule):
    """Measures from each end to the next, on one level: continued dimensions, A to B to C
    ([`Timeline.measure_chain`][anytimeline.Timeline.measure_chain]).

    Args:
        through: Its ends in turn, two or more: [`Edge`][anytimeline.Edge]s or times.
        lane: The lane its measures are drawn in; ``None``: the upper of its ends' lanes.
    """

    through: tuple[Any, ...] = ()
    lane: Any = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        super().__post_init__()
        if isinstance(self.through, str) or not isinstance(self.through, Sequence):
            raise TypeError(f"MeasureChain's through is a list of ends, got {self.through!r}")
        if len(self.through) < 2:
            raise ValueError("MeasureChain needs two ends or more")
        for e in self.through:
            _check_end("MeasureChain", e)
        object.__setattr__(self, "through", tuple(self.through))


@dataclass(frozen=True, repr=False)
class MeasureFrom(MeasureRule):
    """Measures from one origin to each of several ends, stacked a level apart, the shortest
    nearest the marks: baseline dimensions
    ([`Timeline.measure_from`][anytimeline.Timeline.measure_from]).

    Args:
        origin: Where each starts: an [`Edge`][anytimeline.Edge] or a time.
        to: Where each ends, one or more.
        lane: The lane its measures are drawn in; ``None``: the upper of its ends' lanes.
    """

    origin: Any = None
    to: tuple[Any, ...] = ()
    lane: Any = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        super().__post_init__()
        _check_end("MeasureFrom", self.origin)
        if isinstance(self.to, str) or not isinstance(self.to, Sequence):
            raise TypeError(f"MeasureFrom's to is a list of ends, got {self.to!r}")
        if not self.to:
            raise ValueError("MeasureFrom needs an end to measure to")
        for e in self.to:
            _check_end("MeasureFrom", e)
        object.__setattr__(self, "to", tuple(self.to))


Note = Annotation | Connection | Measure | MeasureRule
"""What [`Timeline.notes`][anytimeline.Timeline.notes] holds."""


def _check_color(part: str, color: Any) -> None:
    if color is not None and not isinstance(color, str):
        raise TypeError(f"{part}'s color is a colour name or #hex, got {color!r}")


def _positive(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )
