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

`plot.range` is the visible time range, as your data's kind (NumPy datetime64, timedelta64,
or numbers). It is updated a quarter of a second after the view stops moving, and is `None`
until the plot has been shown.

```python
start, end = plot.range
df.filter(pl.col("time").is_between(start, end))
```

## The scale

`plot.xscale = "sequence"` switches to the Order scale, `"time"` back; the toolbar's
Time and Order buttons change it too, and Python sees the change.
