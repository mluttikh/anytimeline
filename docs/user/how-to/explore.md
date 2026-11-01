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

### A measure's text and look

Its text may have fields, each with a format after a colon:

```python
plot.measure(atl.end(3), atl.start(4), "{b.service} waited {time:ms}")
plot.measure(atl.start(8, "cpu"), atl.start(20, "cpu"), "{change:+.1f} % ({rate})")
plot.measure(atl.start(0), atl.end(9), "{a.start:%H:%M} to {b.end:%H:%M}: {time:min.2}")
```

| Field | Is | Formats |
| --- | --- | --- |
| `{time}` | the time between | a unit (`ns`, `us`, `ms`, `s`, `min`, `h`, `d`) and digits: `{time:ms}`, `{time:.2}`, `{time:s.4}` |
| `{events}` | the events between in the order | a number's: `{events:,}` |
| `{change}` | the change in value between two samples | a number's: `{change:+.2f}`, `{change:.1%}` |
| `{rate}` | that change per unit of time ("+8.2 per h") | a number's, for the number |
| `{a}`, `{b}` | the ends' times, exactly | none |
| `{a.col}`, `{b.col}` | a column of an end's row (an end that is a mark) | Python's: `{a.start:%H:%M}`, `{b.bytes:,}` |

A number's format is as Python's: a sign (`+`, or a space), `,` for thousands, the digits
after the point, and `f` (fixed), `e` (exponent), `%` (percent), or `g` or nothing (that many
digits, as the plot writes numbers). A field's format that is none of these raises when the
measure is made.

`label=`, `ends=` and `extend=` set its look:

