"""A marimo app for the levels-of-detail test (levels.spec.ts): an events layer of 500,000
events a values layer of 1,800,000 samples and an intervals layer of 400,000 bars (more than
levels.LEVELS_FROM), so all are sent as levels, their marks in windows."""

import marimo

app = marimo.App()


@app.cell
def _():
    import json

    import marimo as mo
    import numpy as np

    from anytimeline import Timeline

    n = 500_000
    rng = np.random.default_rng(7)
    start = np.datetime64("2026-10-12T08:00:00", "ns")
    # a steady stream on 40 lanes, a burst on lane 3, and a few lone events late on lane 7
    t = rng.integers(0, 3600 * 10**9, n)
    lane = rng.integers(0, 40, n)
    burst = rng.integers(0, n, n // 10)
    t[burst] = 1800 * 10**9 + rng.integers(0, 2 * 10**9, len(burst))
    lane[burst] = 3
    lone = np.arange(5)
    t[lone] = 3500 * 10**9 + lone * 10**10
    lane[lone] = 7
    level = rng.choice(["info", "warn", "error"], n, p=[0.9, 0.08, 0.02])
    data = {
        "time": start + t.astype("timedelta64[ns]"),
        "lane": np.array([f"lane {i:02d}" for i in lane], dtype=object),
        "level": level.astype(object),
        "id": np.arange(n),
    }
    plot = Timeline(title="Levels test", renderer="webgl2", height=520)
    plot.events(data, time="time", lane="lane", color="level", tooltip=["id"])
    # a value sampled every 4 ms on lanes 0 and 1 (900,000 samples each), with a spike on
    # lane 1 and a gap
    m = 900_000
    ts = np.arange(m) * 4 * 10**6
    wave = np.sin(ts / 6e10) + rng.normal(0, 0.05, m)
    spike = wave.copy()
    spike[m // 3] = 6.0
    spike[m // 2 : m // 2 + 5000] = np.nan
    samples = {
        "time": start + np.concatenate([ts, ts]).astype("timedelta64[ns]"),
        "lane": np.array(["lane 00"] * m + ["lane 01"] * m, dtype=object),
        "cpu": np.concatenate([wave, spike]),
    }
    plot.values(samples, time="time", lane="lane", value="cpu")
    # 400,000 short jobs on 8 workers, and a few long ones
    k = 400_000
    begin = rng.integers(0, 3600 * 10**9, k)
    took = (rng.exponential(0.3, k) * 1e9).astype(np.int64)
    took[:20] = rng.integers(60, 600, 20) * 10**9
    jobs = {
        "start": start + begin.astype("timedelta64[ns]"),
        "end": start + (begin + took).astype("timedelta64[ns]"),
        "lane": np.array([f"worker {i}" for i in rng.integers(0, 8, k)], dtype=object),
        "kind": rng.choice(["io", "cpu"], k).astype(object),
        "job": np.arange(k),
    }
    plot.intervals(
        jobs, start="start", end="end", lane="lane", color="kind", tooltip=["job"], name="jobs"
    )
    widget = mo.ui.anywidget(plot.widget)
    widget
    return json, mo, plot, widget


@app.cell
def _(json, mo, plot, widget):
    widget.value
    state = {"selected": {name: len(rows) for name, rows in plot.selection.items()}}
    mo.Html(f"<pre id='python-state'>{json.dumps(state, sort_keys=True)}</pre>")
    return


if __name__ == "__main__":
    app.run()
