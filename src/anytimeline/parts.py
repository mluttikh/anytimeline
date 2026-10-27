"""Parts of a layer whose settings only matter together, as frozen dataclasses: a
[`Route`][anytimeline.Route], a story's [`Stem`][anytimeline.Stem], a
[`Marker`][anytimeline.Marker]. Each has ``of()``, which also takes the short forms its
argument accepts (``route="request"``, ``stems=True``)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, get_args

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


@dataclass(frozen=True)
class Marker:
    """A vertical line across the lanes at a time, such as now or a deadline
    ([`Timeline.markers`][anytimeline.Timeline.markers]).

    Args:
        time: A time of the data's kind (a datetime, ISO text, a duration or a number).
        label: Written at the top of the line.
        color: The line's colour; ``None``: the selection colour.
    """

    time: Any
    label: str = ""
    color: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.label, str):
            raise TypeError(f"Marker's label is text, got {self.label!r}")
        if self.color is not None and not isinstance(self.color, str):
            raise TypeError(f"Marker's color is a colour name or #hex, got {self.color!r}")


def _positive(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )
