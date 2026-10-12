# Tell a story with a timeline

For a few dozen events whose **text** matters (an incident, a release history, a project's
history), a story timeline puts each event on a line and its text in a box above or below
it, joined by a line (a stem) in the event's colour. The boxes take as many levels as they
need so none overlap, and **no stem ever passes behind a box**, so every box is clearly
joined to its event. Where events crowd together and their boxes do not fit at this zoom, a
badge counts them ("+4"): click it to zoom in on them. Here the timeline of an incident, as a
postmortem would list it:

```python exec="on" source="above" session="story" html="true"
from anytimeline import story
from anytimeline.synthetic import incident

kinds = {"deploy": "#4c78a8", "alert": "#e45756", "page": "#f58518",
         "action": "#54a24b", "status": "#9d755d"}
plot = story(incident(), "{time:%H:%M}\n{title}", color="kind", palette=kinds,
             importance="importance", tooltip=["team"], title="Checkout incident")
print(plot._embed_html())
```

- `text=` is a column or a template; a line break makes a box of two lines, the first (here
  the time) smaller. `{time:%H:%M}` formats a datetime column.
- `importance=` decides who keeps a box when they do not all fit: the most important are
  placed first. The others are counted in badges; zoom in (or click a badge) for room.
- Long titles wrap onto two lines, then end in "…": a box is at most 16 × the text size
  wide (`label_width=` sets it in pixels; `0` for no limit). The full text is in the tooltip.
- Hover a box for its event's details; with the **Select** tool, click a box to select its
  event.
- Switch to **Order** in the toolbar: every event gets the same width, which gives the boxes
  more room where much happened in little time.

## Straight or curved stems

By default each box sits over its event and its stem is straight. With
`stem_shape="curved"`, a box may move aside when that gives it room, and its stem bends
near the line: more boxes fit where events crowd, at the cost of some bends.

```python
story(incident(), "{time:%H:%M}\n{title}", color="kind", stem_shape="curved")
```

## A story line per lane

`lane=` gives each team, service or person a line of its own:

```python exec="on" source="above" session="story" html="true"
plot = story(incident(), "{time:%H:%M}\n{title}", lane="team", color="kind", palette=kinds,
             importance="importance", title="Checkout incident by team", height=640)
print(plot._embed_html())
```

## In any plot

`story()` is a [`Timeline`][anytimeline.Timeline] with one events layer that has
`labels="stems"`. Any events layer can have it, next to other layers: a story of deploys and
incidents above the CPU of the services, say.

```python
plot.events(changes, time="time", lane="service", text="title", labels="stems")
```

Story lines need room: a lane gets as many levels of boxes as its height holds, and a lane
too small for one level shows its text beside the events instead.
