# Summarise, find, measure and annotate

What a plot tells you once you are in it: how much is selected, where a text occurs, how long
from one mark to another, and the notes you leave for the next reader.

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

## Measure

The time from one mark's start or end to another's: the gap between two marks, start to
start, a bar's own length, or from a time to a mark. A measure is drawn as a dimension line
with the time at its middle; on the Order scale it also counts the events between its ends.

```python
import anytimeline as atl

plot.measure(atl.end(12), atl.start(40))              # the gap between rows 12 and 40
plot.measure(atl.start(12), atl.end(12))              # row 12's own length
plot.measure(atl.start(3, "jobs"), atl.start(4, "jobs"))  # start to start, layer "jobs"
plot.measure("2026-10-12T08:20", atl.start(40))       # a time to a mark
plot.measure(t0, t1, "budget: {time}")                # two times, with its own text
plot.measure(atl.start(8, "cpu"), atl.start(20, "cpu"))   # two samples: the time and ΔY
```

[`atl.start`][anytimeline.start] and [`atl.end`][anytimeline.end] name a mark's edge by its
row in the table (and its layer, with several): the measure stays on the mark. An event's
start and end are its time, and so are a sample's.

Between two samples of one values layer a measure shows the change in value too, as an
oscilloscope's cursors do: "1.5 h · Δ −1.19", with a dot on each sample. Its tooltip has both
values and the rate of change ("−0.79 per h"), and `{change}` in its text is the change.

In the plot, choose the **Measure** tool (the ruler in the toolbar, or `plot.tool =
"measure"`) and drag from one mark to another: each end takes the start or end of a mark (or
a sample) under the pointer (a tick shows which), or with <kbd>Shift</kbd> the time there. A
double-click on a bar measures its length. Without the tool, <kbd>m</kbd> with the pointer at
one end and <kbd>m</kbd> again at the other measures too, <kbd>M</kbd> measures the bar under
the pointer, and <kbd>&gt;</kbd> <kbd>&lt;</kbd> move the newest measure's second end to the
next or previous edge in its lane.

Hover a measure's time for both ends' times and the time between, exactly. Click it to select
it: drag its ends to other edges, press <kbd>Delete</kbd> to remove it, or use its menu.

Measures made in the plot come to Python, and `plot.measured` is a table of them all, of the
type you plotted, a row per measure: its index in `plot.notes`, its text, both ends' times,
the time between as a duration (`b - a`, so negative when `b` is earlier), the events
between, the values of ends that are samples and the change between them, and the mark and
side of each end. In a page without Python (`save_html`), measures
made in it are gone when the page is closed; each one's menu has **Copy as Python**, the line
that makes it again.

## Annotate

Notes on a time range or a time, over one lane or all, and arrows from one mark's edge to
another's. They show in the plot, in pages (`save_html`) and in pictures (`save_image`), and
stay with the plot when it is copied.

```python
plot.annotate("2026-10-12T08:20", "2026-10-12T08:35", "incident", lane="db")
plot.annotate("2026-10-12T09:00", text="deploy")   # a line across all lanes
plot.annotate(atl.start(12), atl.end(12), "slow", lane="db")  # on a mark
plot.connect(12, 40, "retried")                     # row 12's end to row 40's start
plot.connect(atl.start(12), atl.start(40))          # start to start
plot.connect(("requests", 12), ("jobs", 3))         # (layer, row) with several
```

`plot.notes` is one list of them all, [`Annotation`][anytimeline.Annotation]s,
[`Connection`][anytimeline.Connection]s and [`Measure`][anytimeline.Measure]s, in the order
they were made; set it to change them, `[]` to remove them all.

In the plot: <kbd>a</kbd>, then a drag over a time range (or a click at a time), then type
the text and press <kbd>Enter</kbd>. A drag within one lane makes a note on that lane, a
drag over more lanes a note across all. <kbd>c</kbd> with the pointer on a mark, then
<kbd>c</kbd> on another, draws an arrow between them. Both come to Python, into
`plot.notes`; in a page without Python, make them in Python.

## On a phone or tablet

A plot waits for a tap before it takes your fingers, so a finger on it scrolls the page.
After the tap, one finger pans and two pinch to zoom; a tap outside the plot gives the page
its scrolling back.
