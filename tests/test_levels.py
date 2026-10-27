"""Levels of detail (``anytimeline.levels``): a layer of many events is sent as counts per
lane and bin, and its events in windows the browser asks for. The thresholds are lowered
here, so that small tables are sent as levels."""

import json

import numpy as np
import pytest
from test_spec_contract import check

from anytimeline import Route, Timeline, levels
from anytimeline.codec import decode, decode_strings
from anytimeline.layers import events as ev
from anytimeline.layers import intervals as iv
from anytimeline.layers import values as vl
from anytimeline.levels import Grid, bin_marks, fit_range, gaps, pyramid
from anytimeline.synthetic import instants, service_log


@pytest.fixture
def small(monkeypatch):
    """Layers of more than 100 events are sent as levels."""
    monkeypatch.setattr(levels, "LEVELS_FROM", 100)
    monkeypatch.setattr(levels, "RAW_MARKS", 50)
    monkeypatch.setattr(levels, "LEVEL_BINS", 400)
    monkeypatch.setattr(levels, "WINDOW_MARKS", 300)
    monkeypatch.setattr(levels, "SEQUENCE_STEP_TO", 64)


def events_of(plot):
    """The layer's events in the browser's order."""
    lay = plot._laid["events"]
    assert isinstance(lay, ev.Layout)
    return lay.marks


def sequence(plot):
    """Every instant's time, in the order."""
    assert plot._scene is not None
    assert plot._scene.sequence is not None
    return plot._scene.sequence


def buffer(plot, ref):
    data = plot._buffers.get(ref["id"]) or plot._window_buffers[ref["id"]]
    return decode(ref, data)


def brute(x, lane, n_lanes, grid, k, imp=None, codes=None, n_codes=0):
    """The bins of level k, one by one."""
    j = np.floor((x - grid.x0) / grid.width(k)).astype(np.int64)
    out = []
    for key in sorted(set(zip(lane.tolist(), j.tolist(), strict=True))):
        idx = np.flatnonzero((lane == key[0]) & (j == key[1]))
        top = idx[np.argmax(imp[idx])] if imp is not None else idx[0]
        dom = (
            int(np.bincount(codes[idx], minlength=n_codes).argmax()) if codes is not None else None
        )
        out.append((key[0], x[idx].min(), x[idx].max(), len(idx), top, dom))
    return out


def test_bins_hold_their_marks_first_last_count_top_and_colour():
    rng = np.random.default_rng(3)
    n, n_lanes = 2000, 5
    lane = np.sort(rng.integers(0, n_lanes, n))
    x = np.concatenate(
        [np.sort(rng.uniform(0, 100, int((lane == i).sum()))) for i in range(n_lanes)]
    )
    imp = rng.uniform(0, 1, n)
    codes = rng.integers(0, 3, n).astype(np.int32)
    grid = Grid.over((0.0, 100.0))
    for k in (0, 1, 2):
        b = bin_marks(x, lane, n_lanes, grid, k, importance=imp, codes=codes, n_codes=3)
        want = brute(x, lane, n_lanes, grid, k, imp, codes, 3)
        assert len(b) == len(want)
        assert b.lo.tolist() == [w[1] for w in want]
        assert b.hi.tolist() == [w[2] for w in want]
        assert b.count.tolist() == [w[3] for w in want]
        assert b.top.tolist() == [w[4] for w in want]
        assert b.dominant is not None
        assert b.dominant.tolist() == [w[5] for w in want]
        lanes = np.repeat(np.arange(n_lanes), np.diff(b.lane_starts))
        assert lanes.tolist() == [w[0] for w in want]
        assert int(b.count.sum()) == n


def test_without_importance_a_bin_stands_for_its_first_mark():
    x = np.array([0.0, 0.1, 0.2, 50.0])
    b = bin_marks(x, np.zeros(4, dtype=np.int64), 1, Grid.over((0.0, 100.0)), 0)
    assert b.top.tolist() == [0, 3]
    assert b.count.tolist() == [3, 1]


