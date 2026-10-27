"""Traces in depth: the flame layout of spans, merged flame graphs (``traces.merge``), two
traces compared (``traces.compare``, ``compare_traces``), and the readers of Jaeger's JSON and
Chrome's trace event format."""

from __future__ import annotations

import json

import numpy as np
import pytest

from anytimeline import Timeline, compare_traces
from anytimeline.chrome import read_chrome
from anytimeline.jaeger import read_jaeger
from anytimeline.layers import intervals as iv
from anytimeline.synthetic import traces
from anytimeline.traces import compare, merge

MS = np.timedelta64(1, "ms").astype("timedelta64[ns]")


def bars_of(p: Timeline, name: str = "spans") -> iv.IntervalsRecord:
    rec = p._layers[name]
    assert isinstance(rec, iv.IntervalsRecord)
    return rec


def table(rows: list[tuple]) -> dict[str, np.ndarray]:
    """Spans from (id, parent, service, name, start ms, end ms)."""
    ids, parents, services, names, starts, ends = zip(*rows, strict=True)
    return {
        "span_id": np.array(ids, dtype=object),
        "parent_id": np.array(parents, dtype=object),
        "service": np.array(services, dtype=object),
        "name": np.array(names, dtype=object),
        "start": np.array(starts) * MS,
        "end": np.array(ends) * MS,
    }


# a root with a call to auth, then two calls to db in parallel
BEFORE = table(
    [
        ("r", None, "api", "GET /", 0, 100),
        ("a", "r", "auth", "check", 0, 10),
        ("d1", "r", "db", "query", 10, 60),
        ("d2", "r", "db", "query", 10, 50),
        ("c", "d1", "db", "lock", 20, 30),
    ]
)


def test_flame_puts_spans_on_a_lane_per_depth() -> None:
    p = Timeline().spans(BEFORE, layout="flame")
    assert p._spec["lanes"]["names"] == ["0", "1", "2"]
    assert p._spec["lanes"]["title"] == "depth"
    assert p._spec["lanes"]["tree"] is None  # depths do not fold
    rec = bars_of(p)
    assert rec.overlap == "pack"
    assert rec.text == ["GET /", "check", "query", "query", "lock"]  # the name, in the bar
    assert "name" in rec.tooltip
    assert not rec.durations
    assert not rec.critical  # a waterfall's defaults, not a flame's


def test_flame_packs_parallel_spans_under_their_parents() -> None:
    p = Timeline().spans(BEFORE, layout="flame")
    lay = p._laid["spans"]
    assert isinstance(lay, iv.Layout)
    bars = lay.bars
    assert bars is not None
    # sorted bars: depth 1 holds check, query (d1), query (d2): the two queries overlap
    depth1 = np.flatnonzero(bars.lane == 1)
    assert sorted(bars.row[depth1].tolist()) == [0.0, 0.0, 1.0]
    assert set(bars.rows[depth1].tolist()) == {2.0}
    # lock (in d1) goes on d1's sub-row, though row 0 is free
    d1 = depth1[np.argmax(bars.hi[depth1] - bars.lo[depth1])]
    (lock,) = np.flatnonzero(bars.lane == 2)
    assert bars.row[lock] == bars.row[d1]


def test_flame_marks_the_critical_path_when_asked() -> None:
    p = Timeline().spans(BEFORE, layout="flame", critical_path=True)
    assert p._spec["layers"][0]["critical"]["count"] > 0


def test_flame_per_trace_with_groups() -> None:
    tr = traces(3, seed=2)
    p = Timeline().spans(tr.spans, layout="flame", group="trace_id")
    names = p._spec["lanes"]["names"]
    headers = p._spec["lanes"]["tree"]["header"]
    assert len(headers) == 3
    assert [names[i] for i in headers] == sorted(set(tr.spans["trace_id"].tolist()))


def test_a_wrong_layout_says_so() -> None:
    with pytest.raises(ValueError, match="layout"):
        Timeline().spans(BEFORE, layout="icicle")  # ty: ignore[invalid-argument-type]


def test_spans_follow_with_depends() -> None:
    spans = {**BEFORE, "after": np.array([None, None, "a", None, None], dtype=object)}
    p = Timeline().spans(spans, depends="after")
    assert len(bars_of(p).links) == 1


