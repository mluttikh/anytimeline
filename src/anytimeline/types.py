"""The options of anytimeline's arguments as types, so an editor completes them and a type
checker catches a misspelled one (``tool="zom"``) before the cell runs. Arguments that also
take a column or a colour are ``<Option> | str``: the plot checks those when it runs.

```python
from anytimeline.types import Tool

def plot_log(log, tool: Tool = "select"):
    return Timeline(tool=tool).events(log, lane="service")
```

A test checks each type against the values the code accepts (``tests/test_types.py``).
"""

from __future__ import annotations

from typing import Literal

__all__ = [
    "Align",
    "BarOverlap",
    "Clim",
    "Display",
    "EventOverlap",
    "Expand",
    "LaneSort",
    "Renderer",
    "SelectionMode",
    "StemShape",
    "Symbol",
    "Tool",
    "ValuesKind",
    "ValuesScale",
    "XScale",
]

Renderer = Literal["auto", "webgpu", "webgl2", "canvas2d"]
"""How the plot is drawn: the first of WebGPU, WebGL2 and Canvas 2D that works, or one."""
Tool = Literal["pan", "zoom", "select"]
"""What a drag does in the plot."""
XScale = Literal["time", "order"]
"""The time axis: events at their time, or by the order they happened in (evenly spaced)."""
SelectionMode = Literal["multiple", "single"]
"""What a selection can hold; ``None``: nothing can be selected."""
Display = Literal["widget", "html"]
"""How a notebook shows a plot: as a widget, connected to Python, or as a page."""
Align = Literal["time", "start"]
"""What lines up: the same times, or each group's (plot's) first time."""
LaneSort = Literal["name", "first", "last", "count", "table"]
"""The order of lanes: by name, by the time of their first or last event, by their number
of events, or as they first appear in the table."""
EventOverlap = Literal["dodge", "overlay"]
"""Events that would overlap: spread over the lane's height, or drawn on top of each
other."""
BarOverlap = Literal["pack", "overlay"]
"""Bars of a lane that overlap in time: stacked in sub-rows, or drawn on top of each
other."""
ValuesKind = Literal["line", "area", "step"]
"""How a values layer draws its samples: a line, a filled area, or steps (each value held
until the next)."""
ValuesScale = Literal["lane", "shared"]
"""The range of a values lane: its own lowest to highest value, or one for all lanes."""
StemShape = Literal["straight", "curved"]
"""The stems of a story: each box over its event, or moved aside with a bending stem."""
Expand = int | Literal["auto", "all"]
"""The levels of a tree shown at first: a number (1: the top only), all of them, or as many
as keep about 200 lanes."""
Clim = tuple[float, float] | Literal["robust"]
"""Colour limits for numbers: two numbers, or the 2nd to 98th percentile."""
Symbol = Literal[
    "circle",
    "square",
    "diamond",
    "triangle",
    "triangle-down",
    "cross",
    "x",
    "tick",
    "circle-open",
    "square-open",
    "diamond-open",
    "triangle-open",
    "triangle-down-open",
]
"""The shapes of events."""
