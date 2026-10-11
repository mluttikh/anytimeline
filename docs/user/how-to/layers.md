# Several layers in one plot

Each `events()` call adds a layer. Layers share the lanes, the time axis and the Order scale,
so their events line up.

```python exec="on" source="above" html="true"
import polars as pl
from anytimeline import Timeline
from anytimeline.synthetic import service_log

log = pl.DataFrame(service_log(300))
plot = Timeline(lane_order=["gateway", "auth", "api", "cache", "db"], height=260)
plot.events(log, time="time", lane="service", color="#c3cad3", size=6, name="all events")
plot.events(
    log.filter(pl.col("level") != "info"),
    time="time",
    lane="service",
    color="level",
    symbol="x",
    size=11,
    name="problems",
    palette={"warning": "#f58518", "error": "#e45756"},
)
print(plot._embed_html())
```

- Layers are drawn in the order you add them: later layers on top.
- `name=` names a layer (default `"events"`). Adding a layer with an existing name replaces
  that layer: call `events()` again with new data to update a plot that is already shown.
- `plot.layers` lists them; `plot.remove("problems")` removes one, `plot.clear()` all.
- The selection is per layer: `plot.selection == {"problems": [3, 17]}`.
- All layers need times of one kind (all datetimes, all durations or all numbers), or none
  (order only).
