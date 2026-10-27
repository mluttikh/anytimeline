"""Benchmarks of layers sent as levels (docs/architecture.md): a plot of many events, samples
or bars, built in Python. Prints the time to build it, the bytes of its first frame (the spec
and the buffers the browser asks for first), the time to cut a window, and the memory Python
holds (the process's peak resident memory, before building and after).

    uv run python scripts/bench_levels.py [events|values|bars] [n] [lanes]
"""

from __future__ import annotations

import json
import sys
import time

import numpy as np

from anytimeline import Timeline
from anytimeline.scene import BarDetail, ValueDetail


def data(kind: str, n: int, lanes: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(1)
    start = np.datetime64("2026-10-12T08:00", "ns")
    t = rng.integers(0, 3600 * 10**9, n)
    names = np.array([f"lane {i:03d}" for i in range(lanes)], dtype=object)
    lane = names[rng.integers(0, lanes, n)]
    if kind == "values":
        return {"time": start + np.sort(t).astype("timedelta64[ns]"), "lane": lane,
                "value": np.cumsum(rng.normal(0, 1, n))}  # fmt: skip
    level = rng.choice(["info", "warn", "error"], n, p=[0.9, 0.08, 0.02]).astype(object)
    if kind == "bars":
        took = (rng.exponential(0.2, n) * 1e9).astype(np.int64)
        end = start + (t + took).astype("timedelta64[ns]")
        return {"start": start + t.astype("timedelta64[ns]"), "end": end, "lane": lane,
                "level": level}  # fmt: skip
    return {"time": start + t.astype("timedelta64[ns]"), "lane": lane, "level": level}


def ids(v: object, levels: bool = False) -> set[str]:
    """The buffers a spec refers to (as the browser's specBufferIds)."""
    if isinstance(v, list):
        return set().union(*(ids(x, levels) for x in v)) if v else set()
    if not isinstance(v, dict):
        return set()
    if isinstance(v.get("id"), str) and "byteLength" in v:
        return {v["id"]}
    out: set[str] = set()
    for k, x in v.items():
        if levels or k != "levels":
            out |= ids(x, levels)
    return out


def first_ids(spec: dict) -> set[str]:
    """What the browser asks for first: the spec's buffers, and each layer's coarsest level."""
    out = ids(spec)
    for layer in spec["layers"]:
        lv = layer.get("levels")
        if lv:
            first = (lv["time"]["levels"] if "time" in lv else lv["levels"])[0]
            out |= ids(first)
    return out


def peak_mb() -> float:
    """The process's peak resident memory so far (MB; NaN on Windows)."""
    if sys.platform == "win32":
        return float("nan")
    import resource  # (not on Windows)

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 1e6 if sys.platform == "darwin" else peak / 1e3  # bytes on macOS, else kB


def main() -> None:
    kind = sys.argv[1] if len(sys.argv) > 1 else "events"
    n = int(float(sys.argv[2])) if len(sys.argv) > 2 else 10_000_000
    lanes = int(sys.argv[3]) if len(sys.argv) > 3 else 100
    table = data(kind, n, lanes)
    before = peak_mb()
    t0 = time.perf_counter()
    plot = Timeline()
    if kind == "values":
        plot.values(table, lane="lane", value="value")
    elif kind == "bars":
        plot.intervals(table, start="start", end="end", lane="lane", color="level")
    else:
        plot.events(table, lane="lane", color="level")
    built = time.perf_counter() - t0
    after = peak_mb()
    assert plot._scene is not None
    spec = plot._spec
    first = first_ids(spec)
    sent = len(json.dumps(spec)) + sum(len(plot._buffers[i]) for i in first)
    total = sum(len(b) for b in plot._buffers.values())
    name, d = next(iter(plot._scene.detail.items()))
    x0, top = spec["time"]["extent"][0], spec["time"]["extent"][1] - spec["time"]["extent"][0]
    t1 = time.perf_counter()
    plot._window({"layer": name, "scale": "time", "range": [x0 + top * 0.5, x0 + top * 0.501],
                  "k": None})  # fmt: skip
    raw = time.perf_counter() - t1
    t1 = time.perf_counter()
    plot._window({"layer": name, "scale": "time", "range": [x0, x0 + top * 0.25], "k": 6})
    level = time.perf_counter() - t1
    what = (
        "samples" if isinstance(d, ValueDetail) else "bars" if isinstance(d, BarDetail) else "bins"
    )
    print(f"{kind}: {n:,} on {lanes} lanes ({what})")
    print(f"  build          {built:6.2f} s")
    print(f"  first frame    {sent / 1e6:6.2f} MB (all levels {total / 1e6:.1f} MB)")
    print(f"  window raw     {raw * 1e3:6.0f} ms")
    print(f"  window k=6     {level * 1e3:6.0f} ms")
    print(f"  peak memory    {after:6.0f} MB ({before:.0f} MB with the table, before building)")


if __name__ == "__main__":
    main()
