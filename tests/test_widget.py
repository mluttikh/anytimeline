import copy
import json
import pickle
import re

import numpy as np
import pytest

from anytimeline import Timeline, View
from anytimeline.synthetic import service_log
from anytimeline.widget import CHUNK_BYTES, TimelineWidget


def plot_of_log():
    log = service_log(30)
    plot = Timeline().events(log, lane="service", order="seq", tooltip=["request", "bytes"])
    return log, plot


def sent_by(plot, monkeypatch):
    """The messages the plot's widget sends: (content, buffers)."""
    sent = []
    monkeypatch.setattr(
        plot.widget, "send", lambda content, buffers=None: sent.append((content, buffers))
    )
    return sent


def payload_of(page: str) -> dict:
    data = re.search(r'<script type="application/json">(.*?)</script>', page, re.DOTALL)
    assert data is not None
    return json.loads(data.group(1))


def test_a_plot_is_no_widget_until_it_is_shown():
    _, plot = plot_of_log()
    assert plot._widget is None
    plot.to_html()
    plot.display = "html"
    plot._repr_mimebundle_()
    assert plot._widget is None  # pages need none
    plot.display = "widget"
    bundle = plot._repr_mimebundle_()
    data = bundle[0] if isinstance(bundle, tuple) else bundle
    assert "application/vnd.jupyter.widget-view+json" in data
    assert isinstance(plot.widget, TimelineWidget)
    assert plot.widget is plot.widget
    assert repr(plot.widget).startswith("TimelineWidget of Timeline(events: ")


def test_settings_reach_the_widget_and_come_back():
    _, plot = plot_of_log()
    plot.tool = "zoom"
    widget = plot.widget
    assert widget.tool == "zoom"  # made with the plot's settings
    plot.font_size = 16
    assert widget.font_size == 16
    widget.tool = "select"  # the browser changed it
    assert plot.tool == "select"
    seen = []
    widget.observe(lambda change: seen.append(change["new"]), "tool")
    plot.tool = "pan"
    assert seen == ["pan"]
    # a value the plot refuses: the widget gets the plot's back
    with pytest.raises(ValueError, match="font_size"):
        widget.font_size = 40
    assert (plot.font_size, widget.font_size) == (16, 16)
    # not synced: the display, the layout settings
    assert not widget.has_trait("display")
    assert not widget.has_trait("sort")


def test_no_bulk_data_in_synced_state():
    _, plot = plot_of_log()
    state = plot.widget.get_state()
    assert len(str(state["_spec"])) < 20_000
    assert all(not isinstance(v, bytes | memoryview) for v in state["_spec"].values())


def test_buffers_are_served_in_chunks(monkeypatch):
    _, plot = plot_of_log()
    sent = sent_by(plot, monkeypatch)
    some = next(iter(plot._buffers))
    plot.widget._on_msg(plot.widget, {"type": "need", "ids": [some, "nope"]}, [])
    assert sent[0][0]["type"] == "put"
    assert sent[0][0]["id"] == some
    assert bytes(sent[0][1][0]) == plot._buffers[some]
    assert sent[-1][0] == {"type": "missing", "id": "nope"}
    big = b"x" * (CHUNK_BYTES * 2 + 5)
    plot._buffers["big"] = big
    sent.clear()
    plot.widget._send_buffer("big")
    assert [c["chunk"] for c, _ in sent] == [0, 1, 2]
    assert b"".join(bytes(b[0]) for _, b in sent) == big


