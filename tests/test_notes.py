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
from anytimeline import Annotation, Connection, Edge, Measure, Timeline, image
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


def test_measures_moved_and_edited_in_the_plot() -> None:
    p = plot().measure(atl.end(0), atl.start(2)).annotate(T0 + H)
    w = p.widget
    w._on_msg(w, {"type": "note_change", "id": 0, "at": "bottom", "level": 1, "lane": 2}, [])
    assert p.notes[0] == Measure(atl.end(0), atl.start(2), lane="c", at="bottom", level=1)
    assert p._notes["measures"][0]["at"] == "bottom"
    w._on_msg(w, {"type": "note_change", "id": 0, "text": "gap {time}"}, [])
    assert p.notes[0].text == "gap {time}"
    w._on_msg(w, {"type": "note_change", "id": 0, "label": "below"}, [])
    assert p._notes["measures"][0]["label"] == "below"
    # back to automatic; empty text is the time again
    back = {"type": "note_change", "id": 0, "at": "auto", "level": None, "lane": None, "text": ""}
    back["label"] = "auto"
    w._on_msg(w, back, [])
    assert p.notes[0] == Measure(atl.end(0), atl.start(2))
    # a value on a values layer
    q = with_samples().measure(atl.start(0, "cpu"), atl.end(3, "cpu"), at=atl.value(30))
    w = q.widget
    w._on_msg(w, {"type": "note_change", "id": 0, "at": {"value": 55.5, "layer": "cpu"}}, [])
    assert q.notes[0] == Measure(atl.start(0, "cpu"), atl.end(3, "cpu"), at=atl.value(55.5, "cpu"))
    # no note there: nothing changes; a place that is none is refused
    w._on_msg(w, {"type": "note_change", "id": 1, "at": "top"}, [])
    with pytest.raises(ValueError, match="at must be one of"):
        w._on_msg(w, {"type": "note_change", "id": 0, "at": "left"}, [])
    assert q.notes[0] == Measure(atl.start(0, "cpu"), atl.end(3, "cpu"), at=atl.value(55.5, "cpu"))
    w = p.widget
    w._on_msg(w, {"type": "note_change", "id": 1, "at": "top"}, [])  # an annotation
    assert p.notes[1] == Annotation(T0 + H)


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


# ---------------------------------------------------------------------- where measures go


def test_a_measure_goes_where_it_is_put() -> None:
    p = plot().measure(atl.end(0), atl.start(2), at="middle", level=1, nudge=-2.5, lane="c")
    (m,) = p._notes["measures"]
    assert (m["at"], m["level"], m["nudge"], m["lane"]) == ("middle", 1, -2.5, 2)
    (m,) = plot().measure(atl.end(0), atl.start(2))._notes["measures"]
    assert (m["at"], m["level"], m["nudge"]) == ("auto", None, 0.0)


def test_where_a_measure_goes_is_checked() -> None:
    with pytest.raises(ValueError, match="at must be one of"):
        Measure(T0, T0 + H, at="above")  # ty: ignore[invalid-argument-type]
    for level in (-1, 1.5, True):
        with pytest.raises(TypeError, match="level is a whole number"):
            Measure(T0, T0 + H, level=level)  # ty: ignore[invalid-argument-type]
    with pytest.raises(TypeError, match="nudge is a number"):
        Measure(T0, T0 + H, nudge=float("nan"))
    with pytest.raises(TypeError):
        Measure(T0, T0 + H, None, None, None, "header")  # ty: ignore[too-many-positional-arguments]
    with pytest.raises(TypeError, match="a number on the layer's scale"):
        atl.value("80")  # ty: ignore[invalid-argument-type]


def test_a_measure_at_a_value_is_on_a_values_layer() -> None:
    p = with_samples().measure(atl.start(0, "cpu"), atl.end(3, "cpu"), at=atl.value(30))
    assert p._notes["measures"][0]["at"] == {"value": 30.0, "layer": "cpu"}
    # two times: the plot's one values layer
    p.measure(T0, T0 + H, at=atl.value(12))
    assert p._notes["measures"][1]["at"] == {"value": 12.0, "layer": "cpu"}
    with pytest.raises(ValueError, match="'intervals' is not one"):
        p.measure(T0, T0 + H, at=atl.value(12, "intervals"))
    with pytest.raises(ValueError, match="needs a values layer"):
        plot().measure(T0, T0 + H, at=atl.value(12))


def test_measured_has_where_they_go() -> None:
    p = plot().measure(atl.end(0), atl.start(2), at="header", level=0)
    p.measure(atl.start(1), atl.end(1), lane="b")
    t = p.measured
    assert t["at"].tolist() == ["header", "auto"]
    assert t["lane"].tolist() == [None, "b"]
    assert t["level"].tolist() == [0, -1]


