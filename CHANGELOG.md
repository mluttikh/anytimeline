# Changelog

All notable changes to anytimeline. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

Foundations: plots that show where widgets do not, and checks that Python and the browser
agree. And the plot as a Python object, with one name per idea: a release that changes
code. Each old spelling raises an error that names the new one, for this release.

### Breaking changes

- **A plot is a Python object, not a widget.** `Timeline` owns the widget that shows it,
  `plot.widget`, made the first time the plot is shown (pages and images need none). Where
  a widget itself is needed, use `plot.widget`:
  `mo.ui.anywidget(plot.widget)` in marimo, `ipywidgets.VBox([a.widget, b.widget])`;
  `plot.widget.observe(fn, "tool")` instead of `plot.observe`.
- A setting set to a value of the wrong kind raises a `TypeError`, a wrong value a
  `ValueError` (was `traitlets.TraitError`).
- `plot.range` is `plot.view`: a `View(start, end, lanes)` of what the plot shows, which can
  also be set (see Added).
- `plot.perf` is `plot.dev.perf`.
- `xscale="sequence"` is `xscale="order"`, the name the toolbar gives it.
- `selection_mode="none"` is `selection_mode=None`; `states(text=False)` is `text=None`.
- `intervals(label=)` is `lane=`: with `parent=`, the column that names each bar's lane;
  `spans(label=)` is `lane=` too (default `"name"`).
