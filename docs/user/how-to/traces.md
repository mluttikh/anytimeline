# Plot traces

[`Timeline.spans`][anytimeline.Timeline.spans] draws the spans of traces as a waterfall: a
lane per span, under the span that called it, its duration beside it, and the **critical
path** (what the end of the request waited for) as a dark line through the bars. Lanes fold,
so many traces fit: here eight requests, folded to one lane each, with the events in their
spans (exceptions, retries, cache misses).

```python exec="on" source="above" session="traces" html="true"
from anytimeline import Timeline
from anytimeline.synthetic import traces

tr = traces(8, seed=3)  # .spans and .events: dicts of columns
plot = Timeline(title="Eight requests", height=380)
plot.spans(tr.spans, color="service", tooltip=["service", "status"], expand=1)
plot.events(tr.events, time="time", lane="span_id", symbol="name", color="#333333",
            tooltip=["attributes"], name="span events")
print(plot._embed_html())
```

## Fold, unfold, zoom

- **Click** the name of a span with a triangle before it to show the spans under it; click
  it again to fold them. **Alt + click** does every level under it at once.
- **Double-click** a name to zoom to that span and everything under it.
- <kbd>]</kbd> unfolds every lane, <kbd>[</kbd> folds them all to the roots.
- `expand=` sets what shows at first: `1` the roots only, `2` their children too, `None`
  everything. The default, `"auto"`, opens as many levels as keep about 200 lanes.

A folded span says how many spans it hides (`+9`). Events on hidden spans are hidden with
them.

## One trace

With one trace, everything is open. The request below failed once: the query timed out after
250 ms (the ● is its exception) and was retried (■). The critical path runs through the
timeout and the retry; the parallel stock checks are not on it except the one that ended
last.

```python exec="on" source="above" session="traces" html="true"
bad = tr.spans["trace_id"][list(tr.spans["status"]).index("error")]
spans = {k: v[tr.spans["trace_id"] == bad] for k, v in tr.spans.items()}
events = {k: v[tr.events["trace_id"] == bad] for k, v in tr.events.items()}

plot = Timeline(title="GET /orders, with a retry")
plot.spans(spans, color="service", tooltip=["service", "status"])
plot.events(events, time="time", lane="span_id", symbol="name", color="#333333",
            tooltip=["attributes"], name="span events")
print(plot._embed_html())
```

Switch to **Order** in the toolbar: each start and end gets the same width, so the order of
the calls shows however long each took.

## Traces from OpenTelemetry

[`read_otlp`][anytimeline.otel.read_otlp] reads OTLP/JSON: what the OpenTelemetry
Collector's file exporter writes (one export request per line), and what Jaeger and Tempo
export.

```python
from anytimeline import Timeline
from anytimeline.otel import read_otlp

tr = read_otlp("traces.jsonl")
plot = Timeline().spans(tr.spans, color="service")
plot.events(tr.events, time="time", lane="span_id", symbol="name")
plot
```

The spans have the columns `trace_id`, `span_id`, `parent_id`, `name`, `service`, `kind`,
`status`, `status_message`, `start`, `end` and `attributes`; any of them can go into
`color=` or `tooltip=`. Times are UTC: give the plot `Timeline(timezone="Europe/Amsterdam")`
for local times.

## Your own table

Any table with a row per span works. By default `spans()` reads the columns `span_id`,
`parent_id`, `name`, `start` and `end`; name yours with `id=`, `parent=`, `label=`, `start=`
and `end=` (or `duration=`). Span ids must be unique in the table; a span whose parent is not
in it (a trace cut short) is shown at the top.

## Other trees

The tree is not only for traces: `intervals(..., id=, parent=)` draws any bars with parents
(jobs with steps, tasks with sub-tasks), and [`gantt(..., parent=)`](gantt.md#sub-tasks)
gives a Gantt chart with sub-tasks. Set `critical_path=True` or `durations=True` there as
you like.