def test_the_levels_go_down_to_the_finest_with_few_enough_bins(monkeypatch):
    monkeypatch.setattr(levels, "LEVEL_BINS", 300)
    rng = np.random.default_rng(1)
    x = np.sort(rng.uniform(0, 1000, 5000))
    made = pyramid(x, np.zeros(5000, dtype=np.int64), 1, Grid.over((0.0, 1000.0)))
    assert [b.k for b in made] == [0]  # level 1 has up to 1,024 bins
    assert all(len(b) <= 300 for b in made)
    # many lanes: coarser than level 0, so that the first level is small
    lane = np.sort(rng.integers(0, 40, 5000))
    x = np.concatenate([np.sort(rng.uniform(0, 1000, int((lane == i).sum()))) for i in range(40)])
    made = pyramid(x, lane, 40, Grid.over((0.0, 1000.0)))
    assert made[0].k < 0
    assert len(made[0]) <= 300


def test_a_range_is_cut_to_its_middle_to_hold_few_enough():
    x = np.arange(1000.0)
    count = levels.count_in(x, np.array([0, 1000]))
    assert fit_range(count, 0, 999, 2000) == (0, 999)
    a, b = fit_range(count, 0, 999, 100)
    assert 90 <= count(a, b) <= 100
    assert abs((a + b) / 2 - 499.5) < 1e-6


def test_gaps_are_the_browsers():
    # over 20× the median gap; at most one per 50 instants, the longest
    times = np.array([0, 1, 2, 3, 100, 101, 102, 500, 501], dtype=float)
    assert gaps(times).tolist() == [[6.5, 398.0]]
    times = np.concatenate([np.arange(100.0), 1000 + np.arange(100.0), 5000 + np.arange(100.0)])
    assert gaps(times).tolist() == [[99.5, 901.0], [199.5, 3901.0]]
    assert gaps(np.array([0.0, 1.0])).shape == (0, 2)


def big_log():
    """600 events on 10 lanes."""
    return instants(600, lanes=10, seed=2)


def test_a_large_layer_is_sent_as_levels(small):
    plot = Timeline().events(big_log(), lane="lane", color="kind", importance="value")
    check(plot._spec)
    layer = plot._spec["layers"][0]
    assert layer["count"] == 0  # its events come in windows
    lv = layer["levels"]
    assert lv["total"] == 600
    assert lv["raw"] == 50
    assert lv["windows"] is True
    legend = [item["label"] for item in layer["color"]["legend"]["items"]]
    assert lv["categories"][: len(legend)] == legend
    for scale in ("time", "order"):
        first = lv[scale]["levels"][0]
        assert sum(buffer(plot, first["n"]).tolist()) == 600
        assert first["rgba"] is not None
    seq = plot._spec["sequence"]
    assert seq["count"] == 600
    assert seq["step"] > 1
    assert "gaps" in seq
    assert len(buffer(plot, seq["times"])) <= 65


def test_small_layers_and_stories_are_sent_whole(small):
    plot = Timeline().events(service_log(10), lane="service")
    assert "levels" not in plot._spec["layers"][0]
    assert "step" not in plot._spec["sequence"]


def test_a_window_holds_the_events_of_its_range(small):
    log = big_log()
    plot = Timeline().events(log, lane="lane", color="kind", route=Route("kind"))
    t0, t1 = plot._spec["time"]["extent"]
    a, b = t0 + (t1 - t0) * 0.4, t0 + (t1 - t0) * 0.5
    answer = plot._window({"layer": "events", "scale": "time", "range": [a, b], "k": None})
    spec = answer["spec"]
    check({**plot._spec, "layers": [spec]})
    times = buffer(plot, spec["time"])
    index = buffer(plot, spec["index"])
    assert answer["range"] == [a, b]
    assert ((times >= a) & (times <= b)).all()
    marks = events_of(plot)
    inside = np.flatnonzero((marks.primary >= a) & (marks.primary <= b))
    assert sorted(index.tolist()) == inside.tolist()
    assert (np.diff(index) > 0).all()
    assert buffer(plot, spec["rank"]).tolist() == plot._ranks["events"][index, 0].tolist()
    lane = buffer(plot, spec["lane"])
    assert (
        buffer(plot, spec["lane_starts"]).tolist() == np.searchsorted(lane, np.arange(11)).tolist()
    )
    # the route's segments join the window's events
    seg = buffer(plot, spec["route"]["segments"])
    assert seg.max() < len(times)
    # the exact times of the order there
    seq = answer["sequence"]
    times_all = sequence(plot)
    assert (
        buffer(plot, seq["times"]).tolist()
        == times_all[seq["offset"] : seq["offset"] + seq["times"]["count"]].tolist()
    )