def test_in_marimo_large_buffers_go_as_files(monkeypatch):
    """A buffer of FILE_BYTES or more goes as a marimo virtual file (here a fake one): one put
    with its url; the file is dropped once fetched, and a failed fetch asks for messages."""
    from anytimeline import widget as w

    made, dropped = [], []

    class File:
        def __init__(self, data):
            self.filename = f"f{len(made)}.bin"
            self.url = f"./@file/{len(data)}-{self.filename}"
            made.append(self)

    monkeypatch.setattr(w, "_marimo_file", File)
    monkeypatch.setattr(w, "_remove_marimo_file", dropped.append)
    _, plot = plot_of_log()
    sent = sent_by(plot, monkeypatch)
    plot._buffers["big"] = b"x" * w.FILE_BYTES
    plot._buffers["small"] = b"x" * 10
    plot.widget._on_msg(plot.widget, {"type": "need", "ids": ["big", "small"]}, [])
    (put, parts), (small, _) = sent
    assert put["url"] == "./@file/65536-f0.bin"
    assert put["file"] == "f0.bin"
    assert put["byteLength"] == w.FILE_BYTES
    assert not parts
    assert "url" not in small
    plot.widget._on_msg(plot.widget, {"type": "fetched", "file": "f0.bin"}, [])
    assert dropped == made
    # a fetch failed: messages from now on
    sent.clear()
    plot.widget._on_msg(plot.widget, {"type": "need", "ids": ["big"], "files": False}, [])
    assert "url" not in sent[0][0]
    assert bytes(sent[0][1][0]) == plot._buffers["big"]


def test_outside_marimo_buffers_go_as_messages():
    from anytimeline import widget as w

    assert w._marimo_file(b"x" * w.FILE_BYTES) is None


def test_tooltip_answers_with_the_row(monkeypatch):
    log, plot = plot_of_log()
    sent = sent_by(plot, monkeypatch)
    plot.widget._on_msg(
        plot.widget, {"type": "tooltip", "request": 7, "layer": "events", "index": 0}, []
    )
    rec = plot._layers["events"]
    row = int(rec.rows[rec.perm[0]])
    assert sent[0][0]["request"] == 7
    assert sent[0][0]["rows"] == [
        ["request", log["request"][row]],
        ["bytes", str(log["bytes"][row])],
    ]


def test_clicks_and_boxes_select_table_rows():
    log, plot = plot_of_log()
    rec = plot._layers["events"]
    seen = []
    plot.on_select(seen.append)
    plot._pick = {"n": 1, "kind": "click", "layer": "events", "index": 3, "mode": "replace"}
    row = int(rec.rows[rec.perm[3]])
    assert plot.selection == {"events": [row]}
    assert np.frombuffer(plot._marks["events"], "<i4").tolist() == [3]
    plot._pick = {"n": 2, "kind": "click", "layer": "events", "index": 3, "mode": "toggle"}
    assert plot.selection == {}
    plot._pick = {
        "n": 3,
        "kind": "box",
        "x": [-1, 1e18],
        "lanes": [0, 0],
        "mode": "replace",
        "xscale": "time",
    }
    lane0 = plot._spec["lanes"]["names"][0]
    assert plot.selection["events"] == sorted(np.flatnonzero(log["service"] == lane0).tolist())
    plot._pick = {"n": 4, "kind": "clear"}
    assert plot.selection == {}
    assert len(seen) == 4


def test_a_click_from_the_browser_selects_through_the_widget():
    _, plot = plot_of_log()
    plot.widget._pick = {"n": 1, "kind": "click", "layer": "events", "index": 0, "mode": "replace"}
    assert plot.selection
    assert plot.widget.selection == plot.selection


def test_selection_from_python_marks_the_events():
    _, plot = plot_of_log()
    plot.selection = {"events": [5, 0, 5]}
    assert plot.selection == {"events": [0, 5]}
    marks = np.frombuffer(plot._marks["events"], "<i4")
    rec = plot._layers["events"]
    assert sorted(int(rec.rows[rec.perm[i]]) for i in marks) == [0, 5]
    with pytest.raises(ValueError, match="no layer"):
        plot.selection = {"nope": [1]}
    with pytest.raises(TypeError, match="dict"):
        plot.selection = [1, 2]
    with pytest.raises(TypeError, match="list of rows"):
        plot.selection = {"events": 3}


