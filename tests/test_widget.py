import numpy as np
import pytest

from anytimeline import Timeline
from anytimeline.synthetic import service_log
from anytimeline.widget import CHUNK_BYTES


def plot_of_log():
    log = service_log(30)
    plot = Timeline().events(log, lane="service", order="seq", tooltip=["request", "bytes"])
    return log, plot


def test_no_bulk_data_in_synced_state():
    _, plot = plot_of_log()
    state = plot.get_state()
    assert len(str(state["_spec"])) < 20_000
    assert all(not isinstance(v, bytes | memoryview) for v in state["_spec"].values())


def test_buffers_are_served_in_chunks(monkeypatch):
    _, plot = plot_of_log()
    sent = []
    monkeypatch.setattr(plot, "send", lambda content, buffers=None: sent.append((content, buffers)))
    some = next(iter(plot._buffers))
    plot._on_frontend_msg(plot, {"type": "need", "ids": [some, "nope"]}, [])
    assert sent[0][0]["type"] == "put"
    assert sent[0][0]["id"] == some
    assert bytes(sent[0][1][0]) == plot._buffers[some]
    assert sent[-1][0] == {"type": "missing", "id": "nope"}
    big = b"x" * (CHUNK_BYTES * 2 + 5)
    plot._buffers["big"] = big
    sent.clear()
    plot._send_buffer("big")
    assert [c["chunk"] for c, _ in sent] == [0, 1, 2]
    assert b"".join(bytes(b[0]) for _, b in sent) == big


def test_tooltip_answers_with_the_row(monkeypatch):
    log, plot = plot_of_log()
    sent = []
    monkeypatch.setattr(plot, "send", lambda content, buffers=None: sent.append(content))
    plot._on_frontend_msg(
        plot, {"type": "tooltip", "request": 7, "layer": "events", "index": 0}, []
    )
    rec = plot._layers["events"]
    row = int(rec.rows[rec.perm[0]])
    assert sent[0]["request"] == 7
    assert sent[0]["rows"] == [["request", log["request"][row]], ["bytes", str(log["bytes"][row])]]


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


def test_selection_from_python_marks_the_events():
    _, plot = plot_of_log()
    plot.selection = {"events": [0, 5]}
    marks = np.frombuffer(plot._marks["events"], "<i4")
    rec = plot._layers["events"]
    assert sorted(int(rec.rows[rec.perm[i]]) for i in marks) == [0, 5]
    with pytest.raises(Exception, match="no layer"):
        plot.selection = {"nope": [1]}


def test_zoom_to_and_range():
    log, plot = plot_of_log()
    plot.zoom_to(log["time"][2], log["time"][10])
    t0, t1 = plot._zoom["range"]
    assert t1 > t0
    assert plot.range is None
    plot._on_frontend_msg(plot, {"type": "view", "range": [t0, t1]}, [])
    a, b = plot.range
    assert a == log["time"][2]
    assert b == log["time"][10]
    with pytest.raises(ValueError, match="after start"):
        plot.zoom_to(log["time"][10], log["time"][2])


def test_perf_messages_and_settings():
    _, plot = plot_of_log()
    plot._on_frontend_msg(plot, {"type": "perf", "update": {"renderer": "webgl2"}}, [])
    assert plot.perf == {"renderer": "webgl2"}
    with pytest.raises(ValueError, match="sort"):
        Timeline(sort="size")  # ty: ignore[invalid-argument-type]


def test_tool_is_synced_and_checked():
    plot = Timeline(tool="zoom")
    assert plot.tool == "zoom"
    assert plot.get_state()["tool"] == "zoom"
    plot.tool = "select"
    with pytest.raises(Exception, match="tool"):
        plot.tool = "lasso"


def test_font_size_is_synced_and_checked():
    plot = Timeline(font_size=16)
    assert plot.get_state()["font_size"] == 16
    with pytest.raises(Exception, match="font_size"):
        plot.font_size = 40


def test_save_html(tmp_path):
    import json
    import re

    from anytimeline.synthetic import traces

    tr = traces(3, seed=1)
    plot = Timeline(title="A <b>trace</b>").spans(tr.spans, tooltip=["service"])
    out = plot.save_html(tmp_path / "plot.html")
    page = out.read_text(encoding="utf-8")
    assert "<title>A &lt;b&gt;trace&lt;/b&gt;</title>" in page
    assert 'data-fill="window"' in page
    assert page.count("<script") == 2  # the data, and the drawing code: nothing loaded
    data = re.search(r'<script type="application/json">(.*?)</script>', page, re.DOTALL)
    assert data is not None
    payload = json.loads(data.group(1))
    assert set(payload["buffers"]) == set(plot._buffers)
    tips = payload["tooltips"]["spans"]
    assert tips["columns"] == ["service"]
    # by the order the browser has the spans in (the tree's), not the table's
    rec = plot._layers["spans"]
    assert tips["values"][0] == [str(v) for v in tr.spans["service"][rec.perm]]


def test_save_html_needs_layers(tmp_path):
    with pytest.raises(ValueError, match="no layers"):
        Timeline().save_html(tmp_path / "empty.html")


def test_save_png_writes_what_the_browser_sends(tmp_path, monkeypatch):
    plot = Timeline().events({"time": [1.0, 2.0], "lane": ["a", "b"]}, lane="lane")
    sent: list[dict] = []
    monkeypatch.setattr(plot, "send", lambda content, buffers=None: sent.append(content))
    plot.save_png(tmp_path / "plot.png")
    assert sent == [{"type": "snapshot", "request": "1"}]
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    plot._on_frontend_msg(plot, {"type": "image", "request": "1"}, [memoryview(png)])
    assert (tmp_path / "plot.png").read_bytes() == png
    # a second view answering the same request changes nothing
    plot._on_frontend_msg(plot, {"type": "image", "request": "1"}, [memoryview(b"other")])
    assert (tmp_path / "plot.png").read_bytes() == png