def test_a_window_too_wide_is_cut(small):
    plot = Timeline().events(big_log(), lane="lane")
    t0, t1 = plot._spec["time"]["extent"]
    answer = plot._window({"layer": "events", "scale": "time", "range": [t0, t1], "k": None})
    assert answer["spec"]["count"] <= 300
    assert t0 < answer["range"][0] < answer["range"][1] < t1


def test_a_window_of_bins_and_one_on_the_order_scale(small):
    plot = Timeline().events(big_log(), lane="lane", color="kind")
    lv = plot._spec["layers"][0]["levels"]
    finest = lv["order"]["levels"][-1]["k"]
    answer = plot._window(
        {"layer": "events", "scale": "order", "range": [100, 300], "k": finest + 1}
    )
    spec = answer["spec"]
    assert spec["k"] == finest + 1
    assert spec["range"] == [100, 300]
    assert sum(buffer(plot, spec["n"]).tolist()) == 201  # ranks 100 .. 300
    raw = plot._window({"layer": "events", "scale": "order", "range": [100, 199], "k": None})
    assert sorted(buffer(plot, raw["spec"]["rank"]).tolist()) == list(range(100, 200))


def test_windows_buffers_are_kept_for_the_last_few(small):
    plot = Timeline().events(big_log(), lane="lane")
    t0, _t1 = plot._spec["time"]["extent"]
    for i in range(12):
        plot._window({"layer": "events", "scale": "time", "range": [t0 + i, t0 + i + 2], "k": None})
    assert len(plot._windows) == 8
    assert set(plot._window_buffers) == {i for ids in plot._windows for i in ids}


def test_a_bin_tooltip_counts_its_events_by_colour(small):
    log = big_log()
    plot = Timeline().events(log, lane="lane", color="kind")
    marks = events_of(plot)
    lane = int(marks.lane[0])
    on = np.flatnonzero(marks.lane == lane)
    a, b = float(marks.primary[on[0]]), float(marks.primary[on[40]])
    rows = plot._bin_tooltip({"layer": "events", "scale": "time", "lane": lane, "range": [a, b]})
    assert sum(int(r[1].replace(",", "")) for r in rows) == 41
    counts = [int(r[1].replace(",", "")) for r in rows]
    assert counts == sorted(counts, reverse=True)


def test_selecting_in_a_layer_sent_as_levels(small):
    log = big_log()
    plot = Timeline().events(log, lane="lane")
    t0, t1 = plot._spec["time"]["extent"]
    plot._on_pick(
        {
            "new": {
                "kind": "box",
                "x": [t0, t1],
                "lanes": [0, 9],
                "mode": "replace",
                "layer": "events",
            }
        }
    )
    assert len(plot.selection["events"]) == 600
    plot._on_pick({"new": {"kind": "click", "layer": "events", "index": 5, "mode": "replace"}})
    assert plot.selection["events"] == [
        int(plot._layers["events"].rows[plot._layers["events"].perm[5]])
    ]


def test_selected_events_of_a_layer_sent_as_levels_are_placed_for_its_bins(small):
    plot = Timeline().events(big_log(), lane="lane")
    plot.selection = {"events": [3, 10, 200]}
    at = np.frombuffer(plot._marked["events"], dtype="<f8").reshape(-1, 3)
    marks = events_of(plot)
    index = np.frombuffer(plot._marks["events"], dtype="<i4")
    assert at[:, 0].tolist() == marks.primary[index].tolist()
    assert at[:, 1].tolist() == plot._ranks["events"][index, 0].tolist()
    assert at[:, 2].tolist() == marks.lane[index].tolist()
    plot.selection = {}
    assert plot._marked == {}
    # layers sent whole show their selection themselves
    small_plot = Timeline().events(service_log(10), lane="service")
    small_plot.selection = {"events": [1]}
    assert small_plot._marked == {}


