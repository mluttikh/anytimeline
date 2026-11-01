# How to set defaults, and change a layer

## Defaults for every plot

When every plot of a project takes the same arguments (a text size, a height, the lane
column of your logs), set them once with
[`set_defaults`][anytimeline.set_defaults], for example in a module your team imports:

```python
import anytimeline

anytimeline.set_defaults(
    plot={"font_size": 14, "height": 420, "timezone": "Europe/Amsterdam"},
    events={"lane": "service", "tooltip": ["request", "user"]},
    spans={"color": "service"},
    measure={"ends": "ticks", "label": "above", "text": "{time:ms}"},
)
```

`plot` is for `Timeline(...)`; `events`, `intervals`, `states`, `values`, `spans` and
`measure` for those methods (a measure's look and text, not its ends; measures made in the
plot, and the rules `measure_each`, `measure_gaps`, `measure_chain` and `measure_from`, take
those of them they have too). Every plot and layer made afterwards takes them, also those made by
[`gantt`][anytimeline.gantt], [`story`][anytimeline.story] and
[`compare_traces`][anytimeline.compare_traces].

- **The call wins**: `Timeline(font_size=18)` is 18 whatever the default.
- **Checked when set**: an argument the method does not take, or a word that is not one of
  its options (`events={"overlap": "spread"}`), raises at `set_defaults`, and nothing of
  that call is kept. A layer's table and its `name`, and a measure's ends, cannot have
  defaults.
- Setting a method's defaults again adds to those set before.
  [`get_defaults`][anytimeline.get_defaults] shows what is set (to copy into your team's
  module), and [`reset_defaults`][anytimeline.reset_defaults] removes them, of one method
  (`reset_defaults("events")`) or all.

For a few plots only, use [`defaults`][anytimeline.defaults] in a `with` block; afterwards
the defaults are as before, also after an error:

```python
with anytimeline.defaults(plot={"font_size": 18, "height": 360}):
    slide = Timeline(title="Checkout").events(log)  # larger text, for slides
```

## Change a layer

[`plot.update`][anytimeline.Timeline.update] calls a layer's method again with its last
arguments and your changes. The layer keeps its name and its place:

```python
plot = Timeline().events(log, lane="service", color="level")
plot.update("events", color="bytes", colormap="viridis")
plot.update("events", data=log_of_today)  # the same layer of other rows
```

Without `data=` it draws the table it has, as read the first time: a lazy table (a Polars
`LazyFrame`, a DuckDB relation, an Ibis table) is not queried again. A change it does not
take raises, and the layer stays as it was.

[`plot.arguments`][anytimeline.Timeline.arguments] shows what a layer was made with: the
arguments that differ from the method's own defaults, also those that came from
`set_defaults`:

```python
plot.arguments("events")  # {'lane': 'service', 'color': 'bytes', 'colormap': 'viridis'}
```
