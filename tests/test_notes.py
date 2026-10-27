"""Annotations and connections (``Timeline.annotate``, ``Timeline.connect``): notes on a time
range or a time, over a lane or all, and arrows between marks; made in Python or in the plot
(the widget's messages), sent to the browser as ``_notes``, kept in pages, images and copies."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from anytimeline import Annotation, Connection, Timeline
from anytimeline.data import NotFoundError

T0 = np.datetime64("2026-10-01T00:00:00", "ns")
H = np.timedelta64(3600, "s").astype("timedelta64[ns]")


def plot() -> Timeline:
    bars = {
        "task": np.array(["a", "b", "c"], dtype=object),
        "start": T0 + np.array([0, 2, 5]) * H,
        "end": T0 + np.array([2, 5, 8]) * H,
    }
    return Timeline().intervals(bars, lane="task", text="{task}")


def ticks(p: Timeline, hours: float) -> float:
    assert p._base is not None
    return p._base.to_ticks(T0 + np.timedelta64(int(hours * 3600), "s"))


def test_annotations_go_to_the_browser_in_ticks_and_lanes() -> None:
    p = plot().annotate(T0 + H, T0 + 3 * H, "freeze", lane="b").annotate(T0 + 6 * H, text="demo")
    assert p.annotations == [
        Annotation(T0 + H, T0 + 3 * H, "freeze", "b"),
        Annotation(T0 + 6 * H, None, "demo"),
    ]
    freeze, demo = p._notes["bands"]
    assert (freeze["x0"], freeze["x1"]) == (ticks(p, 1), ticks(p, 3))
    assert p._spec["lanes"]["names"][freeze["lane"]] == "b"
    assert freeze["point"] is False
    assert demo["point"] is True
    assert demo["lane"] is None
    p.annotations = []
    assert p._notes == {}


def test_connections_join_marks_end_to_start() -> None:
    p = plot().connect(0, 2, "then")
    assert p.connections == [Connection(("intervals", 0), ("intervals", 2), "then")]
    (arrow,) = p._notes["arrows"]
    assert arrow["a"]["x2"] == ticks(p, 2)  # from a's end
    assert arrow["b"]["x"] == ticks(p, 5)  # to c's start
    assert arrow["text"] == "then"


def test_wrong_annotations_say_what_is_wrong() -> None:
    p = plot()
    with pytest.raises(NotFoundError, match="lane"):
        p.annotate(T0, T0 + H, lane="nope")
    with pytest.raises(ValueError, match="ends before"):
        p.annotate(T0 + H, T0)
    with pytest.raises(TypeError, match="text"):
        p.annotate(T0, text=3)  # ty: ignore[invalid-argument-type]
    with pytest.raises(NotFoundError, match="row"):
        p.connect(0, 99)
    with pytest.raises(NotFoundError):
        p.connect(("nope", 0), 1)
    with pytest.raises(TypeError, match="Annotations"):
        p.annotations = ["x"]  # ty: ignore[invalid-assignment]
    with pytest.raises(TypeError, match="layer, row"):
        Connection(("a", "b"), ("a", 1))  # ty: ignore[invalid-argument-type]
    assert p.annotations == []
    assert p.connections == []


def test_annotations_before_layers_show_once_there_are_layers() -> None:
    p = Timeline().annotate(T0 + H, T0 + 2 * H, "early")
    assert p.annotations
    p.intervals(
        {"start": [T0], "end": [T0 + 3 * H], "lane": np.array(["x"], dtype=object)}, lane="lane"
    )
    assert p._notes["bands"][0]["text"] == "early"


def test_made_in_the_plot_they_come_to_python() -> None:
    p = plot()
    w = p.widget
    w._on_msg(
        w, {"type": "annotate", "x0": ticks(p, 1), "x1": ticks(p, 2), "lane": 1, "text": "x"}, []
    )
    w._on_msg(w, {"type": "annotate", "x0": ticks(p, 4), "x1": None, "lane": None, "text": ""}, [])
    (a, b) = p.annotations
    assert a == Annotation(T0 + H, T0 + 2 * H, "x", "b")
    assert b.end is None
    assert b.lane is None
    # marks by their index in the browser: rows of the table
    ends = {"a": {"layer": "intervals", "index": 0}, "b": {"layer": "intervals", "index": 1}}
    w._on_msg(w, {"type": "connect", **ends}, [])
    assert p.connections == [Connection(("intervals", 0), ("intervals", 1))]
    assert len(w._notes["arrows"]) == 1  # the widget has them too


def test_pages_images_and_copies_keep_them() -> None:
    p = plot().annotate(T0 + H, T0 + 3 * H, "freeze", lane="b").connect(0, 2, "then")
    html = p.to_html()
    assert '"notes":{"bands":[{' in html
    svg = p.to_svg(width=700)
    assert "freeze" in svg
    assert "then" in svg
    q = copy.deepcopy(p)
    assert q.annotations == p.annotations
    assert q._notes == p._notes
