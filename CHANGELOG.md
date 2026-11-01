# Changelog

All notable changes to anytimeline. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Measures by rule**: `plot.measure_each` (each bar's length; `rows=` for some),
  `plot.measure_gaps` (the gaps between marks in each lane or `by=` group; `min=`, `max=`),
  `plot.measure_chain` (A to B to C on one level) and `plot.measure_from` (from one origin to
  each end, a level apart). Each is one note (`MeasureEach`, `MeasureGaps`, `MeasureChain`,
  `MeasureFrom`) worked out again when the data changes; `plot.measured` has a row per
  measure it makes, with `part`. In the plot, its measures are selected one at a time and
  change, move and are removed as the rule. They take the `measure` defaults.
- **`limit=`** on a measure and a rule: a measure longer than it is drawn red (the theme's
  new `--atl-over` colour), and `plot.measured` has `over`.

## [0.6.0] - 2026-11-01

More control over measures: put a measure's line where you want it (in its lane, in a band
above or below the lanes, or at a value), move it in the plot with the mouse, its menu or
the keys, and choose its text, label position, ends and extension lines. Levels no longer
change while zooming.

### Added

- **Where a measure goes**: `plot.measure(..., at=...)` puts its line at the top, middle or
  bottom of its lane, on the border under it (`"between"`), in a band above or below the
  lanes (`"header"`, `"footer"`; a band takes room only when used), or at a value on a values
  layer (`at=atl.value(80)`). `level=` keeps it on a level, and `nudge=` moves it a few
  pixels. `lane=` places it also when its ends are marks. `plot.measured` has `at`, `lane`
  and `level`; a measure's Copy as Python writes them.
- **Move a measure in the plot**: drag a selected measure's line to another level, place,
  lane, or into the header or footer band; its menu has Place, Automatic and Edit text; with
  a measure selected, ↑ and ↓ move it a level, 0 puts it back to automatic and Enter edits
  its text. Each change replaces the measure in `plot.notes`. **Show measures** in the
  Display panel hides them all.
- **A measure's text and look**: fields `{rate}`, `{a}`, `{b}` and a column of an end's row
  (`{b.service}`, `{a.start:%H:%M}`), and formats (`{time:ms}`, `{time:s.2}`,
  `{change:+.2f}`, `{events:,}`). `label=` puts the text on, above or below the line, before
  or after it, or only on hover; `ends=` ends the line in arrows, ticks, dots or nothing;
  `extend=` draws the extension lines from the marks, through every lane, or not. The
  measure's menu has a Label row. `set_defaults(measure={...})` sets them for every measure.

### Changed

- **Breaking:** measures stack by their times, not their pixels: zooming and panning no
  longer move one to another level. A label that has no room beside its line shows when the
  measure is hovered or selected, instead of lifting it a level. Measures the top of a lane
  has no room for continue in the header band, and a measure of two times goes there (it was
  drawn over the top lane).

### Fixed

- A measure's extension lines start at the mark it measures: at a bar's own sub-row when bars
  of a lane overlap, and at an event moved aside by `overlap="dodge"`. They started at the
  lane's middle. The tick on the edge a measure would take is on the bar too.

## [0.5.2] - 2026-11-01

An Export menu: copy, download or save the plot as PNG or SVG. And defaults per method,
`plot.update`, an import without the widget, the drawing code once per page
(`html_script`), and toolbar tips that show at once.

### Added

- **An Export menu** in the toolbar (key `e`) replaces the Save as PNG button: Copy image,
  Copy as vector (SVG with a PNG beside it, in Chrome, Edge and VS Code), Download PNG,
  Download SVG, and Save PNG or SVG next to the notebook (Python writes the file and never
  overwrites one). The PNG is the plot as on screen; the SVG is drawn by Python for the same
  view, size, folded lanes and theme. A saved page (`save_html`, `display="html"`) offers the
  PNG entries. See the new how-to "Make images for slides".
- **Defaults per method**: `anytimeline.set_defaults(plot={...}, events={...}, ...)` sets
  arguments for every `Timeline(...)` and `events`, `intervals`, `states`, `values` and
  `spans` call made afterwards; the call's own arguments win. They are checked when set.
  `anytimeline.defaults(...)` sets them inside a `with` block only; `get_defaults()` and
  `reset_defaults()` list and remove them. New how-to "Set defaults, and change a layer".
