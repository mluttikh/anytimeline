"""Parts of a layer whose settings only matter together, as frozen dataclasses: a
[`Route`][anytimeline.Route], a story's [`Stem`][anytimeline.Stem]; and the notes on a plot:
an [`Annotation`][anytimeline.Annotation], a [`Connection`][anytimeline.Connection], a
[`Measure`][anytimeline.Measure], whose ends may be [`Edge`][anytimeline.Edge]s. Route and
Stem have ``of()``, which also takes the short forms its argument accepts
(``route="request"``, ``stems=True``)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, get_args

import numpy as np

from anytimeline.types import StemShape

STEM_SHAPES = get_args(StemShape)


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
    begin or end, so that it stays on the mark. An event's start and end are its time.
    [`start`][anytimeline.start] and [`end`][anytimeline.end] make one.

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
    """The start of a mark: an [`Edge`][anytimeline.Edge] (an event's start is its time).

    Args:
        row: The mark: a row of its layer's table.
        layer: The mark's layer; ``None``: the plot's one layer.
    """
    return Edge(row, "start", layer)


def end(row: int, layer: str | None = None) -> Edge:
    """The end of a mark: an [`Edge`][anytimeline.Edge] (an event's end is its time).

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
        text: Written at its middle; ``None``: the time between. ``{time}`` in it is the time
            between, ``{events}`` the number of events between them in the order.
        lane: The lane it is drawn in when neither end is an edge (a lane's name); ``None``:
            at the top of the plot.
        color: Its colour; ``None``: the accent colour.
    """

    a: Any
    b: Any
    text: str | None = None
    lane: Any = None
    color: str | None = None

    def __post_init__(self) -> None:
        for end in (self.a, self.b):
            if end is None or isinstance(end, bool | tuple):
                raise TypeError(f"Measure's ends are Edges or times, got {end!r}")
        if self.text is not None and not isinstance(self.text, str):
            raise TypeError(f"Measure's text is text or None, got {self.text!r}")
        _check_color("Measure", self.color)


Note = Annotation | Connection | Measure
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
