"""The notes on a plot (``Timeline.notes``): annotations, connections and measures, whose ends
are times or marks' edges (``atl.start``, ``atl.end``); made in Python or in the plot (the
widget's messages), sent to the browser as ``_notes``, kept in pages, images and copies; and
the measured times as a table (``Timeline.measured``)."""

from __future__ import annotations

import copy
import datetime as dt

import numpy as np
import pytest

import anytimeline as atl
from anytimeline import Annotation, Connection, Edge, Measure, Timeline
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


def two_layers() -> Timeline:
    p = plot()
    p.events(
        {"time": T0 + np.array([1, 6]) * H, "task": np.array(["a", "c"], dtype=object)},
        lane="task",
        name="checks",
    )
    return p


def ticks(p: Timeline, hours: float) -> float:
    assert p._base is not None
    return p._base.to_ticks(T0 + np.timedelta64(int(hours * 3600), "s"))


# ---------------------------------------------------------------------- parts


def test_edges_name_a_marks_start_or_end() -> None:
    assert atl.start(3) == Edge(3, "start")
    assert atl.end(3, "db") == Edge(3, "end", "db")
    assert Edge(np.int64(2)).row == 2  # ty: ignore[invalid-argument-type]
    with pytest.raises(TypeError, match="row"):
        Edge(True)
    with pytest.raises(ValueError, match="side"):
        Edge(1, "middle")  # ty: ignore[invalid-argument-type]
    with pytest.raises(TypeError, match="layer"):
        Edge(1, "end", 3)  # ty: ignore[invalid-argument-type]


def test_a_connection_of_marks_runs_end_to_start() -> None:
    c = Connection(("intervals", 0), ("intervals", 2))
    assert (c.a, c.b) == (Edge(0, "end", "intervals"), Edge(2, "start", "intervals"))
    with pytest.raises(TypeError, match="layer, row"):
        Connection(("a", "b"), ("a", 1))  # ty: ignore[invalid-argument-type]


def test_a_measure_has_two_ends() -> None:
    with pytest.raises(TypeError, match="ends"):
        Measure(None, atl.start(1))
    with pytest.raises(TypeError, match="ends"):
        Measure(("intervals", 1), atl.start(1))
    with pytest.raises(TypeError, match="text"):
        Measure(atl.start(0), atl.end(0), text=3)  # ty: ignore[invalid-argument-type]


def test_markers_are_gone() -> None:
    with pytest.raises(AttributeError, match="annotate"):
        atl.Marker  # noqa: B018
    p = plot()
    with pytest.raises(AttributeError, match="annotate"):
        p.marker(T0, "now")
    with pytest.raises(AttributeError, match="notes"):
        p.markers  # noqa: B018
    with pytest.raises(AttributeError, match="notes"):
        p.annotations  # noqa: B018


# ---------------------------------------------------------------------- notes


def test_annotations_go_to_the_browser_in_ticks_and_lanes() -> None:
    p = plot().annotate(T0 + H, T0 + 3 * H, "freeze", lane="b").annotate(T0 + 6 * H, text="demo")
    assert p.notes == [
        Annotation(T0 + H, T0 + 3 * H, "freeze", "b"),
        Annotation(T0 + 6 * H, None, "demo"),
    ]
    freeze, demo = p._notes["bands"]
    assert (freeze["x0"], freeze["x1"]) == (ticks(p, 1), ticks(p, 3))
    assert p._spec["lanes"]["names"][freeze["lane"]] == "b"
    assert freeze["point"] is False
    assert (demo["point"], demo["lane"], demo["id"]) == (True, None, 1)
    p.notes = []
    assert p._notes == {}


def test_an_annotation_may_stay_on_a_mark() -> None:
    p = plot().annotate(atl.start(1), atl.end(1), "build", lane="b")
    (band,) = p._notes["bands"]
    assert (band["x0"], band["x1"]) == (ticks(p, 2), ticks(p, 5))