def test_the_view_is_read_and_set():
    log, plot = plot_of_log()
    assert plot.view == View()
    plot.view = View(log["time"][2], log["time"][10], lanes=["api"])
    t0, t1 = plot._zoom["range"]
    assert t1 > t0
    assert plot._zoom["lanes"] == "api"
    assert plot.view == View(log["time"][2], log["time"][10], ("api",))  # before it is shown
    plot.widget._on_msg(
        plot.widget, {"type": "view", "range": [t0, t1], "lanes": ["api", "cache"]}, []
    )
    shown = plot.view
    assert (shown.start, shown.end) == (log["time"][2], log["time"][10])
    assert shown.lanes == ("api", "cache")
    other = Timeline().events(log, lane="service")
    other.view = plot.view  # the same view in another plot
    assert other._zoom["range"] == other._zoom["range"]
    plot.view = None  # the whole timeline, from the top
    assert plot._zoom["range"] is None
    assert plot._zoom["lanes"] is None
    with pytest.raises(ValueError, match="no lane 'nope'"):
        plot.view = View(lanes=["nope"])
    with pytest.raises(ValueError, match="after its start"):
        plot.view = View(log["time"][10], log["time"][2])
    with pytest.raises(TypeError, match="View"):
        plot.view = (log["time"][2], log["time"][10])


def test_zoom_to_keeps_the_lanes():
    log, plot = plot_of_log()
    plot.zoom_to(log["time"][2], log["time"][10])
    assert "lanes" not in plot._zoom  # the browser keeps its lanes in sight
    with pytest.raises(ValueError, match="after start"):
        plot.zoom_to(log["time"][10], log["time"][2])


def test_dev_perf_and_benchmark(monkeypatch):
    _, plot = plot_of_log()
    plot.widget._on_msg(plot.widget, {"type": "perf", "update": {"renderer": "webgl2"}}, [])
    assert plot.dev.perf == {"renderer": "webgl2"}
    sent = sent_by(plot, monkeypatch)
    plot.dev.benchmark(30)
    assert sent == [({"type": "benchmark", "frames": 30}, None)]


def test_removed_names_say_what_replaced_them():
    _, plot = plot_of_log()
    with pytest.raises(AttributeError, match=r"plot.view"):
        plot.range  # noqa: B018
    with pytest.raises(AttributeError, match=r"plot.dev.perf"):
        plot.perf  # noqa: B018
    with pytest.raises(AttributeError, match=r"plot.widget.observe"):
        plot.observe(print, "tool")
    with pytest.raises(ValueError, match="'order'"):
        Timeline(xscale="sequence")  # ty: ignore[invalid-argument-type]
    with pytest.raises(ValueError, match="selection_mode=None"):
        plot.selection_mode = "none"
    plot.selection_mode = None
    assert plot.widget.selection_mode is None


def test_settings_are_checked():
    with pytest.raises(ValueError, match="sort"):
        Timeline(sort="size")  # ty: ignore[invalid-argument-type]
    with pytest.raises(ValueError, match="tool"):
        Timeline(tool="lasso")  # ty: ignore[invalid-argument-type]
    with pytest.raises(TypeError, match="height"):
        Timeline(height="tall")  # ty: ignore[invalid-argument-type]
    with pytest.raises(ValueError, match="height"):
        Timeline(height=-1)
    with pytest.raises(TypeError, match="font_size"):
        Timeline(font_size=12.5)  # ty: ignore[invalid-argument-type]
    with pytest.raises(ValueError, match="mark_scale"):
        Timeline(mark_scale=5)
    with pytest.raises(TypeError, match="dodge"):
        Timeline(dodge="yes")  # ty: ignore[invalid-argument-type]


def test_layout_settings_lay_the_plot_out_again():
    log, plot = plot_of_log()
    plot.sort = "count"
    counts = {s: int((log["service"] == s).sum()) for s in set(log["service"])}
    names = plot._spec["lanes"]["names"]
    assert [counts[n] for n in names] == sorted(counts.values(), reverse=True)
    plot.lane_order = ["db"]
    assert plot._spec["lanes"]["names"][0] == "db"
    plot.lane_names = False
    assert plot._spec["lanes"]["show_names"] is False
    plot.timezone = "Europe/Amsterdam"
    assert plot._spec["time"]["timezone"] == "Europe/Amsterdam"
    # a setting the layers do not fit keeps the plot as it was
    times = Timeline().events({"step": [1, 2]}, time=None, order="step")
    with pytest.raises(ValueError, match="times"):
        times.annotate(1)
    assert times.notes == []


