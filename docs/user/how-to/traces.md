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

## A flame chart

`layout="flame"` puts the spans on a lane per depth instead of a lane per span: each span
under the one that called it, its name in its bar. A deep trace stays a few lanes high, and
the shape of the request shows at a glance. Spans of one depth that ran at the same time
(the stock checks) go to sub-rows, each under its parent where it can.

```python exec="on" source="above" session="traces" html="true"
plot = Timeline(title="GET /orders, as a flame chart", height=260)
plot.spans(spans, layout="flame", color="service", tooltip=["service", "status"])
print(plot._embed_html())
```

With many traces, give each its own lanes: `group="trace_id"` (any column works: a host, an
endpoint). The flame chart marks no critical path and writes no durations by default;
`critical_path=True` and `durations=True` add them.

## Many traces as one flame graph

[`merge`][anytimeline.traces.merge] adds up the spans of many traces: a row per *path* (the
service and name of each span from the root down), as wide as the time spent in it, its
children side by side in it, the heaviest first. Where does the time of all these requests
go? The axis is time spent, from 0, not time of day.

```python exec="on" source="above" session="traces" html="true"
from anytimeline.traces import merge

merged = merge(tr.spans)
plot = Timeline(title="Eight requests, merged", height=260)
plot.spans(merged, layout="flame", color="service",
           tooltip=["path", "count", "total", "self"])
print(plot._embed_html())
```

`count` is the number of spans merged, `total` their time, `self` the part of it not spent
in a child. Calls made in parallel can take longer together than their parent: they then
share its width, and their `total` still says how long each took. `by=` names a call by
other columns (`by=["name"]` merges one name across services).

## Compare two traces

[`compare_traces`][anytimeline.compare_traces] matches the spans of two traces by their path
and colours each by what changed: **added**, **removed**, **slower**, **faster** (by more
than `threshold=`, 10%) or the same. The first trace's span is behind each in grey, and the
change is in its bar. Both traces' times are from their own start, so they line up. Here a
request that worked against one that had to retry its query:

```python exec="on" source="above" session="traces" html="true"
from anytimeline import compare_traces

roots = tr.spans["parent_id"] == None  # noqa: E711
first = {t: n for t, n in zip(tr.spans["trace_id"][roots], tr.spans["name"][roots])}
good = next(t for t, n in first.items() if n == first[bad] and t != bad)
ok = {k: v[tr.spans["trace_id"] == good] for k, v in tr.spans.items()}

print(compare_traces(ok, spans, title="GET /orders: fine, then with a retry")._embed_html())
```

Spans whose names hold an id (`GET /stock/E09`) match only the same id: pass `by=` with
columns that name the call without it. The table behind the plot, a row per span of either
trace with both durations and the change, is [`compare`][anytimeline.traces.compare]'s.

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

## Traces from Jaeger

[`read_jaeger`][anytimeline.jaeger.read_jaeger] reads Jaeger's JSON: the Jaeger UI's
**Download JSON**, and the answers of its query API (`/api/traces`). It returns the spans
and events with the same columns as `read_otlp`, so everything above works on them. A span's
logs are its events.

```python
from anytimeline.jaeger import read_jaeger

tr = read_jaeger("trace.json")
Timeline().spans(tr.spans, color="service").events(tr.events, lane="span_id")
```

## Traces from Chrome, Perfetto and profilers

[`read_chrome`][anytimeline.chrome.read_chrome] reads Chrome's trace event format: what
Chrome's DevTools (Performance: save profile) and `chrome://tracing` save, what Perfetto
exports as JSON, and what many tools write (PyTorch's profiler, `viztracer`, Bazel's and
Clang's `-ftime-trace`). Its slices become spans, nested as they are on their thread; its
flows become arrows; its counters become values.

```python
from anytimeline.chrome import read_chrome

trace = read_chrome("trace.json")
plot = Timeline().spans(
    trace.spans, layout="flame", group="track", depends="follows", color="category"
)
plot.values(trace.counters, lane="name", value="value")
plot.events(trace.events, lane="thread", group="track", name="instants")
```

`group="track"` gives each thread (`"process / thread"`) its own lanes; async slices are on
a track of their own. Times are durations from the trace's first event: the format's clock
has no date. A slice that never ended (a trace cut short) is drawn open, to the end.

## Your own table

Any table with a row per span works. By default `spans()` reads the columns `span_id`,
`parent_id`, `name`, `start` and `end`; name yours with `id=`, `parent=`, `lane=`, `start=`
and `end=` (or `duration=`). Span ids must be unique in the table; a span whose parent is not
in it (a trace cut short) is shown at the top.

## Other trees

The tree is not only for traces: `intervals(..., id=, parent=)` draws any bars with parents
(jobs with steps, tasks with sub-tasks), and [`gantt(..., parent=)`](gantt.md#sub-tasks)
gives a Gantt chart with sub-tasks. Set `critical_path=True` or `durations=True` there as
you like.