def test_connections_join_marks_edges() -> None:
    p = plot().connect(0, 2, "then").connect(atl.start(0), atl.start(1))
    assert p.notes[0] == Connection(Edge(0, "end"), Edge(2, "start"), "then")
    then, ss = p._notes["arrows"]
    assert (then["a"]["x"], then["a"]["side"]) == (ticks(p, 2), "end")  # from a's end
    assert (then["b"]["x"], then["b"]["side"]) == (ticks(p, 5), "start")  # to c's start
    assert then["text"] == "then"
    assert (ss["a"]["x"], ss["b"]["x"]) == (ticks(p, 0), ticks(p, 2))


def test_measures_go_to_the_browser_with_the_time_between() -> None:
    p = plot().measure(atl.end(0), atl.start(2)).measure(atl.start(1), atl.end(1), "build")
    gap, own = p._notes["measures"]
    assert (gap["a"]["x"], gap["b"]["x"]) == (ticks(p, 2), ticks(p, 5))
    assert gap["span"] == ticks(p, 5) - ticks(p, 2)
    assert gap["a"]["lane"] == 0
    assert gap["b"]["lane"] == 2
    assert (gap["id"], own["id"]) == (0, 1)
    assert own["text"] == "build"
    # the order: a's start, b's start, a's end (b starts as a ends), c's start, b's end, c's
    # end; nothing between a's end and c's start, and two instants during b
    assert gap["events"] == 0
    assert own["events"] == 2


def test_a_measure_may_end_at_a_time() -> None:
    p = plot().measure(T0 + H, atl.start(2), lane="a")
    (m,) = p._notes["measures"]
    assert (m["a"]["x"], m["a"]["lane"], m["a"]["side"]) == (ticks(p, 1), None, None)
    assert m["lane"] == 0
    assert m["events"] == 2  # b's start, a's end


def test_wrong_notes_say_what_is_wrong() -> None:
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
    with pytest.raises(NotFoundError, match="row"):
        p.measure(atl.start(0), atl.end(99))
    with pytest.raises(NotFoundError, match="lane"):
        p.measure(T0, T0 + H, lane="nope")
    with pytest.raises(TypeError, match="notes"):
        p.notes = ["x"]  # ty: ignore[invalid-assignment]
    assert p.notes == []


def test_an_edge_of_one_of_several_layers_names_it() -> None:
    p = two_layers()
    with pytest.raises(ValueError, match="layer"):
        p.measure(atl.start(0), atl.end(0))
    p.measure(atl.start(0, "checks"), atl.start(1, "checks"))
    (m,) = p._notes["measures"]
    assert (m["a"]["layer"], m["a"]["x"], m["b"]["x"]) == ("checks", ticks(p, 1), ticks(p, 6))


def test_notes_on_marks_gone_are_left_out() -> None:
    p = two_layers().measure(atl.start(0, "checks"), atl.end(1, "intervals"))
    p.notes = [*p.notes, Annotation(T0, text="t0")]
    p.remove("checks")
    assert "measures" not in p._notes
    assert p._notes["bands"][0]["id"] == 1


def test_notes_before_layers_show_once_there_are_layers() -> None:
    p = Timeline().annotate(T0 + H, T0 + 2 * H, "early")
    assert p.notes
    p.intervals(
        {"start": [T0], "end": [T0 + 3 * H], "lane": np.array(["x"], dtype=object)}, lane="lane"
    )
    assert p._notes["bands"][0]["text"] == "early"


def test_notes_at_a_time_need_times() -> None:
    p = Timeline().events({"step": [1, 2]}, time=None, order="step")
    with pytest.raises(ValueError, match="times"):
        p.annotate(1)
    assert p.notes == []


# ---------------------------------------------------------------------- measured


def test_measured_is_a_table_of_the_times() -> None:
    p = plot().measure(atl.end(0), atl.start(2), "gap").measure(T0 + 6 * H, atl.start(1))
    p.annotate(T0, text="not a measure")
    t = p.measured
    assert t["note"].tolist() == [0, 1]
    assert t["text"].tolist() == ["gap", None]
    assert list(t["a"]) == [T0 + 2 * H, T0 + 6 * H]
    assert list(t["time"]) == [3 * H, -4 * H]
    assert t["events"].tolist() == [0, 3]
    assert t["a_row"].tolist() == [0, -1]
    assert t["a_side"].tolist() == ["end", None]
    assert t["b_layer"].tolist() == ["intervals", "intervals"]


