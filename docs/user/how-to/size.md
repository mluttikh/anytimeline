# Text size, height and full screen

## Text size

`font_size=` sets the size of all text in the plot, in pixels (8 to 24, default 12): lane
names, the time axis, labels, the legend, tooltips.

```python exec="on" source="above" html="true"
import polars as pl
from anytimeline import Timeline
from anytimeline.synthetic import service_log

log = pl.DataFrame(service_log(150))
plot = Timeline(font_size=15, height=280, title="Larger text")
plot.events(log, time="time", lane="service", color="level")
print(plot._embed_html())
```

In the plot, the **Aa** button in the toolbar has − and + and Reset; Python sees the change in
`plot.font_size`. The time axis grows with the text, and lanes are at least 1.5 × the text
size.

## Height

By default a plot is about 30 pixels per lane (at most 640 px in all). `height=` fixes it:

```python
Timeline(height=800)
```

Lanes always fill the plot's height. A taller lane gives events that would overlap more room
to move apart ([why](../explanation/dodging.md)).

## Full screen

The full-screen button in the toolbar (or **f**) shows the plot on the whole screen. It keeps
the time range you were looking at, so the extra width shows more detail; the lanes fill the
screen's height, and bursts of events spread out. **Esc** (or the button) leaves full screen.

The button is not shown where the browser does not allow full screen, for example in a frame
that does not permit it.