- `expand=None` (every level of a tree) is `expand="all"`.
- `events(labels="stems")`, `stem_shape=` and `label_width=` (and `story`'s) are one
  argument, `stems=`: `True`, `"curved"`, or a `Stem(shape, width)`.
- Markers are `Marker(time, label, color)` objects in `plot.markers`, a list to set;
  `clear_markers()` is `plot.markers = []`. `plot.marker(time, label)` still adds one.
- The layer modules are in `anytimeline.layers` (`anytimeline.layers.events`, ...).

### Added

- **HTML in the notebook**: `Timeline(display="html")` shows the plot as HTML with its data
  in the output, so a saved, exported (nbconvert, Quarto) or shared notebook shows it without
  a kernel. Zoom, pan, hover, Time / Order, folding, full screen and linking work there.
  Where scripts do not run (an untrusted notebook in JupyterLab, GitHub) the output says so.
  In marimo the plot is shown as a page in a frame, which `marimo export html` keeps.
- `Timeline.to_html()`: the page `save_html` writes, as text; `to_html(full_html=False)`: an
  element for a page of your own, any number per page.
- `Timeline.selected(layer)`: the selected rows as a table of the type plotted (pandas keeps
  its index).
- `anytimeline.marimo.selection(plot)`: the selection as marimo state, so a cell runs again on
  a selection and not on every pan, tool or text size.
- **States**: the tooltip lists every lane's state at the pointer's time, and follows the
  pointer.
- **Warnings for times that look wrong**: datetimes all in January 1970 (epoch numbers read
  in a too fine unit), and plain numbers that look like seconds, milliseconds, microseconds
  or nanoseconds since the epoch. An `end` column of durations says to pass `duration=`.
- A text repr: `Timeline(events: 2,256 events; cpu: 1,810 samples)`.
- `plot.view = View(start, end, lanes=["db"])` shows a time range and brings a lane to the
  top, unfolding the lanes it is under; `other.view = plot.view` shows the same in another
  plot, and `plot.view = None` the whole timeline from the top.
- Plots copy (`copy.copy`, `copy.deepcopy`) and pickle: a plot of its own, without the
  widget, links and callbacks.
- `anytimeline.types`: the options of arguments as `Literal` types (`Tool`, `XScale`,
  `LaneSort`, ...), for your own functions; editors complete them and type checkers catch a
  misspelled one.
- `tooltip=` takes one column name as well as a list.
- `plot.dev.benchmark(frames)` times frames in the browser; the result comes in
  `plot.dev.perf`.

### Changed

- A lazy table (Polars LazyFrame, DuckDB relation) is read once with only the columns its
  layer uses, not every column.
- A widget's plain-text output (what a notebook without the widget shows) says how to show
  the plot as HTML.

### Fixed

- Values layers no longer send an order buffer the browser does not use.

### Development

- The spec Python sends is checked against a JSON Schema generated from the browser's types,
  for a plot of every kind; random plots (Hypothesis) and every kind of table (dict, Polars,
  PyArrow, pandas with NumPy, nullable and Arrow dtypes, DuckDB, with missing values) are
  tested for the same spec and the same selection.
- `scripts/check.py` runs CI's Linux jobs locally; CI runs the Python tests on Windows too.
- Each layer kind is a module of `anytimeline.layers` (reading the table, its layout,
  picking); `widget.py` is only the protocol with the browser, `page.py` the HTML, and
  `scene.py` lays the layers out together.
- The browser's view is split into modules (folding, rendering, drawing, picking, input),
  with no change in what it does.

## [0.3.0] - 2026-10-12

Story timelines: for a few dozen events whose text matters.

### Added

- **Story timelines**: `story(data, text)` and `events(..., labels="stems")` put each event's
  text in a box above or below its lane's line, joined by a stem; the boxes take as many
  levels as they need so none overlap, at every zoom (the more important first). For an
  incident, a release history, a project's history.
- No stem passes behind a box: each stem keeps a corridor through the levels it crosses
  (after labella.js's stubs), and boxes are placed so they do not cover their neighbours'
  stems. Events whose boxes do not fit are counted in badges ("+4") that zoom in when clicked.
- `stem_shape="curved"`: boxes may move aside, their stems bending near the line.
- `label_width=`: long titles wrap onto two lines within the box width (16 × the text size by
  default).
- The boxes' look: stems in the event's colour, tinted boxes with a soft shadow, the time in
  the event's colour.
- `Timeline(lane_names=False)`: a plot without the column of lane names.
- `synthetic.incident()`: the timeline of an incident, for examples.
- Text templates format datetime columns: `"{time:%H:%M}"`.

## [0.2.0] - 2026-10-11

### Changed

- **Dodging uses the lane's height.** Events that would overlap are spread over sub-rows as far
  apart as the lane allows: a mark and a pixel apart when there is room, so marks no longer
  overlap; closer (down to 0.6 of a mark) only when the rows do not fit otherwise, with a
  margin at the lane's edges and up to 101 sub-rows. In full screen a burst of events now
  spreads out instead of overlapping; plots of normal size look as before.
- The toolbar's text-size button became the **Display** panel: text size, mark size and
  spreading on or off.

### Added

- `Timeline(mark_scale=)`: event marks smaller or larger (0.25 to 4 times the layers' sizes),
  also in the Display panel.
- `Timeline(dodge=)`: spread overlapping events, or draw every event on its lane's line; also
  in the Display panel and the key `d`.
- Example notebooks for every kind of chart: Gantt charts, traces, states and values, groups
  and linked plots, sharing.

### Fixed

- The README's link to the architecture notes (not in the package); it now points to the
  documentation's explanation of how the plot is drawn.

## [0.1.0] - 2026-10-11

The first release: interactive timeline charts for Jupyter, VS Code and marimo notebooks,
drawn with WebGPU, WebGL2 or Canvas 2D.

### Added

- **Event charts** (`Timeline.events`): a mark per event on lanes, coloured, shaped and sized
  by columns; overlapping events spread out; routes join the events of a group; labels and
  tooltips. Time can be datetimes in any time zone and century, durations from nanoseconds,
  or plain numbers; the **Order** scale spaces events by the order they happened in.
- **Intervals and Gantt charts** (`Timeline.intervals`, `gantt`): bars from a start to an end,
  packed per lane, with milestones, open bars, progress, dependency arrows and markers.
- **Traces** (`Timeline.spans`, `anytimeline.otel.read_otlp`): spans as a waterfall that folds,
  with each span's duration and the critical path; OpenTelemetry OTLP/JSON reader.
- **States and values** (`Timeline.states`, `Timeline.values`): what state a lane was in, and
  a number over time as a line, area or steps behind the events.
- **Groups** (`group=` on every layer): hosts, days or runs as groups of lanes in one plot;
  `Timeline(align="start")` compares groups from their start.
- **Linked plots** (`Timeline.link`): separate plots that zoom and pan together.
- **Sharing**: `save_html` (one file that works without Python), Save as PNG in the toolbar
  and `Timeline.save_png`.
- Toolbar with Pan, Zoom and Select tools, Time / Order, Back and Home, legend, text size and
  full screen; selections come back to Python as rows of your tables; light and dark themes
  that follow the notebook.
- Synthetic example data (`anytimeline.synthetic`) and documentation with live examples.

[Unreleased]: https://github.com/mluttikh/anytimeline/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/mluttikh/anytimeline/releases/tag/v0.3.0
[0.2.0]: https://github.com/mluttikh/anytimeline/releases/tag/v0.2.0
[0.1.0]: https://github.com/mluttikh/anytimeline/releases/tag/v0.1.0