def test_measured_is_of_the_type_plotted() -> None:
    pl = pytest.importorskip("polars")
    t0 = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
    hour = dt.timedelta(hours=1)
    bars = pl.DataFrame(
        {"task": ["a", "b"], "start": [t0, t0 + 2 * hour], "end": [t0 + hour, t0 + 4 * hour]}
    )
    p = Timeline(timezone="Europe/Amsterdam").intervals(bars, lane="task")
    p.measure(atl.end(0), atl.start(1))
    t = p.measured
    assert isinstance(t, pl.DataFrame)
    assert t["time"].to_list() == [hour]
    assert t["a"].to_list() == [t0 + hour]
    assert str(t.schema["a"]) == "Datetime(time_unit='ns', time_zone='Europe/Amsterdam')"


# ---------------------------------------------------------------------- the plot


def test_made_in_the_plot_they_come_to_python() -> None:
    p = plot()
    w = p.widget
    w._on_msg(
        w, {"type": "annotate", "x0": ticks(p, 1), "x1": ticks(p, 2), "lane": 1, "text": "x"}, []
    )
    w._on_msg(w, {"type": "annotate", "x0": ticks(p, 4), "x1": None, "lane": None, "text": ""}, [])
    (a, b) = p.notes
    assert a == Annotation(T0 + H, T0 + 2 * H, "x", "b")
    assert b == Annotation(T0 + 4 * H)
    # marks by their index in the browser: rows of the table
    ends = {"a": {"layer": "intervals", "index": 0}, "b": {"layer": "intervals", "index": 1}}
    w._on_msg(w, {"type": "connect", **ends}, [])
    assert p.notes[2] == Connection(Edge(0, "end", "intervals"), Edge(1, "start", "intervals"))
    assert len(w._notes["arrows"]) == 1  # the widget has them too


def test_measures_made_moved_and_removed_in_the_plot() -> None:
    p = plot()
    w = p.widget
    a = {"layer": "intervals", "index": 0, "side": "end"}
    b = {"layer": "intervals", "index": 2, "side": "start"}
    w._on_msg(w, {"type": "measure", "a": a, "b": b, "lane": None}, [])
    times = {"a": {"x": ticks(p, 1)}, "b": {"x": ticks(p, 3)}}
    w._on_msg(w, {"type": "measure", **times, "lane": 1}, [])
    assert p.notes == [
        Measure(Edge(0, "end", "intervals"), Edge(2, "start", "intervals")),
        Measure(T0 + H, T0 + 3 * H, lane="b"),
    ]
    to = {"layer": "intervals", "index": 2, "side": "end"}
    w._on_msg(w, {"type": "note_end", "id": 0, "end": "b", "to": to}, [])
    assert p.notes[0] == Measure(Edge(0, "end", "intervals"), Edge(2, "end", "intervals"))
    assert p._notes["measures"][0]["b"]["x"] == ticks(p, 8)
    w._on_msg(w, {"type": "note_remove", "id": 1}, [])
    assert len(p.notes) == 1
    # an end that is no mark's is left as it was
    gone = {"type": "note_end", "id": 0, "end": "a", "to": {"layer": "x", "index": 0}}
    with pytest.raises(NotFoundError):
        w._on_msg(w, gone, [])
    assert p.notes[0] == Measure(Edge(0, "end", "intervals"), Edge(2, "end", "intervals"))


def test_the_plot_asks_python_for_edges() -> None:
    p = plot()
    edge = p._snap({"lane": 1, "at": ticks(p, 4.9), "within": ticks(p, 0.5), "scale": "time"})
    assert edge["edge"] == {
        "layer": "intervals",
        "index": 1,
        "side": "end",
        "x": ticks(p, 5),
        "r": 4.0,
        "lane": 1,
    }
    assert p._snap({"lane": 1, "at": ticks(p, 3.5), "within": 1.0, "scale": "time"})["edge"] is None
    step = p._snap({"lane": 1, "at": ticks(p, 2), "forward": True, "scale": "time"})
    assert step["edge"]["side"] == "end"
    assert p._snap({"lane": 1, "at": ticks(p, 5), "forward": True, "scale": "time"})["edge"] is None


# ---------------------------------------------------------------------- samples


