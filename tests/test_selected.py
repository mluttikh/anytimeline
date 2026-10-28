import warnings

import numpy as np
import pandas as pd
import polars as pl
import pytest

from anytimeline import Timeline
from anytimeline.data import NotFoundError
from anytimeline.synthetic import service_log

LOG = service_log(20)


def test_selected_gives_the_selected_rows_as_the_table_plotted():
    df = pd.DataFrame(LOG).set_index(pd.RangeIndex(100, 100 + len(LOG["seq"])))
    plot = Timeline().events(df, lane="service")
    plot.selection = {"events": [2, 5]}
    picked = plot.selected()
    assert isinstance(picked, pd.DataFrame)
    assert list(picked.index) == [102, 105]
    assert list(picked["request"]) == [LOG["request"][2], LOG["request"][5]]


def test_nothing_selected_gives_no_rows_of_the_same_type():
    plot = Timeline().events(pl.DataFrame(LOG), lane="service")
    picked = plot.selected("events")
    assert isinstance(picked, pl.DataFrame)
    assert picked.height == 0
    assert picked.columns == list(LOG)
    as_dict = Timeline().events(LOG, lane="service").selected()
    assert {k: len(v) for k, v in as_dict.items()} == dict.fromkeys(LOG, 0)


def test_a_dict_of_lists_gives_lists():
    data = {"time": [1.0, 2.0, 3.0], "lane": ["a", "b", "a"], "ids": [[1], [2, 3], []]}
    plot = Timeline().events(data, lane="lane")
    plot.selection = {"events": [1, 2]}
    assert plot.selected() == {"time": [2.0, 3.0], "lane": ["b", "a"], "ids": [[2, 3], []]}


def test_selected_names_the_layer():
    plot = Timeline().events(LOG, lane="service").events(LOG, lane="user", name="users")
    with pytest.raises(ValueError, match="name the layer"):
        plot.selected()
    with pytest.raises(NotFoundError, match="no layer 'nope'"):
        plot.selected("nope")
    with pytest.raises(ValueError, match="name the layer"):
        Timeline().selected()
    plot.remove("users")
    assert len(plot.selected()["seq"]) == 0


def test_a_lazy_table_is_read_once_with_the_columns_used():
    lazy = pl.DataFrame(LOG).lazy()
    plot = Timeline().events(
        lazy, lane="service", color=None, text="{event}!", tooltip=["user"], order="seq"
    )
    table = plot._tables["events"]
    assert isinstance(table, pl.DataFrame)
    assert sorted(table.columns) == ["event", "seq", "service", "time", "user"]
    plot.selection = {"events": [0, 3]}
    assert plot.selected()["user"].to_list() == [LOG["user"][0], LOG["user"][3]]


def test_an_ibis_table_is_read_once_with_the_columns_used():
    import ibis
    import pyarrow as pa

    table = ibis.memtable(pl.DataFrame(LOG).to_arrow()).order_by("seq")
    plot = Timeline().events(table, lane="service", color=None, tooltip=["user"], order="seq")
    read = plot._tables["events"]
    assert isinstance(read, pa.Table)
    assert sorted(read.column_names) == ["seq", "service", "time", "user"]
    plot.selection = {"events": [0, 3]}
    assert plot.selected()["user"].to_pylist() == [LOG["user"][0], LOG["user"][3]]


def test_an_ibis_table_gives_intervals():
    import ibis

    bars = {"lane": ["a", "b", "a"], "start": [0.0, 1.0, 2.0], "end": [1.5, 3.0, 2.5]}
    table = ibis.memtable(pl.DataFrame(bars).to_arrow()).order_by("start")
    plot = Timeline().intervals(table, start="start", end="end", lane="lane")
    assert plot._tables["intervals"].num_rows == 3
    plot.selection = {"intervals": [1]}
    assert plot.selected()["lane"].to_pylist() == ["b"]


def test_a_route_reads_its_group_column():
    from anytimeline import Route

    lazy = pl.DataFrame(LOG).lazy()
    plot = Timeline().events(lazy, lane="service", route=Route("request"))
    assert "request" in plot._tables["events"].columns


def test_a_failed_layer_keeps_no_table():
    plot = Timeline().events(LOG, lane="service")
    with pytest.raises(NotFoundError):
        plot.events(LOG, lane="nope", name="bad")
    assert list(plot._tables) == ["events"]
    plot.clear()
    assert plot._tables == {}


def test_marimo_selection_follows_the_plot():
    pytest.importorskip("marimo")
    import anytimeline.marimo

    plot = Timeline().events(LOG, lane="service")
    get = anytimeline.marimo.selection(plot)
    assert get() == {}
    plot.selection = {"events": [1, 4]}
    assert get() == {"events": [1, 4]}
    # its cell run again: the new state follows the plot, the old one no longer
    again = anytimeline.marimo.selection(plot)
    plot.selection = {"events": [2]}
    assert again() == {"events": [2]}
    assert get() == {"events": [1, 4]}


def warned(**kwargs) -> list[str]:
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        Timeline(**kwargs.pop("plot", {})).events(**kwargs)
    return [str(w.message) for w in seen if w.filename == __file__]


def test_epoch_numbers_read_as_nanoseconds_warn():
    seconds = np.array([1_760_000_000, 1_760_000_060], dtype=np.int64)
    data = {"time": seconds.astype("datetime64[ns]"), "lane": ["a", "b"]}
    [message] = warned(data=data, lane="lane")
    assert "January 1970" in message
    assert "'time'" in message


def test_epoch_numbers_drawn_as_numbers_warn():
    for unit, scale in {"s": 1, "ms": 1_000, "us": 1_000_000, "ns": 1_000_000_000}.items():
        data = {"t": np.array([1_760_000_000, 1_760_000_060]) * scale, "lane": ["a", "b"]}
        [message] = warned(data=data, time="t", lane="lane")
        assert f"unit={unit!r}" in message
        assert "2025-10-09" in message


def test_plausible_times_do_not_warn():
    assert warned(data=LOG, lane="service") == []
    assert warned(data={"time": [0.5, 2.5, 10.0], "lane": ["a"] * 3}, lane="lane") == []
    # durations: a unit given
    data = {"time": [1_760_000_000, 1_760_000_060], "lane": ["a", "b"]}
    assert warned(data=data, lane="lane", plot={"time_unit": "s"}) == []


def test_durations_as_end_say_what_to_pass():
    start = LOG["time"][:3]
    data = {"start": start, "end": np.array([1, 2, 3], dtype="timedelta64[s]"), "lane": list("abc")}
    with pytest.raises(TypeError, match="duration='end'"):
        Timeline().intervals(data, start="start", end="end", lane="lane")
