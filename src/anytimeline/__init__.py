"""anytimeline: GPU-accelerated timeline and event charts for notebooks."""

from __future__ import annotations

from typing import Any

from anytimeline.page import save_html
from anytimeline.parts import Annotation, Connection, Edge, Measure, Route, Stem, end, start
from anytimeline.plot import Timeline
from anytimeline.presets import compare_traces, gantt, story
from anytimeline.styling import SYMBOLS
from anytimeline.view import View

__version__ = "0.5.1"

__all__ = [
    "SYMBOLS",
    "Annotation",
    "Connection",
    "Edge",
    "Measure",
    "Route",
    "Stem",
    "Timeline",
    "View",
    "__version__",
    "compare_traces",
    "end",
    "gantt",
    "save_html",
    "start",
    "story",
]

_GONE = {
    "Marker": "Annotation: plot.annotate(time, text=label) draws a line across all lanes",
}
"""Names removed from the package, and what replaced them."""


def __getattr__(name: str) -> Any:
    if name in _GONE:
        raise AttributeError(f"anytimeline.{name} is now {_GONE[name]} (see the changelog)")
    raise AttributeError(f"module 'anytimeline' has no attribute {name!r}")
