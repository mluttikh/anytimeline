"""Every kind of table gives the same plot: the same spec and data sent to the browser, and
the same rows selected. Polars (eager and lazy), PyArrow, pandas (NumPy, nullable and Arrow
dtypes), DuckDB and a dict of arrays, with missing values in each kind of column."""

import duckdb
import numpy as np
import pandas as pd
import polars as pl
import pytest

from anytimeline import Timeline
from anytimeline.synthetic import service_log

LOG = service_log(20)
N = len(LOG["request"])
# missing values: a time (the event is not drawn), a lane, a colour, a size and a tooltip
MISSING = {"time": 3, "service": 5, "level": 7, "bytes": 11, "user": 13}


def polars() -> pl.DataFrame:
    df = pl.DataFrame(dict(LOG.items()))
    return df.with_columns(
        pl.when(pl.int_range(pl.len()) == row).then(None).otherwise(pl.col(c)).alias(c)
        for c, row in MISSING.items()
    )


def as_dict() -> dict:
    out = {k: v.copy() for k, v in LOG.items()}
    out["time"][MISSING["time"]] = np.datetime64("NaT", "us")
    for c in ("service", "level", "user"):
        out[c][MISSING[c]] = None
    out["bytes"] = out["bytes"].astype(float)
    out["bytes"][MISSING["bytes"]] = np.nan
    return out


TABLES = {
    "dict": as_dict,
    "polars": polars,
    "polars-lazy": lambda: polars().lazy(),
    "pyarrow": lambda: polars().to_arrow(),
    "pandas": lambda: polars().to_pandas(),
    "pandas-nullable": lambda: polars().to_pandas().convert_dtypes(dtype_backend="numpy_nullable"),
    "pandas-arrow": lambda: polars().to_pandas(types_mapper=pd.ArrowDtype),
    # a relation of its own connection: DuckDB reads the Arrow table by its name
    "duckdb": lambda: duckdb.connect().from_arrow(polars().to_arrow()).order("seq"),
}


def plot(table) -> Timeline:
    return Timeline().events(
        table,
        lane="service",
        color="level",
        size="bytes",
        order="seq",
        text="{event} ({user})",
        symbol="event",
        tooltip=["request", "user", "bytes"],
    )


def sent(p: Timeline) -> tuple[dict, dict]:
    spec = {k: v for k, v in p._spec.items() if k != "t"}
    return spec, dict(p._buffers)


EXPECTED = plot(TABLES["polars"]())


@pytest.mark.parametrize("name", list(TABLES))
def test_every_table_gives_the_same_plot(name):
    p = plot(TABLES[name]())
    spec, buffers = sent(p)
    want_spec, want_buffers = sent(EXPECTED)
    assert spec == want_spec
    assert buffers.keys() == want_buffers.keys()
    for k in buffers:
        assert buffers[k] == want_buffers[k], k


@pytest.mark.parametrize("name", list(TABLES))
def test_every_table_selects_the_same_rows(name):
    p = plot(TABLES[name]())
    box = {"kind": "box", "x": [-1, 1e18], "lanes": [0, 1], "mode": "replace", "xscale": "time"}
    p._pick = {"n": 1, **box}
    EXPECTED._pick = {"n": 1, **box}
    assert p.selection == EXPECTED.selection
    rows = p.selection["events"]
    assert 0 < len(rows) < N
    picked = p.selected("events")
    requests = picked["request"]
    requests = requests.to_pylist() if hasattr(requests, "to_pylist") else list(requests)
    assert requests == [LOG["request"][i] for i in rows]
    if name == "pandas":
        assert list(picked.index) == rows  # pandas keeps its index
