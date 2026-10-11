# Plot many events

The plot draws every event on the graphics chip (WebGPU, or WebGL2), so panning stays smooth
with many events. Measured on a laptop (Apple M1 Max, Chrome):

| Events | Python (`events()`) | Shown | Panning, whole range | Panning, zoomed in |
| --- | --- | --- | --- | --- |
| 1,000,000 on 40 lanes | 1.1 s | 0.2 s | 8 ms per frame | 3 ms per frame |

On a computer without a usable graphics chip the plot draws with Canvas 2D: slower, and at
most 40,000 events per frame (an evenly spaced subset while more are in view).

## What to expect

- In this version every event is sent to the browser at once: about 28 bytes per event, so
  28 MB for a million. Up to a few hundred thousand events this is quick; a million takes a
  moment to arrive. (Sending only what the view needs is planned.)
- Zoomed out, a million events on a few lanes are dense bands. Zoom in to see single events;
  labels appear when at most 3,000 are in view, routes when at most 60,000 lines are.
- Thin marks help with dense data: `symbol="tick"`, `size=5`.

```python exec="on" source="above" html="true"
from anytimeline import Timeline
from anytimeline.synthetic import instants

data = instants(100_000, lanes=12)
plot = Timeline(title="100,000 events", height=320)
plot.events(data, lane="lane", color="kind", symbol="tick", size=6)
print(plot._embed_html())
```