| | Options |
| --- | --- |
| `label=` | `"auto"` (on the line where it fits, else beside it where there is room, else when hovered), `"on"`, `"above"`, `"below"`, `"start"` (before the earlier end), `"end"` (after the later end), `"hover"` |
| `ends=` | `"arrows"`, `"ticks"` (oblique strokes, as in a drawing), `"dots"`, `"none"` |
| `extend=` | `"mark"` (from each end's mark to the line), `"lanes"` (through every lane, like cursors), `"none"` |

A label above or below its line stays in sight: the header and footer bands make room for
it, and in the top or bottom lane, where it would be cut off at the plot's edge, it goes on
the other side of its line.

```python
plot.measure(atl.end(3), atl.start(4), label="above", ends="ticks", extend="lanes")
atl.set_defaults(measure={"ends": "ticks", "label": "above"})  # every measure from now on
```

In the plot, choose the **Measure** tool (the ruler in the toolbar, or `plot.tool =
"measure"`) and drag from one mark to another: each end takes the start or end of a mark (or
a sample) under the pointer (a tick shows which), or with <kbd>Shift</kbd> the time there. A
double-click on a bar measures its length. Without the tool, <kbd>m</kbd> with the pointer at
one end and <kbd>m</kbd> again at the other measures too, <kbd>M</kbd> measures the bar under
the pointer, and <kbd>&gt;</kbd> <kbd>&lt;</kbd> move the newest measure's second end to the
next or previous edge in its lane.

Hover a measure's time for both ends' times and the time between, exactly. Click it to select
it: drag its ends to other edges, press <kbd>Delete</kbd> to remove it, or use its menu.

### Where a measure goes

A measure's line goes in a lane: the one you give (`lane=`), else the upper of its ends'
lanes. `at=` says where in it, or in a band above or below the lanes:

```python
plot.measure(atl.end(12), atl.start(40))                     # "auto": the top of the lane
plot.measure(atl.end(12), atl.start(40), at="middle")        # through the marks, in the gap
plot.measure(atl.end(3), atl.start(9), lane="db", at="bottom")
plot.measure(atl.end(3), atl.start(9), at="between")         # on the border under the lane
plot.measure(t0, t1, "freeze", at="header")                   # a band above the lanes
plot.measure(atl.start(8, "cpu"), atl.start(20, "cpu"), at=atl.value(80))  # at 80 on cpu's scale
```

| `at=` | The line |
| --- | --- |
| `"auto"` | at the top of the lane; levels the lane has no room for continue in the header |
| `"top"`, `"bottom"` | at the top or bottom of the lane, stacking down or up from there |
| `"middle"` | through the middle of the lane, at the height of the marks |
| `"between"` | on the border under the lane |
| `"header"`, `"footer"` | in a band above or below the lanes; a band takes room only when used |
| `atl.value(v)` | at value `v` on a values layer's scale |

Measures that overlap in time stack, each on the first free level. `level=` keeps one on a
level (0: nearest the edge it stacks from), and the others go around it. The levels are laid
out in time, so zooming and panning never move a measure: a label that has no room beside
its line is shown when the measure is hovered or selected. A measure of two times, in no
lane, goes to the header. `nudge=` moves a line a few pixels after all that, for a picture.

### Move a measure in the plot

Click a measure's label to select it. Then:

- drag its line up or down: to another level, to the top, middle or bottom of its lane, to the
  border under it, into another lane, or above or below the lanes into the header or footer
  band (a measure at a value moves to the value under the pointer);
- or pick a place in its menu (**Place**: Top, Middle, Bottom, Between, Header, Footer), and
  where its text goes (**Label**: Auto, On, Above, Below, Start, End, Hover);
- **↑** and **↓** move it a level, **0** (or the menu's **Automatic**) puts it back where the
  layout would, and **Enter** (or **Edit text…**) edits its text (empty: the time);
- drag one of its ends to another edge, and **Delete** removes it.

Each change goes to Python, which replaces the measure in `plot.notes` with the same
`at=`, `lane=`, `level=` or text you would write; a measure dragged to a place keeps its
level there. In a page without Python the page changes its own measures. **Show measures** in
the Display panel hides them all, and the bands they take, without removing any.

Measures made in the plot come to Python, and `plot.measured` is a table of them all, of the
type you plotted, a row per measure: its index in `plot.notes`, its text, both ends' times,
the time between as a duration (`b - a`, so negative when `b` is earlier), the events
between, the values of ends that are samples and the change between them, and the mark and
side of each end. In a page without Python (`save_html`), measures
made in it are gone when the page is closed; each one's menu has **Copy as Python**, the line
that makes it again.

### Many measures at once

A rule makes many measures with one call. It is one note in `plot.notes`, worked out again
whenever the data changes (`plot.update(..., data=...)`), and `plot.measured` has a row for
each measure it makes (`part`: its place among them).

```python
plot.measure_each("jobs", limit="2h")                  # every bar's length; red when over
plot.measure_each("jobs", rows=plot.selection["jobs"])  # those selected
plot.measure_gaps("jobs")                              # the idle time on each machine
plot.measure_gaps("events", by="request", min="50ms")  # waits within each request
plot.measure_chain([atl.start(1), atl.end(1), atl.end(4), atl.end(9)])  # A to B to C
plot.measure_from(atl.start(0), [atl.end(3), atl.end(7), atl.end(12)])  # all from one origin
```

```python exec="on" source="above" session="explore-rules" html="true"
import numpy as np
import anytimeline as atl
from anytimeline import Timeline

t0 = np.datetime64("2026-10-12T08:00", "m")
work = {
    "job": ["j1", "j2", "j3", "j4", "j5", "j6", "j7", "j8", "j9"],
    "machine": ["press 1"] * 3 + ["press 2"] * 3 + ["press 3"] * 3,
    "start": t0 + np.array([0, 70, 150, 10, 70, 150, 20, 90, 170]).astype("timedelta64[m]"),
    "minutes": [50, 45, 40, 35, 55, 45, 50, 40, 30],
}
plot = Timeline(title="Measures by rule", height=420)
plot.intervals(work, end=None, duration="minutes", duration_unit="min", lane="machine",
               text="{job}")
plot.measure_gaps(at="middle", text="{time:min}")
plot.measure_each(rows=[3, 4, 5], at="bottom", limit="50min", text="{a.job} {time:min}")
plot.measure_chain([atl.start(0), atl.end(0), atl.end(1), atl.end(2)], at="header",
                   ends="ticks")
plot.measure_from(atl.start(6), [atl.end(6), atl.end(7), atl.end(8)], at="footer",
                  text="{time:min}")
print(plot._embed_html())
```

| Rule | Measures |
| --- | --- |
| [`measure_each`][anytimeline.Timeline.measure_each] | each bar of an intervals layer, start to end (`rows=`: only those rows); milestones are left out |
| [`measure_gaps`][anytimeline.Timeline.measure_gaps] | each gap between marks, in each lane or each group of `by=`: from the end of the marks so far to the next start, so marks that overlap have none; `min=`, `max=` leave out shorter or longer gaps |
| [`measure_chain`][anytimeline.Timeline.measure_chain] | from each end to the next, on one level (continued dimensions) |
| [`measure_from`][anytimeline.Timeline.measure_from] | from one origin to each end, a level apart, the shortest nearest the marks (baseline dimensions) |

Each takes `text=`, `at=`, `level=`, `label=`, `ends=`, `extend=`, `color=` and `limit=` as
`measure` does, for each of its measures, and the defaults set for `measure`. A chain's and a
baseline's measures share a row (`lane=`, else the upper of their ends' lanes) and move as
one; a rule of marks' measures stay in their marks' lanes. A rule makes at most 20,000
measures: narrow it with `rows=`, `min=` or `by=`.

`limit=`, on any measure, is a budget: a measure longer than it is drawn red (the theme's
"over" colour, `--atl-over`), and `plot.measured` says so in `over`. Durations are text
(`"200ms"`, `"1.5 h"`) or a timedelta; on a plot of numbers, numbers.

In the plot, a click selects one of a rule's measures; its menu changes the place, label or
text of them all, **↑** and **↓** move them all a level, and **Remove the rule** (or
**Delete**) removes the rule. Their ends follow the marks, so they are not dragged.

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