def test_merge_sums_paths_heaviest_first() -> None:
    again = table(
        [
            ("r2", None, "api", "GET /", 200, 260),
            ("d3", "r2", "db", "query", 210, 250),
        ]
    )
    both = {k: np.concatenate([BEFORE[k], again[k]]) for k in BEFORE}
    m = merge(both)
    rows = {p: i for i, p in enumerate(m["path"].tolist())}
    root, query = rows["api GET /"], rows["api GET / › db query"]
    auth, lock = rows["api GET / › auth check"], rows["api GET / › db query › db lock"]
    assert m["count"][root] == 2
    assert m["total"][root] == 160 * MS
    assert m["count"][query] == 3
    assert m["total"][query] == 130 * MS  # 50 + 40 + 40: parallel calls add up
    # the root's 160 ms: query (130) and check (10) fit; the heaviest first, from the left
    assert m["start"][query] == 0 * MS
    assert m["end"][query] == 130 * MS
    assert m["start"][auth] == 130 * MS
    assert m["start"][lock] == 0 * MS
    # own time: the root's 100 ms less 0..60 its children cover; 60 less 10..50
    assert m["self"][root] == 40 * MS + 20 * MS
    assert m["parent_id"][query] == root
    Timeline().spans(m, layout="flame")  # plots as spans


def test_merge_fits_parallel_children_into_their_parent() -> None:
    wide = table(
        [
            ("r", None, "api", "GET /", 0, 10),
            ("a", "r", "x", "a", 0, 10),
            ("b", "r", "y", "b", 0, 10),
        ]
    )
    m = merge(wide)
    kids = m["parent_id"] == 0
    assert (m["total"][kids] == 10 * MS).all()
    widths = (m["end"] - m["start"])[kids]
    assert widths.sum() == 10 * MS  # they share the parent's width


def test_merge_by_name_only_and_numbers() -> None:
    spans = {**BEFORE, "start": np.arange(5.0), "end": np.arange(5.0) + 1}
    spans["start"][0], spans["end"][0] = 0.0, 10.0
    m = merge({k: v for k, v in spans.items() if k != "service"})
    assert m["total"].dtype == np.float64
    assert "service" not in m
    assert m["path"].tolist()[0] == "GET /"


def test_compare_matches_spans_by_path_and_order() -> None:
    after = table(
        [
            ("R", None, "api", "GET /", 1000, 1120),
            ("A", "R", "auth", "check", 1000, 1010),
            ("D1", "R", "db", "query", 1010, 1090),  # slower: 50 → 80
            ("C", "D1", "db", "lock", 1020, 1030),
            ("Q", "R", "queue", "send", 1090, 1100),  # added; the second query is gone
        ]
    )
    d = compare(BEFORE, after)
    changes: dict[tuple[str, str], list[str]] = {}
    for s, n, c in zip(d["service"], d["name"], d["change"], strict=True):
        changes.setdefault((s, n), []).append(c)
    assert changes[("api", "GET /")] == ["slower"]  # 100 → 120
    assert changes[("auth", "check")] == ["same"]
    assert sorted(changes[("db", "query")]) == ["removed", "slower"]
    assert changes[("db", "lock")] == ["same"]
    assert changes[("queue", "send")] == ["added"]
    # times from each trace's start
    send = d["name"].tolist().index("send")
    assert d["start"][send] == 90 * MS
    assert np.isnat(d["before_start"][send])
    gone = d["change"].tolist().index("removed")
    assert d["start"][gone] == 10 * MS  # the first trace's time
    assert np.isnat(d["after"][gone])
    root = d["name"].tolist().index("GET /")
    assert d["delta"][root] == 20 * MS
    assert d["difference"][root] == "+20 ms (+20%)"


def test_compare_threshold_and_errors() -> None:
    d = compare(BEFORE, BEFORE)
    assert set(d["change"].tolist()) == {"same"}
    slow = {**BEFORE, "end": BEFORE["end"] + 5 * MS}
    assert compare(BEFORE, slow, threshold=1.0)["change"].tolist().count("slower") == 0
    with pytest.raises(ValueError, match="threshold"):
        compare(BEFORE, BEFORE, threshold=-1)
    tr = traces(2, seed=1)
    with pytest.raises(ValueError, match="one trace each"):
        compare(tr.spans, tr.spans)


