"""Read traces in Chrome's trace event format (JSON): what Chrome's DevTools and
``chrome://tracing`` save, what Perfetto exports as JSON, and what many profilers write (Node's
``--cpu-prof`` aside: that is another format). Its slices become spans, nested as on their
thread; flows become arrows; counters become values::

    from anytimeline import Timeline
    from anytimeline.chrome import read_chrome

    trace = read_chrome("trace.json")
    plot = Timeline().spans(
        trace.spans, layout="flame", group="track", depends="follows", color="category"
    )
    plot.values(trace.counters, lane="name", value="value")

Times are durations from the trace's first event (the format's clock has no date).
"""

from __future__ import annotations

import bisect
import itertools
import json
from collections.abc import Iterable, Mapping
from os import PathLike
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np

from anytimeline.otel import _text


class ChromeTrace(NamedTuple):
    """The slices, instants, counters and flows of a trace, as dicts of columns."""

    spans: dict[str, np.ndarray]
    """A row per slice (complete ``X``, ``B``/``E`` pairs, async ``b``/``e``): ``span_id``,
    ``parent_id`` (the slice it is in, on its thread; None for a top one), ``name``,
    ``category``, ``service`` (the process's name), ``thread`` (the thread's name, or
    ``"async"`` for async slices), ``track`` (``"process / thread"``), ``start`` and ``end``
    (timedelta64[ns] from the trace's first event; missing for a slice that never ended),
    ``args`` (as text) and ``follows`` (the ids of the slices a flow comes from)."""
    events: dict[str, np.ndarray]
    """A row per instant (``i``, ``I``, ``n``, ``R``): ``span_id`` (the slice it is in, on
    its thread, or None), ``time``, ``name``, ``category``, ``service``, ``thread``,
    ``track``, ``scope`` (``"thread"``, ``"process"`` or ``"global"``) and ``args``."""
    counters: dict[str, np.ndarray]
    """A row per value of a counter (``C``): ``time``, ``name`` (the counter, and its series
    when it has several), ``counter``, ``series``, ``service`` and ``value``."""
    flows: dict[str, np.ndarray]
    """A row per arrow of a flow (``s``/``t``/``f``, or slices' ``bind_id``): ``id``,
    ``name``, ``category``, ``from_span`` and ``to_span``."""


def read_chrome(
    source: str | PathLike[str] | bytes | Mapping[str, Any] | Iterable[Any],
) -> ChromeTrace:
    """Read a trace in Chrome's trace event format.

    Args:
        source: A file, JSON text, or the parsed JSON: ``{"traceEvents": [...]}`` or the list
            of events (a list cut short, as a crashed browser leaves it, reads too).

    Returns:
        The slices (as spans), instants, counters and flows.
    """
    return _Reader(_events(source)).read()


def _events(source: Any) -> list[Mapping[str, Any]]:
    if isinstance(source, bytes):
        source = source.decode()
    if isinstance(source, PathLike) or (
        isinstance(source, str) and not source.lstrip().startswith(("{", "["))
    ):
        source = Path(source).read_text()
    if isinstance(source, str):
        try:
            source = json.loads(source)
        except json.JSONDecodeError:
            # the format allows a list without its closing bracket
            source = json.loads(source.rstrip().rstrip(",") + "]")
    if isinstance(source, Mapping):
        source = source.get("traceEvents") or []
    return [e for e in source if isinstance(e, Mapping)]


_INSTANT_SCOPES = {"t": "thread", "p": "process", "g": "global"}


