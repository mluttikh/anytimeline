# Summarise, find and annotate

What a plot tells you once you are in it: how much is selected, where a text occurs, and the
notes you leave for the next reader.

## The selection in numbers

While something is selected, a panel at the bottom right of the plot counts it: in total,
by colour category and by lane, the most first. Bars (intervals, states, spans) add their
total and mean duration; events the time from the first to the last; values their mean,
least and greatest value. Its × hides it until the selection changes;
`Timeline(summary_panel=False)` shows none.

The same numbers as a table, of the type you plotted (Polars, PyArrow, pandas, or a dict of
arrays), a row per lane and colour category:

```python
plot.summary()                 # the plot's one layer; else name it: plot.summary("jobs")
plot.summary(rows="all")       # every row drawn, not only the selected
```

| column | what |
| --- | --- |
| the lane column, the colour column | what the row counts (and `group` with `group=`) |
| `count` | marks |
| `total`, `mean`, `open` | bars: their duration, and bars without an end (they count, without a duration) |
| `first`, `last` | events: the earliest and the latest time, in the plot's time zone |
| `mean`, `min`, `max` | values |

## Undo a selection

<kbd>Ctrl</kbd>/<kbd>⌘</kbd> <kbd>Z</kbd> in the plot takes back the last change of the
selection, <kbd>Shift</kbd> <kbd>Ctrl</kbd>/<kbd>⌘</kbd> <kbd>Z</kbd> makes it again; Python
keeps the last 50 changes, whether made in the plot or by setting `plot.selection`. From
Python:

```python
plot.undo_selection()   # False when there is nothing to take back
plot.redo_selection()
```

## Find text and lanes

<kbd>/</kbd> or <kbd>Ctrl</kbd>/<kbd>⌘</kbd> <kbd>F</kbd> (with the plot focused) opens a
search box. It finds the lanes whose names hold what you type and the marks whose text
(`text=`, a state) does, ignoring case, in time order. <kbd>Enter</kbd> goes to the next
match, <kbd>Shift</kbd> <kbd>Enter</kbd> to the previous: its lane comes into sight
(unfolded), the view moves to it if it is out of sight, and a ring marks it with its text
and time. <kbd>Esc</kbd> closes the box.

In a notebook Python answers, from every mark, also of layers sent as levels; a page
(`save_html`, `display="html"`) searches the marks it holds.

## Step through a lane

<kbd>.</kbd> goes to the next mark of a lane, <kbd>,</kbd> to the previous one: of the lane
of the mark found last, else of the lane at the top, from the view's edge. Events and bars of
every layer on the lane take turns in time order. <kbd>F</kbd> fits the view to the mark: a
bar fills the view, an event is zoomed in on.

## Annotate

Notes on a time range or a time, over one lane or all, and arrows from one mark to another.
They show in the plot, in pages (`save_html`) and in pictures (`save_image`), and stay with
the plot when it is copied.

```python
plot.annotate("2026-10-12T08:20", "2026-10-12T08:35", "incident", lane="db")
plot.annotate("2026-10-12T09:00", text="deploy")   # at one time, across all lanes
plot.connect(12, 40, "retried")                     # rows of the plot's one layer
plot.connect(("requests", 12), ("jobs", 3))         # (layer, row) with several
```

`plot.annotations` and `plot.connections` are lists of
[`Annotation`][anytimeline.Annotation] and [`Connection`][anytimeline.Connection]; set them
to change them, `[]` to remove them all.

In the plot: <kbd>a</kbd>, then a drag over a time range (or a click at a time), then type
the text and press <kbd>Enter</kbd>. A drag within one lane makes a note on that lane, a
drag over more lanes a note across all. <kbd>c</kbd> with the pointer on a mark, then
<kbd>c</kbd> on another, draws an arrow between them. Both come to Python, into
`plot.annotations` and `plot.connections`; in a page without Python, make them in Python.

## On a phone or tablet

A plot waits for a tap before it takes your fingers, so a finger on it scrolls the page.
After the tap, one finger pans and two pinch to zoom; a tap outside the plot gives the page
its scrolling back.
