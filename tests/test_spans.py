import json

import numpy as np
import pytest

from anytimeline import Timeline
from anytimeline import tree as trees
from anytimeline.otel import read_otlp
from anytimeline.synthetic import traces

SPANS = {
    "span_id": ["a", "b", "c", "d", "e"],
    "parent_id": [None, "a", "a", "b", "zz"],
    "name": ["root", "b", "c", "d", "orphan"],
    "start": np.array([0, 5, 1, 2, 3]),
    "end": np.array([10, 9, 4, 3, 6]),
}


def test_tree_order_depth_size():
    t = trees.build(
        np.array(SPANS["span_id"], dtype=object),
        np.array(SPANS["parent_id"], dtype=object),
        np.asarray(SPANS["start"]),
        list(SPANS["name"]),
        "span_id",
    )
    # roots by start (a at 0, e at 3); a's children by start: c (1), then b (5) with d
    assert t.order.tolist() == [0, 2, 1, 3, 4]
    assert t.depth.tolist() == [0, 1, 1, 2, 0]
    assert t.size.tolist() == [4, 1, 2, 1, 1]
    assert t.labels == ["root", "c", "b", "d", "orphan"]
    assert (t.roots, t.orphans) == (2, 1)


def test_tree_expand_levels():
    t = trees.build(
        np.array(SPANS["span_id"], dtype=object),
        np.array(SPANS["parent_id"], dtype=object),
        np.asarray(SPANS["start"]),
        list(SPANS["name"]),
        "span_id",
    )
    assert t.open(1).tolist() == [False] * 5
    assert t.open(2).tolist() == [True, False, False, False, True]  # roots open
    assert t.open(None).all() == (t.depth < 2).all()
    assert t.open("auto").tolist() == t.open(None).tolist()


def test_tree_errors():
    ids = np.array(["a", "b", "a"], dtype=object)
    with pytest.raises(ValueError, match="unique id"):
        trees.build(ids, np.array([None, None, None], dtype=object), np.zeros(3), ids, "id")
    ids = np.array(["a", "b"], dtype=object)
    with pytest.raises(ValueError, match="cycle"):
        trees.build(ids, np.array(["b", "a"], dtype=object), np.zeros(2), ids, "id")
    with pytest.raises(ValueError, match="its own parent"):
        trees.build(ids, np.array(["a", None], dtype=object), np.zeros(2), ids, "id")


def test_critical_path():
    # lanes in depth-first order: root 0..10, b 1..4 (with d 2..3), c 5..9, orphan 3..6
    lo = np.array([0, 1, 2, 5, 3.0])
    hi = np.array([10, 4, 3, 9, 6.0])
    depth = np.array([0, 1, 2, 1, 0])
    size = np.array([4, 2, 1, 1, 1])
    path = {tuple(r) for r in trees.critical_path(lo, hi, depth, size).tolist()}
    assert path == {
        (0, 7, 1),  # root: from c's end to its end
        (3, 6, 7),  # c, whole
        (0, 3, 6),  # root: from b's end to c's start
        (1, 5, 3),  # b: from d's end to its end
        (2, 4, 5),  # d, whole
        (1, 2, 4),  # b: from its start to d's start
        (0, 0, 2),  # root: from its start to b's start
        (4, 8, 9),  # the orphan: a root of its own
    }


def test_critical_path_overlapping_children():
    # two children in parallel: the one that ends last is on the path; the other is not
    lo = np.array([0, 1, 1.0])
    hi = np.array([10, 9, 5.0])
    path = {
        tuple(r)
        for r in trees.critical_path(lo, hi, np.array([0, 1, 1]), np.array([3, 1, 1])).tolist()
    }
    assert path == {(0, 3, 1), (1, 2, 3), (0, 0, 2)}


def test_spans_spec():
    plot = Timeline().spans(SPANS, end="end")
    lanes = plot._spec["lanes"]
    assert lanes["names"] == ["root", "c", "b", "d", "orphan"]
    assert lanes["title"] == "name"
    assert lanes["tree"]["depth"] == [0, 1, 1, 2, 0]
    layer = plot._spec["layers"][0]
    assert layer["durations"] is True
    # root: 3 parts around b and c; b, c and the orphan whole; d (before b starts) not
    assert layer["critical"]["count"] == 6


def test_spans_events_share_lanes_and_other_lanes_follow():
    plot = Timeline().spans(SPANS)
    plot.events(
        {"span_id": ["d", "zzz"], "time": np.array([2, 4])},
        time="time",
        lane="span_id",
        name="logs",
    )
    names = plot._spec["lanes"]["names"]
    assert names[:5] == ["root", "c", "b", "d", "orphan"]
    assert names[5] == "zzz"
    assert plot._spec["lanes"]["tree"]["depth"] == [0, 1, 1, 2, 0, 0]  # zzz: a plain lane