def picture(p: Timeline, height: int) -> image._Picture:
    assert p._scene is not None
    return image._Picture(p, p._scene, 600, height, None, image.THEMES["light"], None)


def test_pictures_have_the_bands_of_measures_only_when_used() -> None:
    p = plot()
    plain = p.to_svg(width=600, height=300)
    p.measure(atl.end(0), atl.start(2), at="header").measure(atl.end(1), atl.start(2), at="footer")
    pic = picture(p, 300)
    head = image.band_height(1, p.font_size)
    assert (pic.f.head_h, pic.f.foot_h) == (head, head)
    assert pic.f.plot[1] == pic.f.axis_h + head  # the lanes start under the header
    assert p.to_svg(width=600, height=300) != plain
    # two times and no lane: the header; a lane too small for its measures: the rest there
    q = plot().measure(T0, T0 + H)
    assert picture(q, 300).f.head_h == head
    r = plot()
    for k in range(4):
        r.measure(atl.start(1), atl.end(1), f"m{k}")
    pic = picture(r, 160)
    assert pic.f.head_h > 0
    assert pic.f.lane_h < 160 / 3


def test_a_measures_text_has_fields_with_formats_and_its_ends_columns() -> None:
    p = plot().measure(atl.end(0), atl.start(2), "{b.task} after {a.task}: {time:min}")
    p.measure(atl.start(0), atl.end(0), "from {a.start:%H:%M}")
    p.measure(T0, T0 + H, "{a.task} {time:s.2}")  # a time has no row
    texts = [m["text"] for m in p._notes["measures"]]
    assert texts == ["c after a: {time:min}", "from 00:00", "– {time:s.2}"]
    assert p._notes["measures"][0]["raw"] == "{b.task} after {a.task}: {time:min}"
    assert "raw" not in plot().measure(T0, T0 + H, "{time}")._notes["measures"][0]
    # filled in a picture as in the browser
    svg = p.to_svg(width=600, height=300)
    assert "c after a: 180 min" in svg
    assert "– 3600 s" in svg
    with pytest.raises(LookupError):
        plot().measure(atl.end(0), atl.start(2), "{a.nope}")
    with pytest.raises(ValueError, match="a time's format"):
        Measure(T0, T0 + H, "{time:hours}")
    with pytest.raises(ValueError, match="a number's format"):
        Measure(T0, T0 + H, "{change:x}")
    with pytest.raises(ValueError, match="takes no format"):
        Measure(T0, T0 + H, "{a:%H}")


def test_a_measures_label_ends_and_extension_lines() -> None:
    p = plot().measure(atl.end(0), atl.start(2), label="above", ends="ticks", extend="lanes")
    m = p._notes["measures"][0]
    assert (m["label"], m["ends"], m["extend"]) == ("above", "ticks", "lanes")
    for key, bad in (("label", "left"), ("ends", "arrow"), ("extend", "all")):
        with pytest.raises(ValueError, match=f"Measure's {key} must be one of"):
            Measure(T0, T0 + H, **{key: bad})  # ty: ignore[invalid-argument-type]
    # in a picture: the label above its line, ticks for heads, lines through every lane
    pic = picture(p, 300)
    [d] = pic._layout_measures(p._notes["measures"])[0]
    assert d["ly"] == pytest.approx(d["y"] - (p.font_size + 4) - 1)
    svg = p.to_svg(width=600, height=300)
    assert "<path" in svg  # drawn without error
    hover = plot().measure(atl.end(0), atl.start(2), label="hover")
    [d] = picture(hover, 300)._layout_measures(hover._notes["measures"])[0]
    assert d["lx"] is None


def test_measures_take_defaults() -> None:
    with atl.defaults(measure={"ends": "dots", "at": "middle", "text": "{time:min}"}):
        p = plot().measure(atl.end(0), atl.start(2)).measure(T0, T0 + H, "own", ends="none")
    assert p.notes == [
        Measure(atl.end(0), atl.start(2), "{time:min}", at="middle", ends="dots"),
        Measure(T0, T0 + H, "own", at="middle", ends="none"),
    ]
    with pytest.raises(TypeError, match="cannot have a default"):
        atl.set_defaults(measure={"a": T0})
    with pytest.raises(ValueError, match="ends must be one of"):
        atl.set_defaults(measure={"ends": "arrow"})
    with pytest.raises(ValueError, match="at must be one of"):
        atl.set_defaults(measure={"at": "side"})
    assert atl.get_defaults() == {}
