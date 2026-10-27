"""Find and step (the search box, the keys ``.`` and ``,``), answered in Python from every
mark: text and lane names that hold the query, in time order; the next or previous mark of a
lane, over layers."""

from __future__ import annotations

import numpy as np

from anytimeline import Timeline
from anytimeline.widget import TimelineWidget

T0 = np.datetime64("2026-10-01T00:00:00", "ns")
S = np.timedelta64(1, "s").astype("timedelta64[ns]")


def plot() -> Timeline:
    events = {
        "time": T0 + np.array([5, 1, 3, 2, 9]) * S,
        "lane": np.array(["db", "db", "api", "db", "api"], dtype=object),
        "what": np.array(["Query slow", "query", "deploy", "fail", "Deploy api"], dtype=object),
    }
    bars = {
        "start": T0 + np.array([0, 4]) * S,
        "end": T0 + np.array([2, 6]) * S,
        "lane": np.array(["db", "api"], dtype=object),
        "task": np.array(["backup", "rollout deploy"], dtype=object),
    }
    return (
        Timeline()
        .events(events, lane="lane", text="{what}")
        .intervals(bars, lane="lane", text="{task}", name="jobs")
    )


def ticks(p: Timeline, seconds: float) -> float:
    assert p._base is not None
    return p._base.to_ticks(T0 + np.timedelta64(int(seconds * 1e9), "ns"))


def test_search_matches_text_ignoring_case_in_time_order() -> None:
    p = plot()
    found = p._find({"q": "DEPLOY", "scale": "time"})
    assert found["total"] == 3
    assert [m["text"] for m in found["matches"]] == ["deploy", "rollout deploy", "Deploy api"]
    m = found["matches"][1]
    assert m["layer"] == "jobs"
    assert (m["x"], m["x2"]) == (ticks(p, 4), ticks(p, 6))
    names = p._spec["lanes"]["names"]
    assert names[m["lane"]] == "api"
    # lanes by name
    assert [names[i] for i in p._find({"q": "d", "scale": "time"})["lanes"]] == ["db"]
    assert p._find({"q": "  ", "scale": "time"}) == {"lanes": [], "matches": [], "total": 0}


def test_search_on_the_order_scale_goes_by_the_order() -> None:
    p = plot()
    found = p._find({"q": "query", "scale": "order"})
    assert [m["text"] for m in found["matches"]] == ["query", "Query slow"]
    assert found["matches"][0]["r"] < found["matches"][1]["r"]


def test_stepping_goes_through_a_lane_over_layers() -> None:
    p = plot()
    db = p._spec["lanes"]["names"].index("db")
    seen = []
    after = {"x": ticks(p, -1), "layer": None, "index": -1}
    while True:
        got = p._step({"lane": db, "after": after, "forward": True, "scale": "time"})["match"]
        if got is None:
            break
        seen.append(got["text"])
        after = {"x": got["x"], "layer": got["layer"], "index": got["index"]}
    assert seen == ["backup", "query", "fail", "Query slow"]
    # and back
    back = p._step({"lane": db, "after": after, "forward": False, "scale": "time"})["match"]
    assert back["text"] == "fail"


def test_ties_break_by_layer_then_index() -> None:
    events = {"time": np.full(3, T0), "lane": np.array(["a"] * 3, dtype=object)}
    p = Timeline().events(events, lane="lane", text="{lane}")
    after = {"x": -1e30, "layer": None, "index": -1}
    order = []
    for _ in range(3):
        got = p._step({"lane": 0, "after": after, "forward": True, "scale": "time"})["match"]
        order.append(got["index"])
        after = {"x": got["x"], "layer": got["layer"], "index": got["index"]}
    assert order == [0, 1, 2]
    assert p._step({"lane": 0, "after": after, "forward": True, "scale": "time"})["match"] is None


def test_the_widget_answers_find_and_step() -> None:
    p = plot()
    w = p.widget
    assert isinstance(w, TimelineWidget)
    sent: list[dict] = []
    w.send = lambda content, buffers=None: sent.append(content)  # ty: ignore[invalid-assignment]
    w._on_msg(w, {"type": "find", "q": "fail", "scale": "time", "request": 7}, [])
    assert sent[-1]["request"] == 7
    assert sent[-1]["total"] == 1
    after = {"x": -1e30, "layer": None, "index": -1}
    ask = {"type": "step", "lane": 0, "after": after, "forward": True, "scale": "time"}
    w._on_msg(w, {**ask, "request": 8}, [])
    assert sent[-1]["request"] == 8
    assert sent[-1]["match"] is not None
    w._on_msg(w, {"type": "step", "request": 9}, [])  # no lane: an error, not a crash
    assert "error" in sent[-1]


def test_a_change_to_the_layers_finds_anew() -> None:
    p = plot()
    assert p._find({"q": "zebra", "scale": "time"})["total"] == 0
    more = {
        "time": [T0],
        "lane": np.array(["db"], dtype=object),
        "t": np.array(["zebra"], dtype=object),
    }
    p.events(more, lane="lane", text="{t}", name="more")
    assert p._find({"q": "zebra", "scale": "time"})["total"] == 1