- **`plot.update(name, **changes)`** calls a layer's method again with its last arguments
  and the changes (also `data=`), keeping the layer's name and place; a lazy table is not
  read again. **`plot.arguments(name)`** gives what a layer was made with.
- **`anytimeline.html_script()`** and **`to_html(full_html=False, script=False)`**: a page
  with many plots carries the drawing code and styles once (put `html_script()` in its
  `<head>` or `<body>`), and each plot only its data, about 250 KB less per plot. A plot
  put in the page later draws after `window.anytimelineEmbed.add()`.

### Changed

- Pictures from Python (`save_image`, `to_svg`) fold lanes as the plot shows them, once it
  was shown; before, as the plot starts.
- `import anytimeline` no longer loads anywidget, ipywidgets or traitlets: pictures, pages,
  the selection and `on_select` work without them (`pip install --no-deps anytimeline numpy
  narwhals` on a server). Showing the widget without anywidget says what to install.
  ipywidgets and traitlets are no longer direct dependencies (anywidget still brings them).
- `on_select` callbacks: one that raises no longer stops the others; its traceback shows in
  the notebook, else in the `anytimeline` log.
- The toolbar's tips show 0.15 s after the pointer comes to a button, and on keyboard
  focus, instead of the browser's own tooltip a second later. A greyed button's tip says why
  it is greyed (Back: no earlier view yet; Home: the whole timeline is shown).
- Ibis tables are tested: they are read once like other lazy tables, and `selected()` gives
  a PyArrow table of the rows drawn. The docs name them with the other tables.

## [0.5.1] - 2026-10-28

ΔY: measures between two samples of a values layer show the change in value. And cleanup:
bins that fade with a selection, faster packing of bars, tests in Firefox and WebKit.

### Added

- **ΔY**: a sample of a values layer is a mark a measure may end at
  (`plot.measure(atl.start(8, "cpu"), atl.start(20, "cpu"))`, or the Measure tool, whose ends
  snap to samples). Between two samples of one layer a measure shows the change in value
  with the time ("1.5 h · Δ −1.19") and a dot on each sample; its tooltip has both values and
  the rate of change, `{change}` in its text is the change, and `plot.measured` has the
  columns `a_value`, `b_value` and `change`.

### Changed

- Bars are packed into sub-rows about three times as fast (0.08 s for a million bars that
  rarely overlap, from 0.33 s); runs of many bars that all overlap take as long as before.
- The browser tests run in Firefox and WebKit too (the scenes, interactions, linked plots
  and pages).

### Removed

- The errors that named the new spelling of what 0.4.0 renamed or removed (`plot.range`,
  `plot.perf`, `plot.observe`, `plot.clear_markers()`, `xscale="sequence"`,
  `selection_mode="none"`, `expand=None`, `states(text=False)`, `label=` of `intervals` and
  `spans`, `labels=`, `stem_shape=` and `label_width=`): they now fail as any unknown name
  or value does. The errors for what 0.5.0 removed stay for a release.

### Fixed

- A selection fades the bins of events too (a layer of many events zoomed out), except the
  bins that hold a selected event, in the plot and in pictures.
- The plot laid itself out inside the browser's resize callback, which Safari reported as
  "ResizeObserver loop completed with undelivered notifications" when the toolbar wrapped.

## [0.5.0] - 2026-10-28

Traces in depth: flame charts, flame graphs of many traces, two traces compared, and traces
from Jaeger and from Chrome's trace format. And measuring: the time from one mark's start or
end to another's, made in Python or in the plot, with all notes in one list.

### Added

- **Measures**: `plot.measure(a, b)` draws the time between two ends as a dimension line
  with the time at its middle (and, on the Order scale, the events between). An end is a
  mark's start or end, `atl.start(row)` or `atl.end(row, layer)` (an `Edge`), or a time, so
  a measure spans a gap, start to start, a bar's own length, or a time to a mark.
  `plot.measured` is a table of them: both times, the time between as a duration, the
  events between, and the mark and side of each end.