class _Reader:
    def __init__(self, events: list[Mapping[str, Any]]) -> None:
        self.events = events
        self.processes: dict[Any, str] = {}
        self.threads: dict[tuple[Any, Any], str] = {}
        for e in events:
            if e.get("ph") == "M":
                name = str((e.get("args") or {}).get("name", ""))
                if e.get("name") == "process_name":
                    self.processes[e.get("pid")] = name
                elif e.get("name") == "thread_name":
                    self.threads[(e.get("pid"), e.get("tid"))] = name
        stamps = [_ns(e["ts"]) for e in events if e.get("ph") != "M" and "ts" in e]
        self.zero = min(stamps, default=0)
        self.spans: dict[str, list[Any]] = {
            k: []
            for k in (
                "span_id", "parent_id", "name", "category", "service", "thread", "track",
                "start", "end", "args",
            )
        }  # fmt: skip
        self.follows: list[list[str]] = []
        self.instants: dict[str, list[Any]] = {
            k: []
            for k in (
                "span_id", "time", "name", "category", "service", "thread", "track", "scope",
                "args",
            )
        }  # fmt: skip
        self.counters: dict[str, list[Any]] = {
            k: [] for k in ("time", "name", "counter", "series", "service", "value")
        }
        self.flows: dict[str, list[Any]] = {
            k: [] for k in ("id", "name", "category", "from_span", "to_span")
        }

    def service(self, pid: Any) -> str:
        return self.processes.get(pid) or f"pid {pid}"

    def thread(self, pid: Any, tid: Any) -> str:
        return self.threads.get((pid, tid)) or f"tid {tid}"

    def add_span(self, e: Mapping[str, Any], thread: str, start: int, parent: str | None) -> int:
        i = len(self.spans["span_id"])
        service = self.service(e.get("pid"))
        self.spans["span_id"].append(str(i))
        self.spans["parent_id"].append(parent)
        self.spans["name"].append(str(e.get("name", "")))
        self.spans["category"].append(str(e.get("cat", "")))
        self.spans["service"].append(service)
        self.spans["thread"].append(thread)
        self.spans["track"].append(f"{service} / {thread}")
        self.spans["start"].append(start - self.zero)
        self.spans["end"].append(None)
        self.spans["args"].append(_text(e.get("args") or {}))
        self.follows.append([])
        return i

    def read(self) -> ChromeTrace:
        # by time; at one time an end before a begin, and the longer of two slices first
        def key(item: tuple[int, Mapping[str, Any]]) -> tuple[int, int, float, int]:
            n, e = item
            ph = e.get("ph")
            return (
                _ns(e.get("ts", 0)),
                0 if ph in ("E", "e", "F") else 1,
                -float(e.get("dur") or 0),
                n,
            )

        timed = sorted(((n, e) for n, e in enumerate(self.events) if e.get("ph") != "M"), key=key)
        stacks: dict[tuple[Any, Any], list[tuple[float, int]]] = {}  # thread: (end, span)
        asyncs: dict[tuple[Any, ...], list[int]] = {}
        # slices on each thread, in start order: (start, span), for flows that bind to the next
        starts: dict[tuple[Any, Any], list[tuple[int, int]]] = {}
        flow_points: list[tuple[Any, int, tuple[Any, Any], Mapping[str, Any]]] = []
        binds: dict[Any, dict[str, list[int]]] = {}

        def enclosing(thread: tuple[Any, Any], t: int) -> int | None:
            stack = stacks.get(thread) or []
            for end, span in reversed(stack):
                if end > t:
                    return span
            return None

        for _, e in timed:
            ph = e.get("ph")
            t = _ns(e.get("ts", 0))
            thread = (e.get("pid"), e.get("tid"))
            stack = stacks.setdefault(thread, [])
            while stack and stack[-1][0] <= t and ph != "E":
                stack.pop()
            if ph in ("X", "B"):
                parent = stack[-1][1] if stack else None
                i = self.add_span(
                    e, self.thread(*thread), t, str(parent) if parent is not None else None
                )
                end = t + _ns(e.get("dur") or 0) if ph == "X" else np.inf
                if ph == "X":
                    self.spans["end"][i] = end - self.zero
                stack.append((end, i))
                starts.setdefault(thread, []).append((t, i))
                if "bind_id" in e:
                    b = binds.setdefault(e["bind_id"], {"out": [], "in": []})
                    if e.get("flow_out"):
                        b["out"].append(i)
                    if e.get("flow_in"):
                        b["in"].append(i)
            elif ph == "E":
                # the innermost slice begun (B) and not ended; slices (X) ended by now go
                while stack and stack[-1][0] != np.inf and stack[-1][0] <= t:
                    stack.pop()
                if stack and stack[-1][0] == np.inf:
                    _, i = stack.pop()
                    self.spans["end"][i] = t - self.zero
                    if e.get("args"):
                        more = _text(e["args"])
                        self.spans["args"][i] = "; ".join(
                            x for x in (self.spans["args"][i], more) if x
                        )
            elif ph in ("b", "S"):
                k = _async_key(e)
                open_ = asyncs.setdefault(k, [])
                parent = open_[-1] if open_ and ph == "b" else None
                i = self.add_span(e, "async", t, str(parent) if parent is not None else None)
                open_.append(i)
            elif ph in ("e", "F"):
                open_ = asyncs.get(_async_key(e)) or []
                if open_:
                    i = open_.pop()
                    self.spans["end"][i] = t - self.zero
            elif ph in ("i", "I", "n", "R"):
                scope = _INSTANT_SCOPES.get(str(e.get("s", "t")), "thread")
                inside = enclosing(thread, t) if scope == "thread" and ph != "n" else None
                name = self.thread(*thread) if ph != "n" else "async"
                service = self.service(e.get("pid"))
                self.instants["span_id"].append(str(inside) if inside is not None else None)
                self.instants["time"].append(t - self.zero)
                self.instants["name"].append(str(e.get("name", "")))
                self.instants["category"].append(str(e.get("cat", "")))
                self.instants["service"].append(service)
                self.instants["thread"].append(name)
                self.instants["track"].append(f"{service} / {name}")
                self.instants["scope"].append(scope)
                self.instants["args"].append(_text(e.get("args") or {}))
            elif ph == "C":
                values = {k: v for k, v in (e.get("args") or {}).items() if _is_number(v)}
                counter = str(e.get("name", "")) + (f" {e['id']}" if "id" in e else "")
                for series, v in values.items():
                    self.counters["time"].append(t - self.zero)
                    self.counters["name"].append(
                        counter if len(values) == 1 else f"{counter} {series}"
                    )
                    self.counters["counter"].append(counter)
                    self.counters["series"].append(str(series))
                    self.counters["service"].append(self.service(e.get("pid")))
                    self.counters["value"].append(float(v))
            elif ph in ("s", "t", "f"):
                # bound to a slice once all slices are read: the one it is in, or (a flow's end,
                # by default) the next one to begin on its thread
                nxt = ph == "f" and e.get("bp") != "e"
                span = -1 if nxt else enclosing(thread, t)
                flow_points.append((_flow_key(e), span if span is not None else -2, thread, e))

        self.bind_flows(flow_points, starts, binds)
        n = len(self.spans["span_id"])
        ended = np.array([v is not None for v in self.spans["end"]], dtype=bool)
        end = np.array([v if v is not None else 0 for v in self.spans["end"]], dtype=np.int64)
        follows = np.empty(n, dtype=object)
        for i, f in enumerate(self.follows):
            follows[i] = f
        return ChromeTrace(
            spans={
                **{
                    k: np.array(v, dtype=object)
                    for k, v in self.spans.items()
                    if k not in ("start", "end")
                },
                "start": np.array(self.spans["start"], dtype=np.int64).astype("timedelta64[ns]"),
                "end": np.where(ended, end.astype("timedelta64[ns]"), np.timedelta64("NaT", "ns")),
                "follows": follows,
            },
            events={
                **{k: np.array(v, dtype=object) for k, v in self.instants.items() if k != "time"},
                "time": np.array(self.instants["time"], dtype=np.int64).astype("timedelta64[ns]"),
            },
            counters={
                **{
                    k: np.array(v, dtype=object)
                    for k, v in self.counters.items()
                    if k not in ("time", "value")
                },
                "time": np.array(self.counters["time"], dtype=np.int64).astype("timedelta64[ns]"),
                "value": np.array(self.counters["value"], dtype=np.float64),
            },
            flows={k: np.array(v, dtype=object) for k, v in self.flows.items()},
        )

    def bind_flows(
        self,
        points: list[tuple[Any, int, tuple[Any, Any], Mapping[str, Any]]],  # span -1: next
        starts: dict[tuple[Any, Any], list[tuple[int, int]]],
        binds: dict[Any, dict[str, list[int]]],
    ) -> None:
        chains: dict[Any, list[tuple[int, Mapping[str, Any]]]] = {}
        for key, bound, thread, e in points:
            span = bound
            if span == -1:  # the next slice to begin on its thread, at or after the point
                on = starts.get(thread, [])
                at = bisect.bisect_left(on, (_ns(e.get("ts", 0)), -1))
                span = on[at][1] if at < len(on) else -2
            if span >= 0:  # (-2: no slice to bind to)
                chains.setdefault(key, []).append((span, e))
        for key, chain in chains.items():
            for (a, e), (b, _) in itertools.pairwise(chain):
                self.link(key[1], e, a, b)
        for bind_id, b in binds.items():
            for a in b["out"]:
                for z in b["in"]:
                    self.link(bind_id, {}, a, z)

    def link(self, id: Any, e: Mapping[str, Any], a: int, b: int) -> None:
        if a == b:
            return
        self.flows["id"].append(str(id))
        self.flows["name"].append(str(e.get("name", "")))
        self.flows["category"].append(str(e.get("cat", "")))
        self.flows["from_span"].append(str(a))
        self.flows["to_span"].append(str(b))
        self.follows[b].append(str(a))


def _ns(ts: Any) -> int:
    """A timestamp in µs (the format's unit) as ns."""
    return round(float(ts) * 1000)


def _async_key(e: Mapping[str, Any]) -> tuple[Any, ...]:
    ident = e.get("id")
    if ident is None and isinstance(e.get("id2"), Mapping):
        id2 = e["id2"]
        ident = ("local", id2.get("local")) if "local" in id2 else ("global", id2.get("global"))
    # a local id is the process's own; a plain one is global, as Chrome reads it
    pid = e.get("pid") if isinstance(ident, tuple) and ident[0] == "local" else None
    return (e.get("cat", ""), str(ident), pid, e.get("scope"))


def _flow_key(e: Mapping[str, Any]) -> tuple[Any, ...]:
    return (e.get("cat", ""), str(e.get("id", e.get("bind_id"))))


def _is_number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)
