"""A plot of every kind, with the options that change its spec: for the tests that check
every plot (the spec's contract, pages, HTML in the notebook)."""

from __future__ import annotations

import numpy as np

from anytimeline import Route, Stem, Timeline, compare_traces, gantt, levels, story
from anytimeline.synthetic import (
    incident,
    instants,
    service_health,
    service_log,
    service_metrics,
    traces,
)
from anytimeline.traces import merge

SERVICES = ["gateway", "auth", "api", "cache", "db"]


def every_kind() -> dict[str, Timeline]:
    """Plots by name: every layer type, time kind, scale and lane layout."""
    log = service_log(120, seed=1)
    metrics = service_metrics(120, seed=1)
    health = service_health(120, seed=1)
    tr = traces(4, seed=3)
    plots: dict[str, Timeline] = {}

    plots["events"] = Timeline(title="Events", lane_order=SERVICES).events(
        log,
        lane="service",
        order="seq",
        color="level",
        symbol="event",
        size="bytes",
        text="{event}",
        importance="bytes",
        tooltip=["request", "user"],
        route=Route("request", color="theme", width=2),
    )
    plots["events_numeric_color"] = Timeline(xscale="order", sort="count").events(
        log, lane="service", color="bytes", colormap="viridis", clim="robust", size=6
    )
    plots["events_solid"] = Timeline(dodge=False, mark_scale=2).events(
        log, lane="service", color="#336699", overlap="overlay", hover=False, select=False
    )
    plots["order_only"] = Timeline().events(
        {"step": np.arange(10), "lane": np.array(["a", "b"] * 5)},
        time=None,
        order="step",
        lane="lane",
    )
    plots["numbers"] = Timeline().events({"time": np.linspace(0, 10, 25)}, lane=None)
    plots["durations"] = Timeline(time_unit="ms").events(
        {"time": np.arange(0, 1000, 7.5), "kind": np.array(["x", "y", "z"] * 45)},
        lane="kind",
    )
    plots["timezone"] = Timeline(timezone="Europe/Amsterdam").events(log, lane="service")
    plots["story"] = story(
        incident(),
        "{time:%H:%M}\n{title}",
        color="kind",
        importance="importance",
        stems=Stem(shape="curved", width=200),
        today="2026-10-12T15:00:00",
    )
    plots["no_lane_names"] = Timeline(lane_names=False).events(incident(), text="title", stems=True)

    plan = {
        "task": ["Design", "Build", "Review", "Ship", "Support"],
        "start": np.array(
            ["2026-09-01", "2026-09-08", "2026-09-29", "2026-10-05", "2026-10-05"],
            dtype="datetime64[D]",
        ),
        "end": np.array(
            ["2026-09-08", "2026-09-29", "2026-09-29", "2026-10-05", "NaT"], dtype="datetime64[D]"
        ),
        "after": [None, "Design", "Build", ["Review", "Build"], "Ship"],
        "done": [1.0, 0.7, 0.0, 0.0, 0.0],
        "phase": ["plan", "build", "build", "ship", "ship"],
    }
    plots["gantt"] = gantt(
        plan, depends="after", progress="done", color="phase", text="{task}", today="2026-10-01"
    )
    plots["intervals_packed"] = Timeline().intervals(
        plan, lane="phase", color="done", colormap="viridis", durations=True, tooltip=["task"]
    )

    plots["spans"] = Timeline().spans(tr.spans, color="service", tooltip=["status"], expand=1)
    plots["spans_events"] = (
        Timeline()
        .spans(tr.spans, color="service")
        .events(tr.events, time="time", lane="span_id", symbol="name", name="span events")
    )
    plots["flame"] = Timeline().spans(tr.spans, layout="flame", group="trace_id", color="service")
    one = tr.spans["trace_id"] == tr.spans["trace_id"][0]
    two = tr.spans["trace_id"] == tr.spans["trace_id"][-1]
    plots["merged_flame"] = Timeline().spans(merge(tr.spans), layout="flame", tooltip=["count"])
    plots["compare_traces"] = compare_traces(
        {k: v[one] for k, v in tr.spans.items()}, {k: v[two] for k, v in tr.spans.items()}
    )
    plots["intervals_tree"] = Timeline().intervals(
        tr.spans, id="span_id", parent="parent_id", lane="name", critical_path=True, expand="all"
    )

    plots["states_values"] = (
        Timeline(lane_order=SERVICES)
        .states(health, lane="service", tooltip=["reason"], height=1.0, opacity=0.3)
        .values(metrics, value="cpu", lane="service", kind="area", ylim=(0, 100), name="cpu")
        .events(log, lane="service", color="level")
    )
    lat = {
        "time": np.concatenate([metrics["time"]] * 2),
        "service": np.concatenate([metrics["service"]] * 2),
        "quantile": np.repeat(["p50", "p99"], len(metrics["time"])),
        "ms": np.concatenate([metrics["p50_ms"], metrics["p99_ms"]]),
    }
    plots["values_series"] = Timeline().values(
        lat, value="ms", lane="service", series="quantile", kind="step", scale="shared"
    )
    plots["values_only"] = Timeline().values(
        metrics, value="queue", lane="service", ylim={"api": (0, 50)}, tooltip=["rate"]
    )
    plots["states_text"] = Timeline().states(
        health, lane="service", text="{state} ({reason})", color="#888888", end=health["time"].max()
    )

    hosts = np.where(np.isin(log["user"], [f"u{i:02d}" for i in range(10)]), "web-1", "web-2")
    plots["groups"] = Timeline(group_order=["web-2"]).events(
        {**log, "host": hosts}, lane="service", group="host", color="level"
    )
    roots = tr.spans["parent_id"] == None  # noqa: E711
    which = dict(zip(tr.spans["trace_id"][roots], tr.spans["name"][roots], strict=True))
    endpoint = np.array([which[t] for t in tr.spans["trace_id"]], dtype=object)
    plots["aligned_groups"] = Timeline(align="start").spans(
        {**tr.spans, "endpoint": endpoint}, group="endpoint"
    )

    marked = Timeline(title="Marked").events(log, lane="service")
    marked.marker(log["time"][10], "deploy", color="#c62828")
    marked.zoom_to(log["time"][0], log["time"][50])
    marked.selection = {"events": [1, 2, 3]}
    plots["markers_zoom_selection"] = marked

    linked_a = Timeline().events(log, lane="service")
    linked_b = Timeline().values(metrics, value="cpu", lane="service")
    linked_a.link(linked_b, align="start")
    plots["linked"] = linked_a
    # a layer of many events, sent as levels (the threshold lowered for it)
    from_ = levels.LEVELS_FROM
    levels.LEVELS_FROM = 200
    try:
        plots["events_levels"] = Timeline().events(
            instants(400, lanes=6), lane="lane", color="kind", importance="value", size="value"
        )
        plots["values_levels"] = Timeline().values(
            many_samples(600), lane="lane", value="cpu", series="series"
        )
    finally:
        levels.LEVELS_FROM = from_
    return plots


def many_samples(n: int, *, seed: int = 0) -> dict[str, np.ndarray]:
    """``n`` samples of a value on 3 lanes, 2 series on the first, with gaps (NaN)."""
    rng = np.random.default_rng(seed)
    lane = np.sort(rng.integers(0, 3, n))
    series = np.where((lane == 0) & (rng.uniform(size=n) < 0.5), "b", "a")
    value = np.cumsum(rng.normal(0, 1, n))
    value[rng.integers(0, n, n // 50)] = np.nan
    return {
        "time": np.datetime64("2026-10-12T08:00", "ms") + rng.integers(0, 3_600_000, n),
        "lane": np.array([f"host {i}" for i in lane], dtype=object),
        "series": series.astype(object),
        "cpu": value,
        "id": np.arange(n),
    }
