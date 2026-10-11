# Arrange the lanes

`lane=` names the column whose values are the lanes. Without it, all events of a layer go in
one lane named after the layer.

## The order of the lanes

By default lanes are sorted by name, with numbers in names compared as numbers (`w9` before
`w10`). A Polars `Enum` or a pandas `Categorical` keeps its declared order. To choose:

```python
Timeline(lane_order=["gateway", "auth", "api"])  # these first, in this order
Timeline(sort="first")  # by the time of each lane's first event
Timeline(sort="last")  # by the time of each lane's last event
Timeline(sort="count")  # the busiest lanes first
```

`lane_order=` and `sort=` work together: the lanes you name come first, the rest follow
sorted.

```python exec="on" source="above" html="true"
import polars as pl
from anytimeline import Timeline
from anytimeline.synthetic import service_log

log = pl.DataFrame(service_log(200))
plot = Timeline(sort="count", height=240, title="Busiest service first")
plot.events(log, time="time", lane="service", color="level")
print(plot._embed_html())
```

## Many lanes

Lanes fill the plot's height. When they do not fit at their smallest (1.5 × the text size,
at least 18 px), they keep that height and the plot scrolls: **Shift + wheel**, the arrow
keys ↑ ↓, or drag up and down.

To give each lane more room, make the plot taller (`Timeline(height=800)`) or show it
[full screen](size.md).
