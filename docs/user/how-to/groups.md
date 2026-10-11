# Groups and linked plots

To compare hosts, regions, days or runs, put them in **one plot as groups**: one time axis,
one toolbar, one legend; full screen, Save as PNG and the HTML page take all of them, and a
selection box can span them. For plots that live apart (in different cells of a notebook,
side by side in a dashboard), **link** them so they zoom together.

## Groups

`group=` on a layer splits its rows by a column: each group gets a header lane with its own
lanes under it, in the same order in every group, so the groups compare row by row. A
category has one colour everywhere (there is one legend), and a values lane has one range in
every group. Click a group's name to fold it; double-click to zoom to it.

```python exec="on" source="above" session="groups" html="true"
import numpy as np
from anytimeline import Timeline
from anytimeline.synthetic import service_log

log = service_log(1200)
host = np.where(np.isin(log["user"], [f"u{i:02d}" for i in range(30)]), "web-1", "web-2")
log = {**log, "host": host}

plot = Timeline(title="Two web servers", height=520,
                lane_order=["gateway", "auth", "api", "cache", "db"])
plot.events(log, time="time", lane="service", group="host", color="level", symbol="event",
            palette={"info": "#4c78a8", "warning": "#f58518", "error": "#e45756"})
print(plot._embed_html())
```

- Every layer takes `group=`: events, intervals, spans, states and values. Layers without it
  go above the groups.
- `Timeline(group_order=["web-2"])` puts groups first; the others follow in natural order.
- Spans with `group=` put each trace under its group's header (traces by endpoint, by
  release); events with `lane="span_id"` still go on their spans.
- `plot.selection` gives rows of the tables, from all groups.

## Compare from the start: align="start"

`Timeline(align="start")` starts each group's times at 0: groups of different periods
(days, test runs, traces) line up, and the axis counts from their start. Here the slowest and
the fastest of twelve requests, one above the other:

```python exec="on" source="above" session="groups" html="true"
from anytimeline.synthetic import traces

tr = traces(12, seed=3)
roots = tr.spans["parent_id"] == None  # noqa: E711
took = (tr.spans["end"] - tr.spans["start"])[roots]
slow, fast = tr.spans["trace_id"][roots][[took.argmax(), took.argmin()]]
pick = np.isin(tr.spans["trace_id"], [slow, fast])
pair = {k: v[pick] for k, v in tr.spans.items()}
pair["request"] = np.where(pair["trace_id"] == slow, "slowest", "fastest")

plot = Timeline(title="Slowest and fastest, from their start", align="start", height=520)
plot.spans(pair, color="service", group="request")
print(plot._embed_html())
```

## Link plots that live apart

[`Timeline.link`][anytimeline.Timeline.link] links separate plots: zoom or pan one, and the
others show the same time; the pointer's time shows as a dashed line in all; their lane names
and legends take the same width, so their axes line up when stacked. It works between plots
in different cells of a notebook and in a page from `save_html`. Times of other origins or
units line up; `align="start"` lines plots up from their own start. `unlink()` leaves the
group.

```python
trace_plot.link(metrics_plot)
```

[`save_html`][anytimeline.save_html] writes several plots to one page, still linked:

```python
from anytimeline import save_html

save_html("compare.html", trace_plot, metrics_plot)
```
