"""Synthetic event data for examples and tests: no real data needed, reproducible by seed."""

from __future__ import annotations

from typing import Any

import numpy as np

from anytimeline.otel import Traces

SERVICES = ("gateway", "auth", "api", "db", "cache")


def service_log(
    requests: int = 2_000, *, seed: int = 0, start: str = "2026-10-12T08:00:00"
) -> dict[str, np.ndarray]:
    """A log of web requests passing through services: one row per event.

    Each request arrives at the gateway, is authorised, handled by the API (with a database
    query or a cache hit) and answered. About 3% fail somewhere along the way. Requests
    arrive over about an hour with a burst in the middle; times have microsecond precision.

    Returns:
        Columns ``time`` (datetime64[us]), ``service``, ``event``, ``level``
        (``"info"``, ``"warning"``, ``"error"``), ``request`` (``"r0001"``, ...), ``user``,
        ``bytes`` and ``seq`` (the order in which the log wrote the events).
    """
    rng = np.random.default_rng(seed)
    t0 = np.datetime64(start, "us")
    gaps = rng.exponential(1.0, requests)
    burst = slice(requests // 2, requests // 2 + requests // 10)
    gaps[burst] *= 0.05  # a burst: many requests within a few seconds
    arrivals = np.cumsum(gaps) * (3_600 / gaps.sum()) * 1e6  # µs over about an hour

    rows: list[tuple[float, str, str, str, int, int, int]] = []
    for r, at in enumerate(arrivals):
        user = int(rng.integers(1, 60))
        t = float(at)
        steps = [("gateway", "received"), ("auth", "authorized")]
        if rng.random() < 0.3:
            steps += [("api", "handled"), ("cache", "hit")]
        else:
            steps += [("api", "handled"), ("db", "query"), ("db", "result")]
        steps += [("gateway", "responded")]
        fail_at = int(rng.integers(1, len(steps))) if rng.random() < 0.03 else None
        for k, (service, step) in enumerate(steps):
            t += rng.lognormal(np.log(800 if service == "db" else 150), 0.6)
            event, level = step, "info"
            if fail_at is not None and k == fail_at:
                event, level = "failed", "error"
            elif service == "db" and step == "result" and rng.random() < 0.05:
                level = "warning"
            size = int(rng.lognormal(7, 1)) if event in ("result", "responded") else 0
            rows.append((t, service, event, level, r, user, size))
            if level == "error":
                break
    rows.sort(key=lambda row: row[0])
    times = np.array([round(row[0]) for row in rows], dtype=np.int64)
    return {
        "time": t0 + times.astype("timedelta64[us]"),
        "service": np.array([row[1] for row in rows], dtype=object),
        "event": np.array([row[2] for row in rows], dtype=object),
        "level": np.array([row[3] for row in rows], dtype=object),
        "request": np.array([f"r{row[4]:04d}" for row in rows], dtype=object),
        "user": np.array([f"u{row[5]:02d}" for row in rows], dtype=object),
        "bytes": np.array([row[6] for row in rows], dtype=np.int64),
        "seq": np.arange(len(rows), dtype=np.int64),
    }


def instants(n: int = 100_000, *, lanes: int = 20, seed: int = 0) -> dict[str, np.ndarray]:
    """Many events on many lanes, for performance tests: ``time`` (datetime64[ns] over a
    day), ``lane``, ``kind`` (8 categories) and ``value``."""
    rng = np.random.default_rng(seed)
    t0 = np.datetime64("2026-10-12T00:00:00", "ns")
    ns = np.sort(rng.integers(0, 86_400 * 10**9, n))
    return {
        "time": t0 + ns.astype("timedelta64[ns]"),
        "lane": np.array([f"lane {i}" for i in rng.integers(0, lanes, n)], dtype=object),
        "kind": np.array([f"k{i}" for i in rng.integers(0, 8, n)], dtype=object),
        "value": rng.normal(size=n),
    }


def traces(
    n: int = 12, *, seed: int = 0, start: str = "2026-10-12T08:00:00", error_rate: float = 0.15
) -> Traces:
    """Traces of web requests through services: spans under spans, as an OpenTelemetry
    exporter would give them (the columns of [`read_otlp`][anytimeline.otel.read_otlp]).

    Three kinds of request: ``GET /orders`` (auth, a cache, database queries and a fan-out to
    the inventory service in parallel), ``POST /checkout`` (a transaction around a slow
    payment) and ``GET /search`` (shards queried in parallel). Some fail: a query times out,
    is retried, and the error is recorded as an ``exception`` event. Requests start a few
    seconds apart and may overlap; times have microsecond precision.

    Returns:
        ``spans`` (``trace_id``, ``span_id``, ``parent_id``, ``name``, ``service``,
        ``kind``, ``status``, ``start``, ``end``) and ``events`` (``trace_id``, ``span_id``,
        ``time``, ``name``, ``attributes``).
    """
    rng = np.random.default_rng(seed)
    t0 = np.datetime64(start, "us")
    b = _Trace(rng)
    at = 0.0
    for _ in range(n):
        at += float(rng.exponential(2_000_000))  # µs between requests
        b.new_trace()
        fail = rng.random() < error_rate
        kind = rng.choice(["orders", "checkout", "search"], p=[0.5, 0.25, 0.25])
        {"orders": _orders, "checkout": _checkout, "search": _search}[kind](b, at, fail)
    s, e = b.spans, b.events
    return Traces(
        spans={
            "trace_id": np.array(s["trace_id"], dtype=object),
            "span_id": np.array(s["span_id"], dtype=object),
            "parent_id": np.array(s["parent_id"], dtype=object),
            "name": np.array(s["name"], dtype=object),
            "service": np.array(s["service"], dtype=object),
            "kind": np.array(s["kind"], dtype=object),
            "status": np.array(s["status"], dtype=object),
            "start": t0 + np.round(s["start"]).astype(np.int64).astype("timedelta64[us]"),
            "end": t0 + np.round(s["end"]).astype(np.int64).astype("timedelta64[us]"),
        },
        events={
            "trace_id": np.array(e["trace_id"], dtype=object),
            "span_id": np.array(e["span_id"], dtype=object),
            "time": t0
            + np.round(np.array(e["time"], dtype=np.float64))
            .astype(np.int64)
            .astype("timedelta64[us]"),
            "name": np.array(e["name"], dtype=object),
            "attributes": np.array(e["attributes"], dtype=object),
        },
    )


class _Trace:
    """Builds spans: ``open`` a span at a time, ``close`` it later (times in µs)."""

    def __init__(self, rng: np.random.Generator) -> None:
        self.rng = rng
        self.trace = ""
        self.spans: dict[str, list[Any]] = {
            k: []
            for k in (
                "trace_id",
                "span_id",
                "parent_id",
                "name",
                "service",
                "kind",
                "status",
                "start",
                "end",
            )
        }
        self.events: dict[str, list[Any]] = {
            k: [] for k in ("trace_id", "span_id", "time", "name", "attributes")
        }

    def new_trace(self) -> None:
        self.trace = self.rng.bytes(16).hex()

    def open(
        self, parent: int | None, service: str, name: str, at: float, kind: str = "internal"
    ) -> int:
        s = self.spans
        s["trace_id"].append(self.trace)
        s["span_id"].append(self.rng.bytes(8).hex())
        s["parent_id"].append(s["span_id"][parent] if parent is not None else None)
        s["name"].append(name)
        s["service"].append(service)
        s["kind"].append(kind)
        s["status"].append("unset")
        s["start"].append(at)
        s["end"].append(at)
        return len(s["span_id"]) - 1

    def close(self, span: int, at: float, error: bool = False) -> float:
        self.spans["end"][span] = at
        if error:
            self.spans["status"][span] = "error"
        return at

    def event(self, span: int, at: float, name: str, attributes: str = "") -> None:
        e = self.events
        e["trace_id"].append(self.trace)
        e["span_id"].append(self.spans["span_id"][span])
        e["time"].append(at)
        e["name"].append(name)
        e["attributes"].append(attributes)

    def leaf(
        self, parent: int, service: str, name: str, at: float, mean_us: float, kind: str = "client"
    ) -> float:
        """A span without children that takes about ``mean_us``; returns its end."""
        span = self.open(parent, service, name, at, kind)
        return self.close(span, at + float(self.rng.lognormal(np.log(mean_us), 0.45)))

    def wait(self, mean_us: float) -> float:
        return float(self.rng.lognormal(np.log(mean_us), 0.5))

    def query(self, parent: int, name: str, at: float, mean_us: float, fail: bool) -> float:
        """A database query; when ``fail``, it times out and is retried."""
        span = self.open(parent, "db", name, at, "client")
        if fail:
            end = at + 250_000
            self.event(
                span,
                end,
                "exception",
                "exception.type=TimeoutError; exception.message=timeout after 250 ms",
            )
            self.close(span, end, error=True)
            retry = self.open(parent, "db", f"{name} (retry)", end + self.wait(2_000), "client")
            self.event(retry, self.spans["start"][retry], "retry", "attempt=2")
            return self.close(retry, self.spans["start"][retry] + self.wait(mean_us))
        end = at + self.wait(mean_us)
        if end - at > 3 * mean_us:
            self.event(span, end, "slow query", f"db.duration_ms={(end - at) / 1000:.1f}")
        return self.close(span, end)

    def cache(self, parent: int, key: str, at: float) -> float:
        span = self.open(parent, "cache", f"GET {key}", at, "client")
        end = at + self.wait(300)
        if self.rng.random() < 0.3:
            self.event(span, end, "cache miss", f"key={key}")
        return self.close(span, end)

    def auth(self, root: int, at: float) -> float:
        span = self.open(root, "auth", "verify token", at, "server")
        end = self.cache(span, "session", at + self.wait(100))
        return self.close(span, end + self.wait(200))


def _orders(b: _Trace, at: float, fail: bool) -> None:
    root = b.open(None, "gateway", "GET /orders", at, "server")
    t = b.auth(root, at + b.wait(150))
    api = b.open(root, "api", "list orders", t + b.wait(100), "server")
    t = b.query(api, "SELECT orders", b.spans["start"][api] + b.wait(80), 4_000, fail)
    t = b.cache(api, "prices", t + b.wait(50))
    # the inventory of each order's items, in parallel
    stock = b.open(api, "api", "check stock", t + b.wait(50))
    ends = [
        b.leaf(
            stock, "inventory", f"GET /stock/{item}", b.spans["start"][stock] + b.wait(60), 3_000
        )
        for item in b.rng.choice(
            ["A12", "B07", "C33", "D41", "E09"], size=int(b.rng.integers(2, 5)), replace=False
        )
    ]
    t = b.close(stock, max(ends) + b.wait(40))
    t = b.leaf(api, "api", "render json", t + b.wait(30), 600, "internal")
    t = b.close(api, t + b.wait(50))
    b.close(root, t + b.wait(120), error=False)


def _checkout(b: _Trace, at: float, fail: bool) -> None:
    root = b.open(None, "gateway", "POST /checkout", at, "server")
    t = b.auth(root, at + b.wait(150))
    api = b.open(root, "api", "create order", t + b.wait(100), "server")
    t = b.query(api, "BEGIN", b.spans["start"][api] + b.wait(60), 300, False)
    t = b.query(api, "INSERT order", t + b.wait(40), 2_000, False)
    pay = b.open(api, "payments", "charge card", t + b.wait(80), "client")
    declined = fail and b.rng.random() < 0.5
    t = b.leaf(pay, "payments", "POST /v1/charges", b.spans["start"][pay] + b.wait(200), 180_000)
    if declined:
        b.event(pay, t, "exception", "exception.type=CardDeclined; exception.message=card declined")
    t = b.close(pay, t + b.wait(150), error=declined)
    t = b.query(
        api, "ROLLBACK" if declined else "COMMIT", t + b.wait(50), 800, fail and not declined
    )
    if not declined:
        t = b.leaf(api, "queue", "publish order.created", t + b.wait(40), 1_500, "producer")
    t = b.close(api, t + b.wait(60), error=declined)
    b.close(root, t + b.wait(120), error=declined)


def _search(b: _Trace, at: float, fail: bool) -> None:
    root = b.open(None, "gateway", "GET /search", at, "server")
    t = b.auth(root, at + b.wait(150))
    api = b.open(root, "api", "search", t + b.wait(100), "server")
    t = b.cache(api, "query", b.spans["start"][api] + b.wait(50))
    index = b.open(api, "search", "query index", t + b.wait(60), "client")
    ends = []
    for shard in range(4):
        slow = fail and shard == 2
        ends.append(
            b.leaf(
                index,
                "search",
                f"shard {shard}",
                b.spans["start"][index] + b.wait(80),
                40_000 if slow else 8_000,
            )
        )
        if slow:
            b.event(len(b.spans["span_id"]) - 1, ends[-1], "slow query", "reason=segment merge")
    t = b.close(index, max(ends) + b.wait(100))
    t = b.leaf(api, "api", "rank results", t + b.wait(40), 1_200, "internal")
    t = b.close(api, t + b.wait(50))
    b.close(root, t + b.wait(120))


def service_metrics(
    requests: int = 2_000,
    *,
    seed: int = 0,
    start: str = "2026-10-12T08:00:00",
    step_s: float = 10.0,
) -> dict[str, np.ndarray]:
    """Metrics of the services in [`service_log`][anytimeline.synthetic.service_log] (same
    ``requests``, ``seed`` and ``start``): a sample per service every ``step_s`` seconds, from
    the log's load, so the burst of requests shows in them.

    Returns:
        Columns ``time`` (datetime64[ms]), ``service``, ``rate`` (events per second),
        ``cpu`` (%), ``queue`` (requests waiting), ``p50_ms`` and ``p99_ms`` (latency).
    """
    log = service_log(requests, seed=seed, start=start)
    rng = np.random.default_rng(seed + 1)
    t0 = np.datetime64(start, "ms")
    step = np.timedelta64(round(step_s * 1000), "ms")
    last = log["time"].max().astype("datetime64[ms]")
    edges = np.arange(t0, last + 2 * step, step)
    out: dict[str, list[Any]] = {
        k: [] for k in ("time", "service", "rate", "cpu", "queue", "p50_ms", "p99_ms")
    }
    capacity = {"gateway": 3.0, "auth": 2.0, "api": 2.0, "db": 2.5, "cache": 4.0}
    base_ms = {"gateway": 2.0, "auth": 4.0, "api": 12.0, "db": 25.0, "cache": 0.8}
    for service in SERVICES:
        at = log["time"][log["service"] == service].astype("datetime64[ms]")
        counts = np.histogram(at.astype(np.int64), bins=edges.astype(np.int64))[0]
        rate = counts / step_s
        load = rate / capacity[service]
        queue = np.zeros(len(rate))
        for i in range(1, len(rate)):
            queue[i] = max(0.0, queue[i - 1] + (rate[i] - capacity[service]) * step_s * 0.5)
        cpu = np.clip(8 + 70 * load + rng.normal(0, 3, len(rate)) + 0.5 * queue, 0, 100)
        p50 = base_ms[service] * (1 + 0.6 * load + 0.05 * queue) * rng.lognormal(0, 0.08, len(rate))
        p99 = p50 * (3 + 2 * load) * rng.lognormal(0, 0.15, len(rate))
        out["time"] += edges[:-1].tolist()
        out["service"] += [service] * len(rate)
        out["rate"] += rate.tolist()
        out["cpu"] += cpu.tolist()
        out["queue"] += np.round(queue).tolist()
        out["p50_ms"] += p50.tolist()
        out["p99_ms"] += p99.tolist()
    return {
        "time": np.array(out["time"], dtype="datetime64[ms]"),
        "service": np.array(out["service"], dtype=object),
        **{
            k: np.array(out[k], dtype=np.float64)
            for k in ("rate", "cpu", "queue", "p50_ms", "p99_ms")
        },
    }


def service_health(
    requests: int = 2_000, *, seed: int = 0, start: str = "2026-10-12T08:00:00"
) -> dict[str, np.ndarray]:
    """The health of the services in [`service_log`][anytimeline.synthetic.service_log] as
    changes of state: ``"up"``, ``"degraded"`` (while the CPU is above 75%) and ``"down"``
    (the cache, for two minutes, restarting after the burst). A row per change, with the
    reason.

    Returns:
        Columns ``time`` (datetime64[ms]), ``service``, ``state`` and ``reason``.
    """
    m = service_metrics(requests, seed=seed, start=start)
    rows: list[tuple[Any, str, str, str]] = []
    for service in SERVICES:
        mine = m["service"] == service
        t, cpu = m["time"][mine], m["cpu"][mine]
        state = "up"
        rows.append((t[0], service, "up", ""))
        for i in range(len(t)):
            new = "degraded" if cpu[i] > 75 else "up" if cpu[i] < 60 else state
            if new != state:
                rows.append((t[i], service, new, f"cpu {cpu[i]:.0f}%"))
                state = new
        if service == "cache":
            # a restart after the burst
            busy = t[np.argmax(cpu)]
            down = busy + np.timedelta64(4, "m")
            rows += [
                (down, service, "down", "restarting"),
                (down + np.timedelta64(2, "m"), service, "up", ""),
            ]
    rows.sort(key=lambda r: (r[1], r[0]))
    return {
        "time": np.array([r[0] for r in rows], dtype="datetime64[ms]"),
        "service": np.array([r[1] for r in rows], dtype=object),
        "state": np.array([r[2] for r in rows], dtype=object),
        "reason": np.array([r[3] for r in rows], dtype=object),
    }


def incident(*, start: str = "2026-10-12T14:00:00") -> dict[str, np.ndarray]:
    """What happened during an incident, as a postmortem's timeline lists it: a bad deploy, the
    alerts, the people paged, the rollback and the recovery, about two hours of events.

    Returns:
        Columns ``time`` (datetime64[s]), ``title``, ``kind`` (``"deploy"``, ``"alert"``,
        ``"page"``, ``"action"``, ``"status"``), ``team`` and ``importance`` (1 to 3).
    """
    rows = [
        (0, "Deploy checkout 4.12", "deploy", "payments", 2),
        (6, "Error rate above 2%", "alert", "monitoring", 3),
        (7, "On-call paged", "page", "payments", 2),
        (9, "Latency p99 above 2 s", "alert", "monitoring", 2),
        (11, "Incident declared (SEV-2)", "status", "payments", 3),
        (14, "Status page: investigating", "status", "support", 1),
        (17, "Database CPU at 95%", "alert", "monitoring", 2),
        (19, "DB team paged", "page", "databases", 1),
        (24, "Slow query found in 4.12", "action", "databases", 3),
        (27, "Rollback started", "action", "payments", 3),
        (34, "Rollback finished", "deploy", "payments", 2),
        (36, "Error rate back below 1%", "alert", "monitoring", 2),
        (41, "Status page: monitoring", "status", "support", 1),
        (48, "Queue of failed payments retried", "action", "payments", 2),
        (63, "Retries done: 1,842 payments", "action", "payments", 2),
        (75, "Fix for the query reviewed", "action", "databases", 1),
        (92, "Deploy checkout 4.12.1", "deploy", "payments", 2),
        (101, "Incident resolved", "status", "payments", 3),
        (104, "Status page: resolved", "status", "support", 1),
        (118, "Postmortem scheduled", "action", "payments", 1),
    ]
    t0 = np.datetime64(start, "s")
    return {
        "time": t0 + np.array([r[0] * 60 for r in rows], dtype="timedelta64[s]"),
        "title": np.array([r[1] for r in rows], dtype=object),
        "kind": np.array([r[2] for r in rows], dtype=object),
        "team": np.array([r[3] for r in rows], dtype=object),
        "importance": np.array([r[4] for r in rows], dtype=np.int64),
    }
