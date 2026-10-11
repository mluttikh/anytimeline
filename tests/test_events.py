import numpy as np
import pandas as pd
import polars as pl
import pyarrow as pa
import pytest

from anytimeline import Route, Timeline
from anytimeline.codec import decode, decode_strings
from anytimeline.data import NotFoundError
from anytimeline.synthetic import service_log


def buffer(plot, ref):
    return decode(ref, plot._buffers[ref["id"]])


def small():
    return {
        "time": np.array(
            [
                "2026-01-01T00:00:03",
                "2026-01-01T00:00:01",
                "2026-01-01T00:00:02",
                "2026-01-01T00:00:01",
            ],
            dtype="datetime64[ms]",
        ),
        "lane": ["b", "a", "a", "b"],
        "kind": ["x", "y", "x", "y"],
        "seq": [4, 1, 3, 2],
    }


def test_events_are_sorted_by_lane_then_time():
    plot = Timeline().events(small(), lane="lane", color="kind")
    layer = plot._spec["layers"][0]
    assert plot._spec["lanes"]["names"] == ["a", "b"]
    assert buffer(plot, layer["lane"]).tolist() == [0, 0, 1, 1]
    assert buffer(plot, layer["time"]).tolist() == [0.0, 1.0, 0.0, 2.0]
    assert buffer(plot, layer["lane_starts"]).tolist() == [0, 2, 4]
    # ranks: the order of all events by time (ties by table order)
    assert buffer(plot, layer["rank"]).tolist() == [0.0, 2.0, 1.0, 3.0]
    assert layer["color"]["legend"]["items"] == [
        {"label": "x", "color": "#1f77b4"},
        {"label": "y", "color": "#ff7f0e"},
    ]


def test_every_kind_of_table_gives_the_same_spec():
    data = small()
    tables = [
        data,
        pd.DataFrame(data),
        pl.DataFrame(data),
        pa.table(data),
        pl.DataFrame(data).lazy(),
    ]
    specs = []
    for table in tables:
        plot = Timeline().events(table, lane="lane", color="kind", order="seq")
        layer = plot._spec["layers"][0]
        specs.append([buffer(plot, layer[k]).tolist() for k in ("time", "lane", "rank")])
    assert all(s == specs[0] for s in specs)


def test_order_breaks_ties_and_can_stand_alone():
    plot = Timeline().events(small(), lane="lane", order="seq")
    layer = plot._spec["layers"][0]
    # the two events at 00:00:01: seq 1 (lane a) before seq 2 (lane b)
    assert buffer(plot, layer["rank"]).tolist() == [0.0, 2.0, 1.0, 3.0]
    steps = Timeline().events({"step": [3, 1, 2]}, time=None, order="step")
    assert steps._spec["time"]["kind"] == "order"
    assert steps._spec["sequence"]["count"] == 3


def test_missing_times_are_dropped_and_counted():
    data = small()
    data["time"] = data["time"].copy()
    data["time"][0] = np.datetime64("NaT", "ms")
    plot = Timeline().events(data, lane="lane")
    assert plot._spec["layers"][0]["count"] == 3
    assert plot._spec["layers"][0]["dropped"] == 1


def test_routes_join_each_group_in_time_order():
    data = {
        "time": np.array([1, 5, 3, 2, 4], dtype="timedelta64[s]"),
        "lane": ["a", "b", "a", "b", "a"],
        "req": ["r1", "r1", "r1", "r2", "r2"],
    }
    plot = Timeline().events(data, lane="lane", route=Route("req", color="theme"))
    layer = plot._spec["layers"][0]
    seg = buffer(plot, layer["route"]["segments"]).reshape(-1, 2)
    times = buffer(plot, layer["time"])
    # sorted index space: a: t1(r1) t3(r1) t4(r2); b: t2(r2) t5(r1)
    pairs = {(times[i], times[j]) for i, j in seg}
    assert pairs == {(0.0, 2.0), (2.0, 4.0), (1.0, 3.0)}
    assert layer["route"]["color"] == "theme"


def test_text_templates_symbols_and_sizes():
    data = small()
    data["n"] = [1.0, 2.0, 3.0, 4.0]
    plot = Timeline().events(data, lane="lane", text="{kind}/{n}", symbol="kind", size="n")
    layer = plot._spec["layers"][0]
    texts = decode_strings(layer["text"], plot._buffers[layer["text"]["id"]])
    assert sorted(texts) == ["x/1.0", "x/3.0", "y/2.0", "y/4.0"]
    assert layer["symbol"]["legend"]["items"] == [
        {"label": "x", "symbol": "circle"},
        {"label": "y", "symbol": "square"},
    ]
    sizes = buffer(plot, layer["size"]["values"])
    assert sizes.min() == pytest.approx(4.0)
    assert sizes.max() == pytest.approx(16.0)


def test_colours_one_colour_numbers_and_errors():
    data = small()
    plot = Timeline().events(data, lane="lane", color="#ff0000", opacity=0.5)
    color = plot._spec["layers"][0]["color"]
    assert color["solid"] == "#ff0000"
    assert color["alpha"] == 128
    data["v"] = [0.0, 1.0, 2.0, 3.0]
    plot = Timeline().events(data, lane="lane", color="v", colormap="viridis")
    assert plot._spec["layers"][0]["color"]["legend"]["kind"] == "continuous"
    with pytest.raises(NotFoundError, match="neither a column nor a colour"):
        Timeline().events(data, lane="lane", color="nope")
    with pytest.raises(NotFoundError, match="columns not found"):
        Timeline().events(data, lane="missing")


def test_lane_order_and_sorting():
    plot = Timeline(lane_order=["b"]).events(small(), lane="lane")
    assert plot._spec["lanes"]["names"] == ["b", "a"]
    plot = Timeline(sort="count").events(
        {"time": np.arange(4).astype("timedelta64[s]"), "lane": ["a", "b", "b", "c"]}, lane="lane"
    )
    assert plot._spec["lanes"]["names"][0] == "b"
    plot = Timeline().events(
        {"time": np.arange(3).astype("timedelta64[s]"), "lane": ["w10", "w9", "w1"]}, lane="lane"
    )
    assert plot._spec["lanes"]["names"] == ["w1", "w9", "w10"]
    df = pl.DataFrame(
        {"time": np.arange(3).astype("timedelta64[ms]"), "lane": ["lo", "hi", "mid"]}
    ).with_columns(pl.col("lane").cast(pl.Enum(["hi", "mid", "lo"])))
    assert Timeline().events(df, lane="lane")._spec["lanes"]["names"] == ["hi", "mid", "lo"]


def test_layers_share_lanes_time_and_order():
    log = service_log(50)
    plot = Timeline()
    plot.events(log, lane="service", name="all")
    errors = {k: v[log["level"] == "info"][:5] for k, v in log.items()}
    plot.events(errors, lane="service", name="few", symbol="x")
    assert plot.layers == ["all", "few"]
    total = sum(layer["count"] for layer in plot._spec["layers"])
    assert plot._spec["sequence"]["count"] == total
    ranks = np.concatenate([buffer(plot, layer["rank"]) for layer in plot._spec["layers"]])
    assert sorted(ranks.tolist()) == list(range(total))
    plot.remove("few")
    assert plot.layers == ["all"]
    with pytest.raises(TypeError, match="one kind"):
        plot.events({"t": [1.0, 2.0]}, time="t", name="numbers")
    assert plot.layers == ["all"]  # a failed layer leaves the plot as it was
