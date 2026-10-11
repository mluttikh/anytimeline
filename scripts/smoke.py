"""Smoke test of an installed anytimeline (CI's wheel job): a plot of each kind, with only
the package's own dependencies (no pandas, no Polars), and a page saved with save_html.

    python -I scripts/smoke.py
"""

from __future__ import annotations

import tempfile
from importlib import resources
from pathlib import Path

from anytimeline import Timeline, gantt
from anytimeline.synthetic import service_health, service_log, service_metrics, traces


def main() -> None:
    static = resources.files("anytimeline") / "static"
    for name in ("widget.js", "widget.css", "standalone.js"):
        size = len((static / name).read_bytes())
        assert size > 1000, f"{name} is missing from the package or empty"
    log = service_log(300)
    events = Timeline().events(log, time="time", lane="service", color="level", symbol="event")
    tr = traces(3)
    Timeline().spans(tr.spans, color="service").events(tr.events, time="time", lane="span_id")
    plan = {"task": ["a", "b"], "start": [0.0, 2.0], "end": [2.0, 5.0], "after": [None, "a"]}
    gantt(plan, depends="after")
    board = Timeline().states(service_health(300), lane="service")
    board.values(service_metrics(300), value="cpu", lane="service")
    with tempfile.TemporaryDirectory() as tmp:
        page = events.save_html(Path(tmp) / "plot.html").read_text(encoding="utf-8")
        assert "anytimeline-embed" in page
    print("anytimeline works:", ", ".join(sorted(p.name for p in static.iterdir())))


if __name__ == "__main__":
    main()
