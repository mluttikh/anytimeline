# Schedules and spans

[`Timeline.intervals`][anytimeline.Timeline.intervals] draws a bar per row from its start to
its end, on lanes: jobs on machines, shifts of people, the time a request spends in each
service. [`gantt()`](gantt.md) is this with a lane per task.

## Bars that overlap

Bars of one lane that overlap in time are stacked in sub-rows, the first free row first, so
none hides another:

```python exec="on" source="above" session="intervals" html="true"
import numpy as np
from anytimeline import Timeline

rng = np.random.default_rng(5)
n = 160
jobs = {
    "machine": rng.choice([f"press {i}" for i in range(1, 7)], n),
    "start": np.datetime64("2026-10-12T06:00", "m")
    + np.sort(rng.integers(0, 3 * 24 * 60, n)).astype("timedelta64[m]"),
    "minutes": rng.integers(20, 240, n),
    "product": rng.choice(["A", "B", "C", "D"], n),
}
plot = Timeline(title="Jobs per machine", height=380)
plot.intervals(jobs, end=None, duration="minutes", duration_unit="min", lane="machine",
               color="product", text="{product}")
print(plot._embed_html())
```

`overlap="overlay"` draws them on top of each other instead; `height=` sets the bars' height
as a fraction of the lane (default 0.7).

## Start and end, or duration

- `start=` and `end=`: two columns of times of the same kind.
- `end=None, duration=`: a column of durations (timedelta), or of numbers with
  `duration_unit=` (`"d"`, `"h"`, `"min"`, `"s"`, `"ms"`, `"us"`, `"ns"`). With plain-number
  times, durations are in the same numbers.

A row whose end equals its start is a **milestone**, drawn as a diamond. A row without an end
is **open**: it runs to the plot's last time and fades out, like a job that is still running.
A row that ends before it starts is an error that names the first such row.

## Bars and events together

Layers share the lanes and the time axis, so bars and events line up: here the time each
request spends in a service, with the request's events on top.

```python exec="on" source="above" session="intervals" html="true"
import polars as pl
from anytimeline.synthetic import service_log

log = pl.DataFrame(service_log(8)).sort("time")
stays = (
    log.with_columns(end=pl.col("time").shift(-1).over("request"))
    .drop_nulls("end")
    .rename({"time": "start"})
)
plot = Timeline(lane_order=["gateway", "auth", "api", "cache", "db"], height=340)
plot.intervals(stays, lane="service", color="request", height=0.45, opacity=0.5, name="spans")
plot.events(log, time="time", lane="service", symbol="event", order="seq", name="events")
one = log.filter(pl.col("request") == "r0002")["time"]
plot.zoom_to(one.min(), one.max())
print(plot._embed_html())
```

## Everything else

Colors (`color=`, `palette=`, `colormap=`, `clim=`, `opacity=`), `text=`, `tooltip=` and
selection work as for events; the selection gives rows per layer:
`plot.selection == {"intervals": [3, 17]}`. On the **Order** scale each bar's start and end
take a place in the order of all events and bars.
