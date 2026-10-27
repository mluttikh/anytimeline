"""The selection in numbers (``Timeline.summary``, and the panel's ``_summary``): counts by
lane and colour category; bars' total and mean duration; events' first and last time;
values' mean, least and greatest value; a table of the type plotted."""

from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl
import pyarrow as pa
import pytest

from anytimeline import Timeline
from anytimeline.data import NotFoundError
from anytimeline.synthetic import service_log

T0 = np.datetime64("2026-10-01T00:00:00", "ns")
H = np.timedelta64(3600, "s").astype("timedelta64[ns]")


def bars() -> dict[str, np.ndarray]:
    return {
        "task": np.array(["a", "b", "c", "d", "e"], dtype=object),
        "team": np.array(["x", "x", "y", "y", "y"], dtype=object),
        "kind": np.array(["dev", "ops", "dev", "dev", "ops"], dtype=object),
        "start": T0 + np.array([0, 1, 2, 3, 4]) * H,
        "end": np.array(
            [T0 + 2 * H, T0 + 2 * H, T0 + 5 * H, np.datetime64("NaT", "ns"), T0 + 4 * H]
        ),
    }


def test_bars_count_and_sum_their_durations_by_lane_and_category() -> None:
    plot = Timeline().intervals(bars(), lane="team", color="kind")
    plot.selection = {"intervals": [0, 1, 2, 3, 4]}
    s = plot.summary()
    assert list(s) == ["team", "kind", "count", "total", "mean", "open"]
    cols = (s["team"], s["kind"], s["count"], s["total"], s["open"])
    got = {(t, k): (c, tot, o) for t, k, c, tot, o in zip(*cols, strict=True)}
    assert got[("x", "dev")] == (1, 2 * H, 0)
    assert got[("x", "ops")] == (1, H, 0)
    assert got[("y", "dev")] == (2, 3 * H, 1)  # the open bar counts, without a duration
    assert got[("y", "ops")] == (1, np.timedelta64(0, "ns"), 0)  # a milestone
    assert s["mean"][list(s["team"]).index("y")] == 3 * H  # over the bars with an end


def test_only_the_selection_counts_and_nothing_selected_gives_no_rows() -> None:
    plot = Timeline().intervals(bars(), lane="team", color="kind")
    assert len(plot.summary()["count"]) == 0
    plot.selection = {"intervals": [2]}
    s = plot.summary()
    assert s["count"].tolist() == [1]
    assert s["total"][0] == 3 * H
    assert plot.summary(rows="all")["count"].sum() == 5
    with pytest.raises(ValueError, match="rows"):
        plot.summary(rows="some")  # ty: ignore[invalid-argument-type]


def test_events_give_their_first_and_last_time() -> None:
    log = service_log(200, seed=3)
    plot = Timeline().events(log, lane="service", color="level")
    s = plot.summary(rows="all")
    assert list(s) == ["service", "level", "count", "first", "last"]
    assert s["count"].sum() == len(log["time"])
    db = [i for i, v in enumerate(s["service"]) if v == "db"]
    times = log["time"][log["service"] == "db"]
    assert min(s["first"][i] for i in db) == times.min()
    assert max(s["last"][i] for i in db) == times.max()


def test_values_give_mean_least_and_greatest() -> None:
    data = {"time": T0 + np.arange(6) * H, "v": np.array([1.0, 2, 3, 10, np.nan, 30])}
    plot = Timeline().values(data, value="v")
    s = plot.summary(rows="all")
    assert s["count"].tolist() == [6]
    assert s["mean"][0] == pytest.approx(46 / 5)
    assert (s["min"][0], s["max"][0]) == (1.0, 30.0)


@pytest.mark.parametrize("make", [pl.DataFrame, pd.DataFrame, pa.table])
def test_the_table_is_of_the_type_plotted(make: type) -> None:
    plot = Timeline().intervals(make(bars()), lane="team", color="kind")
    s = plot.summary(rows="all")
    assert type(s) is type(make(bars()))
    assert (s.num_rows if isinstance(s, pa.Table) else len(s)) == 4


def test_times_are_in_the_plots_time_zone() -> None:
    log = pl.DataFrame(service_log(50, seed=1)).with_columns(
        pl.col("time").dt.replace_time_zone("Europe/Amsterdam")
    )
    s = Timeline().events(log, lane="service").summary(rows="all")
    assert s.schema["first"] == pl.Datetime("ns", "Europe/Amsterdam")


def test_groups_get_a_column_and_tell_lanes_apart() -> None:
    log = service_log(100, seed=2)
    hosts = np.where(np.arange(len(log["time"])) % 2 == 0, "h1", "h2").astype(object)
    plot = Timeline().events({**log, "host": hosts}, lane="service", group="host")
    s = plot.summary(rows="all")
    assert list(s)[:2] == ["group", "service"]
    assert {(g, v) for g, v in zip(s["group"], s["service"], strict=True)} >= {
        ("h1", "db"),
        ("h2", "db"),
    }
    plot.selection = {"events": list(range(40))}
    lanes = plot._summary[0]["blocks"][-1]["rows"]
    assert all(" · " in r["label"] for r in lanes)


def test_the_panel_shows_totals_by_category_and_by_lane_as_text() -> None:
    plot = Timeline().intervals(bars(), lane="team", color="kind")
    assert plot._summary == []
    plot.selection = {"intervals": [0, 1, 2, 3]}
    (layer,) = plot._summary
    assert layer["layer"] == "intervals"
    assert layer["columns"] == ["count", "total", "mean"]
    assert layer["total"] == {"count": "4", "total": "6 h", "mean": "2 h", "open": "1 open"}
    by_kind, by_team = layer["blocks"]
    assert by_kind["title"] == "kind"
    assert by_team["title"] == "team"
    assert [r["label"] for r in by_kind["rows"]] == ["dev", "ops"]  # the most first
    assert by_kind["rows"][0]["color"].startswith("#")
    assert by_team["rows"][0]["color"] is None
    plot.summary_panel = False
    assert plot._summary == []
    plot.summary_panel = True
    assert plot._summary
    plot.selection = {}
    assert plot._summary == []


def test_the_panel_goes_into_pages() -> None:
    plot = Timeline().intervals(bars(), lane="team")
    plot.selection = {"intervals": [1]}
    assert '"summary":[{"layer":"intervals"' in plot.to_html()


def test_the_layer_must_be_named_among_several() -> None:
    plot = Timeline().intervals(bars(), lane="team").events(service_log(20, seed=1), lane="service")
    with pytest.raises(ValueError, match="name the layer"):
        plot.summary()
    with pytest.raises(NotFoundError):
        plot.summary("nope")
    assert plot.summary("events", rows="all")["count"].sum() == len(service_log(20, seed=1)["time"])
