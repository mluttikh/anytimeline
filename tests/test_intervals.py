import numpy as np
import polars as pl
import pytest

from anytimeline import Marker, Timeline, gantt
from anytimeline.codec import decode


def buffer(plot, ref):
    return decode(ref, plot._buffers[ref["id"]])


def plan():
    return {
        "task": ["Design", "Build", "Test", "Launch", "Docs"],
        "start": np.array(
            ["2026-10-01", "2026-10-06", "2026-10-15", "2026-10-22", "2026-10-08"],
            dtype="datetime64[D]",
        ),
        "end": np.array(
            ["2026-10-06", "2026-10-15", "2026-10-22", "2026-10-22", "2026-10-20"],
            dtype="datetime64[D]",
        ),
        "after": [None, "Design", "Build", ["Test", "Docs"], "Design"],
        "done": [1.0, 0.6, 0.0, 0.0, 0.3],
    }


def test_gantt_lanes_in_table_order_with_milestones_links_and_progress():
    chart = gantt(plan(), depends="after", progress="done", today="2026-10-12")
    spec = chart._spec
    layer = spec["layers"][0]
    assert layer["type"] == "intervals"
    assert spec["lanes"]["names"] == ["Design", "Build", "Test", "Launch", "Docs"]
    assert buffer(chart, layer["kind"]).tolist() == [0, 0, 0, 1, 0]  # Launch: a milestone
    links = buffer(chart, layer["links"]["pairs"]).tolist()
    assert sorted(links) == [[0, 1], [0, 4], [1, 2], [2, 3], [4, 3]]
    assert buffer(chart, layer["progress"]).tolist() == pytest.approx([1.0, 0.6, 0.0, 0.0, 0.3])
    assert spec["markers"] == [{"x": 950400.0, "label": "today", "color": None}]


def test_overlapping_bars_are_packed_into_rows():
    plot = Timeline().intervals(
        {"m": ["a", "a", "a", "b"], "s": [0, 1, 2, 0], "e": [3, 2, 4, 1]},
        start="s",
        end="e",
        lane="m",
    )
    layer = plot._spec["layers"][0]
    assert buffer(plot, layer["row"]).tolist() == [0, 1, 1, 0]
    assert buffer(plot, layer["rows"]).tolist() == [2, 2, 2, 1]
    flat = (
        Timeline()
        .intervals({"s": [0, 1], "e": [3, 2]}, start="s", end="e", overlap="overlay")
        ._spec["layers"][0]
    )
    assert flat["overlap"] == "overlay"


def test_durations_open_ends_and_bad_rows():
    start = np.array(["2026-10-01T08:00", "2026-10-01T09:00"], dtype="datetime64[m]")
    plot = Timeline().intervals(
        {"s": start, "h": [1.5, 2]}, start="s", end=None, duration="h", duration_unit="h"
    )
    assert buffer(plot, plot._spec["layers"][0]["end"]).tolist() == [5400.0, 10800.0]
    with pytest.raises(ValueError, match="duration_unit"):
        Timeline().intervals({"s": start, "h": [1, 2]}, start="s", end=None, duration="h")
    with pytest.raises(ValueError, match=r"end= .* or duration="):
        Timeline().intervals({"s": start}, start="s", end=None)
    end = np.array(["2026-10-01T10:00", "NaT"], dtype="datetime64[m]")
    opened = Timeline().intervals({"s": start, "e": end}, start="s", end="e")
    layer = opened._spec["layers"][0]
    assert buffer(opened, layer["kind"]).tolist() == [0, 2]  # the second has no end: open
    assert buffer(opened, layer["end"]).tolist()[1] == 7200.0  # runs to the last time
    backwards = np.array(["2026-10-01T07:00", "2026-10-01T10:00"], dtype="datetime64[m]")
    with pytest.raises(ValueError, match="end before they start"):
        Timeline().intervals({"s": start, "e": backwards}, start="s", end="e")


def test_dependencies_need_unique_known_ids():
    data = plan()
    data["after"][1] = "Nope"
    with pytest.raises(ValueError, match="not there"):
        gantt(data, depends="after")
    twice = plan()
    twice["task"][1] = "Design"
    with pytest.raises(ValueError, match="unique"):
        gantt(twice, depends="after")
    text = plan()
    text["after"][3] = "Test, Docs"
    links = gantt(text, depends="after")._spec["layers"][0]["links"]["count"]
    assert links == 5


def test_bars_and_events_share_the_time_axis_lanes_and_order():
    tasks = pl.DataFrame({k: v for k, v in plan().items() if k != "after"})
    events = pl.DataFrame(
        {
            "time": np.array(["2026-10-07", "2026-10-16"], dtype="datetime64[ms]"),
            "task": ["Build", "Test"],
        }
    )
    plot = Timeline(sort="table")
    plot.intervals(tasks, lane="task", name="tasks")
    plot.events(events, lane="task", name="notes")
    spec = plot._spec
    assert spec["time"]["unit"] == "s"
    assert spec["sequence"]["count"] == 2 * 5 + 2
    bars, notes = spec["layers"]
    ranks = np.concatenate([buffer(plot, bars["rank"]).ravel(), buffer(plot, notes["rank"])])
    assert sorted(ranks.tolist()) == list(range(12))


def test_selecting_bars_by_click_and_box():
    chart = gantt(plan())
    rec = chart._layers["tasks"]
    chart._pick = {"n": 1, "kind": "click", "layer": "tasks", "index": 2, "mode": "replace"}
    assert chart.selection == {"tasks": [int(rec.rows[rec.perm[2]])]}
    # a box over the first week of October, every lane: the bars that reach into it
    chart._pick = {
        "n": 2, "kind": "box", "x": [0, 6 * 86400], "lanes": [0, 4], "mode": "replace",
        "xscale": "time",
    }  # fmt: skip
    assert chart.selection == {"tasks": [0, 1]}


def test_palette_dict_order_is_the_legend_order():
    data = plan()
    data["phase"] = ["plan", "build", "ship", "ship", "build"]
    chart = gantt(
        data, color="phase", palette={"plan": "#111111", "build": "#222222", "ship": "#333333"}
    )
    items = chart._spec["layers"][0]["color"]["legend"]["items"]
    assert [i["label"] for i in items] == ["plan", "build", "ship"]


def test_markers():
    plot = gantt(plan())
    plot.marker("2026-10-10", "freeze", color="#d62728")
    assert plot._spec["markers"][-1] == {"x": 9 * 86400.0, "label": "freeze", "color": "#d62728"}
    assert plot.markers[-1] == Marker("2026-10-10", "freeze", "#d62728")
    plot.markers = []
    assert plot._spec["markers"] == []
    with pytest.raises(TypeError, match="list of Markers"):
        plot.markers = [("2026-10-10", "freeze")]  # ty: ignore[invalid-assignment]
    with pytest.raises(AttributeError, match="markers = "):
        plot.clear_markers()
    with pytest.raises(ValueError, match="markers need"):
        Timeline().events({"step": [1, 2]}, time=None, order="step").marker(1)
