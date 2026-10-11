# anytimeline

Interactive timeline and event charts for Jupyter and marimo notebooks, drawn on the GPU
(WebGPU, WebGL2, or Canvas 2D on machines without a usable GPU).

```bash
pip install anytimeline
```

Documentation: <https://mluttikh.github.io/anytimeline/> · Changelog:
[CHANGELOG.md](CHANGELOG.md) · Licence: MIT.

Status: version 0.1. It draws **event charts**: one mark per event at the moment it
happened, on lanes, so the order of what happened is easy to see. Time can be datetimes (any
time zone, any century), durations from nanoseconds up, or plain numbers; a Time | Order switch
spaces events by rank instead of time. Up to about a million events. It also draws **Gantt
charts** and schedules: bars from a start to an end, with dependencies, progress and
milestones, and overlapping bars stacked per lane; and **traces**: spans under spans.

```python
from anytimeline import Timeline
from anytimeline.synthetic import service_log

log = service_log()  # a dict of columns; any Polars, pandas or PyArrow table works too
tl = Timeline()
tl.events(
    log,
    time="time",
    lane="service",
    color="level",
    symbol="event",
    route="request",
    order="seq",
    tooltip=["request", "user", "bytes"],
)
tl  # click it, then scroll to zoom time; drag to pan; the toolbar has Zoom and Select
```

A Gantt chart from a table with a row per task:

```python
from anytimeline import gantt

gantt(plan, task="task", start="start", end="end", depends="after", progress="done",
      color="phase", today="2026-10-12")
```

Bars on other lanes (machines, people, services) come from `Timeline.intervals(...)`, and mix
with events on the same lanes.

Traces (OpenTelemetry, or any table of spans with a parent) plot as a waterfall that folds,
with each span's duration and the critical path:

```python
from anytimeline import Timeline
from anytimeline.otel import read_otlp

tr = read_otlp("traces.jsonl")  # or anytimeline.synthetic.traces()
Timeline().spans(tr.spans, color="service").events(tr.events, time="time", lane="span_id")
```

The toolbar has three tools: **Pan** (drag moves through time and lanes), **Zoom** (drag a
time range to show it) and **Select** (drag a box, or click an event; the selection is rows of
your table in `tl.selection`). Time and Order switch the scale; Aa sets the text size (also `Timeline(font_size=14)`).
Press `?` in the plot for every mouse gesture and key; `f` or
the button shows it full screen, where lanes fill the screen and overlapping events spread
out.

States (`Timeline.states`: up, degraded, down per lane) and values (`Timeline.values`: a
number over time, as a line, area or steps) go on the same lanes, behind the events.

`group="host"` on a layer puts each host's lanes under a header of their own, in one plot
(`Timeline(align="start")` compares groups from their start); separate plots link with
`a.link(b)` and zoom and pan together.

`plot.save_html("plot.html")` writes the plot to one file that opens in any browser, still
interactive; the toolbar saves it as a PNG, and so does `plot.save_png("plot.png")`.

Documentation online: <https://mluttikh.github.io/anytimeline/>; or build it with
`uv run python scripts/build_docs.py` and open `site/index.html`. Example notebook:
[`examples/event_charts.ipynb`](examples/event_charts.ipynb). How the plot is drawn:
[the explanation in the docs](https://mluttikh.github.io/anytimeline/explanation/drawing.html).

## Development

Needs Python (via [uv](https://docs.astral.sh/uv/)) and Node.js 20+ for the JavaScript bundle.

```bash
(cd js && npm ci && npm run build)    # build src/anytimeline/static/widget.js
uv sync                               # create .venv with dev tools
uv run pytest                         # Python tests
(cd js && npm run typecheck && npm test)
uv run ruff check . && uv run ruff format --check . && uv run ty check
uv run python scripts/make_scenes.py  # scenes for the visual tests
(cd js && npx playwright install chromium && npm run test:visual)  # every scene × backend, marimo
uv run nbstripout --install           # once per clone: commit notebooks without outputs
uv run python scripts/build_docs.py   # user documentation into site/ (examples run; warnings fail)
uv run python scripts/build_docs.py serve   # preview it at http://localhost:8000
```

The user documentation is in `docs/user/`, built with [Zensical](https://zensical.org) and
organised as tutorials, how-to guides, reference and explanation. Its examples are
```` ```python exec="on" ```` blocks that run while building, and its plots are live: each
example prints `plot._embed_html()`, which `standalone.js` draws in the page. The API
reference comes from the docstrings (Google style). The browser tests check the built site
too (`docs.spec.ts`, skipped until it is built).

Visual tests draw the scenes in `js/test/visual/scenes/` with each backend and compare them
with stored screenshots (macOS); `npm run test:visual:update` stores new ones after an
intended change. `PERF=1 npx playwright test perf` measures a million events (after
`uv run python scripts/make_scenes.py --million`).
