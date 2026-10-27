# Join events into routes

A route is a line through the events of one group (a request, a user, a process) in the order
they happened. It shows the path each group took through the lanes, and where one overtook
another.

```python
plot.events(df, lane="service", route="request")
```

or with a `Route` for its look:

```python
from anytimeline import Route

plot.events(df, lane="service", route=Route("request", color="theme", width=1))
```

- **Color**: by default each line has the color of the event it starts at, so with
  `color="request"` each request has its own color. `color="theme"` draws every route in the
  text color; any other color draws them all in that color.
- **Order**: a group's events are joined by time, then `order=`, then table order.

Routes read best on the **Order** scale, where a burst of events is spread out:

```python exec="on" source="above" html="true"
import polars as pl
from anytimeline import Timeline
from anytimeline.synthetic import service_log

log = pl.DataFrame(service_log(300))
plot = Timeline(lane_order=["gateway", "auth", "api", "cache", "db"], xscale="order", height=300)
plot.events(
    log, time="time", lane="service", color="request", order="seq", route="request", text="{event}"
)
burst = log.filter(pl.col("request").is_in(["r0152", "r0153", "r0154", "r0155"]))
plot.zoom_to(burst["time"].min(), burst["time"].max())
print(plot._embed_html())
```

Lines are drawn while at most 60,000 of them are in view; zoom in when there are more.
