"""Read traces in Jaeger's JSON: what the Jaeger UI downloads ("Download JSON") and what its
query API (``/api/traces``) answers. The spans and the events in them (Jaeger's logs) come
as [`read_otlp`][anytimeline.otel.read_otlp] gives them, so they plot the same::

    from anytimeline import Timeline
    from anytimeline.jaeger import read_jaeger

    traces = read_jaeger("trace.json")
    plot = Timeline().spans(traces.spans, color="service")
    plot.events(traces.events, time="time", lane="span_id", symbol="name")

(Jaeger's newer API, ``/api/v3``, answers in OTLP/JSON: read that with ``read_otlp``.)
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from os import PathLike
from pathlib import Path
from typing import Any

import numpy as np

from anytimeline.otel import KINDS, Traces, _text

_SPAN_COLUMNS = (
    "trace_id",
    "span_id",
    "parent_id",
    "name",
    "service",
    "kind",
    "status",
    "status_message",
    "start",
    "end",
    "attributes",
)
_EVENT_COLUMNS = ("trace_id", "span_id", "time", "name", "attributes")
_KINDS = set(KINDS.values())


def read_jaeger(source: str | PathLike[str] | bytes | Mapping[str, Any] | Iterable[Any]) -> Traces:
    """Read traces in Jaeger's JSON.

    Args:
        source: A file, JSON text, or the parsed JSON: ``{"data": [trace, ...]}`` (the
            UI's download, the query API's answer), one trace (``{"traceID": ...,
            "spans": [...], "processes": {...}}``) or a list of traces.

    Returns:
        The spans and the events in them (Jaeger's logs). A span's kind comes from its
        ``span.kind`` tag, its status from ``error`` or ``otel.status_code``; its other
        tags are its ``attributes``.
    """
    spans: dict[str, list[Any]] = {k: [] for k in _SPAN_COLUMNS}
    events: dict[str, list[Any]] = {k: [] for k in _EVENT_COLUMNS}
    for trace in _traces(source):
        processes = trace.get("processes") or {}
        for sp in trace.get("spans") or []:
            _span(sp, processes, spans, events)
    return Traces(
        spans={
            **{
                k: np.array(spans[k], dtype=object)
                for k in _SPAN_COLUMNS
                if k not in ("start", "end")
            },
            "start": np.array(spans["start"], dtype=np.int64).astype("datetime64[ns]"),
            "end": np.array(spans["end"], dtype=np.int64).astype("datetime64[ns]"),
        },
        events={
            **{k: np.array(events[k], dtype=object) for k in _EVENT_COLUMNS if k != "time"},
            "time": np.array(events["time"], dtype=np.int64).astype("datetime64[ns]"),
        },
    )


def _traces(source: Any) -> list[Mapping[str, Any]]:
    if isinstance(source, bytes):
        source = source.decode()
    if isinstance(source, str) and source.lstrip().startswith(("{", "[")):
        source = json.loads(source)
    elif isinstance(source, str | PathLike):
        source = json.loads(Path(source).read_text())
    if isinstance(source, Mapping):
        if "data" in source and isinstance(source["data"], list):
            return [t for t in source["data"] if isinstance(t, Mapping)]
        return [source]
    return [t for t in source if isinstance(t, Mapping)]


def _span(
    sp: Mapping[str, Any],
    processes: Mapping[str, Any],
    spans: dict[str, list[Any]],
    events: dict[str, list[Any]],
) -> None:
    trace = str(sp.get("traceID", "")).lower()
    span = str(sp.get("spanID", "")).lower()
    refs = sp.get("references") or []
    parent = next(
        (r.get("spanID") for r in refs if r.get("refType") == "CHILD_OF"),
        next((r.get("spanID") for r in refs), sp.get("parentSpanID")),
    )
    tags = _fields(sp.get("tags"))
    process = sp.get("process") or processes.get(sp.get("processID", ""), {}) or {}
    start = int(sp.get("startTime") or 0) * 1000  # µs since 1970
    kind = str(tags.pop("span.kind", "unspecified")).lower()
    code = str(tags.pop("otel.status_code", "")).lower()
    error = tags.pop("error", False) in (True, "true")
    spans["trace_id"].append(trace)
    spans["span_id"].append(span)
    spans["parent_id"].append(str(parent).lower() if parent and parent != "0" else None)
    spans["name"].append(str(sp.get("operationName", "")))
    spans["service"].append(str(process.get("serviceName", "")))
    spans["kind"].append(kind if kind in _KINDS else "unspecified")
    spans["status"].append(
        "error" if error or code == "error" else "ok" if code == "ok" else "unset"
    )
    spans["status_message"].append(str(tags.pop("otel.status_description", "")))
    spans["start"].append(start)
    spans["end"].append(start + int(sp.get("duration") or 0) * 1000)
    spans["attributes"].append(_text(tags))
    for log in sp.get("logs") or []:
        fields = _fields(log.get("fields"))
        name = fields.pop("event", None) or fields.pop("message", None) or ""
        events["trace_id"].append(trace)
        events["span_id"].append(span)
        events["time"].append(int(log.get("timestamp") or 0) * 1000)
        events["name"].append(str(name))
        events["attributes"].append(_text(fields))


def _fields(items: Any) -> dict[str, Any]:
    """Jaeger's key-value lists (tags, log fields) as a dict."""
    return {f.get("key", ""): f.get("value") for f in items or []}
