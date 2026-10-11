# Use anytimeline in marimo

A `Timeline` is an [anywidget](https://anywidget.dev), so marimo shows it as it is. To have
cells react to what happens in the plot (a selection, a tool, the scale), wrap it in
`mo.ui.anywidget`:

```python
import marimo as mo
from anytimeline import Timeline

plot = Timeline().events(df, time="time", lane="service")
widget = mo.ui.anywidget(plot)
widget
```

```python
# runs again whenever the plot changes a setting, such as the selection
widget.value
rows = plot.selection.get("events", [])
df[rows]
```

Settings the plot changes that marimo sees: `selection`, `xscale`, `tool`, `legend`,
`font_size`. Moving and zooming do not re-run cells.
