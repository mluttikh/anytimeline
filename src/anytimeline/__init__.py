"""anytimeline: GPU-accelerated timeline and event charts for notebooks."""

from __future__ import annotations

from anytimeline.page import save_html
from anytimeline.parts import Marker, Route, Stem
from anytimeline.plot import Timeline
from anytimeline.presets import gantt, story
from anytimeline.styling import SYMBOLS
from anytimeline.view import View

__version__ = "0.3.0"

__all__ = [
    "SYMBOLS",
    "Marker",
    "Route",
    "Stem",
    "Timeline",
    "View",
    "__version__",
    "gantt",
    "save_html",
    "story",
]