def test_box_selection_with_folded_lanes():
    plot = Timeline().spans(SPANS)
    plot._pick = {
        "kind": "box",
        "x": [0, 10],
        "lanes": [0, 4],
        "shown": [0, 4],
        "xscale": "time",
        "mode": "replace",
        "n": 1,
    }
    assert plot.selection == {"spans": [0, 4]}
    plot._pick = {
        "kind": "box",
        "x": [0, 10],
        "lanes": [0, 4],
        "xscale": "time",
        "mode": "replace",
        "n": 2,
    }
    assert plot.selection == {"spans": [0, 1, 2, 3, 4]}


def test_parent_needs_id_and_no_lane():
    with pytest.raises(ValueError, match="needs id="):
        Timeline().intervals(SPANS, parent="parent_id")
    with pytest.raises(ValueError, match="needs parent="):
        Timeline().intervals(SPANS, lane="name", critical_path=True)


def test_one_tree_per_plot():
    plot = Timeline().spans(SPANS)
    with pytest.raises(ValueError, match="one layer with parent="):
        plot.spans(SPANS, name="more")
    assert plot.layers == ["spans"]


def test_synthetic_traces_are_trees():
    tr = traces(10, seed=1)
    ids = set(tr.spans["span_id"])
    roots = [p is None for p in tr.spans["parent_id"]]
    assert sum(roots) == 10
    assert all(p is None or p in ids for p in tr.spans["parent_id"])
    assert (tr.spans["end"] >= tr.spans["start"]).all()
    assert set(tr.events["span_id"]) <= ids
    Timeline().spans(tr.spans, color="service")


OTLP = {
    "resourceSpans": [
        {
            "resource": {
                "attributes": [{"key": "service.name", "value": {"stringValue": "checkout"}}]
            },
            "scopeSpans": [
                {
                    "spans": [
                        {
                            "traceId": "5B8EFFF798038103D269B633813FC60C",
                            "spanId": "EEE19B7EC3C1B174",
                            "name": "POST /checkout",
                            "kind": 2,
                            "startTimeUnixNano": "1760256000000000000",
                            "endTimeUnixNano": "1760256000250000000",
                            "status": {"code": 2, "message": "card declined"},
                            "attributes": [
                                {"key": "http.status_code", "value": {"intValue": "402"}}
                            ],
                            "events": [
                                {
                                    "timeUnixNano": "1760256000200000000",
                                    "name": "exception",
                                    "attributes": [
                                        {
                                            "key": "exception.message",
                                            "value": {"stringValue": "declined"},
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "traceId": "W47/95gDgQPSabYzgT/GDA==",
                            "spanId": "AAAAAAAAAAE=",
                            "parentSpanId": "7uGbfsPBsXQ=",
                            "name": "charge",
                            "kind": "SPAN_KIND_CLIENT",
                            "startTimeUnixNano": 1760256000010000000,
                            "endTimeUnixNano": 1760256000200000000,
                        },
                    ]
                }
            ],
        }
    ]
}


def test_read_otlp(tmp_path):
    tr = read_otlp(OTLP)
    s = tr.spans
    assert s["trace_id"].tolist() == ["5b8efff798038103d269b633813fc60c"] * 2  # base64 → hex
    assert s["span_id"].tolist() == ["eee19b7ec3c1b174", "0000000000000001"]
    assert s["parent_id"].tolist() == [None, "eee19b7ec3c1b174"]
    assert s["service"].tolist() == ["checkout", "checkout"]
    assert s["kind"].tolist() == ["server", "client"]
    assert s["status"].tolist() == ["error", "unset"]
    assert s["status_message"][0] == "card declined"
    assert s["attributes"][0] == "http.status_code=402"
    assert s["start"].dtype == np.dtype("datetime64[ns]")
    assert int((s["end"][0] - s["start"][0]).astype(np.int64)) == 250_000_000
    assert tr.events["name"].tolist() == ["exception"]
    assert tr.events["span_id"].tolist() == ["eee19b7ec3c1b174"]
    # a file of JSON lines gives the same
    path = tmp_path / "traces.jsonl"
    path.write_text(json.dumps(OTLP) + "\n" + json.dumps(OTLP) + "\n")
    assert len(read_otlp(path).spans["span_id"]) == 4
    plot = Timeline().spans(read_otlp(OTLP).spans, color="service")
    assert plot._spec["lanes"]["names"] == ["POST /checkout", "charge"]


def test_gantt_with_sub_tasks():
    from anytimeline import gantt

    plan = {
        "task": ["Ship", "Build", "Backend", "Frontend"],
        "part": [None, None, "Build", "Build"],
        "start": np.array(
            ["2026-10-20", "2026-10-01", "2026-10-01", "2026-10-05"], dtype="datetime64[D]"
        ),
        "end": np.array(
            ["2026-10-20", "2026-10-19", "2026-10-15", "2026-10-19"], dtype="datetime64[D]"
        ),
        "after": ["Build", None, None, None],
    }
    chart = gantt(plan, parent="part", depends="after")
    lanes = chart._spec["lanes"]
    assert lanes["names"] == ["Build", "Backend", "Frontend", "Ship"]
    assert lanes["tree"]["open"] == [True, False, False, True]  # everything shows
    assert chart._spec["layers"][0]["links"]["count"] == 1
