"""Presets: plots set up for a common chart in one call. Each returns a ``Timeline`` with its
layers added, so everything else (more layers, notes, settings) works as usual."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from anytimeline import traces
from anytimeline.parts import Stem
from anytimeline.plot import Timeline
from anytimeline.renamed import renamed
from anytimeline.types import StemShape


def gantt(
    data: Any,
    task: str = "task",
    start: str = "start",
    end: str | None = "end",
    *,
    duration: str | None = None,
    duration_unit: str | None = None,
    depends: str | None = None,
    parent: str | None = None,
    progress: str | None = None,
    color: str | None = None,
    palette: Mapping[Any, str] | Sequence[str] | None = None,
    text: str | None = None,
    tooltip: Sequence[str] | None = None,
    title: str = "",
    height: int = 0,
    today: Any = None,
) -> Timeline:
    """A Gantt chart: a lane per task, in the order of the table, with dependencies as
    arrows, progress as a fill, and milestones (start equal to end) as diamonds. With
    ``parent``, tasks have sub-tasks: each under its parent, by start, and they fold.

    Args:
        data: A table with a row per task.
        task: The column of task names; each task gets its own lane.
        start: The column of start times.
        end: The column of end times; or ``end=None`` with ``duration=``.
        duration: A column of durations, or of numbers in ``duration_unit``.
        duration_unit: What one unit of a numeric duration is (``"d"``, ``"h"``, ...).
        depends: A column with the tasks each task follows: a name, a list of names, or
            names separated by commas.
        parent: A column with the task each task is part of (missing for a top task).
        progress: A column of how far each task is done, 0 to 1.
        color: A column to color the bars by (a phase, a team), or one colour.
        palette: Colours for the categories of ``color``.
        text: Written in each bar where it fits (a column or a template).
        tooltip: Columns shown when hovering a task.
        title: Shown above the chart.
        height: Height in pixels; 0 sizes the chart to its tasks.
        today: A time to mark with a line labelled "today" (e.g. ``datetime.now()``).

    Returns:
        The chart: show it as the last expression of a cell.
    """
    plot = Timeline(title=title, height=height, sort="table")
    plot.intervals(
        data,
        start=start,
        end=end,
        duration=duration,
        duration_unit=duration_unit,
        lane=task,
        id=task,
        parent=parent,
        expand="all",
        depends=depends,
        progress=progress,
        color=color,
        palette=palette,
        text=text,
        tooltip=tooltip,
        overlap="overlay",
        name="tasks",
    )
    if today is not None:
        plot.annotate(today, text="today")
    return plot


@renamed(stem_shape="stems=Stem(shape=...), or stems='curved'", label_width="stems=Stem(width=...)")
def story(
    data: Any,
    text: str,
    time: str = "time",
    *,
    lane: str | None = None,
    color: str | None = None,
    palette: Mapping[Any, str] | Sequence[str] | None = None,
    symbol: str | None = None,
    importance: str | None = None,
    stems: Stem | StemShape | bool = True,
    tooltip: str | Sequence[str] | None = None,
    title: str = "",
    height: int = 420,
    today: Any = None,
) -> Timeline:
    """A story timeline: each event on a line, its text in a box above or below it, joined by
    a line (a stem); the boxes take as many levels as they need so none overlap, at every
    zoom. For a few dozen to a few hundred events whose text matters: an incident, a release
    history, a project's history.

    Args:
        data: A table with a row per event.
        text: The text of each event: a column, or a template such as
            ``"{time:%H:%M}\\n{title}"`` (a line break gives the box two lines).
        time: The column of times.
        lane: A column of lanes: a story line per lane (by default, one).
        color: A column to color the events by (a kind, a severity), or one colour.
        palette: Colours for the categories of ``color``.
        symbol: A column to give the events' marks shapes by.
        importance: A numeric column: when the boxes do not fit, the more important keep
            theirs.
        stems: The boxes' stems: ``True`` (straight: each box over its event), ``"curved"``
            (a box may move aside, its stem bending, which fits more boxes where events
            crowd), or a [`Stem`][anytimeline.Stem] with the widest a box gets.
        tooltip: Columns shown when hovering an event or its box.
        title: Shown above the timeline.
        height: Height in pixels.
        today: A time to mark with a line labelled "today" (e.g. ``datetime.now()``).

    Returns:
        The timeline: show it as the last expression of a cell.
    """
    plot = Timeline(title=title, height=height, lane_names=lane is not None, sort="table")
    plot.events(
        data,
        time=time,
        lane=lane,
        text=text,
        stems=stems,
        color=color,
        palette=palette,
        symbol=symbol,
        importance=importance,
        tooltip=tooltip,
        name="events",
    )
    if today is not None:
        plot.annotate(today, text="today")
    return plot


def compare_traces(
    before: Any,
    after: Any,
    *,
    id: str = "span_id",
    parent: str = "parent_id",
    start: str = "start",
    end: str = "end",
    by: Sequence[str] | None = None,
    threshold: float = 0.1,
    title: str = "",
    height: int = 0,
) -> Timeline:
    """Two traces compared span by span: the second's waterfall, each span coloured by what
    changed (added, removed, slower, faster, the same), the first's span behind it in grey,
    and the change in its tooltip and bar. The spans are matched as
    [`traces.compare`][anytimeline.traces.compare] matches them; times are from each trace's
    start.

    Args:
        before: A table with a row per span of the first trace (e.g. ``read_otlp(...).spans``
            of one trace).
        after: A table with a row per span of the second trace.
        id: The column of span ids.
        parent: The column of parent span ids (missing for a root).
        start: The column of start times.
        end: The column of end times.
        by: The columns that name a span: by default ``service`` and ``name`` (those of
            them in the tables).
        threshold: How much longer (as a fraction: 0.1 is 10%) a span must take to be
            "slower"; as much shorter, "faster".
        title: Shown above the chart.
        height: Height in pixels; 0 sizes the chart to its spans.

    Returns:
        The chart: show it as the last expression of a cell.
    """
    diff = traces.compare(
        before, after, id=id, parent=parent, start=start, end=end, by=by, threshold=threshold
    )
    names = [c for c in ("service", "name") if c in diff] if by is None else list(by)
    plot = Timeline(title=title, height=height)
    # the first trace's spans, behind the second's
    plot.intervals(
        diff,
        start="before_start",
        end="before_end",
        lane="span_id",
        color="#a0a0a0",
        opacity=0.45,
        height=0.9,
        overlap="overlay",
        tooltip=[*names, "before"],
        select=False,
        name="before",
    )
    plot.spans(
        diff,
        lane=names[-1],
        color="change",
        palette={c: traces.CHANGE_COLORS[c] for c in traces.CHANGES},
        text="difference",
        tooltip=[*names, "change", "before", "after", "difference"],
        expand="all",
        critical_path=False,
        height=0.5,
        name="spans",
    )
    return plot
