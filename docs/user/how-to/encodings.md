# Colors, symbols and sizes

## Colors

`color=` takes a column, or one color:

```python
plot.events(df, color="level")  # a color per category
plot.events(df, color="latency", colormap="magma")  # numbers through a colormap
plot.events(df, color="#d62728")  # one color
```

- **Categories** get matplotlib's tab10 colors, in the order of the values (sorted, or a
  Polars `Enum`'s / pandas `Categorical`'s order). Choose them with `palette=`: a list of
  colors, or a dict of value → color.
- **Numbers** go through a colormap: `"viridis"` (default), `"magma"`, `"Blues"`, `"Reds"`,
  `"RdBu"`, any matplotlib name when matplotlib is installed, or a list of colors from low to
  high. `clim=(low, high)` fixes the limits; `clim="robust"` leaves out the extreme 0.5% at
  each end.
- `opacity=` (0 to 1) makes events see-through.
- Rows without a value are drawn gray, with "missing" in the legend.

```python exec="on" source="above" session="encodings" html="true"
import numpy as np
from anytimeline import Timeline

rng = np.random.default_rng(1)
n = 400
t = np.sort(rng.integers(0, 3_600, n)).astype("timedelta64[s]")
data = {
    "time": t,
    "job": rng.choice(["build", "test", "deploy"], n),
    "minutes": rng.gamma(2.0, 4.0, n),
}
plot = Timeline(height=200, title="Jobs colored by how long they took")
plot.events(data, lane="job", color="minutes", colormap="magma", clim="robust")
print(plot._embed_html())
```

## Symbols

`symbol=` takes a category column, or one symbol name. A column gets the symbols in this
order: circle, square, diamond, triangle, triangle-down, cross, x, tick, then the open
versions (circle-open, square-open, ...). Choose them with `symbols=`, a list or a dict of
value → symbol. The names are in `anytimeline.SYMBOLS`.

`"tick"` (a short vertical bar) suits dense events, like a rug plot.

## Sizes

`size=` is a diameter in pixels, or a numeric column: the area of each mark then follows the
value, between `size_range=(4, 16)` pixels.

```python exec="on" source="above" session="encodings" html="true"
data["kb"] = rng.lognormal(3, 1, n)
plot = Timeline(height=200, title="Symbols by job, sizes by data")
plot.events(data, lane="job", symbol="job", size="kb", color="#4c78a8", opacity=0.8)
print(plot._embed_html())
```
