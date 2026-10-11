# Text and mark size, height and full screen

The toolbar's **Display** panel (the sliders button) sets the text size, the mark size and
whether overlapping events spread; each is also a setting in Python, and a change in the
panel shows in Python.

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

In the plot, the Display panel has − and + and Reset; Python sees the change in
`plot.font_size`. The time axis grows with the text, and lanes are at least 1.5 × the text
size.

## Mark size

`mark_scale=` makes every event mark smaller or larger, as a factor of the size its layer
gives it (0.25 to 4, default 1), so a `size=` column keeps its proportions. Smaller marks
overlap less in dense data; larger ones read better on a projector. The Display panel steps
through ×0.5, ×0.75, ×1, ×1.25, ×1.5 and ×2.

```python
Timeline(mark_scale=0.75)
```

## Spreading overlapping events

Events that would overlap are spread over the lane's height
([why](../explanation/dodging.md)). `dodge=False` (or the Display panel's switch, or the key
**d**) draws every event on its lane's line instead: to compare times exactly, or to see a
burst as one line. A layer with `overlap="overlay"` never spreads.

## Height

By default a plot is about 30 pixels per lane (at most 640 px in all). `height=` fixes it:

```python
Timeline(height=800)
```

Lanes always fill the plot's height. A taller lane gives events that would overlap more room
to move apart, so they overlap less ([why](../explanation/dodging.md)).

## Full screen

The full-screen button in the toolbar (or **f**) shows the plot on the whole screen. It keeps
the time range you were looking at, so the extra width shows more detail; the lanes fill the
screen's height, and bursts of events spread out. **Esc** (or the button) leaves full screen.

The button is not shown where the browser does not allow full screen, for example in a frame
that does not permit it.