- **The Measure tool** (`plot.tool = "measure"`, the ruler in the toolbar): a drag from one
  mark to another measures between their nearest starts or ends (Shift: a free time); a
  double-click measures a bar. The keys `m` (one end, then the other), `M` (the bar under
  the pointer) and `>` `<` (move the second end to the next or previous edge) work with any
  tool. A measure's label shows both times exactly when hovered; clicked, it selects the
  measure, whose ends can then be dragged and which `Delete` removes. Measures made in the
  plot come to Python; a page keeps its own until it is closed, and offers each one as
  Python to copy.
- Connections and annotations take edges too: `plot.connect(atl.start(3), atl.start(4))`
  draws start to start (and end to end, start to end), and
  `plot.annotate(atl.start(3), atl.end(3))` stays on a mark.

- **Flame charts**: `spans(..., layout="flame")` puts the spans on a lane per depth, each
  under the span that called it and named in its bar, so a deep trace stays a few lanes
  high. Spans of one depth that ran at the same time go to sub-rows, each under its parent
  where it can; `group="trace_id"` gives each trace its own lanes.
- **Flame graphs of many traces**: `anytimeline.traces.merge(spans)` adds up the spans of
  one trace or many by their path (the service and name of each span from the root down),
  the heaviest first, with each path's count, total and own (self) time. Plot it with
  `spans(merged, layout="flame")`.
- **Two traces compared**: `compare_traces(before, after)` colours each span of the second
  trace by what changed (added, removed, slower, faster, the same; `threshold=` 10%), with
  the first trace's span behind it and the change in its bar.
  `anytimeline.traces.compare` gives the table behind it.
- `anytimeline.jaeger.read_jaeger`: Jaeger's JSON (the UI's download, the query API), as
  spans and events with the columns of `read_otlp`.
- `anytimeline.chrome.read_chrome`: Chrome's trace event format (DevTools, `chrome://tracing`,
  Perfetto's JSON, PyTorch's profiler, ...): slices as spans, nested on their thread (async
  slices by their id), instants as events, counters as values, and flows as arrows
  (`depends="follows"`).
- `spans(depends=)`: arrows from the spans a span follows, as `intervals(depends=)` draws
  them.

### Changed

- **Breaking: one list of notes.** `plot.notes` holds the annotations, connections and
  measures, in the order they were made, and replaces `plot.annotations`,
  `plot.connections` and `plot.markers` (each now raises an error that says so).
- **Breaking: markers are annotations.** `Marker` and `plot.marker(time, label)` are gone:
  `plot.annotate(time, text=label)` draws the same line across all lanes, in the selection
  colour, its label on top (`gantt(today=)` and `schedule(today=)` make one).
- **Breaking:** a `Connection`'s ends are `Edge`s; `(layer, row)` still means that mark's
  end for `a` and its start for `b`, as `plot.connect(3, 4)` still does.
- `spans()` marks the critical path and writes durations by default in a waterfall only
  (`critical_path=` and `durations=` default to `None`); `height=` defaults to 0.6 in a
  waterfall and 0.9 in a flame chart.
- The lanes of a plot with a tree are titled as the tree names them, not as the first
  layer does.
- The OpenTelemetry reference page is now Traces, with every reader, `merge` and
  `compare`.

### Fixed

- The errors for `expand=None`, `xscale="sequence"`, `selection="none"` and
  `states(text=False)` said these were 0.4's spellings; they were 0.3's.

## [0.4.0] - 2026-10-27

Foundations: plots that show where widgets do not, and checks that Python and the browser
agree. The plot as a Python object, with one name per idea: a release that changes code.
Each old spelling raises an error that names the new one, for this release. And levels of
detail: ten million events, samples or bars in a plot that opens at once. And images and
analysis: pictures drawn in Python, the selection in numbers, search, and notes.

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

- **Pictures drawn in Python**: `plot.save_image("plot.svg")` and `plot.to_svg()` draw the
  plot as the browser does at that size and view, without a browser: in scripts, tests and
  CI. The SVG holds only shapes, lines and text (no clip paths, filters or images), so
  PowerPoint, Keynote and Google Slides import it as shapes. `.png` through the optional
  `resvg-py` (`pip install 'anytimeline[png]'`). `width=`, `height=`, `view=`,
  `theme="dark"`, `scale=`.
- **The selection in numbers**: while something is selected, a panel counts it in total, by
  colour category and by lane, with bars' total and mean duration, events' span and values'
  mean, least and greatest. `plot.summary(layer, rows="selected" | "all")` gives the same as
  a table of the type plotted. `Timeline(summary_panel=False)` hides the panel.