def test_copies_and_pickles_are_plots_of_their_own(monkeypatch):
    log, plot = plot_of_log()
    other = Timeline().events(log, lane="service")
    plot.link(other)
    plot.selection = {"events": [1, 2]}
    plot.tool = "select"
    seen = []
    plot.on_select(seen.append)
    _ = plot.widget
    for twin in (copy.copy(plot), copy.deepcopy(plot), pickle.loads(pickle.dumps(plot))):
        assert twin is not plot
        assert twin._widget is None
        assert (twin.tool, twin.selection) == ("select", {"events": [1, 2]})
        assert twin.linked == []
        assert twin._spec == plot._spec
        twin.tool = "zoom"
        assert plot.tool == "select"
        twin._pick = {"n": 9, "kind": "clear"}
        assert seen == []  # the original's callbacks stay with it


def test_save_html(tmp_path):
    from anytimeline.synthetic import traces

    tr = traces(3, seed=1)
    plot = Timeline(title="A <b>trace</b>").spans(tr.spans, tooltip=["service"])
    out = plot.save_html(tmp_path / "plot.html")
    page = out.read_text(encoding="utf-8")
    assert "<title>A &lt;b&gt;trace&lt;/b&gt;</title>" in page
    assert 'data-fill="window"' in page
    assert page.count("<script") == 2  # the data, and the drawing code: nothing loaded
    payload = payload_of(page)
    assert set(payload["buffers"]) >= set(plot._buffers)  # and each mark's table row
    tips = payload["tooltips"]["spans"]
    assert tips["columns"] == ["service"]
    # by the order the browser has the spans in (the tree's), not the table's
    rec = plot._layers["spans"]
    assert tips["values"][0] == [str(v) for v in tr.spans["service"][rec.perm]]
    assert plot._widget is None


def test_save_html_needs_layers(tmp_path):
    with pytest.raises(ValueError, match="no layers"):
        Timeline().save_html(tmp_path / "empty.html")


def test_save_png_writes_what_the_browser_sends(tmp_path, monkeypatch):
    plot = Timeline().events({"time": [1.0, 2.0], "lane": ["a", "b"]}, lane="lane")
    with pytest.raises(RuntimeError, match="show the plot"):
        plot.save_png(tmp_path / "plot.png")
    sent = sent_by(plot, monkeypatch)
    plot.save_png(tmp_path / "plot.png")
    assert sent == [({"type": "snapshot", "request": "1"}, None)]
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    plot.widget._on_msg(plot.widget, {"type": "image", "request": "1"}, [memoryview(png)])
    assert (tmp_path / "plot.png").read_bytes() == png
    # a second view answering the same request changes nothing
    plot.widget._on_msg(plot.widget, {"type": "image", "request": "1"}, [memoryview(b"other")])
    assert (tmp_path / "plot.png").read_bytes() == png


def test_mark_scale_and_dodge_settings(tmp_path):
    plot = Timeline(mark_scale=0.75, dodge=False)
    assert (plot.mark_scale, plot.dodge) == (0.75, False)
    plot.mark_scale = 2
    with pytest.raises(ValueError, match="mark_scale"):
        plot.mark_scale = 5
    plot.events({"time": [1.0, 2.0], "lane": ["a", "a"]}, lane="lane")
    payload = payload_of(plot.save_html(tmp_path / "plot.html").read_text(encoding="utf-8"))
    assert (payload["mark_scale"], payload["dodge"]) == (2.0, False)


def test_a_tooltip_of_one_column(monkeypatch):
    log = service_log(5)
    plot = Timeline().events(log, lane="service", tooltip="request")
    sent = sent_by(plot, monkeypatch)
    plot.widget._on_msg(
        plot.widget, {"type": "tooltip", "request": 1, "layer": "events", "index": 0}, []
    )
    rec = plot._layers["events"]
    assert sent[0][0]["rows"] == [["request", log["request"][int(rec.rows[rec.perm[0]])]]]
