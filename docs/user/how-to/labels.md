# Labels and tooltips

## Labels next to events

`text=` takes a column, or a template with column names in braces:

```python
plot.events(df, text="event")
plot.events(df, text="{event} ({user})")
```

A label is drawn right of its event where it fits: labels never overlap, and none are drawn
while more than 3,000 events are in view, so zoom in to see them. Where labels would overlap,
`importance=` (a numeric column, higher is more important) decides which keep theirs:

```python exec="on" source="above" html="true"
import polars as pl
from anytimeline import Timeline
from anytimeline.synthetic import service_log

log = pl.DataFrame(service_log(300)).with_columns(
    rank=pl.col("level").replace_strict({"info": 0, "warning": 1, "error": 2})
)
plot = Timeline(lane_order=["gateway", "auth", "api", "cache", "db"], height=300)
plot.events(
    log,
    time="time",
    lane="service",
    color="level",
    text="{event}",
    importance="rank",
    palette={"info": "#9aa5b1", "warning": "#f58518", "error": "#e45756"},
)
start = log["time"].to_numpy()[log.height // 3]
plot.zoom_to(start, start + (log["time"].to_numpy()[-1] - log["time"].to_numpy()[0]) // 40)
print(plot._embed_html())
```

`font_size=` sets their size, with all other text ([how to](size.md)).

## Labels in boxes on stems

When the text matters more than the pattern, `stems=True` puts each event's text in a box
above or below its lane's line, at as many levels as needed so none overlap, joined to the
event by a line: a [story timeline](story.md).

## Tooltips

Hovering over an event shows its lane, its time to the precision of your data, and its place
in the order of all events. `tooltip=` adds columns:

```python
plot.events(df, tooltip=["request", "user", "bytes"])
```

The extra columns come from Python when you hover, so they are not part of the page or the
notebook's saved state. Turn tooltips off for one layer with `hover=False`, or for the whole
plot with `plot.hover = False`.
