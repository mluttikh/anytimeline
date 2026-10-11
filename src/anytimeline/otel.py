"""Read traces in the OpenTelemetry format (OTLP/JSON): the spans, and the events in them.

OTLP/JSON is what the OpenTelemetry Collector's file exporter writes (one export request per
line), what ``otel-cli`` and many SDK exporters write, and what Jaeger and Tempo export. A trace
from it plots with [`Timeline.spans`][anytimeline.Timeline.spans]::

    from anytimeline import Timeline
    from anytimeline.otel import read_otlp

    traces = read_otlp("traces.jsonl")
    plot = Timeline().spans(traces.spans, color="service")
    plot.events(traces.events, time="time", lane="span_id", symbol="name")
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Iterable, Mapping
from os import PathLike
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np

STATUS = {0: "unset", 1: "ok", 2: "error"}
KINDS = {0: "unspecified", 1: "internal", 2: "server", 3: "client", 4: "producer", 5: "consumer"}


class Traces(NamedTuple):
    """Spans and their events, as dicts of columns (any table library reads them)."""

    spans: dict[str, np.ndarray]
    """A row per span: ``trace_id``, ``span_id``, ``parent_id`` (None for a root), ``name``,
    ``service``, ``kind``, ``status`` (``"unset"``, ``"ok"``, ``"error"``),
    ``status_message``, ``start`` and ``end`` (datetime64[ns], UTC) and ``attributes`` (as
    text)."""
    events: dict[str, np.ndarray]
    """A row per event in a span (a log line, an exception): ``trace_id``, ``span_id``,
    ``time`` (datetime64[ns], UTC), ``name`` and ``attributes`` (as text)."""


def read_otlp(source: str | PathLike[str] | bytes | Mapping[str, Any] | Iterable[Any]) -> Traces:
    """Read OTLP/JSON traces.

    Args:
        source: A file (``.json``, or ``.jsonl`` with one export request per line), JSON
            text, or the parsed JSON: an export request (``{"resourceSpans": [...]}``) or a
            list of them.

    Returns:
        The spans and the events in them.
    """
    spans: dict[str, list[Any]] = {k: [] for k in _SPAN_COLUMNS}
    events: dict[str, list[Any]] = {k: [] for k in _EVENT_COLUMNS}
    for request in _requests(source):
        for rs in request.get("resourceSpans") or request.get("resource_spans") or []:
            resource = _attributes((rs.get("resource") or {}).get("attributes"))
            service = str(resource.get("service.name", ""))
            for ss in (
                rs.get("scopeSpans")
                or rs.get("scope_spans")
                or rs.get("instrumentationLibrarySpans")
                or []
            ):
                for sp in ss.get("spans") or []:
                    _span(sp, service, spans, events)
    n = len(spans["span_id"])
    m = len(events["span_id"])
    return Traces(
        spans={
            **{
                k: np.array(spans[k], dtype=object)
                for k in _SPAN_COLUMNS
                if k not in ("start", "end")
            },
            "start": np.array(spans["start"], dtype=np.int64).astype("datetime64[ns]")
            if n
            else np.zeros(0, "datetime64[ns]"),
            "end": np.array(spans["end"], dtype=np.int64).astype("datetime64[ns]")
            if n
            else np.zeros(0, "datetime64[ns]"),
        },
        events={
            **{k: np.array(events[k], dtype=object) for k in _EVENT_COLUMNS if k != "time"},
            "time": np.array(events["time"], dtype=np.int64).astype("datetime64[ns]")
            if m
            else np.zeros(0, "datetime64[ns]"),
        },
    )


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


def _requests(source: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(source, Mapping):
        return [source]
    if isinstance(source, bytes):
        source = source.decode()
    if isinstance(source, str) and source.lstrip().startswith(("{", "[")):
        return _parse(source)
    if isinstance(source, str | PathLike):
        return _parse(Path(source).read_text())
    return [r for r in source if isinstance(r, Mapping)]


def _parse(text: str) -> list[Mapping[str, Any]]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # JSON lines: one export request per line
        parsed = [json.loads(line) for line in text.splitlines() if line.strip()]
    return parsed if isinstance(parsed, list) else [parsed]


def _span(
    sp: Mapping[str, Any], service: str, spans: dict[str, list[Any]], events: dict[str, list[Any]]
) -> None:
    trace = _id(sp.get("traceId") or sp.get("trace_id"))
    span = _id(sp.get("spanId") or sp.get("span_id"))
    parent = _id(sp.get("parentSpanId") or sp.get("parent_span_id")) or None
    status = sp.get("status") or {}
    code = status.get("code", 0)
    kind = sp.get("kind", 0)
    spans["trace_id"].append(trace)
    spans["span_id"].append(span)
    spans["parent_id"].append(parent)
    spans["name"].append(str(sp.get("name", "")))
    spans["service"].append(service)
    spans["kind"].append(_enum(kind, KINDS, "SPAN_KIND_"))
    spans["status"].append(_enum(code, STATUS, "STATUS_CODE_"))
    spans["status_message"].append(str(status.get("message", "")))
    spans["start"].append(int(sp.get("startTimeUnixNano") or sp.get("start_time_unix_nano") or 0))
    spans["end"].append(int(sp.get("endTimeUnixNano") or sp.get("end_time_unix_nano") or 0))
    spans["attributes"].append(_text(_attributes(sp.get("attributes"))))
    for e in sp.get("events") or []:
        events["trace_id"].append(trace)
        events["span_id"].append(span)
        events["time"].append(int(e.get("timeUnixNano") or e.get("time_unix_nano") or 0))
        events["name"].append(str(e.get("name", "")))
        events["attributes"].append(_text(_attributes(e.get("attributes"))))


def _id(value: Any) -> str:
    """A trace or span id as hex: OTLP/JSON writes hex; some exporters write base64."""
    if not value:
        return ""
    text = str(value)
    if all(c in "0123456789abcdefABCDEF" for c in text):
        return text.lower()
    try:
        return base64.b64decode(text, validate=True).hex()
    except (binascii.Error, ValueError):
        return text


def _enum(value: Any, names: Mapping[int, str], prefix: str) -> str:
    if isinstance(value, str):
        return (
            value.removeprefix(prefix).lower()
            if not value.isdigit()
            else names.get(int(value), value)
        )
    return names.get(int(value), str(value))


def _attributes(items: Any) -> dict[str, Any]:
    return {a.get("key", ""): _value(a.get("value") or {}) for a in items or []}


def _value(v: Mapping[str, Any]) -> Any:
    for key in ("stringValue", "boolValue", "doubleValue"):
        if key in v:
            return v[key]
    if "intValue" in v:
        return int(v["intValue"])
    if "arrayValue" in v:
        return [_value(x) for x in (v["arrayValue"] or {}).get("values") or []]
    if "kvlistValue" in v:
        return _attributes((v["kvlistValue"] or {}).get("values"))
    return None


def _text(attributes: Mapping[str, Any]) -> str:
    return "; ".join(f"{k}={v}" for k, v in attributes.items())
