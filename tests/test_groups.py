import numpy as np
import pytest

from anytimeline import Timeline
from anytimeline.layers.events import EventsRecord
from anytimeline.synthetic import service_log, service_metrics, traces

LOG = {
    "time": np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
    "service": ["db", "api", "api", "db", "cache", "api"],
    "host": ["b", "a", "b", "a", "b", None],
    "level": ["info", "error", "info", "info", "warning", "info"],
}


def test_groups_are_headers_with_the_same_lane_order():
    plot = Timeline(lane_order=["api"]).events(LOG, lane="service", group="host")
    lanes = plot._spec["lanes"]
    # groups in natural order, missing last as a group of its own; lanes ordered alike
    assert lanes["names"] == ["(missing)", "api", "a", "api", "db", "b", "api", "cache", "db"]
    tree = lanes["tree"]
    assert tree["header"] == [0, 2, 5]
    assert tree["depth"] == [0, 1, 0, 1, 1, 0, 1, 1, 1]
    assert tree["size"] == [2, 1, 3, 1, 1, 4, 1, 1, 1]
    assert tree["compact"] is False
    assert plot._spec["layers"][0]["count"] == 6


def test_group_order_and_selection_rows():
    plot = Timeline(group_order=["b"]).events(LOG, lane="service", group="host")
    assert plot._spec["lanes"]["names"][0] == "b"
    # a box over a's lanes and b's first: rows of the table
    names = plot._spec["lanes"]["names"]
    a_db, b_api = names.index("a") + 2, 1
    pick = {"kind": "box", "x": [0, 10], "lanes": [0, 9], "shown": [b_api, a_db], "mode": "replace"}
    plot._pick = {**pick, "xscale": "time", "n": 1}
    assert plot.selection == {"events": [2, 3]}  # b's api (row 2) and a's db (row 3)


def test_one_legend_one_colour_per_category():
    plot = Timeline().events(LOG, lane="service", group="host", color="level")
    items = plot._spec["layers"][0]["color"]["legend"]["items"]
    assert [i["label"] for i in items] == ["error", "info", "warning"]


def test_values_lane_range_is_the_same_in_every_group():
    m = service_metrics(300)
    other = service_metrics(300, seed=4)
    data = {
        "time": np.concatenate([m["time"], other["time"]]),
        "service": np.concatenate([m["service"], other["service"]]),
        "cpu": np.concatenate([m["cpu"], other["cpu"] * 0.5]),
        "host": np.repeat(["a", "b"], [len(m["time"]), len(other["time"])]),
    }
    plot = Timeline().values(data, value="cpu", lane="service", group="host")
    names = plot._spec["lanes"]["names"]
    layer = plot._spec["layers"][0]
    ylim = np.frombuffer(plot._buffers[layer["ylim"]["id"]], dtype=np.float64).reshape(-1, 2)
    api = [i for i, n in enumerate(names) if n == "api"]
    assert len(api) == 2
    assert ylim[api[0]].tolist() == ylim[api[1]].tolist()


def test_align_start_puts_each_group_at_zero():
    t = np.array(
        [
            "2026-10-12T08:00:00",
            "2026-10-12T08:00:05",
            "2026-10-13T09:00:00",
            "2026-10-13T09:00:02",
        ],
        dtype="datetime64[s]",
    )
    data = {"time": t, "lane": ["x", "x", "x", "x"], "day": ["mon", "mon", "tue", "tue"]}
    plot = Timeline(align="start").events(data, lane="lane", group="day")
    time = plot._spec["time"]
    assert time["kind"] == "duration"
    assert time["extent"] == [0.0, 5.0]
    rec = plot._layers["events"]
    assert isinstance(rec, EventsRecord)
    assert rec.times is not None
    assert rec.times.kind == "datetime"  # the layer keeps its own times
    with pytest.raises(ValueError, match="align"):
        Timeline(align="end")  # ty: ignore[invalid-argument-type]


def test_spans_in_groups_keep_events_on_their_lanes_and_the_critical_path():
    tr = traces(4, seed=3)
    roots = tr.spans["parent_id"] == None  # noqa: E711
    name = dict(zip(tr.spans["trace_id"][roots], tr.spans["name"][roots], strict=True))
    endpoint = np.array([name[t] for t in tr.spans["trace_id"]], dtype=object)
    plain = Timeline().spans(tr.spans)
    plot = Timeline().spans({**tr.spans, "endpoint": endpoint}, group="endpoint")
    plot.events(tr.events, time="time", lane="span_id", group="trace_id", name="logs")
    lanes = plot._spec["lanes"]
    headers = lanes["tree"]["header"]
    assert [lanes["names"][h] for h in headers] == sorted(set(endpoint))
    assert lanes["tree"]["compact"] is True
    # the events went on their spans' lanes, not into groups of their own
    assert len(lanes["names"]) == len(tr.spans["span_id"]) + len(headers)
    # the same critical path as without groups
    crit = plot._spec["layers"][0]["critical"]["count"]
    assert crit == plain._spec["layers"][0]["critical"]["count"]


def test_states_and_intervals_take_groups():
    log = service_log(200)
    host = np.where(np.isin(log["user"], [f"u{i:02d}" for i in range(30)]), "a", "b")
    plot = Timeline().events({**log, "host": host}, lane="service", group="host")
    changes = {
        "time": np.datetime64("2026-10-12T08:00", "s") + np.array([0, 10], dtype="timedelta64[s]"),
        "service": ["api", "api"],
        "host": ["a", "b"],
        "state": ["up", "down"],
    }
    plot.states(changes, lane="service", group="host")
    names = plot._spec["lanes"]["names"]
    assert names.count("api") == 2
