# Changelog

All notable changes to anytimeline. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

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

[0.1.0]: https://github.com/mluttikh/anytimeline/releases/tag/v0.1.0