def test_a_page_holds_every_event_or_the_levels(small, monkeypatch, tmp_path):
    plot = Timeline().events(big_log(), lane="lane")
    spec, _ = plot._page_data()
    assert "levels" not in spec["layers"][0]
    assert spec["layers"][0]["count"] == 600
    from anytimeline import page

    monkeypatch.setattr(page, "FULL_BYTES", 100)
    plot._page = None
    spec, _ = plot._page_data()
    assert spec["layers"][0]["levels"]["windows"] is False
    out = plot.save_html(tmp_path / "p.html")
    payload = out.read_text().split('<script type="application/json">')[1].split("</script>")[0]
    data = json.loads(payload)
    assert data["spec"]["layers"][0]["levels"]["total"] == 600
    ids = {r["id"] for r in [data["spec"]["layers"][0]["levels"]["time"]["levels"][0]["lo"]]}
    assert ids <= set(data["buffers"])


# ---------------------------------------------------------------------- values layers


def values_plot(n=3000, **kw):
    from kinds import many_samples

    return Timeline().values(
        many_samples(n), lane="lane", value="cpu", series="series", tooltip=["id"], **kw
    )


def samples_of(plot):
    lay = plot._laid["values"]
    assert isinstance(lay, vl.Layout)
    return lay.samples


def test_m4_keeps_each_runs_first_lowest_highest_last_and_gap_per_bin():
    plot = values_plot(400)
    s = samples_of(plot)
    grid = Grid.over((float(s.time.min()), float(s.time.max())))
    every = np.arange(len(s.time))
    for k in (0, 2, 4):
        kept = set(vl.m4(s, every, grid, k).tolist())
        j = np.floor((s.time - grid.x0) / grid.width(k)).astype(np.int64)
        run = np.searchsorted(s.run_starts, every, side="right") - 1
        want = set()
        for key in set(zip(run.tolist(), j.tolist(), strict=True)):
            idx = np.flatnonzero((run == key[0]) & (j == key[1]))
            v = s.value[idx]
            want |= {int(idx[0]), int(idx[-1])}
            if np.isfinite(v).any():
                want |= {int(idx[np.nanargmin(v)]), int(idx[np.nanargmax(v)])}
            if np.isnan(v).any():
                want.add(int(idx[np.flatnonzero(np.isnan(v))[0]]))
        assert kept == want


def test_a_values_layer_of_many_samples_is_sent_as_levels(small):
    plot = values_plot()
    check(plot._spec)
    layer = plot._spec["layers"][0]
    assert layer["count"] == 0
    assert layer["width"] == 1.5  # the line's, not a bin's
    lv = layer["levels"]
    assert lv["total"] == 3000
    counts = [level["count"] for level in lv["levels"]]
    assert counts == sorted(counts)
    s = samples_of(plot)
    for level in lv["levels"]:
        assert level["width"] == layer["width"]
        index = buffer(plot, level["index"])
        assert (np.diff(index.astype(np.int64)) > 0).all()
        # every run's first and last sample
        assert set(s.run_starts[:-1].tolist()) <= set(index.tolist())
        assert set((s.run_starts[1:] - 1).tolist()) <= set(index.tolist())
        assert buffer(plot, level["time"]).tolist() == s.time[index].tolist()
        starts = buffer(plot, level["runs"]["starts"])
        assert starts[-1] == level["count"]
    # events are not in the order: none was sent as levels
    assert "step" not in (plot._spec["sequence"] or {})


def test_a_values_window_has_the_samples_of_its_range_or_a_finer_level(small, monkeypatch):
    plot = values_plot()
    s = samples_of(plot)
    t0, t1 = plot._spec["time"]["extent"]
    a, b = t0 + (t1 - t0) * 0.4, t0 + (t1 - t0) * 0.41
    answer = plot._window({"layer": "values", "scale": "time", "range": [a, b], "k": 9})
    assert answer["k"] is None  # few: every sample there
    spec = answer["spec"]
    check({**plot._spec, "layers": [spec]})
    index = buffer(plot, spec["index"])
    inside = set(np.flatnonzero((s.time >= a) & (s.time <= b)).tolist())
    got = set(index.tolist())
    assert inside <= got
    # and one beyond each end per run
    assert len(got - inside) <= 2 * (len(s.run_starts) - 1)
    # many: those of level k
    monkeypatch.setattr(levels, "RAW_MARKS", 10)
    answer = plot._window({"layer": "values", "scale": "time", "range": [t0, t1], "k": 2})
    assert answer["k"] == 2
    assert answer["spec"]["k"] == 2
    # (the range cut to hold at most WINDOW_MARKS)
    a, b = answer["range"]
    assert t0 < a < b < t1
    rows = vl.window_rows(s, a, b)
    assert len(rows) <= 300 + 2 * (len(s.run_starts) - 1)
    assert plot._scene is not None
    grid = plot._scene.detail["values"].grid
    want = vl.m4(s, rows, grid, 2)
    assert buffer(plot, answer["spec"]["index"]).tolist() == want.tolist()


