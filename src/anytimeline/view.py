"""What a plot shows: its time range and the lanes in sight."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class View:
    """What a plot shows: [`plot.view`][anytimeline.Timeline.view], read or set.

    Args:
        start: The first time shown, of the data's kind (a datetime, ISO text, a duration or a
            number). ``None``: from the first time of the data.
        end: The last time shown. ``None``: to the last time of the data.
        lanes: The names of the lanes in sight, top to bottom. Set, the plot scrolls so the
            first of them is at the top, unfolding what it is in. ``None``: from the top.

    Read from a plot that is shown, ``start`` and ``end`` are the range in sight and
    ``lanes`` the lanes in sight; before that, what was set. Lane names repeat across
    groups (``group=``); a name stands for its first lane.
    """

    start: Any = None
    end: Any = None
    lanes: Sequence[str] | None = None
    """A tuple, once made (a list or one name is turned into one)."""

    def __post_init__(self) -> None:
        if self.lanes is not None:
            if isinstance(self.lanes, str):
                object.__setattr__(self, "lanes", (self.lanes,))
            else:
                object.__setattr__(self, "lanes", tuple(str(n) for n in self.lanes))
