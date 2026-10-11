# anytimeline

Interactive timeline charts for Jupyter and marimo notebooks, drawn on the GPU: **event
charts** (one mark per event at the moment it happened, on lanes, so you see what happened,
when, and in what order) and **Gantt charts** and schedules (bars from a start to an end). From a hundred events to a million; from
nanoseconds to centuries.

The plots on these pages are live: hover over an event, drag to move through time, and click
a plot and scroll to zoom. Switch between **Time** and **Order** in the toolbar.

```python exec="on" html="true"
from anytimeline import Timeline
from anytimeline.synthetic import service_log

log = service_log(600)
plot = Timeline(
    title="Requests through five services",
    height=340,
    lane_order=["gateway", "auth", "api", "cache", "db"],
)
plot.events(
    log,
    time="time",
    lane="service",
    color="level",
    symbol="event",
    order="seq",
    palette={"info": "#4c78a8", "warning": "#f58518", "error": "#e45756"},
)
print(plot._embed_html())
```

## What it does

- **Events on lanes**, colored, shaped and sized by your columns, with labels and tooltips
  ([tutorial](tutorials/first-chart.md), [how to](how-to/encodings.md)).
- **The order of events**: the Order scale spaces events evenly, so a burst within a
  millisecond reads as clearly as events hours apart; routes join the events of one request,
  user or process ([tutorial](tutorials/order.md), [how to](how-to/routes.md)).
- **Any time**: datetimes in any time zone and century, durations from nanoseconds up, plain
  numbers, or only an order ([how to](how-to/time.md)).
- **Story timelines**: a few dozen events, each with its text in a box on a stem, above
  and below the line, never overlapping (an incident, a release history:
  [tell a story](how-to/story.md)).
- **Traces**: spans under spans as a waterfall that folds, with the critical path; read
  from OpenTelemetry ([plot traces](how-to/traces.md)).
- **Groups and linked plots**: hosts, days or runs as groups of lanes in one plot, or
  compared from their start; separate plots that zoom together
  ([groups and linked plots](how-to/groups.md)).
- **States and values**: what state a service was in, its CPU or latency as a line, behind
  its events ([states and values](how-to/states-values.md)).
- **Gantt charts, schedules and spans**: bars from a start to an end, with dependencies,
  progress and milestones; overlapping bars stacked per lane
  ([Gantt chart](how-to/gantt.md), [schedules](how-to/intervals.md)).
- **Selection** by click or box, given back as rows of your table
  ([tutorial](tutorials/select.md)).
- **Many events**: a million events pan smoothly on a laptop's graphics chip, and the plot
  still works without one ([how to](how-to/large.md)).

It reads Polars, pandas, PyArrow and DuckDB tables, and works in JupyterLab, VS Code and
marimo.

**Example notebooks** to run yourself: [event charts](https://github.com/mluttikh/anytimeline/blob/main/examples/event_charts.ipynb),
[Gantt charts](https://github.com/mluttikh/anytimeline/blob/main/examples/gantt_charts.ipynb),
[story timelines](https://github.com/mluttikh/anytimeline/blob/main/examples/story_timelines.ipynb), [traces](https://github.com/mluttikh/anytimeline/blob/main/examples/traces.ipynb),
[states and values](https://github.com/mluttikh/anytimeline/blob/main/examples/states_and_values.ipynb),
[groups and linked plots](https://github.com/mluttikh/anytimeline/blob/main/examples/groups_and_linked_plots.ipynb) and
[sharing](https://github.com/mluttikh/anytimeline/blob/main/examples/sharing.ipynb).

## Where to start

<div class="grid cards" markdown>

- **[Tutorials](tutorials/index.md)**: learn by drawing your first event chart, step by step.
- **[How-to guides](how-to/index.md)**: recipes for a task: your own tables, time columns,
  lanes, colors, routes.
- **[Reference](reference/index.md)**: every argument and setting, every mouse gesture and key.
- **[Explanation](explanation/index.md)**: why the plot works the way it does.

</div>