def test_a_values_tooltip_takes_the_samples_index_among_the_layers(small):
    plot = values_plot()
    lv = plot._spec["layers"][0]["levels"]["levels"][0]
    i = int(buffer(plot, lv["index"])[7])
    rec = plot._layers["values"]
    assert plot._tooltip("values", i) == [["id", str(int(rec.perm[i]))]]


def test_without_levels_and_pages_of_values(small, monkeypatch):
    plot = values_plot()
    spec, _ = plot._page_data()
    assert spec["layers"][0]["count"] == 3000
    from anytimeline import page

    monkeypatch.setattr(page, "FULL_BYTES", 100)
    plot._page = None
    spec, buffers = plot._page_data()
    assert spec["layers"][0]["levels"]["windows"] is False
    assert {lv["index"]["id"] for lv in spec["layers"][0]["levels"]["levels"]} <= set(buffers)


# ---------------------------------------------------------------------- intervals layers


def jobs(n=2000, lanes=4, seed=0):
    """``n`` short jobs on ``lanes`` workers, a few long ones, and some depending on others."""
    rng = np.random.default_rng(seed)
    start = rng.uniform(0, 10_000, n)
    took = rng.exponential(2, n)
    took[:10] = 3000
    return {
        "start": start,
        "end": start + took,
        "lane": rng.integers(0, lanes, n),
        "kind": rng.choice(["io", "cpu"], n).astype(object),
        "id": np.arange(n),
        "after": np.array([i - 1 if i % 100 == 1 else None for i in range(n)], dtype=object),
    }


def bars_plot(n=2000, **kw):
    data = jobs(n)
    del data["after"]
    return Timeline().intervals(
        data, start="start", end="end", lane="lane", color="kind", tooltip=["id"], **kw
    )


def bars_of(plot):
    lay = plot._laid["intervals"]
    assert isinstance(lay, iv.Layout)
    assert lay.bars is not None
    return lay.bars


