# Follow the order of events

In this tutorial you look at the same log by the **order** of its events instead of their
time, and join the events of each request into a route. It continues
[your first event chart](first-chart.md).

## 1. A burst you cannot read

```python exec="on" source="above" session="order" html="true"
import polars as pl
from anytimeline import Timeline
from anytimeline.synthetic import service_log

log = pl.DataFrame(service_log(300))
services = ["gateway", "auth", "api", "cache", "db"]
plot = Timeline(lane_order=services)
plot.events(log, time="time", lane="service", color="request", order="seq")
plot
print(plot._embed_html())  # markdown-exec: hide
```

Each request now has its own color. Halfway the hour there is a burst: many requests within a
few seconds. On the time scale their events pile up, and which came first is hard to see.

`order="seq"` names the column that says in which order the log wrote the events. It decides
the order of events with the same timestamp.

## 2. Switch to Order

Click **Order** in the toolbar (or press **t**). Every event now takes the same width, one
after another, in the order they happened. The axis counts events (#1, #2, ...) instead of
time, and a break mark ⫽ shows where a long gap was skipped, with how long it was.

You can start a plot on the Order scale with `xscale="sequence"`:

```python exec="on" source="above" session="order" html="true"
plot = Timeline(lane_order=services, xscale="sequence")
plot.events(
    log, time="time", lane="service", color="request", order="seq", route="request", text="{event}"
)
burst = log.filter(pl.col("request").is_in(["r0152", "r0153", "r0154", "r0155"]))
plot.zoom_to(burst["time"].min(), burst["time"].max())
plot
print(plot._embed_html())  # markdown-exec: hide
```

## 3. Read the routes

`route="request"` draws a line through the events of each request, in the order they
happened: gateway, auth, api, then the database or the cache, and back to the gateway.
`text="{event}"` writes what happened next to each event where there is room.

Now you can read each request's path, see where one request overtook another, and see which
ones took the database and which the cache.

Switch back to **Time**: the same requests, at their real times. The routes become nearly
vertical lines: each request takes about a millisecond.

## What you learned

- **Time** places events at their time; **Order** places them one after another, evenly.
- `order=` decides the order of events with equal times.
- `route=` joins the events of each group, such as a request, in the order they happened.
- `zoom_to()` shows a time range from Python; here the time of four requests in the burst.

Next: [select events and use them in Python](select.md).
