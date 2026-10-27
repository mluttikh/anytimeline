# Plot many events

The plot draws every event on the graphics chip (WebGPU, or WebGL2), so panning stays smooth
with many events. A layer of more than 250,000 events, samples or bars is sent as **levels of
detail**: zoomed out, the browser gets counts per lane and bin; zoomed in, Python sends the
events where you look. So ten million events open as fast as a few thousand.

Measured on a laptop (Apple M1 Max, Chrome), 10,000,000 on 100 lanes:

| Layer | Python (building the plot) | Sent first | Zooming in (Python's part) |
| --- | --- | --- | --- |
| events | 6.5 s | 1.3 MB | 3 ms (75 ms for a finer level) |
| values (samples) | 2.4 s | 1.6 MB | 1 ms (0.3 s for a finer level) |
| intervals (bars) | 15 s | 2.0 MB | 13 ms (0.3 s for a finer level) |

A frame takes about 8 ms at any zoom. Python keeps the table's columns it plots: about
170 bytes per event for an events layer, more for bars.

## What you see

- **Zoomed out**, each lane shows its events per bin (bins a factor of 4 apart, at least 4
  px wide): a bar from a bin's first to its last event, as tall as it has events (a log
  scale), in its most frequent colour. A bin of one event is that event. Hover a bin for its
  count, its range and (colours by category) its events per colour.
- **Zoomed in**, when at most 200,000 events are in view, they come from Python and are
  drawn one by one, as any layer's: labels, routes, tooltips, dodging.
- **Values** are drawn from each bin's first, lowest, highest and last sample, so spikes and
  gaps stay; zoomed in, every sample.
- **Bars** shorter than a bin are merged per lane and bin into one band, as opaque as the
  bars fill the lane; longer bars, their text, dependencies and the critical path are drawn
  as always. Zoomed in, every bar.
- **The Order scale** has levels of its own (bins of ranks).
- `importance=` picks which event shows a bin (the most important); by default its first.
- **Selecting** works at every zoom: a box selects the events in it, and a click on a bin
  (the Select tool, or Shift-click) selects its events. Selected events are marked over the
  bins.

On a computer without a usable graphics chip the plot draws with Canvas 2D: slower, and at
most 40,000 events per frame (an evenly spaced subset while more are in view).

## Pages and HTML

A page (`save_html`, `to_html`, `display="html"`) has no Python to ask: it holds every event
when the layers sent as levels come to at most 20 MB, else only the levels (zoomed in it
shows their finest bins). In marimo, large buffers come to the browser as files rather than
in messages.

## Tips

- Labels appear when at most 3,000 events are in view, routes when at most 60,000 lines are.
- Thin marks help with dense data: `symbol="tick"`, `size=5`.

```python exec="on" source="above" html="true"
from anytimeline import Timeline
from anytimeline.synthetic import instants

data = instants(100_000, lanes=12)
plot = Timeline(title="100,000 events", height=320)
plot.events(data, lane="lane", color="kind", symbol="tick", size=6)
print(plot._embed_html())
```