def test_a_level_keeps_long_bars_and_merges_short_ones_per_lane_and_bin():
    plot = bars_plot(300)
    b = bars_of(plot)
    rank = plot._ranks["intervals"]
    width = 50.0
    rows = np.arange(len(b.lo))
    long, merged = iv.merge(b, rank, b.lo, b.hi, rows, width, 0.0)
    assert set(long.tolist()) == set(np.flatnonzero(b.hi - b.lo >= width).tolist())
    short = np.flatnonzero(b.hi - b.lo < width)
    keys = {}
    for i in short.tolist():
        keys.setdefault((int(b.lane[i]), int(b.lo[i] // width)), []).append(i)
    assert len(merged) == len(keys)
    assert int(merged.n.sum()) == len(short)
    # as tall as the lane
    assert (merged.row == 0).all()
    assert (merged.rows == 1).all()
    for g in range(len(merged)):
        members = keys[(int(merged.lane[g]), int(merged.lo[g] // width))]
        assert merged.n[g] == len(members)
        assert merged.lo[g] == b.lo[members].min()
        assert merged.hi[g] == b.hi[members].max()
        d = b.hi[members] - b.lo[members]
        assert merged.longest[g] == members[int(np.argmax(d))]
        filled = d.sum() / ((b.hi[members].max() - b.lo[members].min()) * b.rows[members[0]])
        assert merged.cover[g] == pytest.approx(min(filled, 1.0))


def test_an_intervals_layer_of_many_bars_is_sent_as_levels(small):
    plot = bars_plot()
    check(plot._spec)
    layer = plot._spec["layers"][0]
    assert layer["count"] == 0
    lv = layer["levels"]
    assert lv["total"] == 2000
    b = bars_of(plot)
    for scale in ("time", "order"):
        for level in lv[scale]["levels"]:
            n = buffer(plot, level["n"])
            index = buffer(plot, level["index"])
            assert int(n.sum()) == 2000
            real = index != 0xFFFFFFFF
            assert (n[real] == 1).all()
            # real bars are the layer's, in its order; merged ones are opaque as they cover
            assert (np.diff(index[real].astype(np.int64)) > 0).all()
            assert buffer(plot, level["start"])[real].tolist() == b.lo[index[real]].tolist()
            assert buffer(plot, level["kind"])[~real].tolist() == [iv.KIND_MERGED] * int(
                (~real).sum()
            )
            alpha = buffer(plot, level["alpha"])
            assert (alpha[real] == 255).all()
            lane = buffer(plot, level["lane"])
            assert (np.diff(lane.astype(np.int64)) >= 0).all()
            assert buffer(plot, level["rank"]).shape == (level["count"], 2)
    assert plot._spec["sequence"]["step"] > 1


def test_a_bars_window_has_the_bars_that_reach_into_it(small):
    plot = bars_plot()
    b = bars_of(plot)
    a, z = 4000.0, 4050.0
    answer = plot._window({"layer": "intervals", "scale": "time", "range": [a, z], "k": 9})
    assert answer["k"] is None
    spec = answer["spec"]
    check({**plot._spec, "layers": [spec]})
    index = buffer(plot, spec["index"])
    want = np.flatnonzero((b.lo <= z) & (b.hi >= a))
    assert index.tolist() == want.tolist()
    # the order's exact times there
    assert "sequence" in answer
    # many: level k there
    monkeypatch_raw = levels.RAW_MARKS
    levels.RAW_MARKS = 5
    try:
        answer = plot._window({"layer": "intervals", "scale": "order", "range": [0, 500], "k": 1})
    finally:
        levels.RAW_MARKS = monkeypatch_raw
    assert answer["k"] == 1
    n = buffer(plot, answer["spec"]["n"])
    ranks = plot._ranks["intervals"]
    inside = (ranks[:, 0] <= answer["range"][1]) & (ranks[:, 1] >= answer["range"][0])
    assert int(n.sum()) == int(inside.sum())


def test_a_level_of_short_bars_only():
    plot = bars_plot(300)
    b = bars_of(plot)
    rec = plot._layers["intervals"]
    assert isinstance(rec, iv.IntervalsRecord)
    rows = np.arange(len(b.lo))
    long, merged = iv.merge(b, plot._ranks["intervals"], b.lo, b.hi, rows, 1e9, 0.0)
    assert not len(long)
    spec, _ = iv.encode_bars(rec, b, long, unit_ns=1, merged=merged)
    assert spec["count"] == len(merged)


def test_links_between_bars_sent_are_kept():
    data = jobs(400)
    plot = Timeline().intervals(
        data, start="start", end="end", lane="lane", id="id", depends="after"
    )
    b = bars_of(plot)
    assert len(b.links) == 4
    gone = int(b.links[0][1])
    rows = np.delete(np.arange(len(b.lo)), gone)
    rec = plot._layers["intervals"]
    assert isinstance(rec, iv.IntervalsRecord)
    spec, buffers = iv.encode_bars(rec, b, rows, unit_ns=1)
    by_id = {e.id: e.data for e in buffers}
    pairs = decode(spec["links"]["pairs"], by_id[spec["links"]["pairs"]["id"]])
    index = decode(spec["index"], by_id[spec["index"]["id"]])
    sent = {tuple(p) for p in index[pairs].tolist()}
    assert sent == {tuple(p) for p in b.links.tolist() if gone not in p}
    assert len(sent) == 3


def test_a_bars_tooltip_takes_the_bars_index_among_the_layers(small):
    plot = bars_plot()
    level = plot._spec["layers"][0]["levels"]["time"]["levels"][0]
    index = buffer(plot, level["index"])
    i = int(index[index != 0xFFFFFFFF][3])
    rec = plot._layers["intervals"]
    assert plot._tooltip("intervals", i) == [["id", str(int(rec.perm[i]))]]


def test_a_states_layer_of_many_changes_is_sent_as_levels(small):
    rng = np.random.default_rng(2)
    n = 400
    states = {
        "time": np.sort(rng.uniform(0, 1000, n)),
        "lane": rng.integers(0, 3, n),
        "state": rng.choice(["up", "down"], n).astype(object),
    }
    plot = Timeline().states(states, time="time", lane="lane", state="state")
    check(plot._spec)
    level = plot._spec["layers"][0]["levels"]["time"]["levels"][0]
    ref = level["states"]["values"]
    values = decode_strings(ref, plot._buffers[ref["id"]])
    assert set(values) <= {"up", "down"}