def test_compare_traces_plots_both() -> None:
    after = {**BEFORE, "end": BEFORE["end"] * 2}
    p = compare_traces(BEFORE, after, title="after the change")
    assert list(p.layers) == ["before", "spans"]
    assert p._spec["lanes"]["title"] == "name"  # the tree names the lanes
    spans = bars_of(p)
    assert spans.color.legend is not None
    assert spans.color.legend["title"] == "change"
    assert p.to_svg(width=700)


JAEGER = {
    "data": [
        {
            "traceID": "ABC",
            "processes": {"p1": {"serviceName": "frontend"}, "p2": {"serviceName": "db"}},
            "spans": [
                {
                    "traceID": "ABC",
                    "spanID": "S1",
                    "operationName": "GET /",
                    "references": [],
                    "startTime": 1761600000000000,
                    "duration": 5000,
                    "processID": "p1",
                    "tags": [
                        {"key": "span.kind", "type": "string", "value": "server"},
                        {"key": "http.status_code", "type": "int64", "value": 200},
                        {"key": "otel.status_code", "type": "string", "value": "OK"},
                    ],
                    "logs": [
                        {
                            "timestamp": 1761600000001000,
                            "fields": [
                                {"key": "event", "type": "string", "value": "cache miss"},
                                {"key": "key", "type": "string", "value": "u1"},
                            ],
                        }
                    ],
                },
                {
                    "traceID": "ABC",
                    "spanID": "S2",
                    "operationName": "SELECT",
                    "references": [
                        {"refType": "FOLLOWS_FROM", "traceID": "ABC", "spanID": "XX"},
                        {"refType": "CHILD_OF", "traceID": "ABC", "spanID": "S1"},
                    ],
                    "startTime": 1761600000001500,
                    "duration": 2000,
                    "processID": "p2",
                    "tags": [{"key": "error", "type": "bool", "value": True}],
                },
            ],
        }
    ]
}


def test_read_jaeger(tmp_path) -> None:
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(JAEGER))
    for source in (path, str(path), json.dumps(JAEGER), JAEGER, JAEGER["data"], JAEGER["data"][0]):
        t = read_jaeger(source)
        assert t.spans["span_id"].tolist() == ["s1", "s2"]
    s = t.spans
    assert s["trace_id"].tolist() == ["abc", "abc"]
    assert s["parent_id"].tolist() == [None, "s1"]  # CHILD_OF over FOLLOWS_FROM
    assert s["service"].tolist() == ["frontend", "db"]
    assert s["kind"].tolist() == ["server", "unspecified"]
    assert s["status"].tolist() == ["ok", "error"]
    assert s["attributes"].tolist() == ["http.status_code=200", ""]
    assert s["start"][0] == np.datetime64("2025-10-27T21:20:00", "ns")
    assert s["end"][1] - s["start"][1] == 2 * MS
    e = t.events
    assert e["name"].tolist() == ["cache miss"]
    assert e["attributes"].tolist() == ["key=u1"]
    assert e["span_id"].tolist() == ["s1"]
    Timeline().spans(t.spans).events(t.events, lane="span_id")


