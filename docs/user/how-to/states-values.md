# States and values

Next to events and bars, a lane can show what state something was in
([`states`][anytimeline.Timeline.states]) and how a number changed
([`values`][anytimeline.Timeline.values]). On the same lanes as the events, they explain
them: here the health of five services as the lanes' colour, their CPU as an area, and the
errors and warnings of their log on top.

```python exec="on" source="above" session="sv" html="true"
import numpy as np
from anytimeline import Timeline
from anytimeline.synthetic import service_health, service_log, service_metrics

log = service_log()
problems = {k: v[log["level"] != "info"] for k, v in log.items()}

plot = Timeline(title="Health, CPU and problems", height=420,
                lane_order=["gateway", "auth", "api", "cache", "db"])
plot.states(service_health(), lane="service", tooltip=["reason"],
            palette={"up": "#54a24b", "degraded": "#f58518", "down": "#e45756"},
            opacity=0.25, height=1.0)
plot.values(service_metrics(), value="cpu", lane="service", kind="area", ylim=(0, 100),
            name="cpu %")
plot.events(problems, time="time", lane="service", color="level", symbol="event",
            palette={"error": "#c62828", "warning": "#ef6c00"}, name="problems")
plot.zoom_to(np.datetime64("2026-10-12T08:25"), np.datetime64("2026-10-12T08:45"))
print(plot._embed_html())
```

## States

The table has a row per **change**: from its time on, its lane is in its state, until the
lane's next change.

| time | service | state |
| --- | --- | --- |
| 08:00:00 | api | up |
| 08:33:30 | api | degraded |
| 08:34:20 | api | up |

- A row that repeats the state its lane is in changes nothing; a missing state is a gap
  (nothing known then).
- A lane's last state runs to `end=` if you give it, else to the plot's last time.
- Each state's name is written in its band where it fits (`text=False` to leave it out).
- Hover a state to compare the lanes at one moment: the tooltip lists **every lane's state at
  the pointer's time** (the hovered lane in bold), and follows the pointer; under them the
  hovered state's start, end and duration, with the `tooltip=` columns.
- `height=1.0` with a low `opacity` makes the states the lanes' background, as above; the
  default (`height=0.8`, opaque) draws them as a band of their own.
- On the **Order** scale each change takes one place, and a state runs to its lane's next
  change.

## Values

A row per sample: a time, a number, and (optionally) a lane.

- `kind="line"` (default), `"area"` (filled below the line) or `"step"` (each value holds
  until the next sample: gauges, counters, queue lengths).
- Each lane's band runs from its lowest to its highest value (from 0 when the values are
  near it); `scale="shared"` puts all lanes on one range, `ylim=(0, 100)` fixes it. The
  range is written small at the band's left when the lane is tall enough.
- A missing value (NaN, null) is a gap in the line.
- Hover the line for a sample's time and value.
- Many samples are fine: each pixel column of a line shows the lowest and highest value in
  it.

`series=` splits a lane into several lines, coloured by series: the p50 and p99 latency of
each service, from a long table.

```python exec="on" source="above" session="sv" html="true"
m = service_metrics()
latency = {
    "time": np.concatenate([m["time"], m["time"]]),
    "service": np.concatenate([m["service"], m["service"]]),
    "quantile": np.repeat(["p50", "p99"], len(m["time"])),
    "ms": np.concatenate([m["p50_ms"], m["p99_ms"]]),
}
plot = Timeline(title="Latency per service", height=360,
                lane_order=["gateway", "auth", "api", "cache", "db"])
plot.values(latency, value="ms", lane="service", series="quantile", kind="step")
print(plot._embed_html())
```

Samples take no places on the **Order** scale (a metric sampled every second would crowd out
the events): there, each is drawn between the events it falls between. A plot of values
only has no order, and its Order button is off.
