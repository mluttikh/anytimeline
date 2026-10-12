"""Write the scenes of the visual tests: each plot's spec, synced settings and buffers.

    uv run python scripts/make_scenes.py            # the scenes of the visual tests
    uv run python scripts/make_scenes.py --million  # also a million events (perf.spec.ts)

The browser harness (js/test/visual/harness.html) plays the notebook's part: it answers
the plot's requests for buffers from the scene file.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import numpy as np

from anytimeline import Route, Timeline, gantt, save_html, story
from anytimeline.synthetic import (
    incident,
    instants,
    service_health,
    service_log,
    service_metrics,
    traces,
)

OUT = Path(__file__).resolve().parent.parent / "js" / "test" / "visual" / "scenes"


def write(name: str, plot: Timeline, **traits: object) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    state = {
        "_spec": plot._spec,
        "title": plot.title,
        "height": plot.height,
        "xscale": plot.xscale,
        "hover": plot.hover,
        "legend": plot.legend,
        "selection_mode": plot.selection_mode,
        "tool": plot.tool,
        "font_size": plot.font_size,
        "_marks": {k: base64.b64encode(v).decode() for k, v in plot._marks.items()},
        "_zoom": plot._zoom,
        **traits,
    }
    buffers = {k: base64.b64encode(v).decode() for k, v in plot._buffers.items()}
    (OUT / f"{name}.json").write_text(
        json.dumps({"state": state, "buffers": buffers}), encoding="utf-8"
    )
    print(f"{name}: {sum(len(b) for b in plot._buffers.values()) / 1e6:.2f} MB")


def main() -> None:
    log = service_log(400, seed=1)
    services = ["gateway", "auth", "api", "cache", "db"]

    plot = Timeline(title="Requests through services", lane_order=services, height=360)
    plot.events(
        log,
        time="time",
        lane="service",
        color="level",
        symbol="event",
        order="seq",
        tooltip=["request", "user", "bytes"],
        palette={"info": "#4c78a8", "warning": "#f58518", "error": "#e45756"},
    )
    write("service_time", plot)

    def span(*requests: str) -> tuple[np.datetime64, np.datetime64]:
        t = log["time"][np.isin(log["request"], requests)]
        pad = (t.max() - t.min()) // 4
        return t.min() - pad, t.max() + pad

    zoomed = Timeline(title="Overlapping requests, with routes", lane_order=services, height=360)
    zoomed.events(
        log,
        time="time",
        lane="service",
        color="request",
        symbol="event",
        order="seq",
        route=Route("request"),
        text="{event}",
        tooltip=["request"],
    )
    zoomed.zoom_to(*span("r0210", "r0212"))
    rows = np.flatnonzero(log["request"] == "r0211")
    zoomed.selection = {"events": rows.tolist()}
    write("service_routes", zoomed)

    seq = Timeline(
        title="The same requests in order", lane_order=services, xscale="sequence", height=360
    )
    seq.events(
        log,
        time="time",
        lane="service",
        color="request",
        order="seq",
        route="request",
        text="{event}",
    )
    seq.zoom_to(*span("r0210", "r0212"))
    write("service_sequence", seq)

    # the example notebook's first plot on the Order scale: every long gap of a whole log
    overview = Timeline(title="A whole log in order", lane_order=services, xscale="sequence")
    overview.events(
        service_log(),
        time="time",
        lane="service",
        color="level",
        symbol="event",
        order="seq",
        palette={"info": "#4c78a8", "warning": "#f58518", "error": "#e45756"},
    )
    write("order_overview", overview)

    # a project plan: dependencies, progress, milestones, a marker for today
    plan = {
        "task": [
            "Requirements",
            "Design",
            "Prototype",
            "Review",
            "Build backend",
            "Build frontend",
            "Write docs",
            "Test",
            "Release",
        ],
        "start": np.array(
            [
                "2026-09-01",
                "2026-09-08",
                "2026-09-15",
                "2026-09-29",
                "2026-09-30",
                "2026-10-02",
                "2026-10-05",
                "2026-10-20",
                "2026-11-02",
            ],
            dtype="datetime64[D]",
        ),
        "days": [7, 9, 14, 0, 18, 16, 20, 13, 0],
        "after": [
            None,
            "Requirements",
            "Design",
            "Prototype",
            "Review",
            "Review",
            "Design",
            ["Build backend", "Build frontend"],
            ["Test", "Write docs"],
        ],
        "done": [1.0, 1.0, 1.0, 1.0, 0.6, 0.4, 0.3, 0.0, 0.0],
        "phase": ["plan", "plan", "plan", "plan", "build", "build", "build", "ship", "ship"],
    }
    chart = gantt(
        plan,
        end=None,
        duration="days",
        duration_unit="d",
        depends="after",
        progress="done",
        color="phase",
        text="{task}",
        title="Project plan",
        today="2026-10-12",
        palette={"plan": "#4c78a8", "build": "#f58518", "ship": "#54a24b"},
    )
    write("gantt_plan", chart)

    # a machine schedule: jobs that overlap on a machine are packed into sub-rows
    rng = np.random.default_rng(5)
    n = 160
    starts = np.sort(rng.integers(0, 3 * 24 * 60, n))
    jobs = {
        "machine": rng.choice([f"press {i}" for i in range(1, 7)], n),
        "start": np.datetime64("2026-10-12T06:00", "m") + starts.astype("timedelta64[m]"),
        "minutes": rng.integers(20, 240, n),
        "product": rng.choice(["A", "B", "C", "D"], n),
    }
    schedule = Timeline(title="Jobs per machine, packed", height=380)
    schedule.intervals(
        jobs,
        end=None,
        duration="minutes",
        duration_unit="min",
        lane="machine",
        color="product",
        text="{product}",
    )
    write("schedule", schedule)

    # bars and events together: the time each request spends in a service (until its next
    # event), and the events themselves
    import polars as pl

    df = pl.DataFrame({k: v[log["request"] < "r0012"] for k, v in log.items()}).sort("time")
    stays = (
        df.with_columns(end=pl.col("time").shift(-1).over("request"))
        .drop_nulls("end")
        .rename({"time": "start"})
    )
    spans = Timeline(title="Time in each service, and the events", lane_order=services, height=320)
    spans.intervals(stays, lane="service", color="request", height=0.45, name="spans", opacity=0.5)
    spans.events(df, time="time", lane="service", color="request", symbol="event", order="seq")
    one = df.filter(pl.col("request") == "r0002")["time"]
    spans.zoom_to(one.min(), one.max())
    write("spans_events", spans)

    tr = traces(8, seed=3)
    bad = tr.spans["trace_id"][list(tr.spans["status"]).index("error")]
    one = {k: v[tr.spans["trace_id"] == bad] for k, v in tr.spans.items()}
    one_events = {k: v[tr.events["trace_id"] == bad] for k, v in tr.events.items()}
    waterfall = Timeline(title="One trace")
    waterfall.spans(one, color="service", tooltip=["service", "status"])
    waterfall.events(
        one_events, time="time", lane="span_id", symbol="name", color="#222222", name="span events"
    )
    write("trace_waterfall", waterfall)

    listing = Timeline(title="Eight traces, folded", height=360)
    listing.spans(tr.spans, color="service", expand=1)
    listing.events(
        tr.events, time="time", lane="span_id", symbol="name", color="#222222", name="span events"
    )
    write("trace_list", listing)
    # states and values on the lanes of the log's events
    services = ["gateway", "auth", "api", "cache", "db"]
    health = service_health()
    metrics = service_metrics()
    full = service_log()  # the log the metrics and health come from
    errors = {k: v[full["level"] != "info"] for k, v in full.items()}
    board = Timeline(title="Health, CPU and problems", lane_order=services, height=420)
    board.states(
        health,
        lane="service",
        palette={"up": "#54a24b", "degraded": "#f58518", "down": "#e45756"},
        opacity=0.25,
        height=1.0,
        tooltip=["reason"],
    )
    board.values(metrics, value="cpu", lane="service", kind="area", ylim=(0, 100), name="cpu %")
    board.events(
        errors,
        time="time",
        lane="service",
        color="level",
        palette={"error": "#c62828", "warning": "#ef6c00"},
        symbol="event",
        name="problems",
    )
    board.zoom_to(np.datetime64("2026-10-12T08:25"), np.datetime64("2026-10-12T08:45"))
    write("service_health", board)

    lat = {
        "time": np.concatenate([metrics["time"]] * 2),
        "service": np.concatenate([metrics["service"]] * 2),
        "quantile": np.repeat(["p50", "p99"], len(metrics["time"])),
        "ms": np.concatenate([metrics["p50_ms"], metrics["p99_ms"]]),
    }
    latency = Timeline(title="Latency per service", lane_order=services, height=380)
    latency.values(lat, value="ms", lane="service", series="quantile", kind="step")
    write("latency_series", latency)

    # groups: a header per host, its lanes under it, one plot
    hosts = np.where(np.isin(full["user"], [f"u{i:02d}" for i in range(30)]), "web-1", "web-2")
    by_host = {**full, "host": hosts}
    other = service_metrics(seed=5)
    cpu = {k: np.concatenate([metrics[k], other[k]]) for k in ("time", "service", "cpu")} | {
        "host": np.repeat(["web-1", "web-2"], [len(metrics["time"]), len(other["time"])])
    }
    grouped = Timeline(title="Two hosts", lane_order=services, height=520)
    grouped.values(cpu, value="cpu", lane="service", group="host", kind="area", name="cpu %")
    grouped.events(
        by_host, time="time", lane="service", group="host", color="level", symbol="event"
    )
    grouped.zoom_to(np.datetime64("2026-10-12T08:20"), np.datetime64("2026-10-12T08:50"))
    write("host_groups", grouped)

    # traces by endpoint: a group per root span's name, each trace folded
    root_name = dict(
        zip(
            tr.spans["trace_id"][tr.spans["parent_id"] == None],  # noqa: E711
            tr.spans["name"][tr.spans["parent_id"] == None],  # noqa: E711
            strict=True,
        )
    )
    endpoint = np.array([root_name[t] for t in tr.spans["trace_id"]], dtype=object)
    by_endpoint = Timeline(title="Traces by endpoint", height=420)
    by_endpoint.spans(
        {**tr.spans, "endpoint": endpoint}, color="service", group="endpoint", expand=1
    )
    write("trace_groups", by_endpoint)

    # two traces compared from their start, in one plot
    roots = tr.spans["parent_id"] == None  # noqa: E711
    took = (tr.spans["end"] - tr.spans["start"])[roots]
    slow, fast = tr.spans["trace_id"][roots][[took.argmax(), took.argmin()]]
    pick = np.isin(tr.spans["trace_id"], [slow, fast])
    pair = {k: v[pick] for k, v in tr.spans.items()}
    pair["which"] = np.where(pair["trace_id"] == slow, "slowest", "fastest")
    compare = Timeline(title="Slowest and fastest, from their start", align="start", height=560)
    compare.spans(pair, color="service", group="which")
    write("trace_compare", compare)

    # linked plots: two plots that zoom together, in a page of their own
    top = Timeline(title="web-1", lane_order=services, height=260)
    top.events({k: v[hosts == "web-1"] for k, v in full.items()}, lane="service", color="level")
    bottom = Timeline(title="web-2: CPU", lane_order=services, height=260)
    bottom.values(other, value="cpu", lane="service", kind="area")
    top.link(bottom)
    top.zoom_to(np.datetime64("2026-10-12T08:20"), np.datetime64("2026-10-12T08:50"))
    bottom.zoom_to(np.datetime64("2026-10-12T08:20"), np.datetime64("2026-10-12T08:50"))
    save_html(OUT / "saved_linked.html", top, bottom)

    # story timelines: boxes on stems above and below the line
    inc = incident()
    kinds = {
        "deploy": "#4c78a8",
        "alert": "#e45756",
        "page": "#f58518",
        "action": "#54a24b",
        "status": "#9d755d",
    }
    write(
        "story_incident",
        story(
            inc,
            "{time:%H:%M}\n{title}",
            color="kind",
            palette=kinds,
            importance="importance",
            tooltip=["team"],
            title="Checkout incident",
            height=460,
        ),
    )
    write(
        "story_curved",
        story(
            inc,
            "{time:%H:%M}\n{title}",
            color="kind",
            palette=kinds,
            importance="importance",
            stem_shape="curved",
            title="Checkout incident (curved stems)",
            height=460,
        ),
    )
    releases = {
        "time": np.array(
            [
                "2026-01-15",
                "2026-02-02",
                "2026-03-10",
                "2026-03-24",
                "2026-05-05",
                "2026-06-30",
                "2026-07-08",
                "2026-09-01",
                "2026-10-11",
            ],
            dtype="datetime64[D]",
        ),
        "title": [
            "First prototype of event charts drawn with WebGPU in a notebook",
            "Canvas 2D fallback for machines without a usable GPU",
            "Order scale: events by rank, so bursts read as clearly as hours",
            "Time zones and centuries on the axis",
            "Gantt charts with dependencies, progress and milestones",
            "Traces from OpenTelemetry as a waterfall that folds",
            "States and values behind the events of each lane",
            "Groups of lanes, linked plots and pages that work without Python",
            "Story timelines with boxes on stems",
        ],
    }
    write(
        "story_wrapped",
        story(releases, "{time:%b %-d}\n{title}", title="A release history", height=460),
    )
    write(
        "story_teams",
        story(
            inc,
            "{time:%H:%M}\n{title}",
            lane="team",
            color="kind",
            palette=kinds,
            importance="importance",
            title="Checkout incident by team",
            height=640,
        ),
    )

    # a page of its own (save_html), for the test that opens it from disk
    saved = Timeline(title="Saved traces")
    saved.spans(tr.spans, color="service", tooltip=["service", "status"], expand=1)
    saved.events(tr.events, time="time", lane="span_id", tooltip=["attributes"], name="span events")
    saved.save_html(OUT / "saved_traces.html")

    big = instants(100_000, lanes=30)
    dense = Timeline(title="100,000 events on 30 lanes", height=520)
    dense.events(big, lane="lane", color="value", colormap="viridis", size=5)
    write("dense", dense)

    history = {
        "time": np.array(
            [
                "1066-10-14",
                "1215-06-15",
                "1492-10-12",
                "1789-07-14",
                "1914-06-28",
                "1969-07-20",
                "1989-11-09",
                "2001-09-11",
            ],
            dtype="datetime64[D]",
        ),
        "region": [
            "Europe",
            "Europe",
            "Americas",
            "Europe",
            "Europe",
            "Space",
            "Europe",
            "Americas",
        ],
        "event": [
            "Hastings",
            "Magna Carta",
            "Columbus lands",
            "Bastille",
            "Sarajevo",
            "Moon landing",
            "Berlin Wall",
            "9/11",
        ],
    }
    years = Timeline(title="Centuries", height=240)
    years.events(history, lane="region", text="event", symbol="diamond", size=10)
    write("centuries", years)

    rng = np.random.default_rng(3)
    ns = np.sort(rng.integers(0, 50_000, 300)).astype("timedelta64[ns]")
    nano = Timeline(title="Nanoseconds", height=240)
    nano.events({"time": ns, "cpu": rng.integers(0, 4, 300)}, lane="cpu", symbol="tick", size=12)
    write("nanoseconds", nano)

    steps = Timeline(title="Order only (no clock)", height=220)
    steps.events(
        {
            "step": [1, 2, 3, 4, 5, 6],
            "actor": ["client", "server", "db", "server", "client", "server"],
            "what": ["request", "parse", "query", "render", "receive", "log"],
        },
        time=None,
        order="step",
        lane="actor",
        text="what",
        route=Route("actor", color="theme"),
    )
    write("order_only", steps)

    if "--million" in sys.argv:
        million = Timeline(title="1,000,000 events", height=520)
        million.events(instants(1_000_000, lanes=40), lane="lane", color="kind", size=5)
        write("million", million)


if __name__ == "__main__":
    main()
