"""anytimeline: GPU-accelerated timeline and event charts for notebooks."""

from __future__ import annotations

from anytimeline.events import Route
from anytimeline.presets import gantt, story
from anytimeline.styling import SYMBOLS
from anytimeline.widget import Timeline, save_html

__version__ = "0.3.0"

__all__ = ["SYMBOLS", "Route", "Timeline", "__version__", "gantt", "save_html", "story"]