CHROME = [
    {"ph": "M", "name": "process_name", "pid": 1, "tid": 0, "ts": 0, "args": {"name": "Renderer"}},
    {"ph": "M", "name": "thread_name", "pid": 1, "tid": 7, "ts": 0, "args": {"name": "main"}},
    {"ph": "X", "name": "Task", "cat": "top", "pid": 1, "tid": 7, "ts": 1000, "dur": 500},
    {"ph": "X", "name": "Layout", "cat": "blink", "pid": 1, "tid": 7, "ts": 1100, "dur": 200},
    {"ph": "B", "name": "Paint", "cat": "blink", "pid": 1, "tid": 7, "ts": 1350},
    {"ph": "E", "pid": 1, "tid": 7, "ts": 1450, "args": {"rects": 3}},
    {"ph": "i", "name": "mark", "pid": 1, "tid": 7, "ts": 1200, "s": "t"},
    {"ph": "i", "name": "load", "pid": 1, "tid": 7, "ts": 1200, "s": "g"},
    {"ph": "C", "name": "heap", "pid": 1, "tid": 7, "ts": 1000, "args": {"used": 10, "total": 20}},
    {"ph": "C", "name": "fps", "pid": 1, "tid": 7, "ts": 1400, "args": {"value": 60}},
    {"ph": "s", "name": "post", "cat": "ipc", "id": 5, "pid": 1, "tid": 7, "ts": 1150},
    {"ph": "f", "name": "post", "cat": "ipc", "id": 5, "pid": 1, "tid": 9, "ts": 1590},
    {"ph": "X", "name": "Recv", "cat": "ipc", "pid": 1, "tid": 9, "ts": 1600, "dur": 50},
    {
        "ph": "X",
        "name": "Out",
        "pid": 1,
        "tid": 9,
        "ts": 1700,
        "dur": 5,
        "bind_id": 9,
        "flow_out": True,
    },
    {
        "ph": "X",
        "name": "In",
        "pid": 1,
        "tid": 7,
        "ts": 1800,
        "dur": 5,
        "bind_id": 9,
        "flow_in": True,
    },
    {"ph": "b", "name": "fetch", "cat": "net", "id": "0x1", "pid": 1, "tid": 7, "ts": 1000},
    {"ph": "b", "name": "dns", "cat": "net", "id": "0x1", "pid": 1, "tid": 7, "ts": 1010},
    {"ph": "e", "name": "dns", "cat": "net", "id": "0x1", "pid": 1, "tid": 7, "ts": 1050},
    {"ph": "e", "name": "fetch", "cat": "net", "id": "0x1", "pid": 1, "tid": 7, "ts": 1700},
    {"ph": "B", "name": "never ends", "pid": 2, "tid": 1, "ts": 1900},
]


def test_read_chrome_slices_nest_on_their_thread() -> None:
    t = read_chrome({"traceEvents": CHROME, "displayTimeUnit": "ms"})
    s = t.spans
    name = s["name"].tolist()
    parent = dict(zip(name, s["parent_id"].tolist(), strict=True))
    ids = dict(zip(name, s["span_id"].tolist(), strict=True))
    assert parent["Task"] is None
    assert parent["Layout"] == ids["Task"]
    assert parent["Paint"] == ids["Task"]  # a B/E pair in an X
    assert parent["dns"] == ids["fetch"]  # async slices nest by id
    at = name.index("Paint")
    assert s["start"][at] == 350 * MS // 1000  # ns from the first event
    assert s["end"][at] == 450 * MS // 1000
    assert s["args"][at] == "rects=3"
    assert s["service"][at] == "Renderer"
    assert s["thread"][at] == "main"
    assert s["track"][name.index("Recv")] == "Renderer / tid 9"
    assert s["thread"][name.index("fetch")] == "async"
    assert np.isnat(s["end"][name.index("never ends")])
    assert s["track"][name.index("never ends")] == "pid 2 / tid 1"


def test_read_chrome_instants_counters_and_flows() -> None:
    t = read_chrome(json.dumps(CHROME)[:-1])  # a list without its closing bracket
    ids = dict(zip(t.spans["name"].tolist(), t.spans["span_id"].tolist(), strict=True))
    e = t.events
    assert e["name"].tolist() == ["mark", "load"]
    assert e["span_id"].tolist() == [ids["Layout"], None]  # the global one is in no slice
    assert e["scope"].tolist() == ["thread", "global"]
    c = t.counters
    assert c["name"].tolist() == ["heap used", "heap total", "fps"]
    assert c["value"].tolist() == [10.0, 20.0, 60.0]
    f = t.flows
    # s binds to the slice it is in; f to the next slice on its thread; bind_id out → in
    assert list(zip(f["from_span"], f["to_span"], strict=True)) == [
        (ids["Layout"], ids["Recv"]),
        (ids["Out"], ids["In"]),
    ]
    follows = dict(zip(t.spans["name"].tolist(), t.spans["follows"].tolist(), strict=True))
    assert follows["Recv"] == [ids["Layout"]]
    p = Timeline().spans(t.spans, layout="flame", group="track", depends="follows")
    p.values(t.counters, lane="name", value="value")
    assert len(bars_of(p).links) == 2


def test_read_chrome_from_a_file(tmp_path) -> None:
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(CHROME))
    assert len(read_chrome(path).spans["span_id"]) == len(read_chrome(str(path)).spans["span_id"])
    empty = read_chrome([])
    assert len(empty.spans["span_id"]) == 0
    assert empty.spans["start"].dtype == np.dtype("timedelta64[ns]")