- **Find and step**: `/` or Ctrl/Cmd+F finds text and lane names; Enter and Shift+Enter go
  through the matches, bringing each into sight with a ring and its text. `.` and `,` go to
  the next and previous mark of a lane, over layers; `F` fits the view to it. Python answers
  from every mark (layers sent as levels too); a page searches the marks it holds.
- **Annotations**: `plot.annotate(start, end, text, lane=)` (a band, or a line at one time)
  and `plot.connect(a, b, text)` (an arrow from one mark to another), as `Annotation` and
  `Connection` in `plot.annotations` and `plot.connections`. In the plot, `a` then a drag
  or a click makes a note, `c` on two marks an arrow; both come to Python. They show in
  pages and pictures.
- **Undo for the selection**: Ctrl/Cmd+Z and Shift+Ctrl/Cmd+Z, and
  `plot.undo_selection()` / `plot.redo_selection()`; 50 changes kept in Python.
- **Touch waits for a tap**: before it, a finger scrolls the page; after it, one finger pans
  and two pinch to zoom.
- `tzdata` is a dependency on Windows, for time zones.
- **Levels of detail**: a layer of more than 250,000 events, samples or bars is sent as
  levels. Zoomed out, the browser draws counts per lane and bin (bins a factor of 4 apart):
  events as bars from a bin's first to its last event, as tall as it has events, in its most
  frequent colour; values from each bin's first, lowest, highest and last sample (spikes and
  gaps stay); bars shorter than a bin merged into a band per lane and bin, as opaque as they
  fill it. Zoomed in, Python sends the marks there (at most 200,000 in view), drawn as any
  layer's. The Order scale has levels of its own. For 10,000,000 events on 100 lanes, the
  browser gets 1.3 MB first instead of 280 MB.
- A bin's tooltip: its count, its range, and its events per colour category (from Python).
  `importance=` picks the event that shows a bin.
- Selecting works on bins (a box, or a click on a bin with the Select tool or Shift), and
  the selected events are marked over the bins.
- A page of a plot with levels (`save_html`, `display="html"`) holds every event up to 20 MB,
  else the levels alone.
- In marimo, buffers of 64 KB or more come to the browser as files (binary, over HTTP)
  instead of in messages; if a file cannot be fetched, as messages.
- `scripts/bench_levels.py`: build time, first-frame size and window times of a plot of
  many events, samples or bars.
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
- Python 3.15 (tested on 3.12 to 3.15).

### Changed

- Building a plot of millions of rows is faster: sorting by lane and time (no
  `np.lexsort`), missing values found in NumPy, colour categories in one pass, and a values
  layer's range per lane without comparing every lane name. 10,000,000 events: 6.5 s
  (13 s before); 10,000,000 samples: 2.4 s (16 s).
- A lazy table (Polars LazyFrame, DuckDB relation) is read once with only the columns its
  layer uses, not every column.
- A widget's plain-text output (what a notebook without the widget shows) says how to show
  the plot as HTML.

### Fixed

- Month and day ticks across a new year counted on from the old year's months ("Oct, Nov,
  Dec, Oct").
- Values layers no longer send an order buffer the browser does not use.
- A flaky browser test of the Display panel waits for the marks to change.

### Development

- Twins: Python's ports of the browser's time axis, level choice, dodging and stem layout
  (for pictures) are tested against the browser's code on the same cases
  (`tests/fixtures/twins.json`, written by `UPDATE_TWINS=1 npm test`).
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

[0.6.0]: https://github.com/mluttikh/anytimeline/releases/tag/v0.6.0
[0.5.2]: https://github.com/mluttikh/anytimeline/releases/tag/v0.5.2
[0.5.1]: https://github.com/mluttikh/anytimeline/releases/tag/v0.5.1
[0.5.0]: https://github.com/mluttikh/anytimeline/releases/tag/v0.5.0
[0.4.0]: https://github.com/mluttikh/anytimeline/releases/tag/v0.4.0
[0.3.0]: https://github.com/mluttikh/anytimeline/releases/tag/v0.3.0
[0.2.0]: https://github.com/mluttikh/anytimeline/releases/tag/v0.2.0
[0.1.0]: https://github.com/mluttikh/anytimeline/releases/tag/v0.1.0
