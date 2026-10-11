# Your first event chart

In this tutorial you draw a log of events on lanes, color the events by a column, and look
around in the plot. It takes about ten minutes.

You need a notebook (JupyterLab, VS Code or marimo) with anytimeline and Polars installed;
see [how to install anytimeline](../how-to/install.md). Type each step into a new cell and
run it.

## 1. Get some events

anytimeline draws tables with **one row per event**. For this tutorial it makes an example log
for you: web requests passing through five services.

```python exec="on" source="above" session="first" html="true"
import polars as pl
from anytimeline.synthetic import service_log

log = pl.DataFrame(service_log(300))
log.head()
print(log.head()._repr_html_())  # markdown-exec: hide
```

Each row is one event: when it happened (`time`, to the microsecond), in which service, what
happened (`event`), how serious it was (`level`), and which request and user it belongs to.

## 2. Draw the events

```python exec="on" source="above" session="first" html="true"
from anytimeline import Timeline

plot = Timeline()
plot.events(log, time="time", lane="service")
plot
print(plot._embed_html())  # markdown-exec: hide
```

The last line, `plot`, shows the plot below the cell. Each event is a dot at its time, in the
lane of its service. Where events would overlap, they move up and down a little within their
lane, so you can still count them.

## 3. Look around

The plot above is live, like the one in your notebook. Try this:

1. **Click the plot**, then **scroll** to zoom in on time. (Before a click, scrolling scrolls
   the page.)
2. **Drag** to move through time.
3. **Hover** over an event: the tooltip shows its service and its time, to the microsecond.
4. Press **0**, or double-click, to see the whole log again.

The axis adapts as you zoom: hours and minutes, then seconds, then fractions of a second,
with the date above.

## 4. Color by a column

Give `color=` a column, and `symbol=` another:

```python exec="on" source="above" session="first" html="true"
plot = Timeline(lane_order=["gateway", "auth", "api", "cache", "db"], height=340)
plot.events(log, time="time", lane="service", color="level", symbol="event")
plot
print(plot._embed_html())  # markdown-exec: hide
```

`lane_order=` puts the lanes in the order requests pass through them, and `height=` makes
the plot taller (in pixels). The legend shows what
each color and shape means. The few red events are errors; zoom in on one and hover over it.

## What you learned

- A table with one row per event becomes an event chart with `Timeline().events(...)`.
- `lane=` names the column whose values are the lanes; `color=` and `symbol=` name columns
  to color and shape the events by.
- Click, then scroll to zoom; drag to pan; **0** shows everything.

Next: [follow the order of events](order.md).
