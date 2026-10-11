from typing import Any

import numpy as np
import pytest

from anytimeline import Timeline
from anytimeline.intervals import IntervalsRecord
from anytimeline.synthetic import service_health, service_metrics

T = np.array(
    [
        "2026-10-12T08:00",
        "2026-10-12T08:10",
        "2026-10-12T08:12",
        "2026-10-12T08:30",
        "2026-10-12T08:05",
        "2026-10-12T08:20",
        "2026-10-12T08:40",
    ],
    dtype="datetime64[m]",
)
CHANGES = {
    "time": T,
    "service": ["api", "api", "api", "api", "db", "db", "db"],
    "state": ["up", "up", "degraded", "up", "up", None, "down"],
}


def states_of(plot: Timeline) -> IntervalsRecord:
    rec = plot._layers["states"]
    assert isinstance(rec, IntervalsRecord)
    return rec


def minutes(times):
    return [int(v) for v in (times.raw * times.per // 60_000_000_000) % 1440]


def test_states_join_repeats_and_leave_gaps():
    plot = Timeline().states(CHANGES, lane="service")
    rec = states_of(plot)
    # api: up 8:00 (8:10 repeats it) → degraded 8:12 → up 8:30 (open); db: up → gap → down
    assert rec.rows.tolist() == [0, 2, 3, 4, 6]
    assert rec.text == ["up", "degraded", "up", "up", "down"]
    assert minutes(rec.starts) == [480, 492, 510, 485, 520]
    assert rec.ends.valid.tolist() == [True, True, False, True, False]
    assert minutes(rec.ends)[:2] == [492, 510]
    assert minutes(rec.ends)[3] == 500  # db's up ends where its gap starts
    layer = plot._spec["layers"][0]
    assert layer["fade_open"] is False
    assert layer["color"]["legend"]["title"] == "state"


def test_states_end_and_order_of_rows():
    shuffled: dict[str, Any] = {
        k: list(np.asarray(v, dtype=object)[[6, 0, 3, 1, 5, 2, 4]]) for k, v in CHANGES.items()
    }
    shuffled["time"] = T[[6, 0, 3, 1, 5, 2, 4]]
    plot = Timeline().states(shuffled, lane="service", end=np.datetime64("2026-10-12T09:00"))
    rec = states_of(plot)
    assert rec.ends.valid.all()  # the last states end at end=
    assert sorted(minutes(rec.ends))[-2:] == [540, 540]
    with pytest.raises(ValueError, match="before the last change"):
        Timeline().states(CHANGES, lane="service", end=np.datetime64("2026-10-12T08:35"))


def test_states_simultaneous_changes_draw_no_empty_bar():
    d = {"time": np.array([0, 5, 5, 9]), "state": ["a", "b", "c", "a"]}
    rec = states_of(Timeline().states(d))
    assert rec.text == ["a", "c", "a"]


def test_values_runs_ranges_and_extent():
    t = np.datetime64("2026-10-12T08:00", "s") + np.arange(0, 600, 60).astype("timedelta64[s]")
    d = {
        "time": np.concatenate([t, t, t]),
        "service": ["api"] * 20 + ["db"] * 10,
        "quantile": ["p50"] * 10 + ["p99"] * 10 + ["p50"] * 10,
        "ms": np.concatenate([np.full(10, 5.0), np.full(10, 40.0), np.linspace(100, 200, 10)]),
    }
    d["ms"][3] = np.nan
    plot = Timeline().values(d, value="ms", lane="service", series="quantile")
    layer = plot._spec["layers"][0]
    assert layer["runs"]["count"] == 3
    assert layer["series"] == ["p50", "p99", "p50"]
    assert layer["color"]["legend"]["title"] == "quantile"
    lay = plot._laid["values"]
    assert lay.instants == []
    assert plot._spec["sequence"] is None  # samples alone have no order
    assert plot._spec["time"]["extent"] == [0.0, 540.0]
    ylim = np.frombuffer(plot._buffers[layer["ylim"]["id"]], dtype=np.float64).reshape(-1, 2)
    assert ylim.tolist() == [[0.0, 40.0], [100.0, 200.0]]  # api from 0: its low is near it


def test_values_behind_events_take_no_place_in_the_order():
    t = np.arange(0, 100, 1.0)
    plot = Timeline()
    plot.events({"time": np.array([10.0, 50.0]), "lane": ["a", "a"]}, lane="lane")
    plot.values({"time": t, "lane": ["a"] * 100, "value": t**2}, lane="lane", ylim=(0, 1e4))
    assert plot._spec["sequence"]["count"] == 2
    assert plot._spec["time"]["extent"] == [0.0, 99.0]
    assert plot._spec["lanes"]["names"] == ["a"]
    with pytest.raises(ValueError, match="ylim"):
        plot.values({"time": t, "value": t}, ylim=(1, 1))
    with pytest.raises(ValueError, match="kind"):
        plot.values({"time": t, "value": t}, kind="bars")  # ty: ignore[invalid-argument-type]


def test_values_tooltip_and_selection():
    t = np.arange(5.0)
    plot = Timeline().values({"time": t, "value": t, "host": list("abcde")}, tooltip=["host"])
    assert plot._tooltip("values", 2) == [["host", "c"]]
    plot._pick = {
        "kind": "box",
        "x": [0, 5],
        "lanes": [0, 0],
        "xscale": "time",
        "mode": "replace",
        "n": 1,
    }
    assert plot.selection == {}  # samples are not selectable


def test_synthetic_health_and_metrics():
    m = service_metrics(400, seed=1)
    assert set(m["service"]) == {"gateway", "auth", "api", "db", "cache"}
    assert ((m["cpu"] >= 0) & (m["cpu"] <= 100)).all()
    h = service_health(400, seed=1)
    assert set(h["state"]) <= {"up", "degraded", "down"}
    assert "down" in set(h["state"])
    plot = Timeline().states(h, lane="service", tooltip=["reason"])
    text = states_of(plot).text
    assert text is not None
    i = text.index("down")
    assert plot._tooltip("states", i) == [["state", "down"], ["reason", "restarting"]]
    Timeline().states(h, lane="service").values(m, value="cpu", lane="service")
