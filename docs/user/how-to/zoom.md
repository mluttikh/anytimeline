# Zoom from Python

`zoom_to(start, end)` shows a time range. The times are of your data's kind: datetimes (or
ISO text), durations, or numbers.

```python
plot.zoom_to("2026-10-12T08:30", "2026-10-12T08:35")
plot.zoom_to(np.datetime64("2026-10-12T08:30"), np.datetime64("2026-10-12T08:31"))
```

On the Order scale the plot shows the events in that time range.

A `zoom_to` before the plot is shown applies when it is shown. **Back** in the toolbar (or
Backspace) returns to the view before.

## What the plot shows

[`plot.view`][anytimeline.Timeline.view] is what the plot shows: a
[`View`][anytimeline.View] of the time range in sight (`start`, `end`, as your data's kind:
NumPy datetime64, timedelta64, or numbers) and the names of the lanes in sight (`lanes`, top
to bottom). It is updated a quarter of a second after the view stops moving; before the
plot is shown, it is what was set (`View()`: everything).

```python
view = plot.view
df.filter(pl.col("time").is_between(view.start, view.end))
```

Set it to show a time range and bring a lane to the top, unfolding the lanes it is under.
Another plot's view works too, and `None` shows the whole timeline from the top:

```python
from anytimeline import View

plot.view = View("2026-10-12T08:30", "2026-10-12T08:35", lanes=["db"])
other.view = plot.view
plot.view = None
```

`zoom_to` sets the time range only and keeps the lanes in sight as they are.

## The scale

`plot.xscale = "order"` switches to the Order scale, `"time"` back; the toolbar's
Time and Order buttons change it too, and Python sees the change.