def with_samples() -> Timeline:
    """``plot()`` and a values layer ``cpu`` in lane b: 10, 40, NaN (a gap), 25 at 2, 3, 3.5
    and 4 h."""
    samples = {
        "time": T0 + np.array([4, 6, 7, 8]) * H / 2,
        "task": np.array(["b"] * 4, dtype=object),
        "cpu": [10.0, 40.0, np.nan, 25.0],
    }
    return plot().values(samples, lane="task", value="cpu", name="cpu")


def test_a_measure_between_samples_has_the_change_in_value() -> None:
    p = with_samples().measure(atl.start(0, "cpu"), atl.end(3, "cpu"))
    (m,) = p._notes["measures"]
    assert (m["a"]["x"], m["b"]["x"]) == (ticks(p, 2), ticks(p, 4))
    assert (m["a"]["value"], m["b"]["value"], m["change"]) == (10.0, 25.0, 15.0)
    assert (m["a"]["lane"], m["b"]["side"]) == (1, "end")
    # on the Order scale a sample is where the browser draws it: at an instant of its time
    # (b's start, place 1), else as far between the instants around it as its time is
    assert m["a"]["r"] == 1.0
    assert m["b"]["r"] == pytest.approx(2 + 2 / 3)  # from a's end (2 h) to c's start (5 h)
    assert m["events"] == 1  # a's end
    # a sample and a bar's edge, or a gap: no change
    p.measure(atl.end(0, "intervals"), atl.start(1, "cpu"))
    p.measure(atl.start(0, "cpu"), atl.start(2, "cpu"))
    assert [n["change"] for n in p._notes["measures"][1:]] == [None, None]
    assert p._notes["measures"][2]["b"]["value"] is None


def test_measured_has_the_values_and_the_change() -> None:
    p = with_samples().measure(atl.start(1, "cpu"), atl.start(3, "cpu"), "{change}")
    p.measure(atl.end(0, "intervals"), atl.start(1, "cpu"))
    t = p.measured
    assert t["a_value"][0] == 40.0
    assert np.isnan(t["a_value"][1])
    assert t["b_value"].tolist() == [25.0, 40.0]
    assert t["change"][0] == -15.0
    assert np.isnan(t["change"][1])
    assert t["a_layer"].tolist() == ["cpu", "intervals"]


def test_samples_are_ends_in_the_plot_and_in_pictures() -> None:
    p = with_samples()
    snap = p._snap({"lane": 1, "at": ticks(p, 3.1), "within": ticks(p, 0.5), "scale": "time"})
    assert snap["edge"] == {
        "layer": "cpu",
        "index": 1,
        "side": "start",
        "x": ticks(p, 3),
        "r": pytest.approx(2 + 1 / 3),
        "lane": 1,
    }
    step = p._snap({"lane": 1, "at": ticks(p, 3), "forward": True, "scale": "time"})
    assert step["edge"]["x"] == ticks(p, 3.5)  # samples of gaps too: Python finds every one
    w = p.widget
    ends = {"a": {"layer": "cpu", "index": 0, "side": "start"}, "b": snap["edge"]}
    w._on_msg(w, {"type": "measure", **ends, "lane": None}, [])
    assert p.notes == [Measure(Edge(0, "start", "cpu"), Edge(1, "start", "cpu"))]
    assert "1 h · Δ +30" in p.to_svg()
    p.notes = [Measure(atl.start(1, "cpu"), atl.start(3, "cpu"), "fell {change} in {time}")]
    assert "fell \u221215 in 1 h" in p.to_svg()


def test_the_measure_tool_is_a_setting() -> None:
    p = plot()
    p.tool = "measure"
    assert p.widget.tool == "measure"


def test_pages_images_and_copies_keep_them() -> None:
    p = plot().annotate(T0 + H, T0 + 3 * H, "freeze", lane="b").connect(0, 2, "then")
    p.measure(atl.end(0), atl.start(2), "gap {time}")
    html = p.to_html()
    assert '"notes":{"bands":[{' in html
    assert '"measures":[{' in html
    assert '"table_rows"' in html  # to copy a measure as Python
    svg = p.to_svg(width=700)
    assert "freeze" in svg
    assert "then" in svg
    assert "gap 3 h" in svg
    q = copy.deepcopy(p)
    assert q.notes == p.notes
    assert q._notes == p._notes
