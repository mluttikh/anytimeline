# Select events and use them in Python

In this tutorial you select events in the plot and get their rows back in Python. Selecting
needs a running notebook: the plots on these pages show a selection made in Python, but you
cannot select in them.

## 1. Draw the log

```python exec="on" source="above" session="select" html="true"
import polars as pl
from anytimeline import Timeline
from anytimeline.synthetic import service_log

log = pl.DataFrame(service_log(300))
plot = Timeline(lane_order=["gateway", "auth", "api", "cache", "db"], height=340)
plot.events(
    log,
    time="time",
    lane="service",
    color="level",
    symbol="event",
    tooltip=["request", "user", "bytes"],
)
plot
print(plot._embed_html())  # markdown-exec: hide
```

`tooltip=` adds columns to the tooltip: hover over an event to see its request, user and size.

## 2. Select events

In your notebook:

1. Click the **Select** tool in the toolbar (the dashed box), or press **s**.
2. **Click** an event to select it, or **drag a box** around several, in one lane or across
   lanes. Hold **Shift** to add to the selection, **Alt** to remove from it.
3. The other events fade; the selected ones get a ring.

With the **Pan** tool (the default), a plain click selects nothing, so a click to focus the
plot never loses a selection; Shift-click still adds an event.

## 3. Use the selection

The selection is rows of your table, by layer name:

```python
plot.selection  # {"events": [12, 13, 58]}
rows = plot.selection.get("events", [])
log[rows]  # pandas: df.iloc[rows]
```

To run code whenever the selection changes in the plot:

```python
def show(selection):
    print(f"{len(selection.get('events', []))} events selected")


plot.on_select(show)
```

You can also select from Python, for example every error:

```python exec="on" source="above" session="select" html="true"
errors = log.with_row_index().filter(pl.col("level") == "error")["index"].to_list()
plot.selection = {"events": errors}
plot
print(plot._embed_html())  # markdown-exec: hide
```

Press **Esc** in the plot, or the ✕ in the toolbar, to clear the selection.

## What you learned

- The **Select** tool selects by click or box; Shift adds, Alt removes.
- `plot.selection` holds the selected rows of your table, per layer; set it to select from
  Python.
- `plot.on_select(fn)` runs `fn` after every change made in the plot.
