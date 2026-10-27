# Use anytimeline in marimo

marimo shows a `Timeline` as it is. To have cells react to what happens in the plot (a
selection, a tool, the scale), wrap the widget that shows it,
[`plot.widget`][anytimeline.Timeline.widget], in `mo.ui.anywidget`:

```python
import marimo as mo
from anytimeline import Timeline

plot = Timeline().events(df, time="time", lane="service")
widget = mo.ui.anywidget(plot.widget)
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

## React to the selection only

A cell that reads `widget.value` runs again on every setting the plot changes: a tool, the
scale, the text size. [`anytimeline.marimo.selection`][anytimeline.marimo.selection] gives the
selection as marimo state, so a cell runs again when the selection changes and on nothing
else. [`selected`][anytimeline.Timeline.selected] gives the selected rows as a table:

```python
import anytimeline.marimo

get_selection = anytimeline.marimo.selection(plot)
plot
```

```python
get_selection()  # this cell runs again when the selection changes
plot.selected("events")
```

## In an exported app

`marimo export html` saves the app's outputs, not its Python: a widget is empty there. With
`Timeline(display="html")` marimo shows the plot as a page in a frame, which the export keeps
and which works without Python (selecting aside).
