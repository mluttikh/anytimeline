# Draw a Gantt chart

`gantt()` draws a table with a row per task: a lane per task in the order of the table, a bar
from each task's start to its end, dependencies as arrows, progress as a fill, and milestones
(a start equal to the end) as diamonds.

```python exec="on" source="above" session="gantt" html="true"
import numpy as np
from anytimeline import gantt

plan = {
    "task": ["Requirements", "Design", "Prototype", "Review", "Build backend",
             "Build frontend", "Write docs", "Test", "Release"],
    "start": np.array(["2026-09-01", "2026-09-08", "2026-09-15", "2026-09-29", "2026-09-30",
                       "2026-10-02", "2026-10-05", "2026-10-20", "2026-11-02"],
                      dtype="datetime64[D]"),
    "days": [7, 9, 14, 0, 18, 16, 20, 13, 0],
    "after": [None, "Requirements", "Design", "Prototype", "Review", "Review", "Design",
              "Build backend, Build frontend", "Test, Write docs"],
    "done": [1.0, 1.0, 1.0, 1.0, 0.6, 0.4, 0.3, 0.0, 0.0],
    "phase": ["plan", "plan", "plan", "plan", "build", "build", "build", "ship", "ship"],
}
chart = gantt(
    plan, end=None, duration="days", duration_unit="d",
    depends="after", progress="done", color="phase", text="{task}",
    palette={"plan": "#4c78a8", "build": "#f58518", "ship": "#54a24b"},
    title="Project plan", today="2026-10-12",
)
chart
print(chart._embed_html())  # markdown-exec: hide
```

## The columns

| Argument | The column | Default |
| --- | --- | --- |
| `task=` | the task's name: its lane, and how other tasks refer to it | `"task"` |
| `start=` | when it starts | `"start"` |
| `end=` | when it ends; or `end=None` with `duration=` | `"end"` |
| `duration=`, `duration_unit=` | how long it takes: durations, or numbers in `"d"`, `"h"`, `"min"`, ... | — |
| `depends=` | the tasks it follows: a name, a list of names, or names separated by commas | — |
| `parent=` | the task it is part of (missing for a top task) | — |
| `progress=` | how far it is done, 0 to 1 | — |
| `color=` | a category to color it by (a phase, a team), or one color | the theme's color |

`palette=` given as a dict sets the colors **and** the order of the legend. `text=` writes in
each bar where it fits (here the task's name again). `today=` draws a line labelled "today";
give it `datetime.now()` for a live plan.

## Read it

- Hover over a task for its start, end, duration and progress.
- Arrows run from the end of a task to the start of each task that follows it; when the next
  task starts before this one ends, the arrow goes around.
- Switch to **Order** in the toolbar: every start and end gets the same width, so short tasks
  and long waits take the same room and the sequence of steps stands out.

## Sub-tasks

`parent=` names the task each task is part of: sub-tasks go under their task, which you can
fold (click its name; double-click to zoom to it).

```python exec="on" source="above" session="gantt" html="true"
work = {
    "task": ["Backend", "API", "Database", "Frontend", "Pages", "Styles", "Release"],
    "part of": [None, "Backend", "Backend", None, "Frontend", "Frontend", None],
    "start": np.array(["2026-10-01", "2026-10-01", "2026-10-06", "2026-10-05", "2026-10-05",
                       "2026-10-12", "2026-10-23"], dtype="datetime64[D]"),
    "end": np.array(["2026-10-20", "2026-10-14", "2026-10-20", "2026-10-22", "2026-10-16",
                     "2026-10-22", "2026-10-23"], dtype="datetime64[D]"),
    "after": [None, None, None, None, None, None, "Backend, Frontend"],
}
chart = gantt(work, parent="part of", depends="after", color="#4c78a8", title="Work breakdown")
print(chart._embed_html())
```

## More than `gantt()` gives

`gantt()` returns a [`Timeline`][anytimeline.Timeline], so everything else works on it:

```python
chart.marker("2026-10-30", "code freeze", color="#d62728")  # more lines
chart.events(meetings, time="time", lane="task", symbol="x")  # events on the tasks' lanes
chart.selection  # selected tasks, as rows
```

For bars on lanes that are not tasks (machines, people, services), with several bars per lane,
see [schedules and spans](intervals.md).
