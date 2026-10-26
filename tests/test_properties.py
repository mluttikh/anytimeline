"""Random plots: any layers with any options, on any plot settings. Each must give a spec the
browser declares (types.ts), serve every buffer the spec names, save as a page with all its
data, and select each drawn row once with a box over the whole plot."""

from __future__ import annotations

from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from test_spec_contract import check

from anytimeline import Route, Timeline
from anytimeline.synthetic import service_health, service_log, service_metrics, traces
from anytimeline.widget import _page

SEEDS = st.integers(0, 5)


@st.composite
def events(draw: st.DrawFn) -> tuple[str, dict[str, Any], dict[str, Any]]:
    data = service_log(draw(st.integers(1, 12)), seed=draw(SEEDS))
    options = {
        "lane": draw(st.sampled_from(["service", "user", None])),
        "order": draw(st.sampled_from([None, "seq"])),
        "color": draw(st.sampled_from([None, "level", "bytes", "#336699"])),
        "symbol": draw(st.sampled_from([None, "event"])),
        "size": draw(st.sampled_from([None, 4, "bytes"])),
        "text": draw(st.sampled_from([None, "event", "{event} ({user})"])),
        "tooltip": draw(st.sampled_from([None, ["request"], ["user", "bytes"]])),
        "route": draw(st.sampled_from([None, Route("request")])),
        "overlap": draw(st.sampled_from(["dodge", "overlay"])),
        "select": draw(st.booleans()),
        "group": draw(st.sampled_from([None, "level"])),
    }
    if options["color"] == "bytes":
        options["colormap"] = draw(st.sampled_from([None, "viridis"]))
    return "events", data, options


@st.composite
def intervals(draw: st.DrawFn) -> tuple[str, dict[str, Any], dict[str, Any]]:
    spans = traces(draw(st.integers(1, 3)), seed=draw(SEEDS)).spans
    tree = draw(st.booleans())
    options: dict[str, Any] = {
        "start": "start",
        "end": "end",
        "color": draw(st.sampled_from([None, "service", "status"])),
        "tooltip": draw(st.sampled_from([None, ["name"]])),
        "select": draw(st.booleans()),
    }
    if tree:
        options |= {"id": "span_id", "parent": "parent_id", "label": "name"}
        options["critical_path"] = draw(st.booleans())
    else:
        options["lane"] = draw(st.sampled_from(["service", "trace_id"]))
        options["text"] = draw(st.sampled_from([None, "{name}"]))
    return "intervals", spans, options


@st.composite
def states(draw: st.DrawFn) -> tuple[str, dict[str, Any], dict[str, Any]]:
    data = service_health(draw(st.integers(2, 12)), seed=draw(SEEDS))
    options = {
        "lane": "service",
        "text": draw(st.sampled_from([True, False, "{state} ({reason})"])),
        "tooltip": draw(st.sampled_from([None, ["reason"]])),
        "height": draw(st.sampled_from([0.8, 1.0])),
        "opacity": draw(st.sampled_from([1.0, 0.3])),
        "select": draw(st.booleans()),
    }
    return "states", data, options


@st.composite
def values(draw: st.DrawFn) -> tuple[str, dict[str, Any], dict[str, Any]]:
    data = service_metrics(draw(st.integers(2, 12)), seed=draw(SEEDS))
    options = {
        "value": draw(st.sampled_from(["cpu", "queue", "p99_ms"])),
        "lane": draw(st.sampled_from(["service", None])),
        "kind": draw(st.sampled_from(["line", "area", "step"])),
        "scale": draw(st.sampled_from(["lane", "shared"])),
        "ylim": draw(st.sampled_from([None, (0, 100)])),
        "tooltip": draw(st.sampled_from([None, ["rate"]])),
    }
    return "values", data, options


PLOT_OPTIONS = st.fixed_dictionaries(
    {
        "xscale": st.sampled_from(["time", "sequence"]),
        "sort": st.sampled_from([None, "name", "first", "last", "count"]),
        "align": st.sampled_from(["time", "start"]),
        "lane_names": st.booleans(),
        "dodge": st.booleans(),
        "mark_scale": st.sampled_from([0.25, 1.0, 4.0]),
        "font_size": st.sampled_from([8, 12, 24]),
        "timezone": st.sampled_from([None, "Europe/Amsterdam"]),
    }
)


def buffer_ids(spec: Any) -> set[str]:
    """The ids of the buffers that the spec names (its BufferRefs)."""
    if isinstance(spec, dict):
        if {"id", "dtype", "byteLength"} <= spec.keys():
            return {spec["id"]}
        return set().union(*(buffer_ids(v) for v in spec.values()))
    if isinstance(spec, list):
        return set().union(*(buffer_ids(v) for v in spec))
    return set()


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    options=PLOT_OPTIONS,
    layers=st.lists(
        st.one_of(events(), intervals(), states(), values()), min_size=1, max_size=3
    ).filter(lambda layers: sum("parent" in kw for _, _, kw in layers) <= 1),  # one tree a plot
)
def test_any_plot(options, layers):
    plot = Timeline(**options)
    for i, (method, data, kwargs) in enumerate(layers):
        getattr(plot, method)(data, name=f"{method}{i}", **kwargs)

    check(plot._spec)

    named = buffer_ids(plot._spec)
    assert named <= plot._buffers.keys()
    served: list[dict[str, Any]] = []
    setattr(plot, "send", lambda content, buffers=None: served.append(content))  # noqa: B010
    plot._on_frontend_msg(plot, {"type": "need", "ids": sorted(named)}, [])
    assert {c["id"] for c in served if c["type"] == "put"} == named

    page = _page([plot], None)
    assert all(i in page for i in plot._buffers)

    lanes = len(plot._spec["lanes"]["names"])
    plot._pick = {
        "n": 1,
        "kind": "box",
        "x": [-1e300, 1e300],
        "lanes": [0, max(lanes - 1, 0)],
        "mode": "replace",
        "xscale": plot.xscale,
    }
    for name, rec in plot._layers.items():
        if not getattr(rec, "select", False):
            assert name not in plot.selection
            continue
        drawn = rec.rows[rec.perm].tolist()
        assert len(drawn) == len(set(drawn)), "a row drawn twice"
        assert plot.selection.get(name, []) == sorted(drawn)
